"""Google Drive transcript export.

`users.drive_folder_id` — the "Meeting Transcripts" folder our app created in
the user's Drive when they connected Drive. Non-NULL means Drive export is on.
The app only holds the `drive.file` scope, so it can write to this folder (and
the files it put there) and nothing else; the user may rename or move it.

`meetings.drive_files` — {user_id: drive_file_id}, one Doc per recipient, so a
re-processed meeting updates its Doc instead of creating a second one.

Revision ID: av22driveexport
Revises: au21completedat
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "av22driveexport"
down_revision = "au21completedat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("drive_folder_id", sa.String(), nullable=True))
    op.add_column("meetings", sa.Column("drive_files", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("meetings", "drive_files")
    op.drop_column("users", "drive_folder_id")
