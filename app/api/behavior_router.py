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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import Category, Team, User, WorkspaceTemplateLink
from app.dependencies.auth import get_current_user, require_org_admin
from app.services.behavior.overrides import (
    BEHAVIOR_DIMENSIONS, OverrideError,
    count_overrides_for_scope, delete_all_overrides_for_scope,
    delete_override, get_overrides_for_scope, set_override,
)
from app.services.behavior.resolver import resolve_behavior_profile
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/behavior", tags=["Behavior"])


# ---------------------------------------------------------------------------
# Scope sidebar payload
# ---------------------------------------------------------------------------


class ScopeListItem(BaseModel):
    """One row in the sidebar tree.

      - id: the workspace `categories` row id (int).
      - kind: 'category' (top-level department) or 'team' (sub-team).
      - parent_id: for teams, the categories.id of the parent
                   department. None for categories.

    The sidebar tree builder uses parent_id to nest teams under
    their categories."""
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


@router.get("/scopes", response_model=ScopesResponse)
def get_scopes(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Sidebar payload. Categories + teams installed in the workspace,
    plus the override count for each so the UI can render badges
    without N round-trips."""
    workspace_overrides = count_overrides_for_scope(
        db, organization_id=user.organization_id, scope_type="workspace",
    )

    # Pull all the org's links so we can attach template_slug/version
    # to each scope row. Keyed by (entity_type, entity_id_int) since
    # categories.id and teams.id collide on their own.
    links = (
        db.query(WorkspaceTemplateLink)
        .filter(WorkspaceTemplateLink.organization_id == user.organization_id)
        .all()
    )
    link_by_kind_id: dict[tuple[str, int], WorkspaceTemplateLink] = {}
    for ln in links:
        if ln.entity_id_int is None:
            continue
        link_by_kind_id[(ln.entity_type, ln.entity_id_int)] = ln

    # Categories (departments).
    cats = (
        db.query(Category)
        .filter(Category.organization_id == user.organization_id)
        .order_by(Category.name.asc())
        .all()
    )
    cat_items: list[ScopeListItem] = []
    for c in cats:
        link = link_by_kind_id.get(("category", c.id))
        slug = link.source_template_slug if link else None
        version = link.source_template_version if link else None
        oc = count_overrides_for_scope(
            db, organization_id=user.organization_id,
            scope_type="category", scope_id=c.id,
        )
        cat_items.append(ScopeListItem(
            id=c.id, kind="category", name=c.name, parent_id=None,
            template_slug=slug, template_version=version,
            override_count=oc,
        ))

    # Teams nest under categories via teams.category_id.
    teams = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Category.organization_id == user.organization_id)
        .order_by(Team.name.asc())
        .all()
    )
    team_items: list[ScopeListItem] = []
    for t in teams:
        link = link_by_kind_id.get(("team", t.id))
        slug = link.source_template_slug if link else None
        version = link.source_template_version if link else None
        oc = count_overrides_for_scope(
            db, organization_id=user.organization_id,
            scope_type="team", scope_id=t.id,
        )
        team_items.append(ScopeListItem(
            id=t.id, kind="team", name=t.name, parent_id=t.category_id,
            template_slug=slug, template_version=version,
            override_count=oc,
        ))

    return ScopesResponse(
        workspace_overrides_count=workspace_overrides,
        categories=cat_items,
        teams=team_items,
    )


# ---------------------------------------------------------------------------
# Resolve — read the full merged BehaviorProfile
# ---------------------------------------------------------------------------


class ResolvedBehaviorResponse(BaseModel):
    """The runtime ResolvedBehaviorProfile, flattened for the
    frontend. All 11 dimensions plus the trace (which layer
    contributed each one)."""
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

    trace: list[dict]


def _assert_scope_owned_by_org(
    db: Session, *, organization_id: UUID, scope_id: Optional[int],
    scope_type: Optional[str] = None,
) -> None:
    """Cross-org guard. Returns 404 if the scope_id is set and does
    not belong to the caller's org. `scope_type` disambiguates between
    categories.id and teams.id namespaces (they have separate
    sequences). If scope_type is None, the id is checked against both
    tables — useful when the caller doesn't know which kind a generic
    id refers to."""
    if scope_id is None:
        return
    if scope_type == "team":
        found = (
            db.query(Team.id)
            .join(Category, Team.category_id == Category.id)
            .filter(
                Team.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
    elif scope_type == "category":
        found = (
            db.query(Category.id)
            .filter(
                Category.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
    else:
        # Permissive: check either table. Used by /resolve which gets
        # category_id/team_id as separate params and validates each
        # against the appropriate table via the typed callers below.
        cat = (
            db.query(Category.id)
            .filter(
                Category.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
        team = (
            db.query(Team.id)
            .join(Category, Team.category_id == Category.id)
            .filter(
                Team.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
        found = cat or team
    if found is None:
        raise HTTPException(status_code=404, detail="Scope not found")


@router.get("/resolve", response_model=ResolvedBehaviorResponse)
def get_resolved_behavior(
    category_id: Optional[int] = Query(default=None, ge=1),
    team_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Resolve the merged BehaviorProfile for (workspace, category?,
    team?). Read this on every accordion expand to get the live
    inherited value plus its source."""
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=category_id,
        scope_type="category",
    )
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=team_id,
        scope_type="team",
    )
    bp = resolve_behavior_profile(
        db, organization_id=user.organization_id,
        category_id=category_id, team_id=team_id,
    )
    return ResolvedBehaviorResponse(**bp.to_dict())


# ---------------------------------------------------------------------------
# Overrides CRUD
# ---------------------------------------------------------------------------


class OverridesResponse(BaseModel):
    """Sparse overrides for one scope. Shape:
    `{dimension: {field: value}}`. Empty dict if no overrides."""
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["workspace", "category", "team"]
    scope_id: Optional[int]
    overrides: dict
    count: int


def _scope_kind_to_scope_type(scope_type: str) -> str:
    if scope_type not in ("workspace", "category", "team"):
        raise HTTPException(
            status_code=400, detail=f"invalid scope_type {scope_type!r}",
        )
    return scope_type


@router.get("/overrides", response_model=OverridesResponse)
def get_overrides(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if scope_type == "workspace" and scope_id is not None:
        raise HTTPException(
            400, "scope_type='workspace' must not include scope_id",
        )
    if scope_type in ("category", "team") and scope_id is None:
        raise HTTPException(
            400, f"scope_type={scope_type!r} requires scope_id",
        )
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=scope_id,
        scope_type=scope_type if scope_type != 'workspace' else None,
    )
    overrides = get_overrides_for_scope(
        db, organization_id=user.organization_id,
        scope_type=scope_type, scope_id=scope_id,
    )
    count = sum(len(fields) for fields in overrides.values())
    return OverridesResponse(
        scope_type=scope_type, scope_id=scope_id,
        overrides=overrides, count=count,
    )


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


@router.put("/overrides", response_model=OverrideRowResponse)
def put_override(
    payload: SetOverrideRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Upsert one override row. Idempotent on the natural key
    (org, scope, dimension, field)."""
    if payload.dimension not in BEHAVIOR_DIMENSIONS:
        raise HTTPException(
            400, f"unknown dimension {payload.dimension!r}",
        )
    if payload.scope_type == "workspace" and payload.scope_id is not None:
        raise HTTPException(
            400, "scope_type='workspace' must not include scope_id",
        )
    if payload.scope_type in ("category", "team") and payload.scope_id is None:
        raise HTTPException(
            400, f"scope_type={payload.scope_type!r} requires scope_id",
        )
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=payload.scope_id,
        scope_type=payload.scope_type if payload.scope_type != 'workspace' else None,
    )
    try:
        row = set_override(
            db, organization_id=user.organization_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            dimension=payload.dimension,
            field=payload.field,
            value=payload.value,
            actor_user_id=user.id,
        )
    except OverrideError as exc:
        raise HTTPException(400, str(exc))
    return OverrideRowResponse(
        id=str(row.id),
        scope_type=row.scope_type,
        scope_id=row.scope_id_int,
        dimension=row.dimension,
        field=row.field or "",
        value=row.value_json,
    )


class DeleteOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["workspace", "category", "team"]
    scope_id: Optional[int] = Field(default=None, ge=1)
    dimension: str = Field(..., max_length=40)
    field: str = Field(default="", max_length=80)


@router.delete("/overrides")
def delete_one_override(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    dimension: str = Query(..., max_length=40),
    field: str = Query(default="", max_length=80),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Remove a single override (reset that field to inherited)."""
    if dimension not in BEHAVIOR_DIMENSIONS:
        raise HTTPException(400, f"unknown dimension {dimension!r}")
    if scope_type == "workspace" and scope_id is not None:
        raise HTTPException(
            400, "scope_type='workspace' must not include scope_id",
        )
    if scope_type in ("category", "team") and scope_id is None:
        raise HTTPException(400, f"scope_type={scope_type!r} requires scope_id")
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=scope_id,
        scope_type=scope_type if scope_type != 'workspace' else None,
    )
    deleted = delete_override(
        db, organization_id=user.organization_id,
        scope_type=scope_type, scope_id=scope_id,
        dimension=dimension, field=field,
    )
    return {"deleted": deleted}


@router.delete("/overrides/scope")
def delete_scope_overrides(
    scope_type: Literal["workspace", "category", "team"] = Query(...),
    scope_id: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    """Reset an entire scope back to inheriting from below. Returns
    count of rows deleted. Replaces the old `/templates/links/{id}/reset`
    endpoint."""
    if scope_type == "workspace" and scope_id is not None:
        raise HTTPException(
            400, "scope_type='workspace' must not include scope_id",
        )
    if scope_type in ("category", "team") and scope_id is None:
        raise HTTPException(400, f"scope_type={scope_type!r} requires scope_id")
    _assert_scope_owned_by_org(
        db, organization_id=user.organization_id, scope_id=scope_id,
        scope_type=scope_type if scope_type != 'workspace' else None,
    )
    n = delete_all_overrides_for_scope(
        db, organization_id=user.organization_id,
        scope_type=scope_type, scope_id=scope_id,
    )
    return {"deleted_count": n}
