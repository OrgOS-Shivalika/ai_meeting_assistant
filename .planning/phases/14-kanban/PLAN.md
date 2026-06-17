# Phase 14 — Kanban Boards

**Status:** Planned, not started
**Depends on:** Phases 1–13 (existing `tasks` table, organization scoping, auth)
**Target effort:** ~8–11 dev days for v1 across K1→K4

---

## 1. Vision

A first-class task-management surface that lives next to meetings. Auto-extracted tasks land on a Kanban board automatically; users drag them between columns, add details, leave comments, and run a real day-to-day workflow without leaving the app.

Long-term target: feature parity with Jira Kanban — boards, columns, cards, drag-drop, filters, comments, activity log, labels, WIP limits, subtasks, permissions.

**v1 ships the spine** — enough to be usable. Deeper Jira features layer on after v1 ships and gets used.

---

## 2. v1 Scope

### In

- **Boards** scoped to `org`, `category`, or `team` — mirrors the existing [Category](app/db/models.py#L246) / [Team](app/db/models.py#L269) hierarchy
- 4 **default columns** per new board: `To Do`, `In Progress`, `In Review`, `Done`
- **Custom columns** — add / rename / reorder / delete (delete forces target picker for orphan cards)
- **Card drag-and-drop** between columns + reorder within column
- **Card detail drawer** (right-side) — title, markdown description, owner picker, due date, priority, status, comments, activity log
- **Quick-add card** from column footer (manual task creation, not just from meetings)
- **Auto-extracted meeting tasks** land on the org's default board's `To Do` column
- **Filters**: assignee + priority (chips, multi-select)
- **Search** within a board (client-side, fuzzy on title + description)
- **Per-meeting board view** — `MeetingDetailPage` gets a tab that filters the default board by `meeting_id`
- **Optimistic UI** + auto-refetch every 20s when board is focused (no WebSockets in v1)

### Out (later phases)

- Labels / tags
- WIP limits (column field defined in v1 but unused)
- Subtasks
- Swimlanes
- Custom workflows / status transition rules
- Per-board permissions (org scoping only in v1)
- @mentions + notifications (blocked on Members work)
- WebSocket realtime sync
- Backlog separate view
- Sprints (that's Jira Software, not Kanban)
- Custom fields

---

## 3. Locked Decisions

Confirmed with user during planning:

| Decision | Chosen |
|---|---|
| Default board scope | **One org-level board** ("Tasks"). Category/team boards can be created manually later. |
| Card detail surface | **Right-side drawer** (Jira/Linear convention). |
| Status enum | **Fixed**: `todo` / `in_progress` / `in_review` / `done` / `archived`. Column labels are user-renamable; underlying status is fixed for cross-board reporting. |
| Filters in v1 | **Assignee + priority** (cheap once data is there). |
| Per-meeting board tab | **Yes** — adds ~2h in K3. |
| Column delete UX | **Explicit target picker** for orphan cards. ~30min extra UX. |

---

## 4. Data Model

### New tables

```python
# app/db/models.py — additions

class KanbanBoard(Base):
    __tablename__ = "kanban_boards"
    id = Column(Integer, primary_key=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # Scope: where this board "belongs". Mirrors Category/Team linkage.
    scope_type = Column(String(16), nullable=False)  # 'org' | 'category' | 'team'
    scope_id = Column(Integer, nullable=True)        # category.id / team.id; null for org-level
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    is_default = Column(Boolean, default=False, nullable=False)  # one default per (org, scope_type, scope_id)
    created_at = Column(DateTime(timezone=True), default=...)
    updated_at = Column(DateTime(timezone=True), default=..., onupdate=...)

    __table_args__ = (
        CheckConstraint("scope_type IN ('org', 'category', 'team')", name="ck_kanban_boards_scope_type"),
        CheckConstraint(
            "(scope_type = 'org' AND scope_id IS NULL) OR "
            "(scope_type IN ('category', 'team') AND scope_id IS NOT NULL)",
            name="ck_kanban_boards_scope_id_matches",
        ),
        # Partial unique: one default board per scope.
        Index(
            "uq_kanban_boards_default_per_scope",
            "organization_id", "scope_type", "scope_id",
            unique=True, postgresql_where="is_default = true",
        ),
    )


class KanbanColumn(Base):
    __tablename__ = "kanban_columns"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("kanban_boards.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    position = Column(Integer, nullable=False)             # column display order (left→right)
    color = Column(String(16), nullable=True)              # tailwind palette key ('slate', 'indigo', 'emerald', ...)
    is_done_column = Column(Boolean, default=False, nullable=False)  # moving here implies task is "done"
    wip_limit = Column(Integer, nullable=True)             # v2 — defined but UI-unused in v1
    # The column's bound status. When a task is moved into this column,
    # tasks.status is set to this value. Null = "no transition" (rare).
    bound_status = Column(String(24), nullable=True)       # 'todo' | 'in_progress' | 'in_review' | 'done' | 'archived'
    created_at, updated_at = ...

    __table_args__ = (
        UniqueConstraint("board_id", "position", name="uq_kanban_columns_board_position"),
    )


class TaskComment(Base):
    __tablename__ = "task_comments"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String, nullable=True)            # snapshot for when user is deleted
    body = Column(Text, nullable=False)                    # markdown
    created_at, updated_at = ...


class TaskActivity(Base):
    """Append-only audit log per task. Drives the activity feed in the
    card detail drawer. NEVER updated — every event is a new row."""
    __tablename__ = "task_activity"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_name = Column(String, nullable=True)             # snapshot
    event_type = Column(String(32), nullable=False)
    # event_type values:
    #   'created' | 'status_changed' | 'column_moved' | 'owner_changed'
    #   | 'due_changed' | 'priority_changed' | 'description_changed'
    #   | 'title_changed' | 'commented' | 'archived' | 'restored'
    before = Column(JSONB, nullable=True)
    after = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=..., nullable=False)
```

### Extend existing `Task` model

```python
class Task(Base):
    # Existing columns kept untouched.
    # NEW columns:
    board_id  = Column(Integer, ForeignKey("kanban_boards.id", ondelete="SET NULL"), nullable=True, index=True)
    column_id = Column(Integer, ForeignKey("kanban_columns.id", ondelete="SET NULL"), nullable=True, index=True)
    position  = Column(Float, nullable=True)                # Trello-style ordering within column
    status    = Column(String(24), nullable=False, default="todo", server_default="todo")
    description = Column(Text, nullable=True)               # markdown
```

`is_completed` stays for backward compat — derived from `status='done'` going forward. Single source of truth = `status`. Don't drop the column in this migration; remove in a follow-up phase after frontend stops reading it.

### Position ordering (Trello-style float)

- New card → `position = max(column_positions) + 1000`
- Insert between A and B → `position = (A.position + B.position) / 2`
- Drag-drop to end of column → same as new card
- **Rebalance trigger**: when computed gap < `0.01`, rewrite all positions for that column as `(row_number() OVER (...)) * 1000`. Single DB transaction per rebalance.
- Helper: `app/services/kanban/positions.py` — `compute_insert_position(column_id, after_task_id=None, before_task_id=None)` + `rebalance_column(column_id)`.

---

## 5. API Surface

All routes org-scoped via existing [`get_current_user`](app/dependencies/auth.py) dependency. No new auth.

```
# Boards
GET    /boards                          # list visible boards (org-scoped)
POST   /boards                          # create board (with default columns)
GET    /boards/{id}                     # board + columns + cards (grouped, ordered) — single round-trip
PATCH  /boards/{id}                     # rename / change scope / set default
DELETE /boards/{id}                     # cascade columns, dereference tasks

# Columns
POST   /boards/{id}/columns             # add column at position
PATCH  /columns/{id}                    # rename / reorder / color / is_done_column / bound_status
DELETE /columns/{id}                    # body: { move_cards_to_column_id: int }

# Tasks (extend existing)
POST   /boards/{id}/tasks               # manual create card (NOT meeting-derived)
PATCH  /tasks/{id}/move                 # atomic { column_id, position } — server computes if position omitted
PATCH  /tasks/{id}                      # existing — extend to accept status, description, board_id, column_id

# Comments
GET    /tasks/{id}/comments
POST   /tasks/{id}/comments
PATCH  /comments/{id}
DELETE /comments/{id}

# Activity
GET    /tasks/{id}/activity             # ordered desc, paginated (default limit 50)
```

### Board GET response shape (single-fetch optimization)

```json
{
  "id": 1,
  "name": "Tasks",
  "scope_type": "org",
  "scope_id": null,
  "is_default": true,
  "columns": [
    {
      "id": 10,
      "name": "To Do",
      "position": 0,
      "color": "slate",
      "is_done_column": false,
      "bound_status": "todo",
      "wip_limit": null,
      "tasks": [
        {
          "id": 42,
          "task": "Ship the build",
          "owner": "Sarah",
          "due_date": "2026-06-20",
          "priority": "high",
          "status": "todo",
          "position": 1000,
          "meeting_id": 4689,
          "meeting_title": "Sprint planning",
          "comment_count": 2,
          "is_unassigned": false
        }
      ]
    }
  ]
}
```

`GET /boards/{id}` is the hot path. One round-trip = board + all columns + all cards on it. Activity + comments fetched lazily when drawer opens.

---

## 6. Frontend Structure

```
src/features/kanban/
  pages/
    BoardListPage.tsx            # /boards
    BoardPage.tsx                 # /board/:id   ← the Kanban UI
  components/
    BoardHeader.tsx               # title, filters, search, "New card", "Board settings"
    BoardColumn.tsx               # column header + droppable area + quick-add footer
    TaskCard.tsx                  # board card (compact view)
    TaskDetailDrawer.tsx          # right-side panel, opens on card click
    QuickAddCard.tsx              # inline "add card" input at column bottom
    CreateBoardModal.tsx          # name + scope picker
    ColumnEditor.tsx              # rename, color, mark "done column", delete (with picker)
    DeleteColumnModal.tsx         # forces target column for orphan cards
    BoardFilters.tsx              # assignee + priority chips
    TaskActivityList.tsx          # audit log feed in drawer
    TaskComments.tsx              # comment thread in drawer
    TaskDescriptionEditor.tsx     # markdown textarea + preview
  hooks/
    useBoard.ts                   # fetch + 20s polling
    useDragHandlers.ts            # @dnd-kit wiring + optimistic update
  api.ts                          # all kanban API calls
  types.ts                        # Board, Column, BoardTask, Comment, Activity
```

**Drag-and-drop library**: [`@dnd-kit/core`](https://docs.dndkit.com) + `@dnd-kit/sortable`. Modern, accessible, hooks-based, no provider hell. Add to `package.json`.

**Sidebar**: add a `LayoutGrid` icon entry near "Tasks" → routes to `/boards`. The "Tasks" link stays as the flat-list Action Items view (different surface, both valid).

**Meeting detail tab**: add a `Board` tab to [MeetingDetailPage.tsx](meeting_ai_frontend/src/features/meetings/pages/MeetingDetailPage.tsx) that mounts `BoardPage` with `?meeting_id=<id>` query — filters cards on that meeting.

---

## 7. Migration Strategy

Single Alembic migration `phase14a_kanban_foundation`:

1. **Create** `kanban_boards`, `kanban_columns`, `task_comments`, `task_activity` tables.
2. **Add columns** to `tasks`: `board_id`, `column_id`, `position`, `status`, `description`.
3. **For each `organization`**: insert one default board (`name='Tasks'`, `scope_type='org'`, `scope_id=NULL`, `is_default=TRUE`) + the 4 default columns:
   - `To Do` (position=0, bound_status='todo', color='slate')
   - `In Progress` (position=1, bound_status='in_progress', color='indigo')
   - `In Review` (position=2, bound_status='in_review', color='amber')
   - `Done` (position=3, bound_status='done', color='emerald', is_done_column=TRUE)
4. **Backfill** all existing tasks:
   - `board_id` → that org's default board
   - `column_id` → `Done` if `is_completed=1`, else `To Do`
   - `status` → `'done'` if `is_completed=1` else `'todo'`
   - `position` → `(ROW_NUMBER() OVER (PARTITION BY column_id ORDER BY created_at DESC)) * 1000`
5. **Keep `is_completed`** column — derived from `status='done'` server-side. Drop in a follow-up migration after frontend cutover.
6. **Insert one `task_activity` row** per existing task with `event_type='created'` so the activity feed has history from day one.

Auto-extracted task paths that need a one-line change to attach board+column on insert:
- [`LiveTaskPersistence.handle_event`](app/services/live_tasks/persistence.py#L17) — live extractor
- The post-meeting analyzer persistence path in [`app/pipelines/meeting_pipeline.py`](app/pipelines/meeting_pipeline.py)

Single helper `app/services/kanban/defaults.py:get_default_landing_column(org_id) -> Column` keeps the logic in one place.

---

## 8. Phasing — K1 → K4

### K1 — Data model + migration + status enum (1-2 days)

**Deliverables:**
- New models in [`app/db/models.py`](app/db/models.py)
- Alembic migration `phase14a_kanban_foundation.py` with backfill
- Helper module `app/services/kanban/defaults.py` (default board/column lookup)
- Helper module `app/services/kanban/positions.py` (compute_insert_position + rebalance_column)
- Update [`LiveTaskPersistence`](app/services/live_tasks/persistence.py) + analyzer persistence to attach board+column on insert
- Extend `PATCH /tasks/{id}` to accept `status`, `description`, `board_id`, `column_id`
- Keep `GET /tasks` and `GET /meetings/{id}/tasks` working unchanged (backward compat)

**Success criteria:**
- All existing tasks land on the default board, partitioned into `To Do` / `Done` by `is_completed`
- A new meeting produces tasks that auto-attach to the default board's `To Do` column
- `pytest tests/test_kanban_k1.py` passes (new test file: backfill correctness, default-column landing, position assignment)

### K2 — Board + column CRUD API (1-2 days)

**Deliverables:**
- All `/boards/*` and `/columns/*` endpoints (router: `app/api/kanban_router.py`)
- `PATCH /tasks/{id}/move` with position math + rebalance trigger
- `GET /boards/{id}` returns columns + cards in one shot (Pydantic response model in `app/schemas/kanban_schema.py`)
- Activity log auto-written by API layer (helper `record_activity(db, task_id, actor, event_type, before, after)`) on every PATCH/move/comment

**Success criteria:**
- Hitting the full API via curl/Requestly creates a board, columns, cards, moves them, gets a full board JSON
- Position math is correct under stress (insert 50 cards, drag 20 around, verify no overlap)
- `pytest tests/test_kanban_k2.py` passes (move endpoints, activity log, column delete with target picker)

### K3 — Board UI shell + drag-and-drop (3-4 days)

**Deliverables:**
- `BoardListPage` + `BoardPage` skeleton
- Columns + cards render with current data
- Drag-and-drop wired via `@dnd-kit`, optimistic move with rollback on API failure
- Quick-add card inline at column bottom
- 20s polling refresh
- `BoardFilters` (assignee + priority chips)
- Sidebar entry `Boards` (`LayoutGrid` icon)
- Per-meeting `Board` tab in `MeetingDetailPage` (filters by `meeting_id` query param)
- Search box (client-side fuzzy on title + description)

**Success criteria:**
- Feature can be demo'd: create board, drag cards between columns, quick-add a manual card, filter by assignee
- Drag-drop feels snappy (<100ms perceived) — optimistic update, no spinner during the drop
- TypeScript clean, `npm run build` clean

### K4 — Card detail drawer + comments + activity (2-3 days)

**Deliverables:**
- `TaskDetailDrawer` slides in from the right when a card is clicked
- All fields editable in drawer: title, description (markdown w/ preview), owner picker (reuse [`TaskAssignmentEditor`](meeting_ai_frontend/src/features/meetings/components/TaskAssignmentEditor.tsx)), due date, priority, status (column move)
- `TaskComments` thread — add/edit/delete own comments
- `TaskActivityList` — reverse-chronological audit log
- Keyboard shortcuts: `Esc` to close, `e` to edit, `←/→` to navigate between cards
- Deep link: `/board/:id?task=:taskId` opens the drawer on load

**Success criteria:**
- All fields round-trip through the API correctly
- Activity log shows every change made during the session
- Markdown description renders cleanly (links, lists, code blocks)
- TypeScript clean, `npm run build` clean

---

## 9. Open Questions (decide during K1)

- **Markdown library** for description rendering — `react-markdown` (most common, MIT) vs `marked` (lighter). Going with `react-markdown` unless bundle size becomes a concern.
- **Polling vs. visibility-aware polling** — should we pause polling when tab is hidden? Yes — listen to `document.visibilitychange`, pause when hidden. Simple, cheap, kind to the server.
- **What happens when a meeting is deleted** — tasks have `ON DELETE CASCADE` on `meeting_id` today. Confirm this still works after Kanban backfill (tasks linked to board but also to meeting — cascade should still fire).

---

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Position float precision degrades after many moves | Cards land in wrong order | Rebalance trigger when gap < 0.01; covered by helper |
| `@dnd-kit` learning curve | K3 slips | Build a small standalone prototype first (1-2 hours); commit `@dnd-kit` docs link in the K3 PR description |
| `is_completed` and `status` drift apart | Reporting bugs | Server-side derivation only; never write `is_completed` directly in K1+; add a CHECK constraint in K1 migration: `is_completed = (status = 'done')` |
| Per-meeting tab needs back-filtering on board response | Slow render | `?meeting_id=` filter applied server-side in board GET, indexed on `tasks.meeting_id` already |
| Auto-extracted tasks racing default-board lookup at high meeting volume | Tasks land on null board | Cache the org default board lookup per request (LRU cache in `defaults.py`); fall back to creating-if-missing |

---

## 11. References

- Existing Task model: [app/db/models.py:121-137](app/db/models.py#L121-L137)
- Existing task API: [app/api/routes.py:572-652](app/api/routes.py#L572-L652)
- Existing Action Items page: [ActionItemsPage.tsx](meeting_ai_frontend/src/features/meetings/pages/ActionItemsPage.tsx)
- Existing owner picker (will be reused in drawer): [TaskAssignmentEditor.tsx](meeting_ai_frontend/src/features/meetings/components/TaskAssignmentEditor.tsx)
- Live task persistence path: [persistence.py](app/services/live_tasks/persistence.py)
- Sidebar (will get new entry): [Sidebar.tsx](meeting_ai_frontend/src/shared/components/Sidebar.tsx)
- Convention reference for audit tables: [graph_extraction_runs in models.py](app/db/models.py#L836)

---

## 12. Next Action

User to approve plan, then begin **K1 — Data model + migration**.
