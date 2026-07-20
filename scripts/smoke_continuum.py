"""End-to-end smoke test for the Continuum Core build (client=team, auto-path).

Simulates the real flow: Continuum category -> client team -> recorded
meetings -> auto-processing -> stage recommendation -> human confirm ->
brief. Uses real OpenAI calls (3x CONTINUUM_MODEL). Cleans up after itself.

Run:  venv/Scripts/python.exe scripts/smoke_continuum.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.celery_tasks.continuum_tasks import _process_continuum_meeting_sync
from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Category, ContinuumClient, Meeting, Organization, Team, User
from app.services.continuum import service

MEETING_1 = """
Ansh: Hi Rajesh, thanks for taking the time. Continuum Core helps mid-size lenders automate back-office operations with AI.
Rajesh (CTO, FinServe Lending): Sure. Our biggest headache is loan document verification. 14 people manually checking documents, roughly 80 lakhs a year, and errors still slip through.
Ansh: What would success look like?
Rajesh: Cut verification from 2 days to same-day and shrink the team to 4-5 people. Any solution must integrate with our custom .NET LOS, and we're RBI regulated so data cannot leave India.
Ansh: Who else is involved in a decision like this?
Rajesh: Our CFO Meera signs anything above 20 lakhs. I drive the technical evaluation.
Ansh: I'll send our BFSI case study on document automation by Thursday. Follow-up next week?
Rajesh: Works. Send the case study first.
"""

MEETING_2 = """
Ansh: Rajesh, did the BFSI case study land well?
Rajesh: Yes, I shared it with Meera. She liked the ROI numbers but is skeptical about the 6-month payback claim.
Ansh: On timeline - why is this a priority now?
Rajesh: We're scaling to 3 new states in Q4, verification volume doubles. If we don't fix this by October we hire 10 more people.
Ansh: Evaluating anyone else?
Rajesh: We considered building in-house but have no ML experience. A vendor called DocuAI exists but they don't do on-prem.
Ansh: Would you be open to a paid strategy engagement to map the full automation roadmap?
Rajesh: Potentially. Send a scope outline and rough fee. Meera needs to approve.
"""


def main() -> None:
    db = SessionLocal()
    created = {"meetings": [], "client": None, "team": None, "category": None}
    try:
        org = db.query(Organization).first()
        user = db.query(User).filter(User.organization_id == org.id).first()
        assert org and user, "need an org + user in the DB"

        # --- Simulate what POST /continuum/clients does ---------------
        category = (
            db.query(Category)
            .filter(Category.organization_id == org.id,
                    Category.name == settings.CONTINUUM_CATEGORY_NAME)
            .first()
        )
        if category is None:
            category = Category(organization_id=org.id, user_id=user.id,
                                name=settings.CONTINUUM_CATEGORY_NAME)
            db.add(category)
            db.flush()
            created["category"] = category
        team = Team(category_id=category.id, name="__smoke_finserve__")
        db.add(team)
        db.flush()
        created["team"] = team
        client = ContinuumClient(organization_id=org.id, team_id=team.id,
                                 name="__smoke_finserve__")
        db.add(client)
        db.commit()
        db.refresh(client)
        created["client"] = client

        def fake_meeting(transcript: str) -> Meeting:
            m = Meeting(
                meeting_url="https://smoke.test/cc",
                status="completed",
                transcript_text=transcript,
                user_id=user.id,
                organization_id=org.id,
                category_id=category.id,
                team_id=team.id,
            )
            db.add(m)
            db.commit()
            db.refresh(m)
            created["meetings"].append(m)
            return m

        # --- Meeting 1 through the AUTO path ---------------------------
        m1 = fake_meeting(MEETING_1)
        out = _process_continuum_meeting_sync(db, m1)
        assert out["status"] == "completed", out
        db.refresh(client)
        assert client.board_version == 1 and isinstance(client.board, dict)
        assert service.current_stage(client) == "DISCOVERY"
        print("MEETING 1 auto-processed OK — board v1, stage DISCOVERY")

        # --- Idempotency: same meeting again = skipped -----------------
        out = _process_continuum_meeting_sync(db, m1)
        assert out == {"status": "skipped", "reason": "already processed"}, out
        db.refresh(client)
        assert client.board_version == 1, "double-processing bumped the board!"
        print("IDEMPOTENCY OK — reprocessing skipped")

        # --- Meeting 2: carry-over + stage stays pinned -----------------
        m2 = fake_meeting(MEETING_2)
        out = _process_continuum_meeting_sync(db, m2)
        assert out["status"] == "completed", out
        db.refresh(client)
        assert client.board_version == 2
        assert service.current_stage(client) == "DISCOVERY", \
            "agent moved the stage itself — guard failed"
        rec = client.latest_recommendation
        print(f"MEETING 2 OK — board v2, stage pinned DISCOVERY, recommendation: {rec}")

        # --- Human confirm (the kanban drag) ----------------------------
        service.confirm_stage(db, client, "STRATEGY_PITCH")
        db.refresh(client)
        assert service.current_stage(client) == "STRATEGY_PITCH"
        assert client.latest_recommendation is None
        history = client.board["pipeline"]["stage_history"]
        assert history and history[-1]["confirmed_by"] == "human"
        print("STAGE CONFIRM OK — STRATEGY_PITCH, history appended, recommendation cleared")

        # --- Brief: read-only --------------------------------------------
        run = service.run_brief(db, client)
        assert run.status == "completed", run.error_message
        db.refresh(client)
        assert client.board_version == 2, "brief mutated the board!"
        print("BRIEF OK — read-only\n")
        print("--- BRIEF (first 1500 chars) ---")
        print((run.package_markdown or "")[:1500])
        print("\nALL SMOKE CHECKS PASSED")
    finally:
        # Cleanup in FK order.
        try:
            if created["client"] is not None:
                db.delete(created["client"])
            for m in created["meetings"]:
                db.delete(m)
            if created["team"] is not None:
                db.delete(created["team"])
            if created["category"] is not None:
                db.delete(created["category"])
            db.commit()
            print("(smoke rows cleaned up)")
        except Exception as exc:
            db.rollback()
            print("cleanup failed:", exc)
        db.close()


if __name__ == "__main__":
    main()
