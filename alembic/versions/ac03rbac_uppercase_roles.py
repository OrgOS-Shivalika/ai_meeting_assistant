
"""Store ``users.access_role`` uppercase: MEMBER / ADMIN / ORG_ADMIN.

The RBAC foundation (``ab02rbac``) stored lowercase values. Switching to
uppercase needs three things done together, or the table ends up with rows
its own constraint rejects:

  1. drop the CHECK — it still names the lowercase values, so it would
     reject the UPDATE below
  2. uppercase every existing row
  3. re-add the CHECK, and move the server default to 'MEMBER'

Order matters. Doing the UPDATE first fails against the old constraint;
adding the new constraint first fails against the old rows.

Only ``users.access_role`` changes. ``users.role`` (Phase 7E: viewer /
prompt_editor / org_admin) keeps its lowercase values — it is a separate
column governing the agent-prompt surfaces, and the two only coincidentally
share the string 'org_admin'.

``upper()`` rather than a value-by-value mapping so the migration is
correct for any row present, including ones written between ab02rbac and
this revision.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "ac03rbac"
down_revision = "ab02rbac"
branch_labels = None
depends_on = None


_UPPER = ("MEMBER", "ADMIN", "ORG_ADMIN")
_LOWER = ("member", "admin", "org_admin")


def _check_expr(values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"access_role IN ({joined})"


def upgrade() -> None:
    op.drop_constraint("ck_users_access_role", "users", type_="check")

    op.execute("UPDATE users SET access_role = upper(access_role)")

    # Keep the column's own default in step with the enum. A row inserted
    # by something that doesn't set the column explicitly (a raw SQL
    # fixture, a psql session) must still satisfy the constraint.
    op.alter_column(
        "users",
        "access_role",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="MEMBER",
    )

    op.create_check_constraint(
        "ck_users_access_role", "users", _check_expr(_UPPER)
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_access_role", "users", type_="check")
    op.execute("UPDATE users SET access_role = lower(access_role)")
    op.alter_column(
        "users",
        "access_role",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        server_default="member",
    )
    op.create_check_constraint(
        "ck_users_access_role", "users", _check_expr(_LOWER)
    )
