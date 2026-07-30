"""Database logic for meeting types (categories) and teams.

Extracted from ``app/api/category_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership / integrity failures — this
mirrors the existing convention (see ``auth_service``) and keeps behaviour
identical to the previous in-router helpers.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.db.models import Category, Team
from app.services import permissions
from app.schemas.category_schema import (
    CategoryCreate,
    CategoryUpdate,
    TeamCreate,
    TeamUpdate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


def get_owned_category(db: Session, user, category_id: int, *, manage: bool = False) -> Category:
    """Fetch a category the caller may read (or manage).

    Name kept for its many call sites, but "owned" is now the wrong word:
    access comes from a `category_admins` grant or from having attended a
    meeting in the category, not from `categories.user_id` (which only
    records who created it).
    """
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Meeting type not found")
    if category.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    permissions.require_category_access(db, user, category_id, manage=manage)
    return category


def get_owned_team(db: Session, user, team_id: int, *, manage: bool = False) -> Team:
    """Fetch a team, gated on access to its parent category — a team has
    no access rules of its own."""
    team = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Team.id == team_id, Category.organization_id == user.organization_id)
        .first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    permissions.require_category_access(db, user, team.category_id, manage=manage)
    return team


# ---------------------------------------------------------------------------
# Category / meeting-type operations
# ---------------------------------------------------------------------------


def list_categories(db: Session, user):
    """Categories the caller may see.

    Was org-scoped only, which meant granting an admin two categories
    changed nothing about what the categories list showed them — they
    still saw all of them.
    """
    query = (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.organization_id == user.organization_id)
    )
    clause = permissions.category_view_clause(db, user)
    if clause is not None:
        query = query.filter(clause)
    return query.order_by(Category.created_at.asc()).all()


def create_category(db: Session, user, payload: CategoryCreate) -> Category:
    # Adding a category changes the organization's structure, and the new
    # row carries no `category_admins` grant, so an admin creating one
    # would not even be able to manage it afterwards. Org admins only.
    permissions.require_org_admin_role(user)
    category = Category(
        organization_id=user.organization_id,
        user_id=user.id,
        name=payload.name.strip(),
        description=payload.description,
        color=payload.color,
        icon=payload.icon,
    )
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A meeting type with this name already exists")
    db.refresh(category)
    return category


def update_category(db: Session, user, category_id: int, payload: CategoryUpdate) -> Category:
    category = get_owned_category(db, user, category_id, manage=True)
    if payload.name is not None:
        category.name = payload.name.strip()
    if payload.description is not None:
        category.description = payload.description
    if payload.color is not None:
        category.color = payload.color
    if payload.icon is not None:
        category.icon = payload.icon
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A meeting type with this name already exists")
    db.refresh(category)
    return category


def delete_category(db: Session, user, category_id: int) -> dict:
    # Cascades to teams, documents and the category_admins grants. Too
    # destructive to hand to a category admin.
    permissions.require_org_admin_role(user)
    category = get_owned_category(db, user, category_id, manage=True)
    db.delete(category)
    db.commit()
    return {"status": "ok", "deleted_id": category_id}


# ---------------------------------------------------------------------------
# Team operations
# ---------------------------------------------------------------------------


def list_teams(db: Session, user, category_id: int):
    get_owned_category(db, user, category_id)
    return (
        db.query(Team)
        .filter(Team.category_id == category_id)
        .order_by(Team.created_at.asc())
        .all()
    )


def create_team(db: Session, user, category_id: int, payload: TeamCreate) -> Team:
    get_owned_category(db, user, category_id, manage=True)
    team = Team(
        category_id=category_id,
        name=payload.name.strip(),
        description=payload.description,
    )
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A team with this name already exists in this meeting type")
    db.refresh(team)

    # Continuum Core: a team in the Continuum category IS a client, so
    # creating one here must also create the linked client card —
    # otherwise meetings under this team would be silently skipped by
    # the Continuum pipeline. Mirror of what POST /continuum/clients
    # does in the other direction. Best-effort: a hiccup here must not
    # fail the team creation itself.
    from app.config.settings import settings as _settings
    if category.name == _settings.CONTINUUM_CATEGORY_NAME:
        try:
            from app.db.models import ContinuumClient
            exists = (
                db.query(ContinuumClient)
                .filter(
                    ContinuumClient.organization_id == user.organization_id,
                    (ContinuumClient.team_id == team.id)
                    | (ContinuumClient.name == team.name),
                )
                .first()
            )
            if exists is None:
                db.add(ContinuumClient(
                    organization_id=user.organization_id,
                    team_id=team.id,
                    name=team.name,
                ))
                db.commit()
            elif exists.team_id is None:
                # Same-named client orphaned earlier (e.g. its team was
                # deleted) — adopt this new team.
                exists.team_id = team.id
                db.commit()
        except Exception:
            db.rollback()
            logger.warning(
                "continuum: failed to auto-create client for team %s", team.id,
                exc_info=True,
            )

    return team


def update_team(db: Session, user, team_id: int, payload: TeamUpdate) -> Team:
    team = get_owned_team(db, user, team_id, manage=True)
    if payload.name is not None:
        team.name = payload.name.strip()
    if payload.description is not None:
        team.description = payload.description
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A team with this name already exists in this meeting type")
    db.refresh(team)
    return team


def delete_team(db: Session, user, team_id: int) -> dict:
    team = get_owned_team(db, user, team_id, manage=True)
    db.delete(team)
    db.commit()
    return {"status": "ok", "deleted_id": team_id}
