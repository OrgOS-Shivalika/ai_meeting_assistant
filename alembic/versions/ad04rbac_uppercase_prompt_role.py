"""Store ``users.role`` uppercase: VIEWER / PROMPT_EDITOR / ORG_ADMIN.

Companion to ``ac03rbac``, which did the same for ``users.access_role``.
The two columns are unrelated — ``role`` is Phase 7E agent-prompt
governance, ``access_role`` is meeting RBAC — but they now share a casing
convention so the ``users`` table doesn't read as though one of them was
missed.

Same three-step shape as ac03rbac, and the order is equally load-bearing:
drop the CHECK (it names the lowercase values and would reject the
UPDATE), uppercase the rows, re-add the CHECK.

Unlike ``access_role`` this column is NULLABLE, and NULL is meaningful:
it reads as VIEWER, the safe-deny default. So:

  * ``upper(NULL)`` is NULL, which is exactly what we want — NULL rows
    stay NULL rather than becoming a literal.
  * the re-added CHECK keeps its ``OR role IS NULL`` arm.
  * no server default is set, because the column never had one.
"""
from __future__ import annotations

from alembic import op


revision = "ad04rbac"
down_revision = "ac03rbac"
branch_labels = None
depends_on = None


_UPPER = ("VIEWER", "PROMPT_EDITOR", "ORG_ADMIN")
_LOWER = ("viewer", "prompt_editor", "org_admin")


def _check_expr(values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"role IN ({joined}) OR role IS NULL"


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = upper(role) WHERE role IS NOT NULL")
    op.create_check_constraint("ck_users_role", "users", _check_expr(_UPPER))


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.execute("UPDATE users SET role = lower(role) WHERE role IS NOT NULL")
    op.create_check_constraint("ck_users_role", "users", _check_expr(_LOWER))
