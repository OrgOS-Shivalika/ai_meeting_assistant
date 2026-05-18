"""Phase 7E — playground HTTP surface.

Endpoints:

  POST /agent-playground/run           — SSE stream, single-config run
  GET  /agent-playground/history       — paginated list of recent runs
  GET  /agent-playground/history/{id}  — single run detail

The playground is org_admin-only — see plan §14.1. Lower-privilege
users get 403 on every endpoint. Cross-org access to a run id
returns 404.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import PromptTestRun, User
from app.dependencies.auth import require_org_admin
from app.schemas.agent_api_schema import ModularPromptIn
from app.services.agents.playground import run_playground
from app.services.rag.ask_pipeline import event_to_sse_bytes
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/agent-playground", tags=["Agent Playground"])


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class _PlaygroundOverrides(BaseModel):
    """The deltas the playground applies on top of a resolved baseline.
    Every field is optional — a None field means "use the saved
    config's value"."""
    model_config = ConfigDict(extra="forbid")

    modular_prompt: Optional[ModularPromptIn] = None
    retrieval_config: Optional[dict] = None
    model_config_payload: Optional[dict] = Field(
        default=None, alias="model_config_payload",
    )
    # Pydantic v2's `model_config` is reserved on the class itself, so
    # the override key is `model_config_payload` (same convention as
    # PromptVersionCreateRequest in 7B).
    tool_permissions: Optional[dict] = None


class PlaygroundRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_text: str = Field(..., min_length=1, max_length=8000)
    scope_type: Optional[Literal["team", "category", "global"]] = None
    scope_id: Optional[int] = Field(default=None, ge=1)
    agent_profile_slug: Optional[str] = Field(default=None, max_length=64)
    agent_profile_id: Optional[UUID] = None
    inline_overrides: Optional[_PlaygroundOverrides] = None
    simulated_user_id: Optional[UUID] = None
    sources: Literal["all", "meetings", "documents"] = "all"

    @field_validator("scope_id")
    @classmethod
    def _scope_id_consistency(cls, v, info):
        # Same shape as /rag/ask: scope=global → scope_id null;
        # scope=team/category → scope_id required.
        st = info.data.get("scope_type")
        if st in (None, "global") and v is not None:
            raise ValueError("scope_id must be null when scope_type is 'global' (or unset)")
        if st in ("team", "category") and v is None:
            raise ValueError("scope_id is required when scope_type is 'team' or 'category'")
        return v


class PromptTestRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    prompt_version_id: Optional[UUID]
    query_text: str
    status: str
    total_duration_ms: Optional[int]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    created_by: Optional[UUID]
    created_at: datetime


class PromptTestRunDetail(BaseModel):
    """Full detail for the dashboard's playground-history drawer."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    agent_prompt_config_id: Optional[UUID]
    prompt_version_id: Optional[UUID]
    inline_overrides_json: Optional[dict]
    simulated_scope_type: Optional[str]
    simulated_scope_id: Optional[int]
    simulated_user_id: Optional[UUID]
    query_text: str
    assembled_prompt_text: str
    retrieval_bundle_json: Optional[dict]
    answer_text: Optional[str]
    citations_json: Optional[list]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    planner_duration_ms: Optional[int]
    retrieval_duration_ms: Optional[int]
    synth_duration_ms: Optional[int]
    total_duration_ms: Optional[int]
    status: str
    error_message: Optional[str]
    created_by: Optional[UUID]
    created_at: datetime


# ---------------------------------------------------------------------------
# POST /run — SSE stream
# ---------------------------------------------------------------------------


@router.post("/run")
def post_playground_run(
    payload: PlaygroundRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Run one sandboxed query. Streams SSE in the same shape as
    `/rag/ask`. Strict isolation — no rag_query_runs, no access
    events, no conversation touch. Exactly one prompt_test_runs row
    on completion (even on failures)."""
    overrides_dict = None
    if payload.inline_overrides is not None:
        # Translate to the dict shape the service expects. ModularPromptIn
        # is converted to its dict form; the rest pass through.
        raw = payload.inline_overrides.model_dump(
            by_alias=True, exclude_none=False,
        )
        # Rename alias back: `model_config_payload` → `model_config`
        # for the playground service.
        if "model_config_payload" in raw:
            raw["model_config"] = raw.pop("model_config_payload")
        overrides_dict = raw

    def _generate():
        from app.db.database import SessionLocal
        inner_db = SessionLocal()
        try:
            for event in run_playground(
                inner_db,
                organization_id=user.organization_id,
                actor_user_id=user.id,
                query_text=payload.query_text,
                scope_type=payload.scope_type,
                scope_id=payload.scope_id,
                sources=payload.sources,
                agent_profile_slug=payload.agent_profile_slug,
                agent_profile_id=payload.agent_profile_id,
                inline_overrides=overrides_dict,
                simulated_user_id=payload.simulated_user_id,
            ):
                yield event_to_sse_bytes(event)
        finally:
            inner_db.close()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /history — list
# ---------------------------------------------------------------------------


@router.get("/history", response_model=List[PromptTestRunSummary])
def list_playground_history(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Recent playground runs for the user's org, newest first."""
    rows = (
        db.query(PromptTestRun)
        .filter(PromptTestRun.organization_id == user.organization_id)
        .order_by(desc(PromptTestRun.created_at))
        .limit(limit)
        .all()
    )
    return rows


@router.get("/history/{run_id}", response_model=PromptTestRunDetail)
def get_playground_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Single-run detail. Returns the full assembled prompt +
    retrieval bundle so the dashboard can render the comparison
    view."""
    row = (
        db.query(PromptTestRun)
        .filter(
            PromptTestRun.id == run_id,
            PromptTestRun.organization_id == user.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Playground run not found",
        )
    return row
