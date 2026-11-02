"""Every meeting-created task carries its `context` as Task.description.

Walks each path a task can be born on and asserts the description lands:
  1. contract       — ExtractionSummary keeps `context` (pydantic used to drop it)
  2. merger         — master result → normalizer → dedup → ExtractionSummary
  3. dedup          — kept duplicate without context inherits a sibling's
  4. live           — extractor raw → stabilizer → LiveTask → persistence → DB
  5. live → merger  — confirmed live tasks keep their context into synthesis
  6. save_tasks     — post-meeting analyzer insert; fills an empty live row,
                      never overwrites a description a user already edited
  7. create_task    — harness tool writes `context` to description

Needs the local Postgres (docker compose up -d postgres). No LLM calls.

    export PYTHONIOENCODING=utf-8
    python tests/test_task_context.py
"""
import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase12e import _seed_meeting, _cleanup  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import Task  # noqa: E402
from app.services.cognition.contracts import ExtractionContractRuntime, ExtractionSummary  # noqa: E402
from app.services.cognition.models import CognitionFragment  # noqa: E402

CTX = "Checkout latency hit 2s under load last week; the team needs numbers before scaling the API."
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(f"  {'ok ' if cond else 'FAIL'} {name}{'' if cond else '  -- ' + str(detail)}")


def _llm(payload):
    client = MagicMock()
    client.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content=json.dumps(payload)))
    ]
    return client


def test_contract():
    s = ExtractionContractRuntime.validate_and_parse(ExtractionSummary, {
        "title": "t", "summary": "s",
        "action_items": [{"task": "Send load test report", "context": CTX, "owner": "Sarah"}],
    })
    check("contract keeps context", s.action_items[0].context == CTX, s.action_items[0])
    check("contract dump carries it to save_tasks",
          s.model_dump()["action_items"][0]["context"] == CTX)


def test_merger_and_dedup():
    from app.services.cognition import merger, deduplicator, narrative_synthesizer
    master = ExtractionSummary(title="t", summary="s", action_items=[
        {"task": "Send load test report", "owner": "Sarah"},            # no context
        {"task": "Share the load-test numbers", "context": CTX},          # duplicate WITH context
        {"task": "Book the venue", "context": "Offsite on the 20th needs a room for 30."},
    ])
    dedup = _llm({"merges": {"0": 0, "1": 0, "2": 2}})   # 1 folds into 0, which lacks context
    summ = CognitionFragment(type="summary", content="s", source_skill="x")
    with patch.object(deduplicator, "_get_client", return_value=dedup), \
         patch.object(narrative_synthesizer.NarrativeSynthesizer, "synthesize", return_value=summ):
        out = merger.UnifiedCognitionMerger.synthesize(master, {}, meeting_id=None)
    items = {a.task: a.context for a in out.action_items}
    check("dedup kept item inherits sibling context", items.get("Send load test report") == CTX, items)
    check("unique item keeps its own context", items.get("Book the venue", "").startswith("Offsite"), items)
    check("merger output is 2 tasks", len(out.action_items) == 2, items)


def test_live_to_merger():
    from app.services.cognition.normalizer import CognitionNormalizer
    from app.services.live_tasks.live_task_models import LiveTask
    t = LiveTask(id="l1", task="Fix login", fingerprint="f", description=CTX,
                 status="confirmed", confidence=0.9,
                 source_speaker="Sarah", source_transcript_chunk_id=1)
    frags = CognitionNormalizer.normalize_live_tasks([t])
    check("live task context survives into synthesis", frags and frags[0].content.get("context") == CTX,
          frags and frags[0].content)


def test_live_persistence(seed):
    from app.services.live_tasks.stabilizer import TaskStabilizer
    from app.services.live_tasks.persistence import LiveTaskPersistence
    from app.services.meeting_memory.meeting_state_store import MeetingState
    from app.services.live_events.event_models import LiveCognitiveEvent
    mid = seed["meeting_id"]
    state = MeetingState(str(mid))
    [lt] = TaskStabilizer.stabilize(state, [{"task": "Send the load test report", "owner": "Sarah",
                                             "context": CTX, "confidence": 0.9}], 1)
    check("stabilizer maps context -> description", lt.description == CTX, lt.description)
    # a later mention without context must not wipe it
    [lt2] = TaskStabilizer.stabilize(state, [{"task": "Send the load test report", "confidence": 0.9}], 2)
    check("re-mention keeps description", lt2.description == CTX, lt2.description)
    LiveTaskPersistence.handle_event(LiveCognitiveEvent(
        event_type="task.created", meeting_id=str(mid), payload=lt.model_dump(),
        confidence=0.9, trace_id="t"))
    db = SessionLocal()
    try:
        row = db.query(Task).filter(Task.meeting_id == mid, Task.task == "Send the load test report").first()
        check("live task row has description", row is not None and row.description == CTX,
              row and row.description)
    finally:
        db.close()


def test_save_tasks(seed):
    from app.pipelines.meeting_pipeline import MeetingPipeline
    mid = seed["meeting_id"]
    db = SessionLocal()
    try:
        db.add(Task(meeting_id=mid, task="Live empty", status="todo", is_completed=0))
        db.add(Task(meeting_id=mid, task="User edited", description="MY NOTES", status="todo", is_completed=0))
        db.commit()
        p = MeetingPipeline.__new__(MeetingPipeline)
        p.save_tasks(db, mid, [
            {"task": "Brand new", "context": CTX, "owner": "Sarah"},
            {"task": "Live empty", "context": "filled by analyzer"},
            {"task": "User edited", "context": "analyzer text"},
        ])
        db.commit()
        got = {t.task: t.description for t in db.query(Task).filter(Task.meeting_id == mid)}
        check("analyzer insert gets description", got.get("Brand new") == CTX, got)
        check("empty live row is filled", got.get("Live empty") == "filled by analyzer", got)
        check("user-edited description NOT overwritten", got.get("User edited") == "MY NOTES", got)
    finally:
        db.close()


def test_create_task_tool(seed):
    from app.services.agents.tools.builtin import create_task
    from app.services.agents.tools.registry import ToolContext
    mid = seed["meeting_id"]
    db = SessionLocal()
    try:
        out = create_task.handler({"task": "Harness task", "context": f"  {CTX}  "},
                                  ToolContext(db=db, organization_id=uuid.UUID(seed["org_id"]), meeting_id=mid))
        row = db.get(Task, out["task_id"])
        check("create_task stores trimmed context as description", row.description == CTX, row.description)
        out2 = create_task.handler({"task": "Harness no ctx", "context": None},
                                   ToolContext(db=db, organization_id=uuid.UUID(seed["org_id"]), meeting_id=mid))
        check("create_task null context -> NULL, not 'None'", db.get(Task, out2["task_id"]).description is None)
    finally:
        db.close()


def test_brief_pass(seed):
    """Second, focused pass: detailed brief per task from the full transcript."""
    from app.db.models import TaskActivity
    from app.services.cognition import task_briefs
    mid = seed["meeting_id"]
    db = SessionLocal()
    try:
        db.query(Task).filter(Task.meeting_id == mid).delete()
        auto = [Task(meeting_id=mid, task=f"Auto {i}", description="short", status="todo", is_completed=0)
                for i in range(17)]
        human = Task(meeting_id=mid, task="Human edited", description="MY NOTES", status="todo", is_completed=0)
        db.add_all(auto + [human]); db.commit()
        db.add(TaskActivity(task_id=human.id, event_type="description_changed",
                            before={"description": "x"}, after={"description": "MY NOTES"}))
        db.commit()
        calls = []

        def fake_create(**kw):
            ids = [t["id"] for t in json.loads(kw["messages"][1]["content"].split("TASKS:\n", 1)[1])]
            calls.append(ids)
            # leave the last id of each batch out: its old text must survive
            return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(
                {"briefs": {i: f"Detailed brief for {i}\n- point" for i in ids[:-1]}})))])
        client = MagicMock()
        client.chat.completions.create.side_effect = fake_create
        n = task_briefs.enrich_meeting_task_descriptions(db, mid, "Sunil: ETD is mandatory.", client=client)
        db.expire_all()
        got = {t.id: t.description for t in db.query(Task).filter(Task.meeting_id == mid)}
        sent = {i for c in calls for i in c}
        check("brief pass batches 17 tasks as 15 + 2", [len(c) for c in calls] == [15, 2], [len(c) for c in calls])
        check("human-edited task never sent or changed", str(human.id) not in sent and got[human.id] == "MY NOTES")
        check("briefs written to description", n == 15 and got[auto[0].id].startswith("Detailed brief"), n)
        check("missing brief keeps the earlier context", got[auto[14].id] == "short", got[auto[14].id])
        check("empty transcript is a no-op", task_briefs.enrich_meeting_task_descriptions(db, mid, "", client=client) == 0)
    finally:
        db.query(TaskActivity).filter(TaskActivity.task_id.in_(
            db.query(Task.id).filter(Task.meeting_id == mid))).delete(synchronize_session=False)
        db.commit()
        db.close()


def _wipe_tasks(mid):
    db = SessionLocal()
    try:
        db.query(Task).filter(Task.meeting_id == mid).delete()
        db.commit()
    finally:
        db.close()


def main():
    print("== offline")
    test_contract()
    test_merger_and_dedup()
    test_live_to_merger()
    print("== database")
    seed = _seed_meeting()
    try:
        test_live_persistence(seed)
        test_save_tasks(seed)
        test_create_task_tool(seed)
        test_brief_pass(seed)
    finally:
        _wipe_tasks(seed["meeting_id"])
        _cleanup(seed["meeting_id"])
    passed = sum(ok for _, ok in results)
    print(f"\n{'PASSED' if passed == len(results) else 'FAILED'} {passed}/{len(results)}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
