"""Database logic for meeting types (categories) and teams.

Extracted from ``app/api/category_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus the current
user and raise ``HTTPException`` for ownership / integrity failures — this
mirrors the existing convention (see ``auth_service``) and keeps behaviour
identical to the previous in-router helpers.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.db.models import Category, Team
from app.schemas.category_schema import (
    CategoryCreate,
    CategoryUpdate,
    TeamCreate,
    TeamUpdate,
)


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------


def get_owned_category(db: Session, user, category_id: int) -> Category:
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Meeting type not found")
    if category.organization_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return category


def get_owned_team(db: Session, user, team_id: int) -> Team:
    team = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Team.id == team_id, Category.organization_id == user.organization_id)
        .first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


# ---------------------------------------------------------------------------
# Category / meeting-type operations
# ---------------------------------------------------------------------------


def list_categories(db: Session, user):
    return (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.organization_id == user.organization_id)
        .order_by(Category.created_at.asc())
        .all()
    )


def create_category(db: Session, user, payload: CategoryCreate) -> Category:
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
    category = get_owned_category(db, user, category_id)
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
    category = get_owned_category(db, user, category_id)
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
    get_owned_category(db, user, category_id)
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
    return team


def update_team(db: Session, user, team_id: int, payload: TeamUpdate) -> Team:
    team = get_owned_team(db, user, team_id)
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
    team = get_owned_team(db, user, team_id)
    db.delete(team)
    db.commit()
    return {"status": "ok", "deleted_id": team_id}
