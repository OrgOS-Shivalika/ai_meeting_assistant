"""Phase 12A — closing-briefing lifecycle column on meetings.

Adds `meetings.closing_briefing_status` to track the state machine for
the AI verbal recap delivered before the bot leaves the call.

State machine:
    pending → winding_down → ended → (spoken | skipped | failed)

The column doubles as an idempotency guard: Recall.ai webhooks WILL
retry, so the bot.status_change handler must drop duplicate
`call_ended` events when the row is already past 'pending'.

Backfill rule: existing meetings whose pipeline already completed
(`status = 'completed'`) get `closing_briefing_status = 'skipped'`,
because there is no live cognition state left to recap. All other
existing rows stay 'pending' (harmless — no bot is in those meetings).
"""
from alembic import op
import sqlalchemy as sa


revision = "v2d1e3f4a5b6"
down_revision = "b34f1bb6c8f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column(
            "closing_briefing_status",
            sa.String(length=24),
            nullable=False,
            server_default="pending",
        ),
    )

    # Backfill historical completed meetings as 'skipped' — no live state
    # remains to produce a meaningful briefing, and the bot has long since
    # left those calls.
    op.execute(
        "UPDATE meetings SET closing_briefing_status = 'skipped' "
        "WHERE status = 'completed'"
    )


def downgrade() -> None:
    op.drop_column("meetings", "closing_briefing_status")
