"""Google Drive transcript export — naming, Doc content, recipients, idempotency.

Drive HTTP and the naming LLM are faked; needs the local Postgres.

    export PYTHONIOENCODING=utf-8
    python tests/test_drive_export.py
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase12e import _seed_meeting, _cleanup  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Meeting, Participant, Task, User  # noqa: E402
from app.services import drive_export_service as svc  # noqa: E402
from app.services import google_auth_service  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'ok ' if cond else 'FAIL'} {name}{'' if cond else '  -- ' + str(detail)}")


def _llm(company, topic):
    c = MagicMock()
    c.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"company": company, "topic": topic})))]
    return c


class FakeDrive:
    """Stands in for `requests` inside the service. Records every call."""

    def __init__(self):
        self.calls, self.n, self.next_status = [], 0, {}

    def _resp(self, method, url, status=None):
        self.calls.append((method, url))
        status = self.next_status.pop(method, None) or status or 200
        self.n += 1
        r = MagicMock(status_code=status, text="err")
        # Drive keeps a file's id on update; only creates mint a new one.
        fid = url.rsplit("/", 1)[-1] if method == "PATCH" else f"file{self.n}"
        r.json.return_value = {"id": fid, "trashed": False}
        r.raise_for_status.side_effect = None if status < 400 else RuntimeError(f"HTTP {status}")
        return r

    def get(self, url, **kw): return self._resp("GET", url)
    def post(self, url, **kw): return self._resp("POST", url)
    def patch(self, url, **kw): return self._resp("PATCH", url)


def test_naming():
    m = Meeting(id=1, title="Call", started_at=datetime(2026, 10, 27, 20, 0, tzinfo=timezone.utc))  # 01:30 IST next day
    check("IST date, company - topic",
          svc.file_name(m, "Anko Kmart", "SS27 cushion cover BCI") == "2026-10-28 Anko Kmart - SS27 cushion cover BCI",
          svc.file_name(m, "Anko Kmart", "SS27 cushion cover BCI"))
    check("bad characters stripped", svc.file_name(m, "A/B", 'x: "y"?') == "2026-10-28 A B - X y",
          svc.file_name(m, "A/B", 'x: "y"?'))
    check("no company -> date + topic", svc.file_name(m, None, "Weekly sync") == "2026-10-28 Weekly sync")
    check("LLM parts parsed", svc.name_parts(m, ["Sunil"], _llm("Anko Kmart", "SS27 cushions")) == ("Anko Kmart", "SS27 cushions"))
    check("no buyer named -> no company part", svc.name_parts(m, [], _llm(None, "Shirt fit review")) == (None, "Shirt fit review"))
    check("'Internal' is not a company", svc.name_parts(m, [], _llm("Internal", "x")) == (None, "x"))
    m.transcript_text = "Anko Kmart wants BCI cotton"
    c = _llm("Anko Kmart", "BCI")
    svc.name_parts(m, [], c)
    sent = json.loads(c.chat.completions.create.call_args.kwargs["messages"][1]["content"])
    check("naming sees the transcript start", sent.get("transcript_start") == "Anko Kmart wants BCI cotton", sent)
    bad = MagicMock(); bad.chat.completions.create.side_effect = RuntimeError("down")
    check("LLM failure falls back to title", svc.name_parts(m, [], bad) == (None, "Call"))


def test_content():
    m = Meeting(id=1, title="Call", summary="We agreed prices.", transcript_text="Sunil: hello",
                duration_minutes=30, meeting_platform="google_meet",
                started_at=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc))
    ps = [Participant(name="Sunil", email="s@x.com", is_organizer="true"), Participant(name="Sunil"),
          Participant(name="Ravi")]
    ts = [Task(task="Send BCI cert", owner_name="Ravi", due_date=datetime(2026, 11, 1, tzinfo=timezone.utc))]
    t = svc.build_text(m, "NAME", ps, ts, ["Use BCI cotton"])
    for part in ("NAME", "11:30 IST", "- Sunil <s@x.com> (organizer)", "- Ravi", "We agreed prices.",
                 "- Use BCI cotton", "- Send BCI cert (Ravi, due 2026-11-01)", "TRANSCRIPT", "Sunil: hello"):
        check(f"doc contains {part!r}", part in t, t)
    check("duplicate attendee listed once", t.count("Sunil <") + t.count("- Sunil\n") == 1, t)


def test_export(seed):
    mid = seed["meeting_id"]
    db = SessionLocal()
    try:
        owner = db.get(User, uuid.UUID(seed["user_id"]))
        owner.google_access_token, owner.drive_folder_id = "t", "folder-owner"
        invited = User(name="Inv", email=f"inv-{uuid.uuid4()}@example.com", password="x",
                       organization_id=owner.organization_id, google_access_token="t", drive_folder_id="folder-inv")
        stranger = User(name="Str", email=f"str-{uuid.uuid4()}@example.com", password="x",
                        organization_id=owner.organization_id, google_access_token="t", drive_folder_id="folder-str")
        no_drive = User(name="Nd", email=f"nd-{uuid.uuid4()}@example.com", password="x",
                        organization_id=owner.organization_id, google_access_token="t")
        db.add_all([invited, stranger, no_drive])
        m = db.get(Meeting, mid)
        m.title, m.summary, m.transcript_text = "Call", "s", "Sunil: hi"
        m.started_at = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
        m.google_event_data = {"attendees": [{"email": invited.email.upper()}, {"email": no_drive.email}]}
        db.add(Participant(meeting_id=mid, name="Sunil"))
        db.commit()

        got = {u.email for u in svc.recipients(db, m)}
        check("recipients = owner + invited with Drive", got == {owner.email, invited.email}, got)

        fake = FakeDrive()
        with patch.object(svc, "requests", fake), patch.object(svc, "_token", return_value="tok"):
            out = svc.export_meeting(db, mid, client=_llm("Anko Kmart", "SS27"))
            db.expire_all()
            files = dict(db.get(Meeting, mid).drive_files)
            check("one Doc per recipient", out["uploaded"] == 2 and len(files) == 2, (out, files))
            check("named per format", out["name"] == "2026-10-27 Anko Kmart - SS27", out)
            creates = sum(1 for c in fake.calls if c[0] == "POST")

            fake.calls.clear()
            svc.export_meeting(db, mid, client=_llm("Anko Kmart", "SS27"))
            db.expire_all()
            check("re-run updates in place (PATCH, no new POST)",
                  [c[0] for c in fake.calls if c[0] != "GET"] == ["PATCH", "PATCH"] and creates == 2, fake.calls)
            check("re-run keeps file ids", dict(db.get(Meeting, mid).drive_files) == files)

            fake.calls.clear(); fake.next_status = {"PATCH": 404}
            svc.export_meeting(db, mid, only_user_id=str(owner.id), client=_llm("A", "B"))
            db.expire_all()
            check("deleted Doc is recreated", [c[0] for c in fake.calls if c[0] != "GET"] == ["PATCH", "POST"]
                  and db.get(Meeting, mid).drive_files[str(owner.id)] != files[str(owner.id)], fake.calls)

            fake.next_status = {"PATCH": 403}
            out = svc.export_meeting(db, mid, only_user_id=str(owner.id), client=_llm("A", "B"))
            check("lost Drive permission is skipped, not retried", out["uploaded"] == 0, out)

            fake.next_status = {"PATCH": 500}
            try:
                svc.export_meeting(db, mid, only_user_id=str(owner.id), client=_llm("A", "B"))
                check("transient failure raises for Celery retry", False)
            except RuntimeError:
                check("transient failure raises for Celery retry", True)

            check("no transcript -> skipped",
                  svc.export_meeting(db, 10**9)["skipped"] == "no transcript")

            # connect flow
            owner = db.get(User, owner.id)
            check("connect with Drive granted -> folder set",
                  google_auth_service.sync_drive_folder(db, owner, True) and owner.drive_folder_id)
            check("connect without Drive -> export off",
                  not google_auth_service.sync_drive_folder(db, owner, False) and owner.drive_folder_id is None)
    finally:
        db.rollback()
        db.query(Participant).filter(Participant.meeting_id == mid).delete()
        db.commit()
        db.close()


def main():
    print("== offline")
    test_naming()
    test_content()
    print("== database")
    seed = _seed_meeting()
    try:
        test_export(seed)
    finally:
        _cleanup(seed["meeting_id"])
    passed = sum(ok for _, ok in results)
    print(f"\n{'PASSED' if passed == len(results) else 'FAILED'} {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
