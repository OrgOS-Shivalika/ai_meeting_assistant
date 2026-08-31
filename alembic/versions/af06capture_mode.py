"""add meetings.capture_mode for in-room speaker attribution

Revision ID: af06capture
Revises: ae05rbac
Create Date: 2026-08-18

Adds one column. See SPEAKER_ATTRIBUTION_PLAN.md §8.

Safe by construction: NOT NULL with a server_default of 'online', so every
existing row backfills to exactly the behaviour it already had, and the
column is readable by old code paths that never mention it. No data is
rewritten and no index is added — the column is read one row at a time
(by primary key, at bot-creation and at attribution) and never filtered on.

Deliberately NOT included: `categories.default_capture_mode`. Per-meeting
selection covers the requirement, and a per-category default is still an
open product question (plan §15). Adding it later is one more column plus
three lines in the resolver.
"""
from alembic import op
import sqlalchemy as sa


revision = "af06capture"
down_revision = "ae05rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column(
            "capture_mode",
            sa.String(length=16),
            nullable=False,
            server_default="online",
        ),
    )


def downgrade() -> None:
    op.drop_column("meetings", "capture_mode")
