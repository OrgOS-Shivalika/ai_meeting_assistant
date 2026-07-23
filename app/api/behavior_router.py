"""Phase 8E — Behavior orchestration HTTP layer.

The Agent Control dashboard talks to these endpoints. They are
behavior-centric, not template-centric:

  GET  /behavior/scopes
       Sidebar payload: workspace defaults + installed categories +
       installed teams. The UI uses this to render the scope tree.

  GET  /behavior/resolve
       Full ResolvedBehaviorProfile for a (category_id?, team_id?)
       context. Drives the read-side of the editor — what every
       dimension currently looks like AFTER inheritance.

  GET  /behavior/overrides
       Sparse overrides for one scope. Drives the "is this field
       locally overridden?" indicator + the override count badge.

  PUT  /behavior/overrides
       Upsert a single (scope, dimension, field) override. Idempotent.

  DELETE /behavior/overrides
       Remove a single override (i.e. reset to inherited).

  DELETE /behavior/overrides/scope
       Reset an entire scope (wipe all overrides for it).

Auth model:
  - Reads (scopes, resolve, overrides GET): any authenticated user.
  - Writes (PUT / DELETE): require org_admin. Touching AI behavior
    is a real production change.

Cross-org isolation:
  - Every endpoint filters by `user.organization_id`. Category/team
    scope_ids that don't belong to the caller return 404.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user, require_org_admin
from app.services.behavior.overrides import (
    BEHAVIOR_DIMENSIONS, OverrideError,
    delete_all_overrides_for_scope,
    delete_override, get_overrides_for_scope, set_override,
)
from app.services.behavior.resolver import resolve_behavior_profile
from app.services.behavior.scopes import (
    assert_scope_owned_by_org as _assert_scope_owned_by_org,
    get_scope_tree,
)
from app.utils.logger import setup_logger
from app.schemas.intent_schema import IntentProfile

logger = setup_logger(__name__)

router = APIRouter(prefix="/behavior", tags=["Behavior"])


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ScopeListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    kind: Literal["category", "team"]
    name: str
    parent_id: Optional[int] = None
    template_slug: Optional[str] = None
    template_version: Optional[str] = None
    override_count: int = 0

class ScopesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_overrides_count: int
    categories: list[ScopeListItem]
    teams: list[ScopeListItem]

class ResolvedBehaviorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: str
    category_id: Optional[int]
    team_id: Optional[int]
    master_prompt: dict
    enabled_agents: list
    retrieval_config: dict
    memory_config: dict
    output_config: dict
    extraction_rules: dict
    automation_rules: dict
    evaluation_rules: dict
    tone_and_personality: dict
    compliance_and_guardrails: dict
    tools_and_integrations: dict
    intent: dict
    trace: list[dict]

class OverridesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: Literal["workspace", "category", "team"]
    scope_id: Optional[int]
    overrides: dict
    count: int

class SetOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: Literal["workspace", "category", "team"]
    scope_id: Optional[int] = Field(default=None, ge=1)
    dimension: str = Field(..., max_length=40)
    field: str = Field(default="", max_length=80)
    value: Any

class OverrideRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    scope_type: str
    scope_id: Optional[int]
    dimension: str
    field: str
    value: Any

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/scopes", response_model=ScopesResponse)
def get_scopes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return ScopesResponse(**get_scope_tree(db, organization_id=user.organization_id))

@router.get("/resolve", response_model=ResolvedBehaviorResponse)
def get_resolved_behavior(
    category_id: Optional[int] = Query(default=None, ge=1),
    team_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=category_id, scope_type="category")
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=team_id, scope_type="team")
    bp = resolve_behavior_profile(db, organization_id=user.organization_id, category_id=category_id, team_id=team_id)
    return ResolvedBehaviorResponse(**bp.to_dict())

@router.get("/intent", response_model=IntentProfile)
def get_intent(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=scope_id, scope_type=scope_type if scope_type != 'workspace' else None)
    overrides = get_overrides_for_scope(db, organization_id=user.organization_id, scope_type=scope_type, scope_id=scope_id)
    intent_data = overrides.get("intent", {}).get("") or {}
    return IntentProfile.model_validate(intent_data)

@router.put("/intent", response_model=OverrideRowResponse)
def put_intent(
    intent: IntentProfile,
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(require_org_admin)
):
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=scope_id, scope_type=scope_type if scope_type != 'workspace' else None)
    row = set_override(db, organization_id=user.organization_id, scope_type=scope_type, scope_id=scope_id, dimension="intent", field="", value=intent.model_dump(), actor_user_id=user.id)
    return OverrideRowResponse(id=str(row.id), scope_type=row.scope_type, scope_id=row.scope_id_int, dimension=row.dimension, field=row.field or "", value=row.value_json)

@router.get("/overrides", response_model=OverridesResponse)
def get_overrides(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if scope_type == "workspace" and scope_id is not None: raise HTTPException(400, "workspace requires no id")
    if scope_type in ("category", "team") and scope_id is None: raise HTTPException(400, f"{scope_type} requires id")
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=scope_id, scope_type=scope_type if scope_type != 'workspace' else None)
    overrides = get_overrides_for_scope(db, organization_id=user.organization_id, scope_type=scope_type, scope_id=scope_id)
    return OverridesResponse(scope_type=scope_type, scope_id=scope_id, overrides=overrides, count=sum(len(v) for v in overrides.values()))

@router.put("/overrides", response_model=OverrideRowResponse)
def put_override(payload: SetOverrideRequest, db: Session = Depends(get_db), user: User = Depends(require_org_admin)):
    if payload.dimension not in BEHAVIOR_DIMENSIONS: raise HTTPException(400, f"unknown dim {payload.dimension}")
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=payload.scope_id, scope_type=payload.scope_type if payload.scope_type != 'workspace' else None)
    try:
        row = set_override(db, organization_id=user.organization_id, scope_type=payload.scope_type, scope_id=payload.scope_id, dimension=payload.dimension, field=payload.field, value=payload.value, actor_user_id=user.id)
    except OverrideError as exc: raise HTTPException(400, str(exc))
    return OverrideRowResponse(id=str(row.id), scope_type=row.scope_type, scope_id=row.scope_id_int, dimension=row.dimension, field=row.field or "", value=row.value_json)

@router.delete("/overrides")
def delete_one_override(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    dimension: str = Query(..., max_length=40),
    field: str = Query(default="", max_length=80),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(require_org_admin)
):
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=scope_id, scope_type=scope_type if scope_type != 'workspace' else None)
    return {"deleted": delete_override(db, organization_id=user.organization_id, scope_type=scope_type, scope_id=scope_id, dimension=dimension, field=field)}

@router.delete("/overrides/scope")
def delete_scope_overrides(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db), user: User = Depends(require_org_admin)
):
    _assert_scope_owned_by_org(db, organization_id=user.organization_id, scope_id=scope_id, scope_type=scope_type if scope_type != 'workspace' else None)
    return {"deleted_count": delete_all_overrides_for_scope(db, organization_id=user.organization_id, scope_type=scope_type, scope_id=scope_id)}
