"""Continuum Core meeting agent API.

    POST   /continuum/clients                    — create client (+ team under the
                                                   Continuum Core category, both
                                                   auto-created as needed)
    GET    /continuum/clients                    — kanban payload: all clients with
                                                   stage / recommendation / stall flags
    GET    /continuum/clients/{id}               — client + full board
    DELETE /continuum/clients/{id}               — delete client + runs (team stays)
    PATCH  /continuum/clients/{id}/stage         — HUMAN stage confirmation (kanban drag)
    POST   /continuum/clients/{id}/process       — MODE A manual paste (unrecorded meetings)
    POST   /continuum/clients/{id}/brief         — MODE B pre-meeting brief
    GET    /continuum/clients/{id}/runs          — run history (newest first)
    GET    /continuum/runs/{run_id}              — one run's full detail
    POST   /continuum/meetings/{id}/reprocess    — retry auto-processing for a meeting

Recorded meetings flow in automatically via the meeting pipeline hook
(celery_tasks/continuum_tasks.py) — no endpoint involved.

All org-scoped; cross-org access returns 404. LLM endpoints are
synchronous (30-120s on gpt-4o) — fine for single-user volume.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents_v2.shared import tracing
from app.api.db_dependency import get_db
from app.celery_tasks.continuum_tasks import dispatch_continuum_process
from app.config.settings import settings
from app.db.models import (
    Category,
    ContinuumAgentConfig,
    ContinuumClient,
    ContinuumRun,
    Meeting,
    Team,
)
from app.dependencies.auth import get_current_user
from app.services.continuum import service
from app.services.continuum.service import STAGES

router = APIRouter(prefix="/continuum", tags=["Continuum"])


def _get_client_or_404(db: Session, client_id: int, user) -> ContinuumClient:
    row = (
        db.query(ContinuumClient)
        .filter(
            ContinuumClient.id == client_id,
            ContinuumClient.organization_id == user.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return row


def _ensure_continuum_category(db: Session, user) -> Category:
    """Find-or-create the org's Continuum Core category."""
    cat = (
        db.query(Category)
        .filter(
            Category.organization_id == user.organization_id,
            Category.name == settings.CONTINUUM_CATEGORY_NAME,
        )
        .first()
    )
    if cat is None:
        cat = Category(
            organization_id=user.organization_id,
            user_id=user.id,
            name=settings.CONTINUUM_CATEGORY_NAME,
            description="Client engagements tracked by the Continuum Core agent",
        )
        db.add(cat)
        db.flush()
    return cat


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ClientCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class StagePatchRequest(BaseModel):
    stage: str


class ClientCard(BaseModel):
    """One kanban card."""
    id: int
    name: str
    team_id: Optional[int]
    stage: str
    board_version: int
    calls_in_stage: Optional[int]
    stall_flags: list[Any]
    latest_recommendation: Optional[dict[str, Any]]
    updated_at: str


class ClientDetailResponse(ClientCard):
    board: Optional[dict[str, Any]]


class BoardResponse(BaseModel):
    stages: list[str]
    clients: list[ClientCard]


class ProcessRequest(BaseModel):
    raw_input: str = Field(..., min_length=1)
    attendees: list[str] = []
    agenda: list[str] = []
    ideal_outcome: str = ""
    meeting_date: Optional[str] = None


class BriefRequest(BaseModel):
    agenda: list[str] = []
    ideal_outcome: str = ""


class RunResponse(BaseModel):
    id: int
    client_id: int
    meeting_id: Optional[int]
    mode: str
    model: str
    status: str
    package_markdown: Optional[str]
    board_version_after: Optional[int]
    stage_recommendation: Optional[dict[str, Any]]
    error_message: Optional[str]
    duration_ms: Optional[int]
    created_at: str


class RunDetailResponse(RunResponse):
    board_after: Optional[dict[str, Any]]
    playbook_delta: Optional[list[Any]]


def _card(row: ContinuumClient) -> ClientCard:
    pipeline = (row.board or {}).get("pipeline") or {}
    calls = pipeline.get("calls_in_stage")
    return ClientCard(
        id=row.id,
        name=row.name,
        team_id=row.team_id,
        stage=service.current_stage(row),
        board_version=row.board_version or 0,
        calls_in_stage=calls if isinstance(calls, int) else None,
        stall_flags=list(pipeline.get("stall_flags") or []),
        latest_recommendation=row.latest_recommendation,
        updated_at=row.updated_at.isoformat(),
    )


def _run_out(run: ContinuumRun) -> RunResponse:
    return RunResponse(
        id=run.id,
        client_id=run.client_id,
        meeting_id=run.meeting_id,
        mode=run.mode,
        model=run.model,
        status=run.status,
        package_markdown=run.package_markdown,
        board_version_after=run.board_version_after,
        stage_recommendation=run.stage_recommendation,
        error_message=run.error_message,
        duration_ms=run.duration_ms,
        created_at=run.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Clients + kanban payload
# ---------------------------------------------------------------------------

@router.post("/clients", response_model=ClientCard)
def create_client(
    body: ClientCreateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    name = body.name.strip()
    existing = (
        db.query(ContinuumClient)
        .filter(
            ContinuumClient.organization_id == user.organization_id,
            ContinuumClient.name == name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Client with this name already exists")

    category = _ensure_continuum_category(db, user)
    team = (
        db.query(Team)
        .filter(Team.category_id == category.id, Team.name == name)
        .first()
    )
    if team is None:
        team = Team(
            category_id=category.id,
            name=name,
            description="Continuum Core client",
        )
        db.add(team)
        db.flush()
    elif db.query(ContinuumClient).filter(ContinuumClient.team_id == team.id).first():
        raise HTTPException(status_code=409, detail="Team already linked to a client")

    row = ContinuumClient(
        organization_id=user.organization_id,
        team_id=team.id,
        name=name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _card(row)


@router.get("/clients", response_model=BoardResponse)
def list_clients(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(ContinuumClient)
        .filter(ContinuumClient.organization_id == user.organization_id)
        .order_by(ContinuumClient.updated_at.desc())
        .all()
    )
    return BoardResponse(stages=STAGES, clients=[_card(r) for r in rows])


@router.get("/clients/{client_id}", response_model=ClientDetailResponse)
def get_client(client_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = _get_client_or_404(db, client_id, user)
    return ClientDetailResponse(**_card(row).model_dump(), board=row.board)


@router.delete("/clients/{client_id}")
def delete_client(client_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = _get_client_or_404(db, client_id, user)
    db.delete(row)  # cc_runs cascade; the team is left in place
    db.commit()
    return {"ok": True}


@router.patch("/clients/{client_id}/stage", response_model=ClientCard)
def confirm_stage(
    client_id: int,
    body: StagePatchRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """The human side of "agent recommends, orchestration confirms" —
    called when the manager drags a card on the kanban."""
    row = _get_client_or_404(db, client_id, user)
    if body.stage not in STAGES:
        raise HTTPException(status_code=422, detail=f"Unknown stage. Valid: {STAGES}")
    service.confirm_stage(db, row, body.stage)
    db.refresh(row)
    return _card(row)


# ---------------------------------------------------------------------------
# Agent runs
# ---------------------------------------------------------------------------

@router.post("/clients/{client_id}/process", response_model=RunResponse)
def process_manual(
    client_id: int,
    body: ProcessRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Manual paste path — for unrecorded meetings (calls, notes)."""
    row = _get_client_or_404(db, client_id, user)
    if len(body.raw_input.split()) < 10:
        raise HTTPException(status_code=422, detail="Transcript too short to process")
    run = service.run_process(
        db,
        row,
        raw_input=body.raw_input,
        attendees=body.attendees,
        salesperson=user.email or "",
        agenda=body.agenda,
        ideal_outcome=body.ideal_outcome,
        meeting_date=body.meeting_date,
    )
    if run.status == "failed":
        raise HTTPException(status_code=502, detail=f"Agent run failed: {run.error_message}")
    return _run_out(run)


@router.post("/clients/{client_id}/brief", response_model=RunResponse)
def brief(
    client_id: int,
    body: BriefRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    row = _get_client_or_404(db, client_id, user)
    run = service.run_brief(
        db,
        row,
        agenda=body.agenda,
        ideal_outcome=body.ideal_outcome,
    )
    if run.status == "failed":
        raise HTTPException(status_code=502, detail=f"Agent run failed: {run.error_message}")
    return _run_out(run)


@router.get("/clients/{client_id}/runs", response_model=list[RunResponse])
def list_runs(client_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = _get_client_or_404(db, client_id, user)
    runs = (
        db.query(ContinuumRun)
        .filter(ContinuumRun.client_id == row.id)
        .order_by(ContinuumRun.created_at.desc())
        .limit(50)
        .all()
    )
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(run_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    run = (
        db.query(ContinuumRun)
        .join(ContinuumClient, ContinuumClient.id == ContinuumRun.client_id)
        .filter(
            ContinuumRun.id == run_id,
            ContinuumClient.organization_id == user.organization_id,
        )
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunDetailResponse(
        **_run_out(run).model_dump(),
        board_after=run.board_after,
        playbook_delta=run.playbook_delta,
    )


# ---------------------------------------------------------------------------
# Control Panel — agent config + Langfuse traces
# ---------------------------------------------------------------------------

class ConfigResponse(BaseModel):
    model: str
    max_tokens: Optional[int]
    temperature: Optional[float]
    system_prompt: str
    prompt_overridden: bool
    default_model: str


class ConfigUpdateRequest(BaseModel):
    """PATCH semantics — omitted fields unchanged. Explicit nulls reset
    to the built-in default (model/max_tokens/temperature), and
    `reset_prompt: true` drops the prompt override."""
    model: Optional[str] = Field(None, max_length=100)
    max_tokens: Optional[int] = Field(None, ge=1024, le=32_000)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    system_prompt: Optional[str] = Field(None, min_length=200)
    reset_model: bool = False
    reset_max_tokens: bool = False
    reset_temperature: bool = False
    reset_prompt: bool = False


def _config_out(db: Session, user) -> ConfigResponse:
    rt = service.resolve_runtime(db, user.organization_id)
    return ConfigResponse(
        model=rt["model"],
        max_tokens=rt["max_tokens"],
        temperature=rt["temperature"],
        system_prompt=rt["system_prompt"],
        prompt_overridden=rt["prompt_overridden"],
        default_model=settings.CONTINUUM_MODEL,
    )


@router.get("/config", response_model=ConfigResponse)
def get_config(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _config_out(db, user)


@router.put("/config", response_model=ConfigResponse)
def update_config(
    body: ConfigUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cfg = (
        db.query(ContinuumAgentConfig)
        .filter(ContinuumAgentConfig.organization_id == user.organization_id)
        .first()
    )
    if cfg is None:
        cfg = ContinuumAgentConfig(organization_id=user.organization_id)
        db.add(cfg)

    if body.reset_model:
        cfg.model = None
    elif body.model is not None:
        cfg.model = body.model.strip()

    if body.reset_max_tokens:
        cfg.max_tokens = None
    elif body.max_tokens is not None:
        cfg.max_tokens = body.max_tokens

    if body.reset_temperature:
        cfg.temperature = None
    elif body.temperature is not None:
        cfg.temperature = body.temperature

    if body.reset_prompt:
        cfg.system_prompt_override = None
    elif body.system_prompt is not None:
        cfg.system_prompt_override = body.system_prompt

    db.commit()
    return _config_out(db, user)


@router.get("/traces")
def get_traces(limit: int = 50, user=Depends(get_current_user)):
    """Langfuse traces for the Continuum agent (tag='continuum').
    Same shape as /agents_v2/{id}/traces so the Control Panel can reuse
    its report rendering. `enabled: false` when Langfuse isn't configured."""
    return tracing.fetch_agent_traces("continuum", limit=min(limit, 100))


@router.post("/meetings/{meeting_id}/reprocess")
def reprocess_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retry auto-processing for a recorded meeting (e.g. after a failed
    run). Idempotent — a meeting with a completed run is skipped."""
    meeting = (
        db.query(Meeting)
        .filter(
            Meeting.id == meeting_id,
            Meeting.organization_id == user.organization_id,
        )
        .first()
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    dispatch_continuum_process(meeting_id)
    return {"ok": True}
