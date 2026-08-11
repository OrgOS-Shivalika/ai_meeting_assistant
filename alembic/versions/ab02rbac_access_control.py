"""RBAC foundation — member / admin / org_admin access control.

Adds the schema the meeting-access-control feature needs. Nothing here
changes behaviour on its own; the enforcement lives in
``app/services/permissions.py``.

What lands:

  * ``users.access_role``          — 'member' | 'admin' | 'org_admin'
  * ``users.must_change_password`` — set when an org admin provisions an
                                     admin with a generated password
  * ``users.password_set_at``
  * ``participants.user_id``       — attendance → identity. THE column the
                                     member scope rule keys off.
  * ``participants.match_source``  — provenance for that link, see below
  * ``category_admins``            — many-to-many, "categories managed by
                                     this user". ``categories.user_id`` is
                                     the *creator* and is not a grant.
  * ``tasks.assignee_user_id``     — ``owner_name`` is free text and can't
                                     drive "tasks assigned to me"

``match_source`` exists because ``participants.email`` is not read
straight off the calendar — ``MeetingPipeline.save_participants`` derives
it with a fuzzy name-token heuristic that is fine for showing an avatar
and unsafe as an authorization input (two people named "Chris" collide).
Only ``calendar_exact`` and ``manual`` links confer access; see
``permissions.TRUSTED_MATCH_SOURCES``.

Backfills:
  * every existing user → 'org_admin', so nobody loses access they have
    today (all current orgs are effectively single-user)
  * ``category_admins`` seeded from ``categories.user_id`` so the new
    table agrees with the old creator column from day one
  * ``participants.user_id`` linked wherever the stored email matches a
    user in the same org exactly — tagged ``'legacy'``, i.e. NOT trusted
    for access, because we cannot retroactively tell which of those
    emails came from the exact path and which from the heuristic. Costs
    nothing: every pre-existing user is an org_admin anyway.
  * ``tasks.assignee_user_id`` is deliberately NOT backfilled from
    ``owner_name`` — same fuzzy-name hazard, and here it would silently
    grant edit rights.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "ab02rbac"
down_revision = "g3o7j9k1l2m"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. users — access role + provisioned-password lifecycle
    # ------------------------------------------------------------------
    # NOT NULL with a server_default so existing rows are covered without
    # a separate UPDATE pass. Note this is a *new* column, distinct from
    # the Phase 7E `role` ('viewer' | 'prompt_editor' | 'org_admin'),
    # which governs agent-prompt surfaces and keeps its own meaning.
    op.add_column(
        "users",
        sa.Column(
            "access_role",
            sa.String(length=16),
            nullable=False,
            server_default="member",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_access_role",
        "users",
        "access_role IN ('member', 'admin', 'org_admin')",
    )

    # Everyone who exists today keeps full access. Runs before any
    # enforcement ships, so this is a no-op behaviourally — but if it
    # were skipped, the server_default above would silently demote every
    # existing account to 'member' the moment enforcement lands.
    op.execute("UPDATE users SET access_role = 'org_admin'")

    # ------------------------------------------------------------------
    # 2. category_admins — "categories managed by this user"
    # ------------------------------------------------------------------
    op.create_table(
        "category_admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Who granted it. Kept for the audit trail the security spec
        # asks for; SET NULL so removing the granter doesn't revoke the
        # grant.
        sa.Column(
            "granted_by_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.UniqueConstraint("category_id", "user_id", name="uq_category_admin"),
    )
    # The hot path is "all categories managed by user X" — index the
    # user side; the unique constraint already covers the category side.
    op.create_index(
        "ix_category_admins_user_id", "category_admins", ["user_id"]
    )

    # Seed from the existing creator column so the new table is
    # immediately consistent with what the UI already implies.
    op.execute(
        """
        INSERT INTO category_admins (category_id, user_id)
        SELECT c.id, c.user_id
        FROM categories c
        WHERE c.user_id IS NOT NULL
        ON CONFLICT (category_id, user_id) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 3. participants — attendance → identity
    # ------------------------------------------------------------------
    op.add_column(
        "participants",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "participants",
        sa.Column("match_source", sa.String(length=24), nullable=True),
    )
    # Composite in this order: every member-scope query filters
    # `user_id = :me` first and then projects `meeting_id`, so the index
    # can serve the subquery without touching the heap.
    op.create_index(
        "ix_participants_user_meeting",
        "participants",
        ["user_id", "meeting_id"],
    )

    op.execute(
        """
        UPDATE participants p
        SET user_id = u.id,
            match_source = 'legacy'
        FROM users u
        JOIN meetings m ON m.organization_id = u.organization_id
        WHERE p.meeting_id = m.id
          AND p.email IS NOT NULL
          AND lower(p.email) = lower(u.email)
        """
    )

    # ------------------------------------------------------------------
    # 4. tasks — real assignee
    # ------------------------------------------------------------------
    op.add_column(
        "tasks",
        sa.Column(
            "assignee_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_assignee_user_id", "tasks", ["assignee_user_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_assignee_user_id", table_name="tasks")
    op.drop_column("tasks", "assignee_user_id")

    op.drop_index("ix_participants_user_meeting", table_name="participants")
    op.drop_column("participants", "match_source")
    op.drop_column("participants", "user_id")

    op.drop_index("ix_category_admins_user_id", table_name="category_admins")
    op.drop_table("category_admins")

    op.drop_constraint("ck_users_access_role", "users", type_="check")
    op.drop_column("users", "password_set_at")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "access_role")
