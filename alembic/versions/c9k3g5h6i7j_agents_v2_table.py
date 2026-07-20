"""agents_v2 — per-team agent registry with per-org override overlay.

Revision ID: c9k3g5h6i7j
Revises: b8j2f4g5h6i
Create Date: 2026-07-10

Adds the `agents_v2` table. Each row represents one agent scoped to
(org) or (org, category) or (org, category, team). Team scope wins at
route time; org-only is the fallback.

Column model:
  - Manifest defaults live in code (folder's manifest.py).
  - DB row's override columns (allowed_skills, allowed_tools, model, ...)
    win over the manifest when non-empty. Empty = "use manifest default".

Partial unique indexes enforce "one active agent per scope":
  - one org-only agent per org
  - one org+category agent per (org, category)
  - one org+category+team agent per (org, category, team)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c9k3g5h6i7j"
down_revision = "b8j2f4g5h6i"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents_v2",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.BigInteger,
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "team_id",
            sa.BigInteger,
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "parent_id",
            sa.BigInteger,
            sa.ForeignKey("agents_v2.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        # Override columns — empty = "use manifest defaults", non-empty = win.
        sa.Column(
            "allowed_skills",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "allowed_tools",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "system_prompt_key",
            sa.Text,
            nullable=False,
            server_default="master.md",
        ),
        sa.Column("model", sa.Text, nullable=False, server_default="gpt-4o-mini"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="4000"),
        sa.Column(
            "harness_enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('active','archived')",
            name="agents_v2_status_check",
        ),
    )

    # Partial unique indexes — one active agent per scope.
    # (org-only) — category_id IS NULL AND team_id IS NULL
    op.execute(
        "CREATE UNIQUE INDEX agents_v2_org_only_uq "
        "ON agents_v2 (organization_id) "
        "WHERE category_id IS NULL AND team_id IS NULL AND status='active'"
    )
    # (org + category, no team)
    op.execute(
        "CREATE UNIQUE INDEX agents_v2_org_cat_uq "
        "ON agents_v2 (organization_id, category_id) "
        "WHERE team_id IS NULL AND category_id IS NOT NULL AND status='active'"
    )
    # (org + category + team)
    op.execute(
        "CREATE UNIQUE INDEX agents_v2_org_cat_team_uq "
        "ON agents_v2 (organization_id, category_id, team_id) "
        "WHERE team_id IS NOT NULL AND status='active'"
    )
    # Slug lookup index — bootstrap uses this on every app start
    op.create_index("agents_v2_slug_idx", "agents_v2", ["slug"])


def downgrade() -> None:
    op.drop_index("agents_v2_slug_idx", table_name="agents_v2")
    op.execute("DROP INDEX IF EXISTS agents_v2_org_cat_team_uq")
    op.execute("DROP INDEX IF EXISTS agents_v2_org_cat_uq")
    op.execute("DROP INDEX IF EXISTS agents_v2_org_only_uq")
    op.drop_table("agents_v2")
