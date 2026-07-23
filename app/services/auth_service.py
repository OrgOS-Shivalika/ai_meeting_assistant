from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.config.settings import settings
from app.db.models import User, Organization
from app.schemas.auth_schema import UserCreate, UserLogin

SECRET_KEY = settings.AUTH_SECRET_KEY
ALGORITHM = settings.ALGORITHM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str):
    return pwd_context.verify(password, hashed)

def create_token(data: dict):
    payload = data.copy()
    # 7-day TTL: the 1-day TTL was kicking users out every time they
    # opened a tab the next morning. The Phase 2/3/4 pipelines are
    # long-running enough that "refresh and get 401" is a real annoyance
    # — bump it. Real refresh-token flow can come later if anyone cares.
    payload["exp"] = datetime.now(timezone.utc) + timedelta(days=7)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def register_user(db: Session, data: UserCreate) -> dict:
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


def authenticate_user(db: Session, data: UserLogin) -> User:
    user = db.query(User).filter(User.email == data.email).first()

    if not user or not verify_password(data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user