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

from app.db.models import Category, KanbanBoard, Team
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


def _visible_teams_option(db: Session, user):
    """Loader option that eager-loads only the teams ``user`` may see.

    `CategorySchema.teams` reads `category.teams`, so any Category handed
    to the router serializes its whole team collection — a plain
    `joinedload` (or a lazy load) therefore publishes every team in the
    category regardless of what the caller is scoped to. The filter has
    to ride along with the load itself, which is what
    `relationship.and_()` is for.
    """
    clause = permissions.team_view_clause(db, user)
    if clause is None:
        return joinedload(Category.teams)
    return joinedload(Category.teams.and_(clause))


def get_owned_category(db: Session, user, category_id: int, *, manage: bool = False) -> Category:
    """Fetch a category the caller may read (or manage).

    Name kept for its many call sites, but "owned" is now the wrong word:
    access comes from a `category_admins` grant or from having attended a
    meeting in the category, not from `categories.user_id` (which only
    records who created it).

    Teams are eager-loaded pre-filtered, because `GET /categories/{id}`
    returns this row straight through `CategorySchema`, which renders
    `teams`. Applied here rather than at that one route so a future
    caller can't reintroduce the leak by serializing the same object.
    """
    category = (
        db.query(Category)
        .options(_visible_teams_option(db, user))
        .filter(Category.id == category_id)
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Meeting type not found")
    if category.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    permissions.require_category_access(db, user, category_id, manage=manage)
    return category


def get_owned_team(db: Session, user, team_id: int, *, manage: bool = False) -> Team:
    """Fetch a team the caller may reach.

    Gated on the TEAM, not merely on its parent category. Category access
    is satisfied by any grant inside the category, so checking it here let
    someone scoped to one team read a sibling team they hold nothing on.
    """
    team = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Team.id == team_id, Category.organization_id == user.organization_id)
        .first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    permissions.require_team_access(db, user, team, manage=manage)
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
        .options(_visible_teams_option(db, user))
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


def _checked_board_id(db: Session, user, board_id):
    """Validate a `default_board_id` before it is stored, or raise.

    ``None`` passes straight through — that is "clear the choice and inherit",
    not a reference to validate.

    The bar is **same organization**, enforced here because the FK cannot: a
    board carries its own ``organization_id`` and so does the category, so
    Postgres will happily accept a pointer that crosses tenants. That pointer
    is read on the task-insert path, so an unchecked one would file one org's
    action items onto another org's board — a silent cross-tenant leak on a
    surface nobody would think to audit.

    Deliberately NOT gated on ``board_view_clause``. A category admin often
    cannot "see" an empty org-wide board (visibility there is derived from the
    cards it holds), and that is the most natural board to point at. Tenancy
    is the security boundary; who may open the board is a separate question
    governed by the board endpoints themselves.
    """
    if board_id is None:
        return None
    board = (
        db.query(KanbanBoard.id)
        .filter(
            KanbanBoard.id == board_id,
            KanbanBoard.organization_id == user.organization_id,
        )
        .first()
    )
    if board is None:
        # 404, not 403: a board in another tenant must not be distinguishable
        # from one that does not exist. Same rule the meeting endpoints use.
        raise HTTPException(status_code=404, detail="Board not found")
    return board_id


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
    # `default_board_id_set` and not `is not None`: null is a MEANINGFUL value
    # here ("inherit the org default"), so the flag is the only way to tell
    # "clear it" from "leave it alone".
    if payload.default_board_id_set:
        category.default_board_id = _checked_board_id(
            db, user, payload.default_board_id,
        )
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
    """The teams in a category that the caller may see.

    Reaching the category is not the same as reaching everything in it —
    a grant on one team must not enumerate its siblings.
    """
    get_owned_category(db, user, category_id)
    query = db.query(Team).filter(Team.category_id == category_id)
    clause = permissions.team_view_clause(db, user)
    if clause is not None:
        query = query.filter(clause)
    return query.order_by(Team.created_at.asc()).all()


def create_team(db: Session, user, category_id: int, payload: TeamCreate) -> Team:
    # The returned row is used below for the Continuum client check. The
    # binding was dropped when this file was merged, which left
    # `category.name` raising NameError AFTER the team had already been
    # committed — so team creation 500'd while still creating the team.
    category = get_owned_category(db, user, category_id, manage=True)
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
    # NULL means "inherit the category's board" — see `update_category`.
    if payload.default_board_id_set:
        team.default_board_id = _checked_board_id(
            db, user, payload.default_board_id,
        )
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
