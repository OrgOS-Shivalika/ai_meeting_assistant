from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.api.db_dependency import get_db
from app.dependencies.auth import get_current_user
from app.db.models import Category, Team, Meeting
from app.schemas.category_schema import (
    CategoryCreate,
    CategoryUpdate,
    CategorySchema,
    TeamCreate,
    TeamUpdate,
    TeamSchema,
)

# Existing primary surface (kept for backward compatibility with the frontend
# that already uses `/categories`).
router = APIRouter(prefix="/categories", tags=["categories"])
team_router = APIRouter(prefix="/teams", tags=["teams"])

# Alias surface that fulfils the meeting-types-architecture.md API contract.
# Same handlers, mounted under `/meeting-types`. See main.py for inclusion.
meeting_types_router = APIRouter(prefix="/meeting-types", tags=["meeting-types"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_owned_category(db: Session, user, category_id: int) -> Category:
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Meeting type not found")
    if category.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return category


def _get_owned_team(db: Session, user, team_id: int) -> Team:
    team = (
        db.query(Team)
        .join(Category, Team.category_id == Category.id)
        .filter(Team.id == team_id, Category.user_id == user.id)
        .first()
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


# ---------------------------------------------------------------------------
# Category / Meeting-Type handlers (shared by both routers)
# ---------------------------------------------------------------------------


def _list_categories(db: Session, user):
    return (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.user_id == user.id)
        .order_by(Category.created_at.asc())
        .all()
    )


def _create_category(db: Session, user, payload: CategoryCreate) -> Category:
    category = Category(
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


def _update_category(db: Session, user, category_id: int, payload: CategoryUpdate) -> Category:
    category = _get_owned_category(db, user, category_id)
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


def _delete_category(db: Session, user, category_id: int) -> dict:
    category = _get_owned_category(db, user, category_id)
    db.delete(category)
    db.commit()
    return {"status": "ok", "deleted_id": category_id}


def _list_teams(db: Session, user, category_id: int):
    _get_owned_category(db, user, category_id)
    return (
        db.query(Team)
        .filter(Team.category_id == category_id)
        .order_by(Team.created_at.asc())
        .all()
    )


def _create_team(db: Session, user, category_id: int, payload: TeamCreate) -> Team:
    _get_owned_category(db, user, category_id)
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


# ---------------------------------------------------------------------------
# `/categories` (existing surface)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CategorySchema])
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _list_categories(db, user)


@router.post("", response_model=CategorySchema, status_code=201)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_category(db, user, payload)


@router.get("/{category_id}", response_model=CategorySchema)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = _get_owned_category(db, user, category_id)
    # ensure teams loaded
    _ = category.teams
    return category


@router.patch("/{category_id}", response_model=CategorySchema)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _update_category(db, user, category_id, payload)


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _delete_category(db, user, category_id)


@router.get("/{category_id}/teams", response_model=list[TeamSchema])
def list_teams(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _list_teams(db, user, category_id)


@router.post("/{category_id}/teams", response_model=TeamSchema, status_code=201)
def create_team(
    category_id: int,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_team(db, user, category_id, payload)


# ---------------------------------------------------------------------------
# `/meeting-types` alias surface (matches meeting-types-architecture.md)
# ---------------------------------------------------------------------------


@meeting_types_router.get("", response_model=list[CategorySchema])
def mt_list(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _list_categories(db, user)


@meeting_types_router.post("", response_model=CategorySchema, status_code=201)
def mt_create(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_category(db, user, payload)


@meeting_types_router.get("/{meeting_type_id}", response_model=CategorySchema)
def mt_get(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = _get_owned_category(db, user, meeting_type_id)
    _ = category.teams
    return category


@meeting_types_router.patch("/{meeting_type_id}", response_model=CategorySchema)
def mt_update(
    meeting_type_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _update_category(db, user, meeting_type_id, payload)


@meeting_types_router.delete("/{meeting_type_id}")
def mt_delete(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _delete_category(db, user, meeting_type_id)


@meeting_types_router.get("/{meeting_type_id}/teams", response_model=list[TeamSchema])
def mt_teams_list(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _list_teams(db, user, meeting_type_id)


@meeting_types_router.post("/{meeting_type_id}/teams", response_model=TeamSchema, status_code=201)
def mt_teams_create(
    meeting_type_id: int,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _create_team(db, user, meeting_type_id, payload)


# ---------------------------------------------------------------------------
# `/teams` (single-team handlers)
# ---------------------------------------------------------------------------


@team_router.get("/{team_id}", response_model=TeamSchema)
def get_team(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return _get_owned_team(db, user, team_id)


@team_router.patch("/{team_id}", response_model=TeamSchema)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    team = _get_owned_team(db, user, team_id)
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


@team_router.delete("/{team_id}")
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    team = _get_owned_team(db, user, team_id)
    db.delete(team)
    db.commit()
    return {"status": "ok", "deleted_id": team_id}
