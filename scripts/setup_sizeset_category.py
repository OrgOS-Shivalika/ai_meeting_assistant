"""Create the category that Size Set reports are generated in.

WHY THIS EXISTS: `settings.SIZESET_CATEGORY_NAME` gates the "Generate Size Set"
action on a meeting's category name. Setting that env var does nothing on its
own — if no category actually carries the name, the action renders nowhere and
the whole feature is invisible. Same shape as `setup_continuum_for_user.py`.

Idempotent: run it twice and the second run reports the existing rows.

    python -m scripts.setup_sizeset_category                    # busiest org
    python -m scripts.setup_sizeset_category --org <uuid>
    python -m scripts.setup_sizeset_category --team "Size Set"  # also add a team

`categories.user_id` is NOT NULL with ON DELETE CASCADE, so the owner is chosen
explicitly and reported — deleting that user would take the category, its teams
and its documents with it (landmine 14.13).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Category, Organization, Team, User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", help="organization UUID (default: most users)")
    parser.add_argument(
        "--name",
        default=settings.SIZESET_CATEGORY_NAME,
        help="category name; must match SIZESET_CATEGORY_NAME to have any effect",
    )
    parser.add_argument("--team", help="also create this team inside the category")
    args = parser.parse_args()

    wanted = (args.name or "").strip()
    if not wanted:
        print("SIZESET_CATEGORY_NAME is empty — every category is already allowed.")
        return 0

    db = SessionLocal()
    try:
        if args.org:
            org = db.query(Organization).filter(Organization.id == args.org).first()
            if org is None:
                print(f"no organization {args.org}")
                return 1
        else:
            # The org with the most users — on a dev box that is the one being
            # demoed. Explicit --org for anything else.
            org = (
                db.query(Organization)
                .join(User, User.organization_id == Organization.id)
                .group_by(Organization.id)
                .order_by(func.count(User.id).desc())
                .first()
            )
            if org is None:
                print("no organizations exist")
                return 1

        owner = (
            db.query(User)
            .filter(User.organization_id == org.id)
            .order_by(User.created_at.asc())
            .first()
        )
        if owner is None:
            print(f"organization {org.name!r} has no users to own the category")
            return 1

        category = (
            db.query(Category)
            .filter(
                Category.organization_id == org.id,
                func.lower(Category.name) == wanted.lower(),
            )
            .first()
        )
        if category is None:
            category = Category(
                organization_id=org.id,
                user_id=owner.id,
                name=wanted,
                description="Garment size-set inspection reviews.",
            )
            db.add(category)
            db.commit()
            db.refresh(category)
            print(f"created category {category.id} {wanted!r} in {org.name!r}")
        else:
            # Name must match EXACTLY — the gate compares with ==, so a
            # case difference silently disables the feature.
            if category.name != wanted:
                print(
                    f"category {category.id} is named {category.name!r} but the gate "
                    f"expects {wanted!r} — renaming so they match"
                )
                category.name = wanted
                db.commit()
            print(f"category {category.id} {wanted!r} already exists in {org.name!r}")

        print(f"  owner: {owner.email} (categories.user_id — do NOT delete this user)")

        if args.team:
            team = (
                db.query(Team)
                .filter(
                    Team.category_id == category.id,
                    func.lower(Team.name) == args.team.strip().lower(),
                )
                .first()
            )
            if team is None:
                team = Team(category_id=category.id, name=args.team.strip())
                db.add(team)
                db.commit()
                db.refresh(team)
                print(f"  created team {team.id} {team.name!r}")
            else:
                print(f"  team {team.id} {team.name!r} already exists")

        print(
            "\nNext: file a meeting under this category. The 'Generate Size Set' "
            "action appears on its detail page."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
