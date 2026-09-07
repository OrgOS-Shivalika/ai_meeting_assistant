"""Per-column permissions: who may move, add, edit and delete cards here.

A board already answers "who may touch this board at all". What it could not
say is that ONE column is stricter than the rest — that anyone may work the
board but only an org admin may put something in "Done", or that the cards in
"Signed off" are edited by two named people and nobody else.

Stored as ONE JSONB column rather than a `column_permissions` table. Four
actions on sixty boards is not a query workload: nothing filters or joins on
it, and every read already has the column row in hand. A table would be a
join, a migration and a cascade for data that is always fetched whole.

    {"move":   {"mode": "org_admins"},
     "create": {"mode": "specific", "user_ids": ["<uuid>", ...]},
     "edit":   {"mode": "admins"},
     "delete": {"mode": "everyone"}}

An ABSENT key means `everyone`, so `{}` is exactly today's behaviour and every
existing column keeps it. That is the whole backfill.

The cost of JSONB, named so the next person does not discover it: a user id in
`user_ids` has no foreign key, so deleting a user leaves a dead uuid in the
list. It matches nobody, which fails CLOSED — the permission gets narrower,
never wider. A cleanup sweep can come when somebody notices.

Revision ID: ar18colperms
Revises: aq17wfblock
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ar18colperms"
down_revision = "aq17wfblock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kanban_columns",
        sa.Column(
            "permissions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("kanban_columns", "permissions")
