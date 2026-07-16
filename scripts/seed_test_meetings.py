"""One-off — insert N fake uncategorized meetings for a user.

Used to pressure-test pagination on the meetings page. Rows carry no
transcript / bot_id / participants — they're just DB entries with the
minimum fields set. Timestamps spread across the last N days so date
filters have something to bite on.

Run:
    python -m scripts.seed_test_meetings [email] [count]

Defaults: email = divyansh.bhardwaj@smoothops.info, count = 30.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from app.db.database import SessionLocal
from app.db.models import Meeting, User


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "divyansh.bhardwaj@smoothops.info"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"[FAIL] No user with email {email!r}")
            sys.exit(1)

        print(f"Seeding {count} uncategorized meetings for {user.email} "
              f"(org={user.organization_id})…")

        now = datetime.now(timezone.utc)
        for i in range(1, count + 1):
            # Spread timestamps: one every ~6 hours, oldest first.
            ts = now - timedelta(hours=6 * (count - i))
            m = Meeting(
                title=f"Test meeting {i:02d}",
                meeting_url=f"https://meet.google.com/fake-seed-{i:03d}",
                status="completed",
                summary=(
                    f"Seeded meeting {i}. Ignore. Delete freely."
                ),
                created_at=ts,
                updated_at=ts,
                started_at=ts,
                ended_at=ts + timedelta(minutes=30),
                duration_minutes=30,
                organization_id=user.organization_id,
                user_id=user.id,
                category_id=None,
                team_id=None,
                embedding_status="skipped",
                graph_status="skipped",
                closing_briefing_status="skipped",
            )
            db.add(m)

        db.commit()
        print(f"[OK] Inserted {count} meetings.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
