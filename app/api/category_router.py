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

router = APIRouter(prefix="/categories", tags=["categories"])
team_router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("", response_model=list[CategorySchema])
def list_categories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return (
        db.query(Category)
        .options(joinedload(Category.teams))
        .filter(Category.user_id == user.id)
        .order_by(Category.created_at.asc())
        .all()
    )


@router.post("", response_model=CategorySchema, status_code=201)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = Category(user_id=user.id, name=payload.name.strip(), color=payload.color)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Category with this name already exists")
    db.refresh(category)
    return category


def _get_owned_category(db: Session, user, category_id: int) -> Category:
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return category


@router.patch("/{category_id}", response_model=CategorySchema)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = _get_owned_category(db, user, category_id)
    if payload.name is not None:
        category.name = payload.name.strip()
    if payload.color is not None:
        category.color = payload.color
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Category with this name already exists")
    db.refresh(category)
    return category


@router.delete("/{category_id}")
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    category = _get_owned_category(db, user, category_id)
    db.delete(category)
    db.commit()
    return {"status": "ok", "deleted_id": category_id}


@router.get("/{category_id}/teams", response_model=list[TeamSchema])
def list_teams(
    category_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_category(db, user, category_id)
    return (
        db.query(Team)
        .filter(Team.category_id == category_id)
        .order_by(Team.created_at.asc())
        .all()
    )


@router.post("/{category_id}/teams", response_model=TeamSchema, status_code=201)
def create_team(
    category_id: int,
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _get_owned_category(db, user, category_id)
    team = Team(category_id=category_id, name=payload.name.strip())
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team with this name already exists in this category")
    db.refresh(team)
    return team


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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Team with this name already exists in this category")
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
