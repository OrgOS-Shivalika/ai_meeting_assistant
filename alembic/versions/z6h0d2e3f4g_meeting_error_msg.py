"""Add meetings.error_message so pipeline failures persist their reason.

Today the pipeline marks `status='failed'` but the exception text only
goes to stdout — no DB trace. This makes post-mortem impossible after
the celery worker process recycles.
"""
from alembic import op
import sqlalchemy as sa

revision = "z6h0d2e3f4g"
down_revision = "y5g9c1d2e3f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "error_message")
