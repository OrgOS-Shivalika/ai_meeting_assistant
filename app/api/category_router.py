from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.services import category_service
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
# `/categories` (existing surface)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CategorySchema])
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return category_service.list_categories(db, user)


@router.post("", response_model=CategorySchema, status_code=201)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.create_category(db, user, payload)


@router.get("/{category_id}", response_model=CategorySchema)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = category_service.get_owned_category(db, user, category_id)
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
    return category_service.update_category(db, user, category_id, payload)


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.delete_category(db, user, category_id)


@router.get("/{category_id}/teams", response_model=list[TeamSchema])
def list_teams(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.list_teams(db, user, category_id)


@router.post("/{category_id}/teams", response_model=TeamSchema, status_code=201)
def create_team(
    category_id: int,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.create_team(db, user, category_id, payload)


# ---------------------------------------------------------------------------
# `/meeting-types` alias surface (matches meeting-types-architecture.md)
# ---------------------------------------------------------------------------


@meeting_types_router.get("", response_model=list[CategorySchema])
def mt_list(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return category_service.list_categories(db, user)


@meeting_types_router.post("", response_model=CategorySchema, status_code=201)
def mt_create(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.create_category(db, user, payload)


@meeting_types_router.get("/{meeting_type_id}", response_model=CategorySchema)
def mt_get(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = category_service.get_owned_category(db, user, meeting_type_id)
    _ = category.teams
    return category


@meeting_types_router.patch("/{meeting_type_id}", response_model=CategorySchema)
def mt_update(
    meeting_type_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.update_category(db, user, meeting_type_id, payload)


@meeting_types_router.delete("/{meeting_type_id}")
def mt_delete(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.delete_category(db, user, meeting_type_id)


@meeting_types_router.get("/{meeting_type_id}/teams", response_model=list[TeamSchema])
def mt_teams_list(
    meeting_type_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.list_teams(db, user, meeting_type_id)


@meeting_types_router.post("/{meeting_type_id}/teams", response_model=TeamSchema, status_code=201)
def mt_teams_create(
    meeting_type_id: int,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.create_team(db, user, meeting_type_id, payload)


# ---------------------------------------------------------------------------
# `/teams` (single-team handlers)
# ---------------------------------------------------------------------------


@team_router.get("/{team_id}", response_model=TeamSchema)
def get_team(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.get_owned_team(db, user, team_id)


@team_router.patch("/{team_id}", response_model=TeamSchema)
def update_team(
    team_id: int,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.update_team(db, user, team_id, payload)


@team_router.delete("/{team_id}")
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return category_service.delete_team(db, user, team_id)
