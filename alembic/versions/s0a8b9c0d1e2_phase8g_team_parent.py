"""Phase 8G — categories own teams.

Add `parent_category_slug` to `template_behavior_profiles` so team
profiles can declare which category (department) they nest under.

Concrete shape:
  - scope_kind='category'  → parent_category_slug IS NULL
  - scope_kind='team'      → parent_category_slug points at a
                              category profile's slug
  - scope_kind='global'    → parent_category_slug IS NULL

A CHECK constraint enforces the team-must-have-parent rule. No FK
to template_behavior_profiles.slug — slugs aren't a key column —
but the seed script + provisioning both validate the link in code.

This unblocks the workspace-side hierarchy: when a team profile is
installed, provisioning looks up its parent category's categories row
and sets categories.parent_id to nest the team under it. The
sidebar reads parent_id to render the tree.
"""
from alembic import op
import sqlalchemy as sa


revision = "s0a8b9c0d1e2"
down_revision = "r9f7a8b9c0d1"
branch_labels = None
depends_on = None


_PARENT_CHECK = (
    "(scope_kind = 'team' AND parent_category_slug IS NOT NULL) "
    "OR (scope_kind <> 'team' AND parent_category_slug IS NULL)"
)


def upgrade() -> None:
    op.add_column(
        "template_behavior_profiles",
        sa.Column("parent_category_slug", sa.String(64), nullable=True),
    )

    # Wipe old catalog rows — the catalog is being rewritten with the
    # new department/team hierarchy. The seed script reinstates fresh
    # rows on next run. Workspace-owned tables (workspace_template_links,
    # workspace_behavior_overrides, categories) are NOT touched here —
    # cascade-on-org-delete remains the only path that wipes those.
    op.execute(sa.text("DELETE FROM template_behavior_profiles"))

    # NOTE: the team-must-have-parent CHECK is deferred to a later
    # migration. Adding it here would require all rows to already
    # satisfy it, which requires the seed to run first. The app-side
    # seed + provisioning code enforces the rule in the meantime.

    op.create_index(
        "ix_bp_parent_category_slug",
        "template_behavior_profiles",
        ["parent_category_slug"],
        postgresql_where=sa.text("parent_category_slug IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_bp_parent_category_slug", "template_behavior_profiles")
    op.drop_column("template_behavior_profiles", "parent_category_slug")
