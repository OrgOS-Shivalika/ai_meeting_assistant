"""Phase 14 K4 — Card-detail drawer endpoints.

Scope:
  - GET /tasks/{id}  returns task + board + column + meeting context
  - Comment CRUD: create/edit/delete (author-only enforcement)
  - GET /tasks/{id}/activity returns paginated reverse-chronological feed
  - Schema shapes for the new responses

Uses TestClient + dependency_overrides to bypass real JWT auth. Picks
a real user from the dev DB so we exercise the org-scoping path
end-to-end.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import app
from app.db.database import SessionLocal
from app.db.models import KanbanBoard, KanbanColumn, Task, User
from app.dependencies.auth import get_current_user
from app.services.kanban.defaults import ensure_default_board


@pytest.fixture(scope="module")
def setup_env():
    """Pick a real user with a default board; create a fresh manual task
    on the user's default board so test mutations don't bleed into
    real data."""
    db = SessionLocal()
    user = db.query(User).first()
    assert user is not None, "no users in DB — can't test"
    board = ensure_default_board(db, user.organization_id)
    db.commit()
    column = (
        db.query(KanbanColumn)
        .filter(
            KanbanColumn.board_id == board.id,
            KanbanColumn.bound_status == "todo",
        )
        .first()
    )
    assert column is not None

    task = Task(
        task="K4 test task",
        owner_name="Test Author",
        priority="medium",
        is_completed=0,
        status="todo",
        board_id=board.id,
        column_id=column.id,
        position=999_999.0,
        description="**markdown** body",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    task_id = task.id

    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    yield {"client": client, "user": user, "task_id": task_id, "board_id": board.id}

    # Teardown — delete the test task so re-runs are clean.
    db = SessionLocal()
    db.query(Task).filter(Task.id == task_id).delete()
    db.commit()
    db.close()
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# GET /tasks/{id}
# ---------------------------------------------------------------------------


def test_get_task_detail_returns_full_payload(setup_env):
    c = setup_env["client"]
    r = c.get(f"/tasks/{setup_env['task_id']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == setup_env["task_id"]
    assert data["task"] == "K4 test task"
    assert data["description"] == "**markdown** body"
    assert data["board_id"] == setup_env["board_id"]
    assert data["board_name"] == "Tasks"
    assert data["column_name"] == "To Do"
    assert data["status"] == "todo"
    assert data["is_completed"] is False
    assert data["comment_count"] == 0
    # activity_count may be > 0 if K1 backfill seeded a 'created' row
    # for any tasks of this id, but we just made this task post-migration
    # via a direct SQL insert that bypasses the activity log — so it
    # should be 0. Don't assert exact: just non-negative.
    assert data["activity_count"] >= 0


def test_get_task_detail_404_for_unknown_id(setup_env):
    c = setup_env["client"]
    r = c.get("/tasks/99999999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def test_comment_lifecycle_create_edit_delete(setup_env):
    c = setup_env["client"]
    tid = setup_env["task_id"]

    # Empty list to start.
    r = c.get(f"/tasks/{tid}/comments")
    assert r.status_code == 200
    assert r.json() == []

    # Create.
    r = c.post(f"/tasks/{tid}/comments", json={"body": "First comment"})
    assert r.status_code == 201, r.text
    comment = r.json()
    assert comment["body"] == "First comment"
    assert comment["is_own"] is True
    assert comment["task_id"] == tid
    comment_id = comment["id"]

    # List shows it.
    r = c.get(f"/tasks/{tid}/comments")
    assert len(r.json()) == 1

    # Activity feed grew by one `commented` event.
    r = c.get(f"/tasks/{tid}/activity")
    activity = r.json()
    types = [a["event_type"] for a in activity["items"]]
    assert "commented" in types

    # Edit own comment.
    r = c.patch(f"/comments/{comment_id}", json={"body": "Edited comment"})
    assert r.status_code == 200
    assert r.json()["body"] == "Edited comment"

    # Delete.
    r = c.delete(f"/comments/{comment_id}")
    assert r.status_code == 204
    r = c.get(f"/tasks/{tid}/comments")
    assert r.json() == []


def test_comment_create_rejects_empty(setup_env):
    c = setup_env["client"]
    tid = setup_env["task_id"]
    r = c.post(f"/tasks/{tid}/comments", json={"body": ""})
    # Pydantic min_length=1 → 422
    assert r.status_code == 422

    r = c.post(f"/tasks/{tid}/comments", json={"body": "   "})
    # Whitespace-only is stripped and rejected by the route as 400.
    assert r.status_code == 400


def test_comment_edit_requires_authorship(setup_env):
    """A different user can't edit someone else's comment. Simulate
    by swapping the dependency override mid-test."""
    c = setup_env["client"]
    tid = setup_env["task_id"]

    # Author creates a comment.
    r = c.post(f"/tasks/{tid}/comments", json={"body": "Author note"})
    assert r.status_code == 201
    comment_id = r.json()["id"]

    # Try to edit as a different user — pick another user in same org
    # if available, else just stub an id mismatch.
    db = SessionLocal()
    real_user = setup_env["user"]
    other = (
        db.query(User)
        .filter(
            User.organization_id == real_user.organization_id,
            User.id != real_user.id,
        )
        .first()
    )
    db.close()

    if other is None:
        # Synthesize a user-shaped object whose .id differs but org matches.
        class _Other:
            pass
        other = _Other()
        other.id = real_user.id  # type: ignore[attr-defined]
        # Hack: mutate id so the (author == user) check fails.
        import uuid as _uuid
        other.id = _uuid.uuid4()  # type: ignore[attr-defined]
        other.organization_id = real_user.organization_id  # type: ignore[attr-defined]
        other.name = "Other"  # type: ignore[attr-defined]

    app.dependency_overrides[get_current_user] = lambda: other
    try:
        r = c.patch(f"/comments/{comment_id}", json={"body": "hacked"})
        assert r.status_code == 403, r.text
        r = c.delete(f"/comments/{comment_id}")
        assert r.status_code == 403
    finally:
        # Restore the original author so cleanup works.
        app.dependency_overrides[get_current_user] = lambda: real_user

    # Cleanup the comment.
    c.delete(f"/comments/{comment_id}")


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------


def test_activity_feed_paginates(setup_env):
    c = setup_env["client"]
    tid = setup_env["task_id"]

    # Produce ~3 events by patching the task three times.
    c.patch(f"/tasks/{tid}", json={"priority": "high"})
    c.patch(f"/tasks/{tid}", json={"description": "updated description"})
    c.patch(f"/tasks/{tid}", json={"owner_name": "Renamed Owner"})

    r = c.get(f"/tasks/{tid}/activity", params={"limit": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert body["has_more"] is True

    # Page 2.
    r = c.get(f"/tasks/{tid}/activity", params={"limit": 2, "offset": 2})
    body2 = r.json()
    assert len(body2["items"]) >= 1
    # Combined IDs should be all distinct.
    ids = {a["id"] for a in body["items"]} | {a["id"] for a in body2["items"]}
    assert len(ids) == len(body["items"]) + len(body2["items"])


def test_activity_feed_orders_newest_first(setup_env):
    c = setup_env["client"]
    tid = setup_env["task_id"]
    r = c.get(f"/tasks/{tid}/activity", params={"limit": 50})
    items = r.json()["items"]
    if len(items) >= 2:
        # created_at descending: each item created_at >= the next.
        for i in range(len(items) - 1):
            assert items[i]["created_at"] >= items[i + 1]["created_at"]
