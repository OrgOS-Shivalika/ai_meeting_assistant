"""One-off — provision the Continuum Core category for a user's org.

Idempotent: safe to rerun. Just ensures the "Continuum Core" category
exists in the caller's org. Client rows (teams) are created on demand
by the user via the board UI or API.

Run:
    python -m scripts.setup_continuum_for_user [email]

Default email: divyansh.bhardwaj@smoothops.info
"""
from __future__ import annotations

import sys

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Category, ContinuumClient, User


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "divyansh.bhardwaj@smoothops.info"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"[FAIL] No user with email {email!r}")
            sys.exit(1)

        print(f"User:  {user.email}  (id={user.id})")
        print(f"Org:   {user.organization_id}")

        cat = (
            db.query(Category)
            .filter(
                Category.organization_id == user.organization_id,
                Category.name == settings.CONTINUUM_CATEGORY_NAME,
            )
            .first()
        )
        if cat is None:
            cat = Category(
                organization_id=user.organization_id,
                user_id=user.id,
                name=settings.CONTINUUM_CATEGORY_NAME,
                description="Client engagements tracked by the Continuum Core agent",
            )
            db.add(cat)
            db.commit()
            db.refresh(cat)
            print(f"[OK] Created Continuum Core category (id={cat.id})")
        else:
            print(f"[OK] Continuum Core category already exists (id={cat.id})")

        n_clients = (
            db.query(ContinuumClient)
            .filter(ContinuumClient.organization_id == user.organization_id)
            .count()
        )
        print(f"Clients on this org: {n_clients}")
        print()
        print("Done. Open /boards to see the pinned Continuum Core card,")
        print("or open /agent-control to configure the agent.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
