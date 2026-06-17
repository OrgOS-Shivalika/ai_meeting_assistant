"""Phase 14A — Kanban foundation.

Creates the Kanban surface: boards, columns, comments, activity audit
log. Extends `tasks` with `board_id`, `column_id`, `position`, `status`,
`description`. Backfills every existing org with a default board + the
four standard columns, then assigns every existing task to that board's
"To Do" or "Done" column based on its current `is_completed` flag.

Backward compat: the `is_completed` column stays. A CHECK constraint
enforces `(is_completed = 1) ⇔ (status = 'done')` so any path that
writes one without the other will fail loudly instead of silently
diverging. Server-side writers should set `status`; we update
`is_completed` from it in the orchestration layer (Phase 14C).

Seeds one `task_activity` row per existing task (event_type='created')
so the per-card activity feed has history from day one rather than a
"no activity yet" gap.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "x4f8b9c0d1e2"
down_revision = "w3e2f4a5b6c7"
branch_labels = None
depends_on = None


# Default columns seeded for every new board. Kept here (not in
# defaults.py) because this migration is the canonical first writer;
# Phase 14B's board-creation endpoint should re-use the same shape via
# `app/services/kanban/defaults.py:DEFAULT_COLUMNS`.
DEFAULT_COLUMNS = [
    # (name, position, color, is_done_column, bound_status)
    ("To Do",       0, "slate",   False, "todo"),
    ("In Progress", 1, "indigo",  False, "in_progress"),
    ("In Review",   2, "amber",   False, "in_review"),
    ("Done",        3, "emerald", True,  "done"),
]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Create kanban_boards
    # ------------------------------------------------------------------
    op.create_table(
        "kanban_boards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_by_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_default", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
        sa.CheckConstraint(
            "scope_type IN ('org', 'category', 'team')",
            name="ck_kanban_boards_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'org' AND scope_id IS NULL) OR "
            "(scope_type IN ('category', 'team') AND scope_id IS NOT NULL)",
            name="ck_kanban_boards_scope_id_matches",
        ),
    )
    op.create_index(
        "ix_kanban_boards_organization_id",
        "kanban_boards", ["organization_id"],
    )
    op.create_index(
        "ix_kanban_boards_org_scope",
        "kanban_boards", ["organization_id", "scope_type", "scope_id"],
    )
    # Default-board uniqueness — two partial indexes because Postgres
    # treats NULL as distinct in unique indexes by default, which
    # would let multiple org-level (scope_id IS NULL) default boards
    # slip through a single (org, scope_type, scope_id) index. Split:
    #   - scoped boards (category/team) use the full key
    #   - org-level boards key on (org, scope_type) only, with
    #     scope_id IS NULL in the WHERE predicate so the index only
    #     covers those rows
    op.create_index(
        "uq_kanban_boards_default_scoped",
        "kanban_boards",
        ["organization_id", "scope_type", "scope_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND scope_id IS NOT NULL"),
    )
    op.create_index(
        "uq_kanban_boards_default_org",
        "kanban_boards",
        ["organization_id", "scope_type"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND scope_id IS NULL"),
    )

    # ------------------------------------------------------------------
    # 2. Create kanban_columns
    # ------------------------------------------------------------------
    op.create_table(
        "kanban_columns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "board_id", sa.Integer(),
            sa.ForeignKey("kanban_boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column(
            "is_done_column", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column("wip_limit", sa.Integer(), nullable=True),
        sa.Column("bound_status", sa.String(length=24), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
        sa.UniqueConstraint(
            "board_id", "position",
            name="uq_kanban_columns_board_position",
        ),
        sa.CheckConstraint(
            "bound_status IS NULL OR bound_status IN "
            "('todo', 'in_progress', 'in_review', 'done', 'archived')",
            name="ck_kanban_columns_bound_status",
        ),
    )
    op.create_index(
        "ix_kanban_columns_board_id",
        "kanban_columns", ["board_id"],
    )

    # ------------------------------------------------------------------
    # 3. Extend `tasks` with Kanban columns + status enum
    # ------------------------------------------------------------------
    op.add_column(
        "tasks",
        sa.Column("board_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("column_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("position", sa.Float(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "status", sa.String(length=24),
            nullable=False, server_default="todo",
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_board_id",
        "tasks", "kanban_boards",
        ["board_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tasks_column_id",
        "tasks", "kanban_columns",
        ["column_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_board_id", "tasks", ["board_id"])
    op.create_index("ix_tasks_column_id", "tasks", ["column_id"])

    # ------------------------------------------------------------------
    # 4. Create task_comments
    # ------------------------------------------------------------------
    op.create_table(
        "task_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=True,
        ),
    )
    op.create_index(
        "ix_task_comments_task_id",
        "task_comments", ["task_id"],
    )

    # ------------------------------------------------------------------
    # 5. Create task_activity (append-only audit log)
    # ------------------------------------------------------------------
    op.create_table(
        "task_activity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "task_id", sa.Integer(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'created', 'status_changed', 'column_moved', 'owner_changed', "
            "'due_changed', 'priority_changed', 'description_changed', "
            "'title_changed', 'commented', 'archived', 'restored'"
            ")",
            name="ck_task_activity_event_type",
        ),
    )
    op.create_index(
        "ix_task_activity_task_id",
        "task_activity", ["task_id"],
    )
    op.create_index(
        "ix_task_activity_task_created",
        "task_activity", ["task_id", "created_at"],
    )

    # ------------------------------------------------------------------
    # 6. Backfill — for each org, create the default board + columns,
    #    then assign every task on that org's meetings to it.
    #
    # Single SQL block per step so the migration runs in O(orgs + tasks)
    # round-trips, not O(n^2). All inside the same transaction.
    # ------------------------------------------------------------------
    conn = op.get_bind()

    # 6a. Create one default board per org.
    conn.execute(sa.text("""
        INSERT INTO kanban_boards (
            organization_id, name, description, scope_type, scope_id,
            is_default, created_at, updated_at
        )
        SELECT
            o.id, 'Tasks',
            'Default board for all action items across this organization',
            'org', NULL, true, now(), now()
        FROM organizations o
        WHERE NOT EXISTS (
            SELECT 1 FROM kanban_boards b
            WHERE b.organization_id = o.id
              AND b.scope_type = 'org'
              AND b.is_default = true
        );
    """))

    # 6b. Seed the four default columns for each newly-created board.
    for name, position, color, is_done, bound_status in DEFAULT_COLUMNS:
        conn.execute(
            sa.text("""
                INSERT INTO kanban_columns (
                    board_id, name, position, color, is_done_column,
                    bound_status, created_at, updated_at
                )
                SELECT b.id, :name, :position, :color, :is_done,
                       :bound_status, now(), now()
                FROM kanban_boards b
                WHERE b.scope_type = 'org' AND b.is_default = true;
            """),
            {
                "name": name,
                "position": position,
                "color": color,
                "is_done": is_done,
                "bound_status": bound_status,
            },
        )

    # 6c. Backfill every task with (board_id, column_id, status, position).
    # Status comes from is_completed; position is row_number * 1000
    # per (column_id) ordered by created_at DESC so the most recent
    # tasks sort to the top.
    conn.execute(sa.text("""
        WITH task_routing AS (
            SELECT
                t.id AS task_id,
                b.id AS board_id,
                c.id AS column_id,
                CASE WHEN t.is_completed = 1 THEN 'done' ELSE 'todo' END AS status
            FROM tasks t
            JOIN meetings m   ON m.id = t.meeting_id
            JOIN kanban_boards b
              ON b.organization_id = m.organization_id
             AND b.scope_type = 'org'
             AND b.is_default = true
            JOIN kanban_columns c
              ON c.board_id = b.id
             AND c.bound_status = CASE WHEN t.is_completed = 1 THEN 'done' ELSE 'todo' END
        )
        UPDATE tasks t
        SET board_id  = tr.board_id,
            column_id = tr.column_id,
            status    = tr.status
        FROM task_routing tr
        WHERE t.id = tr.task_id;
    """))

    # 6d. Assign positions per column (row_number desc by created_at).
    conn.execute(sa.text("""
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY column_id
                    ORDER BY created_at DESC NULLS LAST, id DESC
                ) * 1000.0 AS pos
            FROM tasks
            WHERE column_id IS NOT NULL
        )
        UPDATE tasks t
        SET position = r.pos
        FROM ranked r
        WHERE t.id = r.id;
    """))

    # 6e. Seed one `task_activity` row per existing task so the feed
    # has history. `actor_user_id` is NULL (system migration), and
    # `before` is NULL because the task was just created from this
    # perspective.
    conn.execute(sa.text("""
        INSERT INTO task_activity (
            task_id, actor_user_id, actor_name, event_type,
            before, after, created_at
        )
        SELECT
            t.id, NULL, 'system',
            'created',
            NULL,
            jsonb_build_object(
                'task', t.task,
                'owner', t.owner_name,
                'status', t.status,
                'priority', t.priority,
                'due_date', t.due_date
            ),
            COALESCE(t.created_at, now())
        FROM tasks t;
    """))

    # ------------------------------------------------------------------
    # 7. Add CHECK constraints AFTER backfill so existing data doesn't
    #    break the migration. Status enum guard + is_completed/status
    #    lockstep enforcement.
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('todo', 'in_progress', 'in_review', 'done', 'archived')",
    )
    op.create_check_constraint(
        "ck_tasks_status_completed_match",
        "tasks",
        "(is_completed = 1 AND status = 'done') OR "
        "(is_completed = 0 AND status <> 'done')",
    )


def downgrade() -> None:
    # Reverse order: constraints → indexes → columns → tables.
    op.drop_constraint("ck_tasks_status_completed_match", "tasks", type_="check")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")

    op.drop_index("ix_task_activity_task_created", table_name="task_activity")
    op.drop_index("ix_task_activity_task_id", table_name="task_activity")
    op.drop_table("task_activity")

    op.drop_index("ix_task_comments_task_id", table_name="task_comments")
    op.drop_table("task_comments")

    op.drop_index("ix_tasks_column_id", table_name="tasks")
    op.drop_index("ix_tasks_board_id", table_name="tasks")
    op.drop_constraint("fk_tasks_column_id", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_board_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "description")
    op.drop_column("tasks", "status")
    op.drop_column("tasks", "position")
    op.drop_column("tasks", "column_id")
    op.drop_column("tasks", "board_id")

    op.drop_index("ix_kanban_columns_board_id", table_name="kanban_columns")
    op.drop_table("kanban_columns")

    # IF EXISTS — this migration shipped with a different index name
    # initially (`uq_kanban_boards_default_per_scope`). Tolerate both
    # so a downgrade works regardless of which version of the upgrade
    # populated the schema.
    op.execute("DROP INDEX IF EXISTS uq_kanban_boards_default_org")
    op.execute("DROP INDEX IF EXISTS uq_kanban_boards_default_scoped")
    op.execute("DROP INDEX IF EXISTS uq_kanban_boards_default_per_scope")
    op.drop_index("ix_kanban_boards_org_scope", table_name="kanban_boards")
    op.drop_index("ix_kanban_boards_organization_id", table_name="kanban_boards")
    op.drop_table("kanban_boards")
