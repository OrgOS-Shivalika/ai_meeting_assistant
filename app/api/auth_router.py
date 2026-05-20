from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.models import User, Organization
from app.dependencies.auth import get_current_user
from app.services.auth_service import hash_password, verify_password, create_token
from app.schemas.auth_schema import UserCreate, UserLogin, Token

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Every new user gets a personal workspace organization. Multi-user invite
    # flows can attach additional users to existing orgs later.
    email_prefix = data.email.split("@", 1)[0].lower()
    org = Organization(
        name=f"{data.name}'s Workspace",
        slug=None,  # not user-facing yet; left unique-nullable
    )
    db.add(org)
    db.flush()

    # First user of a new workspace is its admin. They own provisioning,
    # behavior overrides, and any other org-admin gated actions. Future
    # invited users default to lower roles; that's a separate flow.
    user = User(
        name=data.name,
        email=data.email,
        password=hash_password(data.password),
        organization_id=org.id,
        role="org_admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _ = email_prefix  # reserved for future slug derivation

    # Phase 8B (refactored) — link-only auto-install of the starter
    # bundle. Creates `workspace_template_links` rows pointing at
    # `template_behavior_profiles`. NO prompt_version cloning. The
    # runtime resolver (Phase 8D) merges template defaults with any
    # workspace overrides at query time.
    #
    # Fire-and-forget: failures log + record a failed job row but do
    # NOT block signup. Admins can re-run via /templates/provision.
    from app.config.settings import settings as _settings
    if _settings.TEMPLATE_AUTO_PROVISION_BUNDLE:
        try:
            from app.services.behavior.provisioning import (
                auto_install_starter,
            )
            auto_install_starter(
                db,
                organization_id=org.id,
                user_id=user.id,
                bundle_slug=_settings.TEMPLATE_AUTO_PROVISION_BUNDLE,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "auto-install crashed for new org=%s; signup proceeds",
                org.id, exc_info=True,
            )

    return {"message": "User created", "user_id": str(user.id), "organization_id": str(org.id)}

@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_token({"user_id": str(user.id)})

    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """Return the authenticated user plus their organization. The frontend
    uses this to render identity in the sidebar and gate org-scoped actions."""
    org = user.organization
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "google_profile_picture": user.google_profile_picture,
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "slug": org.slug,
        } if org else None,
    }