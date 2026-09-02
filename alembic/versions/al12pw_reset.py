"""Self-service password reset tokens.

A table rather than a signed/stateless token, because a reset link has to be
revocable BEFORE it expires — single-use, invalidated when the password changes
by any other route, and killable if someone reports a phishing attempt. A JWT
cannot do any of that without server state, at which point it is this table
with extra steps.

Only the SHA-256 of the token is stored. The raw value exists in exactly two
places: the email, and the URL the recipient clicks. A database leak therefore
yields no usable reset links, which is the entire reason to hash it — the same
argument as for password hashes, and it costs one hashlib call.

Revision ID: al12pwreset
Revises: ak11coldefer
"""
from alembic import op
import sqlalchemy as sa


revision = "al12pwreset"
down_revision = "ak11coldefer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # SHA-256 hex of the raw token. Unique so a (vanishingly unlikely)
        # collision is a hard error rather than two people sharing a link.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # NULL = still usable. Set on redemption, and also used to burn every
        # other outstanding token for that user at the same moment.
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        # Audit only — never used to authorize. Recorded so a burst of resets
        # against one account can be traced afterwards.
        sa.Column("requested_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
    )
    # The redemption lookup: by hash, every time.
    op.create_index(
        "ix_password_reset_tokens_hash", "password_reset_tokens", ["token_hash"]
    )
    # The rate-limit query: "how many has this account asked for lately".
    op.create_index(
        "ix_password_reset_tokens_user_created",
        "password_reset_tokens", ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_tokens_user_created", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
