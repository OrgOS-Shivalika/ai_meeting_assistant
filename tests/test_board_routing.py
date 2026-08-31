"""Per-category / per-team task landing board — the resolution ladder.

Offline, assert-based, no DB and no pytest (there is none in this repo).
`resolve_board` is exercised against a fake Session that answers the two
query shapes it issues, so the ladder itself is under test rather than
SQLAlchemy.

What this guards, in order of how badly it would hurt:

  1. A cross-tenant pointer must NOT be honoured. It sits on the task-insert
     path, so honouring one files org A's action items onto org B's board.
  2. Team beats category beats org — and NULL at any level means "ask the
     layer below", never "no board".
  3. Inheritance is live. Re-pointing a category re-routes every team under
     it that has not chosen its own, with no per-team write.

    python tests/test_board_routing.py
"""
import os
import sys
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import Category, KanbanBoard, Team  # noqa: E402
from app.services.kanban import defaults  # noqa: E402

ORG = uuid4()
OTHER_ORG = uuid4()

checks = 0
failures = []


def check(label, cond):
    global checks
    checks += 1
    if cond:
        print(f"  PASS  {label}")
    else:
        failures.append(label)
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Board:
    def __init__(self, board_id, organization_id):
        self.id = board_id
        self.organization_id = organization_id


class _Query:
    """Answers exactly the two shapes `resolve_board` issues.

    Modelled on the real call sites rather than made generic on purpose: a
    permissive fake would keep passing after the production query changed
    shape, which is the failure mode that makes a stub worse than no test.
    """

    def __init__(self, session, entity):
        self.session = session
        self.entity = entity
        self.filters = []

    def filter(self, *conds):
        self.filters.extend(conds)
        return self

    def first(self):
        session = self.session

        # `db.query(Model.default_board_id).filter(Model.id == row_id)`
        for model, table in ((Category, session.categories), (Team, session.teams)):
            if self.entity is model.default_board_id:
                row_id = _rhs(self.filters, model.id)
                row = table.get(row_id)
                return None if row is None else (row,)

        # `db.query(KanbanBoard).filter(...)`
        if self.entity is KanbanBoard:
            board = session.boards.get(_rhs(self.filters, KanbanBoard.id))
            if board is None:
                return None
            # Apply the org filter ONLY IF THE CALLER PASSED ONE — this fake
            # must behave like the database, not like a spec of what the
            # database ought to be asked. An earlier version asserted the
            # filter was present, so deleting it from `resolve_board` blew up
            # the stub instead of failing the tenancy assertion: the test
            # enforced tenancy itself and would have kept "passing" in spirit
            # while the production query leaked. Model the filters, let the
            # assertions do the judging.
            org_id = _rhs(self.filters, KanbanBoard.organization_id, required=False)
            if org_id is not _MISSING and board.organization_id != org_id:
                return None
            return board

        raise AssertionError(f"unexpected query entity: {self.entity!r}")


_MISSING = object()


def _rhs(filters, column, *, required=True):
    """The value a `column == value` clause was built with.

    Returns `_MISSING` when no such clause exists and `required=False`, so a
    caller can distinguish "filtered on this column" from "did not filter".
    """
    for clause in filters:
        left = getattr(clause, "left", None)
        if (
            left is not None
            and left.name == column.key
            and left.table.name == column.parent.persist_selectable.name
        ):
            return clause.right.value
    if required:
        raise AssertionError(f"no equality filter on {column}")
    return _MISSING


class _Session:
    def __init__(self, *, categories=None, teams=None, boards=None):
        # {id: default_board_id}
        self.categories = categories or {}
        self.teams = teams or {}
        # {id: _Board}
        self.boards = boards or {}

    def query(self, entity):
        return _Query(self, entity)


ORG_DEFAULT = _Board(1, ORG)
CATEGORY_BOARD = _Board(2, ORG)
TEAM_BOARD = _Board(3, ORG)
FOREIGN_BOARD = _Board(99, OTHER_ORG)

ALL_BOARDS = {b.id: b for b in (ORG_DEFAULT, CATEGORY_BOARD, TEAM_BOARD, FOREIGN_BOARD)}


def resolve(session, *, category_id=None, team_id=None):
    """Call the real resolver with `ensure_default_board` stubbed.

    Stubbed rather than faked out with rows because it CREATES the board when
    missing, which needs a real Session. Everything above it in the ladder is
    the code under test.
    """
    original = defaults.ensure_default_board
    defaults.ensure_default_board = lambda db, org, **kw: ORG_DEFAULT
    try:
        return defaults.resolve_board(
            session, ORG, category_id=category_id, team_id=team_id,
        )
    finally:
        defaults.ensure_default_board = original


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

print("\n[ladder] most-specific pointer wins")

s = _Session(boards=ALL_BOARDS)
check(
    "no category, no team -> org default",
    resolve(s).id == ORG_DEFAULT.id,
)

s = _Session(categories={10: None}, teams={20: None}, boards=ALL_BOARDS)
check(
    "both pointers NULL -> org default (NULL means inherit, not 'no board')",
    resolve(s, category_id=10, team_id=20).id == ORG_DEFAULT.id,
)

s = _Session(categories={10: CATEGORY_BOARD.id}, teams={20: None}, boards=ALL_BOARDS)
check(
    "category chose, team did not -> category board",
    resolve(s, category_id=10, team_id=20).id == CATEGORY_BOARD.id,
)

s = _Session(
    categories={10: CATEGORY_BOARD.id}, teams={20: TEAM_BOARD.id}, boards=ALL_BOARDS,
)
check(
    "team chose its own -> team board overrides the category",
    resolve(s, category_id=10, team_id=20).id == TEAM_BOARD.id,
)

s = _Session(categories={10: None}, teams={20: TEAM_BOARD.id}, boards=ALL_BOARDS)
check(
    "team chose, category did not -> team board (no category to inherit)",
    resolve(s, category_id=10, team_id=20).id == TEAM_BOARD.id,
)

s = _Session(categories={10: CATEGORY_BOARD.id}, boards=ALL_BOARDS)
check(
    "meeting filed under a category but no team -> category board",
    resolve(s, category_id=10).id == CATEGORY_BOARD.id,
)


print("\n[inheritance] is live, not copied onto the team")

# THE REQUIREMENT, stated as a test: two teams under one category, neither
# with its own pointer. Re-pointing the CATEGORY moves both, with no write to
# either team row. A denormalized copy would leave them on the old board.
s = _Session(
    categories={10: CATEGORY_BOARD.id},
    teams={20: None, 21: None},
    boards=ALL_BOARDS,
)
check(
    "both teams follow the category before the change",
    resolve(s, category_id=10, team_id=20).id == CATEGORY_BOARD.id
    and resolve(s, category_id=10, team_id=21).id == CATEGORY_BOARD.id,
)

s.categories[10] = TEAM_BOARD.id  # category re-pointed; teams untouched
check(
    "both teams follow the category AFTER it is re-pointed, with no team write",
    resolve(s, category_id=10, team_id=20).id == TEAM_BOARD.id
    and resolve(s, category_id=10, team_id=21).id == TEAM_BOARD.id,
)

s.teams[21] = CATEGORY_BOARD.id  # team 21 opts out
check(
    "a team that opts out stops following the category; its sibling still does",
    resolve(s, category_id=10, team_id=21).id == CATEGORY_BOARD.id
    and resolve(s, category_id=10, team_id=20).id == TEAM_BOARD.id,
)


print("\n[tenancy] a pointer across orgs is never honoured")

# The one that actually matters. The FK cannot enforce this — a board carries
# its own organization_id, the category carries its own — so if the resolver
# stops re-checking it, org A's tasks silently land on org B's board.
s = _Session(categories={10: FOREIGN_BOARD.id}, boards=ALL_BOARDS)
check(
    "category pointing at another org's board -> falls back to org default",
    resolve(s, category_id=10).id == ORG_DEFAULT.id,
)

s = _Session(
    categories={10: CATEGORY_BOARD.id}, teams={20: FOREIGN_BOARD.id}, boards=ALL_BOARDS,
)
check(
    "team pointing across orgs falls through to the CATEGORY, not to the team's board",
    resolve(s, category_id=10, team_id=20).id == CATEGORY_BOARD.id,
)

# A board deleted out from under the pointer: the FK's ON DELETE SET NULL
# should prevent this, but the resolver must not crash if it ever happens.
s = _Session(categories={10: 404}, boards=ALL_BOARDS)
check(
    "pointer at a board that no longer exists -> org default, no exception",
    resolve(s, category_id=10).id == ORG_DEFAULT.id,
)

s = _Session(boards=ALL_BOARDS)
check(
    "pointer on a category row that does not exist -> org default",
    resolve(s, category_id=777).id == ORG_DEFAULT.id,
)


print("\n[re-route] re-filing a meeting follows its cards")

# `reroute_meeting_tasks` MOVES USER DATA, so its selection rule needs a guard
# that is independent of the live DB. Board resolution is already covered
# above, so it is stubbed here and only the move logic is under test.


class _Task:
    def __init__(self, task_id, board_id, column_id, status):
        self.id, self.board_id, self.column_id = task_id, board_id, column_id
        self.status, self.position, self.meeting_id = status, 1.0, 500


class _Col:
    def __init__(self, col_id, bound_status, position):
        self.id, self.bound_status, self.position = col_id, bound_status, position


class _Meeting:
    id, organization_id, category_id, team_id = 500, ORG, 10, None


class _RerouteSession:
    """Answers the two `.all()` queries reroute issues, and nothing else."""

    def __init__(self, tasks, columns):
        self.tasks, self.columns, self.activity = tasks, columns, []

    def query(self, entity):
        from app.db.models import KanbanColumn
        session = self

        class _Q:
            def __init__(self):
                self.board_filter = None

            def filter(self, *conds):
                for c in conds:
                    left = getattr(c, "left", None)
                    if left is not None and left.name == "board_id":
                        self.board_filter = c.right.value
                return self

            def order_by(self, *a):
                return self

            def all(self):
                if entity is KanbanColumn:
                    return [c for c in session.columns]
                return [t for t in session.tasks if t.board_id == self.board_filter]

        return _Q()


def _reroute(tasks, columns, old_id, new_id):
    """Run the real function with resolution + audit stubbed out."""
    boards = {old_id: _Board(old_id, ORG), new_id: _Board(new_id, ORG)}
    calls = []

    def fake_resolve(db, org, *, category_id=None, team_id=None):
        calls.append((category_id, team_id))
        return boards[old_id] if len(calls) == 1 else boards[new_id]

    session = _RerouteSession(tasks, columns)
    orig_resolve = defaults.resolve_board
    import app.services.kanban.positions as positions
    import app.services.kanban.activity as activity
    orig_pos, orig_act = positions.position_for_end, activity.record_activity
    defaults.resolve_board = fake_resolve
    positions.position_for_end = lambda db, col: 999.0
    activity.record_activity = lambda db, **kw: session.activity.append(kw)
    try:
        return defaults.reroute_meeting_tasks(
            session, _Meeting(), old_category_id=None, old_team_id=None,
        ), session
    finally:
        defaults.resolve_board = orig_resolve
        positions.position_for_end = orig_pos
        activity.record_activity = orig_act


COLS = [_Col(90, "todo", 0), _Col(91, "in_progress", 1), _Col(92, "done", 2)]

# THE RULE THIS EXISTS FOR: a card someone dragged to another board is a
# deliberate human placement. Re-filing the meeting must not drag it back.
on_default = _Task(1, 61, 219, "todo")
hand_moved = _Task(2, 77, 300, "todo")
moved, sess = _reroute([on_default, hand_moved], COLS, 61, 62)
check("card on the old default board moves", on_default.board_id == 62)
check("hand-placed card on another board is NOT moved", hand_moved.board_id == 77)
check("returns the count actually moved", moved == 1)
check("writes one audit row per moved card", len(sess.activity) == 1)
check(
    "audit row is a column_moved with a reason",
    sess.activity[0]["event_type"] == "column_moved"
    and "reason" in sess.activity[0]["after"],
)

# Status must survive the move — a card in progress must not reset to To Do.
in_prog = _Task(3, 61, 219, "in_progress")
_reroute([in_prog], COLS, 61, 62)
check("card keeps its status column (in_progress -> the in_progress column)",
      in_prog.column_id == 91)

# A status with no matching column falls back rather than crashing.
odd = _Task(4, 61, 219, "in_review")
_reroute([odd], COLS, 61, 62)
check("unmatched status falls back to the first column", odd.column_id == 90)

# Same board on both sides = nothing to do, and no audit noise.
same = _Task(5, 61, 219, "todo")
moved, sess = _reroute([same], COLS, 61, 61)
check("no move when old and new board are the same",
      moved == 0 and same.board_id == 61 and not sess.activity)

# A card that was never routed has no default to follow.
orphan = _Task(6, None, None, "todo")
moved, _ = _reroute([orphan], COLS, 61, 62)
check("card with no board is left alone", moved == 0 and orphan.board_id is None)


print("\n[signature] existing callers keep their behaviour")

# Every pre-existing call site passed org only. Those must resolve exactly as
# they did before this feature — scope kwargs are keyword-only with None
# defaults precisely so that stays true.
import inspect  # noqa: E402

sig = inspect.signature(defaults.resolve_landing_for_meeting)
check(
    "category_id/team_id are keyword-only and default to None",
    all(
        sig.parameters[p].kind is inspect.Parameter.KEYWORD_ONLY
        and sig.parameters[p].default is None
        for p in ("category_id", "team_id")
    ),
)

src = inspect.getsource(defaults.resolve_board)
check(
    "resolve_board still filters boards by organization_id",
    "KanbanBoard.organization_id == organization_id" in src,
)


print(f"\n{'=' * 60}")
if failures:
    print(f"FAILED {len(failures)}/{checks}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"PASSED {checks}/{checks}")
