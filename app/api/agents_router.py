"""Phase 7A — Agent Control Dashboard: agent profile CRUD.

Endpoints:

  GET    /agents                 — list agent_profiles in current org
  GET    /agents/types           — enum of supported agent_types (drives UI)
  GET    /agents/{id}            — single profile
  POST   /agents                 — create a draft profile
  PATCH  /agents/{id}            — partial update
  POST   /agents/{id}/archive    — soft-archive (status='archived')
  POST   /agents/{id}/duplicate  — clone with a new slug

Every endpoint is org-scoped — cross-tenant access returns 404, matching
the convention in consolidation_router / observability_router.

7A does NOT enforce role-based write protection. RBAC lands in 7E
once the role surface is finalized; until then every authenticated user
of the org can edit. This is documented in the plan.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import (
    AgentEvalRun, AgentProfile, AgentPromptConfig, PromptVersion, User,
)
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.dependencies.auth import get_current_user
from app.schemas.agent_api_schema import (
    AgentProfileCreateRequest, AgentProfileDuplicateRequest,
    AgentProfilePatchRequest, AgentProfileResponse,
    AgentTypeDescriptor,
)
from app.services.agents.audit import write_event as _audit
from app.services.agents.eval_gate import (
    EvalGateError, list_runs_for_agent, run_eval_for_version,
)
from app.services.agents.resolver import (
    cache_hit, resolve_agent_runtime_config, resolve_duration_ms,
)
from app.services.tools.registry import list_tools
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/agents", tags=["Agents"])


# ---------------------------------------------------------------------------
# Static agent-type catalog. Keep in sync with the CHECK in the 7A
# migration. `bound_service` documents which file each agent_type
# eventually drives (the wiring lands in 7D).
# ---------------------------------------------------------------------------

_AGENT_TYPE_CATALOG: list[AgentTypeDescriptor] = [
    AgentTypeDescriptor(
        agent_type="rag_synth",
        display_name="RAG Synthesizer",
        description="Generates cited answers from retrieved context.",
        bound_service="app/services/rag/synthesizer.py",
    ),
    AgentTypeDescriptor(
        agent_type="rag_planner",
        display_name="RAG Query Planner",
        description="Classifies query intent and selects scope tier.",
        bound_service="app/services/rag/query_planner.py",
    ),
    AgentTypeDescriptor(
        agent_type="graph_extractor",
        display_name="Graph Extractor",
        description="Pulls entities and relationships from meeting/document text.",
        bound_service="app/ai_agents/graph_extractor_llm.py",
    ),
    AgentTypeDescriptor(
        agent_type="transcript_analyzer",
        display_name="Transcript Analyzer",
        description="Post-meeting analysis: summary, tasks, decisions.",
        bound_service="app/ai_agents/openAI_transcript_analyzer.py",
    ),
    AgentTypeDescriptor(
        agent_type="importance_scorer",
        display_name="Importance Scorer",
        description="Computes per-row importance signals (deterministic today; "
                    "carries importance_weight_overrides for tuning).",
        bound_service="app/services/importance/scorer.py",
    ),
    AgentTypeDescriptor(
        agent_type="summarizer",
        display_name="Summarizer",
        description="Standalone summary agent — per-team override surface.",
        bound_service="(reserved)",
    ),
    AgentTypeDescriptor(
        agent_type="live_copilot",
        display_name="Live In-Meeting Copilot",
        description="Real-time meeting assistance — reserved for Phase 8.",
        bound_service="(reserved for Phase 8)",
        reserved=True,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_owned_profile(
    db: Session, *, profile_id: UUID, organization_id: UUID,
) -> AgentProfile:
    row = (
        db.query(AgentProfile)
        .filter(
            AgentProfile.id == profile_id,
            AgentProfile.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return row


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("/types", response_model=List[AgentTypeDescriptor])
def list_agent_types() -> list[AgentTypeDescriptor]:
    """Enum of supported agent_types. Static — does not require DB.
    Drives the create-agent dropdown in the dashboard."""
    return _AGENT_TYPE_CATALOG


@router.get("", response_model=List[AgentProfileResponse])
def list_agent_profiles(
    agent_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, regex="^(active|archived)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List agent profiles for the user's org. Default returns active
    profiles, newest first. Pass `status=archived` to see archived ones."""
    q = db.query(AgentProfile).filter(
        AgentProfile.organization_id == user.organization_id,
    )
    if agent_type is not None:
        q = q.filter(AgentProfile.agent_type == agent_type)
    if status is not None:
        q = q.filter(AgentProfile.status == status)
    else:
        q = q.filter(AgentProfile.status == "active")
    rows = q.order_by(desc(AgentProfile.created_at)).limit(limit).all()
    return rows


@router.get("/{profile_id}", response_model=AgentProfileResponse)
def get_agent_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=AgentProfileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_agent_profile(
    payload: AgentProfileCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a draft profile. Subsequent slices (7B) add prompt
    versions; 7A only persists the profile shell."""
    default_prompt = {}
    if payload.default_modular_prompt is not None:
        default_prompt = payload.default_modular_prompt.to_modular_prompt().to_dict()

    row = AgentProfile(
        organization_id=user.organization_id,
        slug=payload.slug,
        display_name=payload.display_name,
        description=payload.description,
        agent_type=payload.agent_type,
        status="active",
        default_modular_prompt_json=default_prompt,
        eval_gate_required=payload.eval_gate_required,
        eval_fixture_set_id=payload.eval_fixture_set_id,
        eval_min_score=payload.eval_min_score,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # The soft-active unique on (org, slug) is the most likely cause.
        raise HTTPException(
            status_code=409,
            detail="An active agent profile with this slug already exists.",
        ) from e
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="create",
        after={"slug": row.slug, "agent_type": row.agent_type,
               "display_name": row.display_name},
    )
    return row


@router.patch("/{profile_id}", response_model=AgentProfileResponse)
def patch_agent_profile(
    profile_id: UUID,
    payload: AgentProfilePatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Partial update. Slug and agent_type are immutable post-create —
    duplicate the profile if you need a new slug."""
    row = _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    if row.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot edit an archived profile. Duplicate it first.",
        )

    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.description is not None:
        row.description = payload.description
    if payload.default_modular_prompt is not None:
        row.default_modular_prompt_json = (
            payload.default_modular_prompt.to_modular_prompt().to_dict()
        )
    if payload.eval_gate_required is not None:
        row.eval_gate_required = payload.eval_gate_required
    if payload.eval_fixture_set_id is not None:
        row.eval_fixture_set_id = payload.eval_fixture_set_id
    if payload.eval_min_score is not None:
        row.eval_min_score = payload.eval_min_score

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="update",
        after={"display_name": row.display_name,
               "description": row.description,
               "eval_gate_required": row.eval_gate_required},
    )
    return row


@router.post(
    "/{profile_id}/archive",
    response_model=AgentProfileResponse,
)
def archive_agent_profile(
    profile_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Soft-archive a profile. Its `prompt_configs` are NOT cascaded —
    they stay active until 7B's deactivation flow handles them. For 7A
    the archive is profile-only; admins archiving a profile mid-7B
    workflow should re-archive bindings explicitly."""
    row = _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    if row.status == "archived":
        return row  # idempotent
    row.status = "archived"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="archive",
        before={"status": "active"}, after={"status": "archived"},
    )
    return row


@router.post(
    "/{profile_id}/duplicate",
    response_model=AgentProfileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def duplicate_agent_profile(
    profile_id: UUID,
    payload: AgentProfileDuplicateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Clone a profile under a new slug. Copies the default modular
    prompt + eval settings, but NOT scope bindings or prompt versions
    (those land in 7B). The duplicate starts fresh — a clean editing
    surface for experimentation."""
    src = _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    new_row = AgentProfile(
        organization_id=user.organization_id,
        slug=payload.new_slug,
        display_name=payload.new_display_name,
        description=src.description,
        agent_type=src.agent_type,
        status="active",
        default_modular_prompt_json=dict(src.default_modular_prompt_json or {}),
        eval_gate_required=src.eval_gate_required,
        eval_fixture_set_id=src.eval_fixture_set_id,
        eval_min_score=src.eval_min_score,
        created_by=user.id,
    )
    db.add(new_row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active agent profile with this slug already exists.",
        ) from e
    db.refresh(new_row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=new_row.id, action="duplicate",
        after={"slug": new_row.slug, "duplicated_from": str(src.id)},
    )
    return new_row


# ===========================================================================
# Phase 7C — Runtime resolution debug endpoint
#
# Returns the `ResolvedAgentConfig` the resolver would produce for a
# given (agent_type, profile, scope) tuple. Useful for "why is my
# prompt acting like this" debugging — admins can see the resolution
# path, the merged modular prompt, the retrieval-config knobs that
# would apply.
#
# Not RBAC-gated in 7C — every authenticated user in the org can call
# it. 7E adds an org_admin check.
# ===========================================================================


@router.get("/runtime/resolve", tags=["Agents"])
def debug_resolve_runtime(
    agent_type: str = Query(..., max_length=32),
    agent_profile_id: Optional[UUID] = Query(default=None),
    agent_profile_slug: Optional[str] = Query(default=None, max_length=64),
    team_id: Optional[int] = Query(default=None, ge=1),
    category_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resolve the runtime config that would apply for the given
    (agent_type, profile, scope). Returns the merged bundle + the
    resolution path so admins can see *why* each section came from
    where. Read-only — no side effects. Does NOT write a
    `agent_runtime_logs` row (the resolver only logs when called
    inside an /rag/ask)."""
    resolved = resolve_agent_runtime_config(
        db,
        organization_id=user.organization_id,
        agent_type=agent_type,
        agent_profile_id=agent_profile_id,
        agent_profile_slug=agent_profile_slug,
        team_id=team_id,
        category_id=category_id,
        current_user_id=user.id,
    )
    body = resolved.to_observability_dict()
    # Augment with modular_prompts (kept off the observability dict to
    # keep `agent_runtime_logs.resolution_path_json` small).
    body["modular_prompts"] = resolved.modular_prompts
    body["cache_hit"] = cache_hit(resolved)
    body["resolve_duration_ms"] = resolve_duration_ms(resolved)
    return body


# ===========================================================================
# Phase 7H — Eval gate + tool registry
# ===========================================================================


class EvalRunRequest(BaseModel):
    """Body for POST /agents/{id}/eval/run. All fields optional —
    by default, runs against the profile's currently-active version
    in stub mode."""
    model_config = ConfigDict(extra="forbid")

    prompt_version_id: Optional[UUID] = None
    mode: Literal["stub", "real"] = "stub"
    threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class EvalRunSummary(BaseModel):
    """Slim response for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_version_id: Optional[UUID]
    mode: str
    threshold: float
    score: Optional[float]
    overall_passed: bool
    total_cases: int
    passed_cases: int
    duration_ms: Optional[int]
    triggered_by: str
    triggered_by_user_id: Optional[UUID]
    started_at: datetime
    completed_at: Optional[datetime]


class EvalRunDetail(EvalRunSummary):
    """Full detail incl. the report JSON and any error message."""
    report_json: dict
    error_message: Optional[str]


@router.post("/{profile_id}/eval/run", response_model=EvalRunDetail)
def trigger_eval_run(
    profile_id: UUID,
    payload: EvalRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually trigger an eval run for a profile. Defaults to the
    profile's currently-active version + stub mode. Persists an
    `agent_eval_runs` row and returns the full result."""
    prof = _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )

    # Pick the version. If the request didn't specify one, use the
    # profile's first org-scoped binding's active_version_id.
    version_id = payload.prompt_version_id
    if version_id is None:
        cfg = (
            db.query(AgentPromptConfig)
            .filter(
                AgentPromptConfig.organization_id == user.organization_id,
                AgentPromptConfig.agent_profile_id == prof.id,
                AgentPromptConfig.scope_type == "organization",
                AgentPromptConfig.status == "active",
            )
            .first()
        )
        if cfg is None or cfg.active_version_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No active version found for this profile. Pass "
                    "prompt_version_id explicitly or publish a version first."
                ),
            )
        version_id = cfg.active_version_id

    # Sanity-check tenancy on the version (rejects cross-org or
    # cross-profile version_ids).
    ver = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.organization_id == user.organization_id,
    ).first()
    if ver is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")

    try:
        run = run_eval_for_version(
            db,
            organization_id=user.organization_id,
            agent_profile_id=prof.id,
            prompt_version_id=version_id,
            mode=payload.mode,
            threshold=payload.threshold,
            triggered_by="manual",
            triggered_by_user_id=user.id,
        )
    except EvalGateError as exc:
        raise HTTPException(
            status_code=exc.http_status, detail=str(exc),
        ) from exc
    return run


@router.get(
    "/{profile_id}/eval/runs",
    response_model=List[EvalRunSummary],
)
def list_eval_runs(
    profile_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Most-recent first eval-run history for one profile.
    Cross-org access returns an empty list (because the profile
    lookup 404s before we get here)."""
    _get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    rows = list_runs_for_agent(
        db, organization_id=user.organization_id,
        agent_profile_id=profile_id, limit=limit,
    )
    return rows


@router.get("/tools/catalog")
def list_tool_catalog(
    user: User = Depends(get_current_user),
):
    """List every registered tool descriptor. Drives the dashboard's
    tool-permissions picker on the prompt editor. Read-only;
    open to any authenticated user."""
    return [
        {
            "tool_id": t.tool_id,
            "display_name": t.display_name,
            "description": t.description,
            "cost_class": t.cost_class,
            "side_effecting": t.side_effecting,
            "schema": t.schema,
        }
        for t in list_tools()
    ]
