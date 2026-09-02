"""Reuse the reset-token table for invitations.

Adding a new member used to mail them a password. That is the thing this
removes: a password in an inbox is a plaintext credential sitting in a system
nobody here controls, readable by every hop and every backup, and still
readable months later. The industry answer is that the server never knows a
password the owner has not chosen — provisioning sends a LINK, and the
recipient sets their own.

The mechanism is exactly the reset flow already built in `al12pwreset`:
single-use, hashed at rest, expiring, and it ends with the account holder
choosing a password. So this adds a discriminator rather than a second table
with the same six columns and the same bugs.

`purpose` only changes the TTL and the wording of the email. Redemption is
identical, deliberately: two code paths that both set a password is how one of
them ends up skipping a check.

Revision ID: am13invitetoken
Revises: al12pwreset
"""
from alembic import op
import sqlalchemy as sa


revision = "am13invitetoken"
down_revision = "al12pwreset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "password_reset_tokens",
        # server_default so existing rows — all of them resets — stay valid.
        sa.Column(
            "purpose", sa.String(length=16),
            nullable=False, server_default="reset",
        ),
    )
    # Invalidation is per (user, purpose): accepting an invitation should not
    # silently kill a reset link the same person requested, and vice versa.
    op.create_index(
        "ix_password_reset_tokens_user_purpose",
        "password_reset_tokens", ["user_id", "purpose"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_password_reset_tokens_user_purpose",
        table_name="password_reset_tokens",
    )
    op.drop_column("password_reset_tokens", "purpose")
