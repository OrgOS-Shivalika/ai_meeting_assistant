"""Smoke test — fires a single agents_v2 run so a Langfuse trace appears.

Runs the orchestrator end-to-end against a fabricated in-memory Meeting
scoped to the seeded HR L&D agent (org 0dd7e275..., cat 4554, team 3864).
No DB writes — the Meeting object is transient. Memory lookups fail-safe
to empty when the meeting_id doesn't exist.

Run from repo root:

    python -m scripts.smoke_agents_v2

Then check https://cloud.langfuse.com — a new trace named
`agents_v2.run_meeting_analysis` should appear within a few seconds.
"""
from __future__ import annotations

from uuid import UUID

from app.agents_v2 import orchestrator, registry
from app.agents_v2.shared import tracing
from app.db.database import SessionLocal
from app.db.models import Meeting

ORG_ID = UUID("0dd7e275-9086-40ee-bc37-550cff13818a")
CATEGORY_ID = 4554
TEAM_ID = 3864

TRANSCRIPT = """\
Priya: Kick-off for the Q3 leadership workshop. We need modules on
       feedback delivery, priority-setting, and delegating without
       micromanaging. Target audience is first-time managers.
Arjun: I can own the delegation module. Draft outline by Friday.
Priya: Great. Meera, please pull the survey results from the last
       cohort so we know which topics scored worst on retention.
Meera: Will do. I'll circulate them Monday morning.
Priya: Budget is approved for two external facilitators. Arjun, work
       with procurement on the shortlist next week.
"""


def main() -> None:
    print(f"[smoke] Langfuse enabled: {tracing.is_enabled()}")
    if not tracing.is_enabled():
        print("[smoke] WARNING: tracing is disabled — this run will not "
              "produce a trace. Check LANGFUSE_* env vars.")

    registry.bootstrap()

    meeting = Meeting(
        id=999_999,
        organization_id=ORG_ID,
        category_id=CATEGORY_ID,
        team_id=TEAM_ID,
    )

    db = SessionLocal()
    try:
        if not orchestrator.has_agent_for_scope(db, meeting):
            print(f"[smoke] FAIL: no agents_v2 row for org={ORG_ID} "
                  f"cat={CATEGORY_ID} team={TEAM_ID}. Did bootstrap run?")
            return
        result = orchestrator.run_meeting_analysis(db, TRANSCRIPT, meeting)
        print("[smoke] agent returned:")
        print(result)
    finally:
        db.close()
        tracing.flush()
        print("[smoke] flushed. Check the Langfuse dashboard.")


if __name__ == "__main__":
    main()
