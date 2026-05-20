"""Phase 8F cleanup — drop obsolete template tables.

Drops four tables superseded by the behavior-profile architecture:

  - template_agent_definitions      — replaced by template_behavior_profiles
                                       (scope_kind='category', enabled_agents
                                       carries which agent runners fire)
  - template_category_definitions   — replaced by template_behavior_profiles
                                       (scope_kind='category')
  - template_team_definitions       — replaced by template_behavior_profiles
                                       (scope_kind='team')
  - template_upgrade_proposals      — 3-way-diff upgrade flow removed;
                                       the new sparse-override model handles
                                       upgrades by re-pinning links without
                                       per-key proposals

template_publish_events stays (append-only audit; still useful when
the catalog ships a new version even if we no longer fan out proposals).
template_provisioning_jobs stays (install audit; reused by new flow).
template_bundles + template_bundle_items stay (bundles are still the
distribution mechanism; obsolete item_type='agent' rows are simply
filtered out by the new install path).

Tables are dropped in dependency order. No data migration — Phase 8F
also wipes the cloned workspace artifacts (prompt_versions etc.)
via a runtime SQL run; this migration is schema-only.
"""
from alembic import op
import sqlalchemy as sa


revision = "r9f7a8b9c0d1"
down_revision = "q8e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop in reverse FK dependency order. None of these are referenced
    # by the surviving tables, so any order works in practice; this is
    # the documented order.
    op.drop_table("template_upgrade_proposals")
    op.drop_table("template_agent_definitions")
    op.drop_table("template_category_definitions")
    op.drop_table("template_team_definitions")


def downgrade() -> None:
    # Recovery rebuilds the dropped tables from earlier migrations.
    # We do NOT replicate them here — restoring requires re-running
    # the 8A initial migration. This is a one-way cleanup.
    raise NotImplementedError(
        "Phase 8F cleanup is intentionally one-way. "
        "Restore the schema by reverting to revision m4a1b2c3d4e5 or "
        "earlier, then re-running migrations forward."
    )
