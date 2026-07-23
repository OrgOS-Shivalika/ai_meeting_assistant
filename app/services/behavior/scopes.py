"""Phase 8E — scope ownership + scope-tree assembly.

Extracted from ``app/api/behavior_router.py`` so the router stays a
thin transport layer. Functions take the SQLAlchemy ``Session`` and
raise ``HTTPException`` for cross-org access — mirroring the isolation
convention used across the behavior endpoints.

Cross-org isolation: every query filters by ``organization_id``.
Category/team scope_ids that don't belong to the caller return 404.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.models import Category, Team, WorkspaceTemplateLink
from app.services.behavior.overrides import count_overrides_for_scope


def assert_scope_owned_by_org(
    db: Session, *, organization_id: UUID, scope_id: Optional[int],
    scope_type: Optional[str] = None,
) -> None:
    if scope_id is None:
        return
    if scope_type == "team":
        found = db.query(Team.id).join(Category, Team.category_id == Category.id).filter(
            Team.id == scope_id, Category.organization_id == organization_id
        ).first()
    elif scope_type == "category":
        found = db.query(Category.id).filter(
            Category.id == scope_id, Category.organization_id == organization_id
        ).first()
    else:
        found = db.query(Category.id).filter(
            Category.id == scope_id, Category.organization_id == organization_id
        ).first() or db.query(Team.id).join(Category, Team.category_id == Category.id).filter(
            Team.id == scope_id, Category.organization_id == organization_id
        ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="Scope not found")


def get_scope_tree(db: Session, *, organization_id: UUID) -> dict:
    """Sidebar payload: workspace defaults + installed categories +
    installed teams, each with its template link + override count.

    Returns plain dicts (one per category/team) so the router can
    validate them into its `ScopesResponse` / `ScopeListItem` models.
    """
    workspace_overrides = count_overrides_for_scope(
        db, organization_id=organization_id, scope_type="workspace",
    )
    links = db.query(WorkspaceTemplateLink).filter(
        WorkspaceTemplateLink.organization_id == organization_id
    ).all()
    link_by_kind_id = {
        (ln.entity_type, ln.entity_id_int): ln
        for ln in links if ln.entity_id_int is not None
    }

    cats = db.query(Category).filter(
        Category.organization_id == organization_id
    ).order_by(Category.name.asc()).all()
    cat_items = []
    for c in cats:
        link = link_by_kind_id.get(("category", c.id))
        cat_items.append(dict(
            id=c.id, kind="category", name=c.name, parent_id=None,
            template_slug=link.source_template_slug if link else None,
            template_version=link.source_template_version if link else None,
            override_count=count_overrides_for_scope(
                db, organization_id=organization_id,
                scope_type="category", scope_id=c.id,
            ),
        ))

    teams = db.query(Team).join(Category, Team.category_id == Category.id).filter(
        Category.organization_id == organization_id
    ).order_by(Team.name.asc()).all()
    team_items = []
    for t in teams:
        link = link_by_kind_id.get(("team", t.id))
        team_items.append(dict(
            id=t.id, kind="team", name=t.name, parent_id=t.category_id,
            template_slug=link.source_template_slug if link else None,
            template_version=link.source_template_version if link else None,
            override_count=count_overrides_for_scope(
                db, organization_id=organization_id,
                scope_type="team", scope_id=t.id,
            ),
        ))

    return {
        "workspace_overrides_count": workspace_overrides,
        "categories": cat_items,
        "teams": team_items,
    }
