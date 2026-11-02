"""Set every calendar meeting's title to its Google Calendar event title.

Until 2026-10-28 the pipeline overwrote the calendar title with the AI title.
Meetings whose event had no title keep the AI title. Idempotent.

    export PYTHONIOENCODING=utf-8
    python -m app.scripts.backfill_calendar_titles           # dry run
    python -m app.scripts.backfill_calendar_titles --apply
"""
import sys

from app.db.database import SessionLocal
from app.db.models import Meeting


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        changed = 0
        for m in db.query(Meeting).filter(Meeting.google_event_data.isnot(None)):
            cal = ((m.google_event_data or {}).get("summary") or "").strip()
            if cal and cal != m.title:
                print(f"{m.id}: {m.title!r} -> {cal!r}")
                m.title = cal
                changed += 1
        if apply:
            db.commit()
        else:
            db.rollback()
        print(f"{'updated' if apply else 'would update'} {changed} meeting(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
