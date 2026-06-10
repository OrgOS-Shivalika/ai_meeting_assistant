"""Phase 12E — closing_briefings audit table.

One row per meeting that the orchestrator attempted to brief. UNIQUE
on meeting_id; orchestrator UPDATEs in place across the
composing -> composed -> tts_ready -> playing -> spoken lifecycle.

Soft-coupled to the Phase 12A `meetings.closing_briefing_status`
column: that column is a single-field state indicator for filtering
+ idempotency, this table is the audit detail (script, audio, timings).

No backfill. Existing meetings have no closing briefing row; the
GET /meetings/{id}/closing-briefing endpoint returns 404 for them.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY


revision = "w3e2f4a5b6c7"
down_revision = "v2d1e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "closing_briefings",
        sa.Column(
            "id", UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id", sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("bot_id", sa.String(length=128), nullable=True),

        # Composed script
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("section_breakdown", JSONB(), nullable=True),
        sa.Column("sections_included", ARRAY(sa.String()), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("estimated_seconds", sa.Float(), nullable=True),
        sa.Column("actual_playback_seconds", sa.Float(), nullable=True),

        # Composer audit metadata
        sa.Column("composer_model", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=True),
        sa.Column("source_state_summary", JSONB(), nullable=True),

        # TTS audit metadata
        sa.Column("tts_provider", sa.String(length=32), nullable=True),
        sa.Column("tts_model", sa.String(length=64), nullable=True),
        sa.Column("tts_voice", sa.String(length=32), nullable=True),
        sa.Column("tts_char_count", sa.Integer(), nullable=True),
        sa.Column("tts_cache_hit", sa.Boolean(), nullable=True),

        # Storage + playback
        sa.Column("audio_storage_key", sa.Text(), nullable=True),
        sa.Column("audio_size_bytes", sa.Integer(), nullable=True),
        sa.Column("playback_id", sa.String(length=128), nullable=True),

        # Outcome
        sa.Column(
            "status", sa.String(length=24),
            nullable=False, server_default="composing",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),

        # Timing
        sa.Column("composing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("composed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tts_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("playback_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spoken_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),

        sa.UniqueConstraint("meeting_id", name="uq_closing_briefings_meeting"),
        sa.CheckConstraint(
            "status IN ("
            "'composing','composed','tts_ready','uploading','playing',"
            "'spoken','skipped','failed','upload_failed','playback_failed',"
            "'storage_not_configured','timeout'"
            ")",
            name="ck_closing_briefings_status",
        ),
    )

    op.create_index(
        "ix_closing_briefings_organization_id",
        "closing_briefings", ["organization_id"],
    )
    op.create_index(
        "ix_closing_briefings_meeting_id",
        "closing_briefings", ["meeting_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_closing_briefings_meeting_id", table_name="closing_briefings")
    op.drop_index("ix_closing_briefings_organization_id", table_name="closing_briefings")
    op.drop_table("closing_briefings")
