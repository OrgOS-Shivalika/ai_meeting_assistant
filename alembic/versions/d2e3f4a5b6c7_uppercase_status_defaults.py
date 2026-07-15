"""uppercase server_defaults for embedding/graph status

Flips the stored default from lowercase to UPPERCASE for the status fields
that were enum-ified to uppercase (EmbeddingStatus / GraphStatus). These
columns have no CHECK constraint — only a server_default — and the DB
currently holds 0 rows, so this is a pure default swap with no row rewrite.

meetings.status is intentionally NOT here: it has only a client-side default
(no server_default, no CHECK), so its uppercase switch lives entirely in the
model/enum layer.

DEFERRED (still lowercase): Task.status AND closing_briefing_status. The
latter is entangled with the closing_briefings audit table (shared vocabulary
via final_status / _terminal_status) and must be converted together with it.

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-07-14
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, new_upper_default, old_lower_default)
_DEFAULTS = [
    ("meetings", "embedding_status", "PENDING", "pending"),
    ("meetings", "graph_status", "PENDING", "pending"),
    ("category_documents", "embedding_status", "PENDING", "pending"),
    ("category_documents", "graph_status", "PENDING", "pending"),
    ("team_documents", "embedding_status", "PENDING", "pending"),
    ("team_documents", "graph_status", "PENDING", "pending"),
]


def upgrade() -> None:
    for table, column, new_default, _old in _DEFAULTS:
        op.alter_column(table, column, server_default=new_default)


def downgrade() -> None:
    for table, column, _new, old_default in _DEFAULTS:
        op.alter_column(table, column, server_default=old_default)
