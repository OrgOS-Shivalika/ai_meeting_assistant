"""Admin API for the agents_v2 pipeline.

Endpoints (all org-scoped — cross-org access returns 404):

    GET  /agents_v2/{id}                          — read agent config
    PATCH /agents_v2/{id}                          — update editable fields
                                                     (Category A + B: model,
                                                     LLM params, allowed
                                                     skills/tools, harness,
                                                     display name, status)

    GET  /agents_v2/{id}/prompt                    — current active prompt
    GET  /agents_v2/{id}/prompt/versions           — history
    GET  /agents_v2/{id}/prompt/versions/{ver_id}  — one specific version
    POST /agents_v2/{id}/prompt                    — create new version
    POST /agents_v2/{id}/prompt/rollback/{ver_id}  — activate an older version

Auth model (day-1): any user in the agent's organization. Later this
can be tightened to admin-only via a role check.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents_v2.shared import tracing
from app.agents_v2.shared.prompt_store import (
    PromptValidationError,
    create_version,
    list_versions,
    load_active_prompt,
    rollback_to,
)
from app.api.db_dependency import get_db
from app.db.models import AgentPrompt, AgentV2, Category, Team
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/agents_v2", tags=["Agents v2"])


# ---------------------------------------------------------------------------
# Common — fetch the agent row, enforcing tenant isolation
# ---------------------------------------------------------------------------

def _get_agent_or_404(db: Session, agent_id: int, user) -> AgentV2:
    row = (
        db.query(AgentV2)
        .filter(
            AgentV2.id == agent_id,
            AgentV2.organization_id == user.organization_id,
        )
        .first()
    )
    if row is None:
        # 404 (not 403) — don't leak whether the id exists in another org.
        raise HTTPException(status_code=404, detail="Agent not found")
    return row


def _agent_folder(slug: str) -> Path:
    """Locate the agent's folder on disk for file-fallback lookups."""
    return Path(__file__).resolve().parents[1] / "agents_v2" / slug


# ---------------------------------------------------------------------------
# Read + update agent config (Category A + B fields)
# ---------------------------------------------------------------------------

class AgentReadResponse(BaseModel):
    id: int
    slug: str
    name: str
    status: str
    organization_id: str
    category_id: Optional[int]
    team_id: Optional[int]
    # Category A — core AI
    model: str
    max_tokens: int
    temperature: Optional[float]
    top_p: Optional[float]
    frequency_penalty: Optional[float]
    presence_penalty: Optional[float]
    # Category B — capabilities
    allowed_skills: list[str]
    allowed_tools: list[str]
    harness_enabled: bool
    system_prompt_key: str


class AgentUpdateRequest(BaseModel):
    """Every field optional — PATCH semantics. Omitted fields = no change."""
    # Identity
    name: Optional[str] = Field(None, max_length=200)
    status: Optional[str] = Field(None, pattern="^(active|archived)$")
    # Category A
    model: Optional[str] = Field(None, max_length=100)
    max_tokens: Optional[int] = Field(None, ge=256, le=32_000)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    frequency_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0)
    # Category B
    allowed_skills: Optional[list[str]] = None
    allowed_tools: Optional[list[str]] = None
    harness_enabled: Optional[bool] = None


def _serialize_agent(row: AgentV2) -> AgentReadResponse:
    return AgentReadResponse(
        id=row.id,
        slug=row.slug,
        name=row.name,
        status=row.status,
        organization_id=str(row.organization_id),
        category_id=row.category_id,
        team_id=row.team_id,
        model=row.model,
        max_tokens=row.max_tokens,
        temperature=row.temperature,
        top_p=row.top_p,
        frequency_penalty=row.frequency_penalty,
        presence_penalty=row.presence_penalty,
        allowed_skills=list(row.allowed_skills or []),
        allowed_tools=list(row.allowed_tools or []),
        harness_enabled=row.harness_enabled,
        system_prompt_key=row.system_prompt_key,
    )


class AgentListItem(BaseModel):
    id: int
    slug: str
    name: str
    status: str
    category_id: Optional[int]
    category_name: Optional[str]
    team_id: Optional[int]
    team_name: Optional[str]
    model: str
    harness_enabled: bool


@router.get("", response_model=list[AgentListItem])
def list_agents(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """All agents_v2 rows in the caller's org, with category + team names
    joined so the frontend can group without a second round-trip."""
    rows = (
        db.query(AgentV2, Category.name, Team.name)
        .outerjoin(Category, Category.id == AgentV2.category_id)
        .outerjoin(Team, Team.id == AgentV2.team_id)
        .filter(AgentV2.organization_id == user.organization_id)
        .order_by(Category.name.nulls_first(), Team.name.nulls_first(), AgentV2.name)
        .all()
    )
    return [
        AgentListItem(
            id=r.id, slug=r.slug, name=r.name, status=r.status,
            category_id=r.category_id, category_name=cat_name,
            team_id=r.team_id, team_name=team_name,
            model=r.model, harness_enabled=r.harness_enabled,
        )
        for (r, cat_name, team_name) in rows
    ]


@router.get("/{agent_id}", response_model=AgentReadResponse)
def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _serialize_agent(_get_agent_or_404(db, agent_id, user))


@router.patch("/{agent_id}", response_model=AgentReadResponse)
def update_agent(
    agent_id: int,
    payload: AgentUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _serialize_agent(row)


# ---------------------------------------------------------------------------
# Prompt CRUD (versioned)
# ---------------------------------------------------------------------------

class PromptReadResponse(BaseModel):
    agent_id: int
    prompt_key: str
    source: str            # "db" or "file"
    version: int
    hash: str
    text: str
    row_id: Optional[int] = None
    edited_by: Optional[str] = None
    edited_at_iso: Optional[str] = None
    notes: Optional[str] = None


class PromptVersionMeta(BaseModel):
    id: int
    version: int
    prompt_key: str
    hash: str
    is_active: bool
    created_by: Optional[str]
    created_at_iso: str
    notes: Optional[str]


class PromptCreateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=30_000)
    prompt_key: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


class TraceItem(BaseModel):
    id: str
    timestamp: Optional[str]
    name: Optional[str]
    session_id: Optional[str]
    latency: Optional[float]
    total_cost: Optional[float]


class TraceReportResponse(BaseModel):
    enabled: bool
    host: Optional[str]
    traces: list[TraceItem]
    error: Optional[str]


@router.get("/{agent_id}/traces", response_model=TraceReportResponse)
def get_agent_traces(
    agent_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Recent Langfuse traces for this agent (filtered by tag=slug).
    Fails-safe to an empty list if Langfuse isn't configured or the
    call errors — the UI renders a graceful message either way.
    """
    row = _get_agent_or_404(db, agent_id, user)
    return tracing.fetch_agent_traces(row.slug, limit=min(max(limit, 1), 200))


@router.get("/{agent_id}/prompt/keys", response_model=list[str])
def list_prompt_keys(
    agent_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Union of prompt_keys available for this agent — both from the DB
    (any keys ever created) and from disk (the agent's prompts/*.md
    files shipped in the folder). Empty list only for a broken agent.
    """
    row = _get_agent_or_404(db, agent_id, user)
    keys: set[str] = set()

    # From DB
    for (k,) in (
        db.query(AgentPrompt.prompt_key)
        .filter(AgentPrompt.agent_id == row.id)
        .distinct()
        .all()
    ):
        keys.add(k)

    # From disk
    folder = _agent_folder(row.slug) / "prompts"
    if folder.is_dir():
        for p in folder.glob("*.md"):
            keys.add(p.name)

    return sorted(keys)


@router.get("/{agent_id}/prompt", response_model=PromptReadResponse)
def get_active_prompt(
    agent_id: int,
    prompt_key: str = "master.md",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    try:
        loaded = load_active_prompt(
            db,
            agent_id=row.id,
            agent_folder=_agent_folder(row.slug),
            prompt_key=prompt_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return PromptReadResponse(
        agent_id=row.id,
        prompt_key=loaded.prompt_key,
        source=loaded.source,
        version=loaded.version,
        hash=loaded.hash,
        text=loaded.text,
        row_id=loaded.row_id,
        edited_by=loaded.edited_by,
        edited_at_iso=loaded.edited_at_iso,
        notes=loaded.notes,
    )


@router.get("/{agent_id}/prompt/versions", response_model=list[PromptVersionMeta])
def list_prompt_versions(
    agent_id: int,
    prompt_key: str = "master.md",
    limit: int = 50,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    versions = list_versions(
        db, agent_id=row.id, prompt_key=prompt_key, limit=min(max(limit, 1), 200),
    )
    return [
        PromptVersionMeta(
            id=v.id,
            version=v.version,
            prompt_key=v.prompt_key,
            hash=v.prompt_hash,
            is_active=v.is_active,
            created_by=str(v.created_by) if v.created_by else None,
            created_at_iso=v.created_at.isoformat() if v.created_at else "",
            notes=v.notes,
        )
        for v in versions
    ]


@router.get("/{agent_id}/prompt/versions/{version_id}", response_model=PromptReadResponse)
def get_prompt_version(
    agent_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    v = (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.id == version_id,
            AgentPrompt.agent_id == row.id,
        )
        .first()
    )
    if v is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return PromptReadResponse(
        agent_id=row.id,
        prompt_key=v.prompt_key,
        source="db",
        version=v.version,
        hash=v.prompt_hash,
        text=v.prompt_text,
        row_id=v.id,
        edited_by=str(v.created_by) if v.created_by else None,
        edited_at_iso=v.created_at.isoformat() if v.created_at else None,
        notes=v.notes,
    )


@router.post("/{agent_id}/prompt", response_model=PromptVersionMeta, status_code=201)
def create_prompt_version(
    agent_id: int,
    payload: PromptCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    try:
        v = create_version(
            db,
            agent_id=row.id,
            text=payload.text,
            created_by=user.id,
            prompt_key=payload.prompt_key or "master.md",
            notes=payload.notes,
        )
        db.commit()
    except PromptValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(v)
    return PromptVersionMeta(
        id=v.id,
        version=v.version,
        prompt_key=v.prompt_key,
        hash=v.prompt_hash,
        is_active=v.is_active,
        created_by=str(v.created_by) if v.created_by else None,
        created_at_iso=v.created_at.isoformat() if v.created_at else "",
        notes=v.notes,
    )


@router.post("/{agent_id}/prompt/rollback/{version_id}", response_model=PromptVersionMeta, status_code=201)
def rollback_prompt(
    agent_id: int,
    version_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_agent_or_404(db, agent_id, user)
    try:
        v = rollback_to(
            db,
            agent_id=row.id,
            target_version_id=version_id,
            created_by=user.id,
        )
        db.commit()
    except (ValueError, PromptValidationError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    db.refresh(v)
    return PromptVersionMeta(
        id=v.id,
        version=v.version,
        prompt_key=v.prompt_key,
        hash=v.prompt_hash,
        is_active=v.is_active,
        created_by=str(v.created_by) if v.created_by else None,
        created_at_iso=v.created_at.isoformat() if v.created_at else "",
        notes=v.notes,
    )
