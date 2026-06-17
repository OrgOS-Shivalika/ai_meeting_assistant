"""Phase 14 K1 — Kanban foundation tests.

Scope (K1 only — K2/K3/K4 each ship their own test file):
  - positions.py math: midpoint insert, end-of-column, rebalance trigger
  - defaults.DEFAULT_COLUMNS shape and idempotent semantics
  - schema enum sanity (status set matches both model + validator)
  - migration revision id wires up correctly

The migration itself (table creation + backfill SQL) is verified by
running `alembic upgrade head` against a Postgres instance, not by
this file — the backfill uses PG-specific features (CTE UPDATE,
partial unique indexes) that don't round-trip on SQLite.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.kanban import positions, defaults


# ---------------------------------------------------------------------------
# Fake Session — minimal stub. The helpers we test here only call
# `db.query(...).filter(...).scalar()`, so we model the chain explicitly.
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Records the chain, returns a scripted scalar value."""

    def __init__(self, scalar_value):
        self._scalar = scalar_value

    def filter(self, *_args, **_kw):
        return self

    def scalar(self):
        return self._scalar


def _fake_db(*, scalar_results):
    """`scalar_results` is consumed FIFO across db.query().scalar() calls."""
    results = list(scalar_results)

    db = MagicMock()
    def _query(*_a, **_kw):
        if not results:
            return _FakeQuery(None)
        return _FakeQuery(results.pop(0))
    db.query.side_effect = _query
    return db


# ---------------------------------------------------------------------------
# positions.position_for_end / position_for_start
# ---------------------------------------------------------------------------


def test_position_for_end_uses_initial_when_column_empty():
    db = _fake_db(scalar_results=[None])
    pos = positions.position_for_end(db, column_id=1)
    assert pos == positions.INITIAL_POSITION


def test_position_for_end_adds_step_to_max():
    db = _fake_db(scalar_results=[5000.0])
    pos = positions.position_for_end(db, column_id=1)
    assert pos == 5000.0 + positions.STEP


def test_position_for_start_uses_initial_when_column_empty():
    db = _fake_db(scalar_results=[None])
    pos = positions.position_for_start(db, column_id=1)
    assert pos == positions.INITIAL_POSITION


def test_position_for_start_subtracts_step_from_min():
    db = _fake_db(scalar_results=[3000.0])
    pos = positions.position_for_start(db, column_id=1)
    assert pos == 3000.0 - positions.STEP


# ---------------------------------------------------------------------------
# positions.compute_insert_position — midpoint, anchors, rebalance flag
# ---------------------------------------------------------------------------


def test_compute_insert_no_anchors_appends_to_end():
    db = _fake_db(scalar_results=[2000.0])  # max position
    pos, rebalance = positions.compute_insert_position(db, column_id=1)
    assert pos == 3000.0
    assert rebalance is False


def test_compute_insert_after_with_next_card_returns_midpoint():
    # Sequence of scalar calls the helper makes when after_task_id is set:
    #   1. _get_position(after_task_id) → 1000.0
    #   2. min(position > 1000.0)       → 2000.0
    db = _fake_db(scalar_results=[1000.0, 2000.0])
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, after_task_id=42,
    )
    assert pos == 1500.0
    assert rebalance is False


def test_compute_insert_after_with_no_next_card_appends_step():
    db = _fake_db(scalar_results=[5000.0, None])
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, after_task_id=42,
    )
    assert pos == 5000.0 + positions.STEP
    assert rebalance is False


def test_compute_insert_triggers_rebalance_when_gap_too_small():
    # Gap between 1000.0 and 1000.005 is < MIN_GAP (0.01), so we should
    # still return a midpoint but mark rebalance=True.
    db = _fake_db(scalar_results=[1000.0, 1000.005])
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, after_task_id=42,
    )
    assert 1000.0 < pos < 1000.005
    assert rebalance is True


def test_compute_insert_before_with_prev_card_returns_midpoint():
    db = _fake_db(scalar_results=[2000.0, 1000.0])  # before_pos, prev_pos
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, before_task_id=42,
    )
    assert pos == 1500.0
    assert rebalance is False


def test_compute_insert_before_with_no_prev_card_prepends():
    db = _fake_db(scalar_results=[1000.0, None])
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, before_task_id=42,
    )
    assert pos == 1000.0 - positions.STEP


def test_compute_insert_both_anchors_returns_midpoint():
    # When both anchors given, helper calls _get_position twice (no min/max).
    db = _fake_db(scalar_results=[1000.0, 2000.0])
    pos, rebalance = positions.compute_insert_position(
        db, column_id=1, after_task_id=10, before_task_id=20,
    )
    assert pos == 1500.0
    assert rebalance is False


# ---------------------------------------------------------------------------
# defaults — DEFAULT_COLUMNS shape (single source of truth for seed)
# ---------------------------------------------------------------------------


def test_default_columns_have_expected_shape():
    """The 4 default columns + their bound statuses MUST match what the
    K1 migration seeds. Any change here without a follow-up migration
    breaks backfill consistency."""
    cols = defaults.DEFAULT_COLUMNS
    assert len(cols) == 4
    names = [c[0] for c in cols]
    assert names == ["To Do", "In Progress", "In Review", "Done"]

    bound_statuses = [c[4] for c in cols]
    assert bound_statuses == ["todo", "in_progress", "in_review", "done"]

    # Exactly one is_done_column = True, and it's the last one.
    done_flags = [c[3] for c in cols]
    assert done_flags == [False, False, False, True]

    # Positions are 0..3 ascending — column ordering is deterministic.
    posns = [c[1] for c in cols]
    assert posns == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Schema / enum sanity — the route validator and the model CHECK
# constraint must reference the same set of statuses.
# ---------------------------------------------------------------------------


def test_route_validator_status_set_matches_model_constraint():
    from app.api.routes import _VALID_STATUSES
    from app.db.models import Task

    assert _VALID_STATUSES == {"todo", "in_progress", "in_review", "done", "archived"}

    # Pull the CHECK constraint expression from the model and verify
    # it references every status in the allowlist. Cheap text match —
    # if someone edits one without the other, this fails.
    constraint_texts = [
        str(c.sqltext) for c in Task.__table_args__
        if getattr(c, "name", None) == "ck_tasks_status"
    ]
    assert len(constraint_texts) == 1
    expr = constraint_texts[0]
    for status in _VALID_STATUSES:
        assert status in expr, f"status {status!r} missing from CHECK constraint"


def test_task_update_request_accepts_new_kanban_fields():
    """The K1 PATCH schema must accept the new fields without complaint."""
    from app.schemas.meeting_schema import TaskUpdateRequest

    payload = TaskUpdateRequest(
        status="in_progress",
        description="**Implement** the thing",
        board_id=5,
        column_id=12,
    )
    assert payload.status == "in_progress"
    assert payload.description.startswith("**Implement**")
    assert payload.board_id == 5
    assert payload.column_id == 12


def test_task_update_request_unset_fields_excluded():
    """`exclude_unset=True` is the contract the route relies on — make
    sure unsupplied fields don't accidentally show up as None and
    overwrite real data."""
    from app.schemas.meeting_schema import TaskUpdateRequest

    payload = TaskUpdateRequest(status="done")
    data = payload.model_dump(exclude_unset=True)
    assert data == {"status": "done"}
    assert "owner_name" not in data
    assert "board_id" not in data


# ---------------------------------------------------------------------------
# Migration smoke — revision id wires up cleanly. Catches typos in
# `down_revision` that would orphan the migration.
# ---------------------------------------------------------------------------


def test_migration_revision_wires_to_phase12e():
    """Phase 14A should chain off the most recent existing migration
    (Phase 12E). If a later phase ships before 14A, this needs to be
    rebased — the test makes that explicit."""
    import importlib.util
    from pathlib import Path

    mig_path = Path(__file__).parent.parent / "alembic" / "versions" / "x4f8b9c0d1e2_phase14a_kanban_foundation.py"
    assert mig_path.exists(), "K1 migration file is missing"

    spec = importlib.util.spec_from_file_location("phase14a_mig", str(mig_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "x4f8b9c0d1e2"
    assert mod.down_revision == "w3e2f4a5b6c7"  # phase12e


def test_migration_default_columns_match_helper():
    """The migration and the helper module BOTH list the seed columns.
    They must stay in sync or a freshly-migrated org and a
    runtime-created org will have different column shapes."""
    import importlib.util
    from pathlib import Path

    mig_path = Path(__file__).parent.parent / "alembic" / "versions" / "x4f8b9c0d1e2_phase14a_kanban_foundation.py"
    spec = importlib.util.spec_from_file_location("phase14a_mig", str(mig_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.DEFAULT_COLUMNS == defaults.DEFAULT_COLUMNS
