"""add label_mappings for in-room speaker attribution

Revision ID: ag07labelmap
Revises: af06capture
Create Date: 2026-08-18

See SPEAKER_ATTRIBUTION_PLAN.md §8. Stores "voice cluster N is Karthik" per
meeting — the one artifact in this feature that cannot be re-derived, since
turns come back out of `meetings.transcript_raw` at will but the mapping is
either evidence captured at the time or a human correction.

Additive and safe: a brand-new table, nothing backfilled, no existing column
touched. Old code paths never mention it.

`UNIQUE(meeting_id, speaker_key)` on a serialized key rather than
`UNIQUE(meeting_id, participant_id, diarization_label)` — Postgres treats
NULLs as DISTINCT in unique indexes, so the latter would accept duplicate rows
for the same roster speaker. Same reason this schema already carries paired
partial unique indexes elsewhere.

`ondelete='CASCADE'` on meeting_id so deleting a meeting cannot FK-violate;
`ondelete='SET NULL'` on corrected_by so removing a user preserves the
correction while forgetting who made it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ag07labelmap"
down_revision = "af06capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "label_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("speaker_key", sa.String(length=64), nullable=False),
        sa.Column("participant_id", sa.String(), nullable=True),
        sa.Column("diarization_label", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column(
            "confidence", sa.Float(), nullable=False, server_default="0",
        ),
        sa.Column("matched_email", sa.String(), nullable=True),
        sa.Column(
            "needs_review", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("corrected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["meeting_id"], ["meetings.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["corrected_by"], ["users.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "speaker_key", name="uq_label_mappings_meeting_key",
        ),
    )
    op.create_index(
        "ix_label_mappings_meeting_id", "label_mappings", ["meeting_id"],
    )
    op.create_index("ix_label_mappings_id", "label_mappings", ["id"])


def downgrade() -> None:
    op.drop_index("ix_label_mappings_id", table_name="label_mappings")
    op.drop_index("ix_label_mappings_meeting_id", table_name="label_mappings")
    op.drop_table("label_mappings")
