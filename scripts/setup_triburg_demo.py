"""Provision the Triburg demo workspace end to end.

Creates everything the Size Set feature needs to be reachable by one login:

    organization  Triburg
    user          demo@triburg.com  (ORG_ADMIN)
    category      <SIZESET_CATEGORY_NAME>   e.g. "Quality Team"
    team          Size Set

Why ORG_ADMIN and not MEMBER: `POST /api/sizeset/from-meeting/{id}` guards with
`permissions.get_viewable_meeting`, and a MEMBER only sees meetings they
ATTENDED via a trusted participant link. A demo account that did not sit in the
call would get a 403 on every meeting. ORG_ADMIN sees the whole org, which is
what a demo needs.

`must_change_password=False` so the account logs straight in — the normal
provisioning flow forces a reset on first login, which is wrong for a demo.

Idempotent: re-running reports the existing rows and resets the password.

    python -m scripts.setup_triburg_demo
    python -m scripts.setup_triburg_demo --password "something-else"
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Category, Organization, Team, User  # noqa: E402
from app.services.auth_service import hash_password  # noqa: E402
from app.utils.admin_enums import AccessRole  # noqa: E402

ORG_NAME = "Triburg"
EMAIL = "demo@triburg.com"
DISPLAY_NAME = "Triburg Demo"
TEAM_NAME = "Size Set"
DEFAULT_PASSWORD = "TriburgDemo@2026"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default=EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--org", default=ORG_NAME)
    args = parser.parse_args()

    category_name = (settings.SIZESET_CATEGORY_NAME or "").strip()
    if not category_name:
        print(
            "SIZESET_CATEGORY_NAME is empty, so every category is allowed and "
            "there is no specific one to create. Set it first."
        )
        return 1

    db = SessionLocal()
    try:
        # --- organization ---
        org = (
            db.query(Organization)
            .filter(func.lower(Organization.name) == args.org.lower())
            .first()
        )
        if org is None:
            org = Organization(name=args.org)
            db.add(org)
            db.commit()
            db.refresh(org)
            print(f"created organization {org.id} {org.name!r}")
        else:
            print(f"organization {org.id} {org.name!r} already exists")

        # --- user ---
        email = args.email.strip().lower()
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if user is None:
            user = User(
                name=DISPLAY_NAME,
                email=email,
                password=hash_password(args.password),
                organization_id=org.id,
                access_role=AccessRole.ORG_ADMIN.value,
                must_change_password=False,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"created user {email} as {user.access_role}")
        else:
            # Re-running is how you recover a forgotten demo password.
            user.password = hash_password(args.password)
            user.must_change_password = False
            user.access_role = AccessRole.ORG_ADMIN.value
            if user.organization_id != org.id:
                print(
                    f"  WARNING: {email} already belongs to another organization "
                    f"({user.organization_id}); leaving it there rather than "
                    f"moving a live account between tenants"
                )
            db.commit()
            print(f"user {email} already exists — password reset, role ORG_ADMIN")

        if hasattr(user, "password_set_at"):
            user.password_set_at = datetime.now(timezone.utc)
            db.commit()

        owning_org_id = user.organization_id

        # --- category ---
        # Created in the user's OWN org, which may differ from the one above if
        # the account pre-existed. Putting it anywhere else would leave the
        # demo login unable to see it.
        category = (
            db.query(Category)
            .filter(
                Category.organization_id == owning_org_id,
                func.lower(Category.name) == category_name.lower(),
            )
            .first()
        )
        if category is None:
            category = Category(
                organization_id=owning_org_id,
                user_id=user.id,
                name=category_name,
                description="Garment size-set inspection reviews.",
            )
            db.add(category)
            db.commit()
            db.refresh(category)
            print(f"created category {category.id} {category_name!r}")
        else:
            # The gate compares with ==, so a case difference disables the
            # feature silently.
            if category.name != category_name:
                category.name = category_name
                db.commit()
                print(f"renamed category {category.id} to {category_name!r}")
            else:
                print(f"category {category.id} {category_name!r} already exists")

        # --- team ---
        team = (
            db.query(Team)
            .filter(
                Team.category_id == category.id,
                func.lower(Team.name) == TEAM_NAME.lower(),
            )
            .first()
        )
        if team is None:
            team = Team(category_id=category.id, name=TEAM_NAME)
            db.add(team)
            db.commit()
            db.refresh(team)
            print(f"created team {team.id} {TEAM_NAME!r}")
        else:
            print(f"team {team.id} {TEAM_NAME!r} already exists")

        print("\n--- ready ---")
        print(f"  login      {email} / {args.password}")
        print(f"  org        {owning_org_id}")
        print(f"  category   {category.id} {category_name!r}  <- file meetings here")
        print(f"  team       {team.id} {TEAM_NAME!r}")
        print(
            "\nStart the Size Set service, then open a meeting filed under "
            f"{category_name!r} — 'Generate Size Set' appears on its detail page."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
