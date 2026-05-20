"""Phase 8A: Prebuilt Enterprise Template System — global registry.

Five new tables, all platform-owned (no `organization_id`). Read-only
from the application's perspective once seeded — only platform-staff
admins INSERT/UPDATE.

Architectural notes:

  1. **`template_bundles`** — the unit a workspace installs. Carries
     a semver `version`. The 8A migration seeds a baseline; future
     bundles ship as INSERTs without a schema change.

  2. **`template_*_definitions`** — reusable team/category/agent
     recipes. Each definition is versioned independently. Bundles
     reference a definition by `(slug, version)`; null version = latest.

  3. **`template_bundle_items`** — join table. Item types are the
     three definition kinds.

  4. **Marketplace-ready, marketplace-deferred** — `signature` +
     `manifest_hash` reserved on `template_bundles`. Signing infra
     ships in a future slice.

  5. Versioning is application-managed (no DB sequence). A new
     version is a new row with the same slug + bumped version string.

This migration creates only the tables. The seed (9 teams + 11
categories + 9 agents + N bundles) runs via the separate
`app/scripts/seed_global_templates.py` CLI which can be re-run
idempotently as the catalog evolves.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "m4a1b2c3d4e5"
down_revision = "l3f6a7b8c9d0"
branch_labels = None
depends_on = None


_BUNDLE_STATE_CHECK = "state IN ('draft','published','deprecated')"
_BUNDLE_VERSION_CHECK = r"version ~ '^\d+\.\d+\.\d+$'"

# Mirrors Phase 7A's agent_type enum exactly.
_AGENT_TYPE_CHECK = (
    "agent_type IN ("
    "'rag_synth','rag_planner','graph_extractor','transcript_analyzer',"
    "'importance_scorer','summarizer','live_copilot'"
    ")"
)

_BUNDLE_ITEM_TYPE_CHECK = "item_type IN ('team','category','agent')"


def upgrade() -> None:
    # ----- template_bundles -----
    op.create_table(
        "template_bundles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Curated grouping for the UI's category filter. Open enum;
        # the API validates against a known list at write time.
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column(
            "state", sa.String(length=16),
            nullable=False, server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_by", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        # Reserved for the future marketplace — see §18 of the plan.
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=True),
        # Auto-provisioned on new-org signup when state='published' AND
        # this flag is true. Multiple bundles may carry it; the
        # signup hook honors a single env-var-selected bundle by
        # default.
        sa.Column(
            "is_recommended_on_signup", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_template_bundles_slug_version",
        "template_bundles", ["slug", "version"],
    )
    op.create_check_constraint(
        "ck_template_bundles_state", "template_bundles", _BUNDLE_STATE_CHECK,
    )
    op.create_check_constraint(
        "ck_template_bundles_version_semver",
        "template_bundles", _BUNDLE_VERSION_CHECK,
    )
    op.create_index(
        "ix_template_bundles_published_recommended",
        "template_bundles", ["is_recommended_on_signup"],
        postgresql_where=sa.text("state = 'published'"),
    )
    op.create_index(
        "ix_template_bundles_category_state",
        "template_bundles", ["category", "state"],
    )

    # ----- template_team_definitions -----
    op.create_table(
        "template_team_definitions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "suggested_category_slugs",
            postgresql.ARRAY(sa.String()),
            nullable=False, server_default="{}",
        ),
        sa.Column(
            "meta_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.String(length=32),
            nullable=False, server_default="1.0.0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_template_team_defs_slug_version",
        "template_team_definitions", ["slug", "version"],
    )
    op.create_check_constraint(
        "ck_template_team_defs_version_semver",
        "template_team_definitions", _BUNDLE_VERSION_CHECK,
    )

    # ----- template_category_definitions -----
    op.create_table(
        "template_category_definitions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "default_agent_slugs",
            postgresql.ARRAY(sa.String()),
            nullable=False, server_default="{}",
        ),
        sa.Column("default_color", sa.String(length=24), nullable=True),
        sa.Column("default_icon", sa.String(length=64), nullable=True),
        sa.Column(
            "meta_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.String(length=32),
            nullable=False, server_default="1.0.0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_template_category_defs_slug_version",
        "template_category_definitions", ["slug", "version"],
    )
    op.create_check_constraint(
        "ck_template_category_defs_version_semver",
        "template_category_definitions", _BUNDLE_VERSION_CHECK,
    )

    # ----- template_agent_definitions -----
    op.create_table(
        "template_agent_definitions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column(
            "default_modular_prompt_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "default_variables_schema_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "default_retrieval_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "default_model_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "default_tool_permissions_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'{"allowed":[],"denied":[]}'::jsonb"""),
        ),
        sa.Column(
            "eval_gate_required", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column("eval_min_score", sa.Float(), nullable=True),
        sa.Column(
            "meta_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "version", sa.String(length=32),
            nullable=False, server_default="1.0.0",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_template_agent_defs_slug_version",
        "template_agent_definitions", ["slug", "version"],
    )
    op.create_check_constraint(
        "ck_template_agent_defs_agent_type",
        "template_agent_definitions", _AGENT_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_template_agent_defs_version_semver",
        "template_agent_definitions", _BUNDLE_VERSION_CHECK,
    )

    # ----- template_bundle_items -----
    op.create_table(
        "template_bundle_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "bundle_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_bundles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("item_slug", sa.String(length=64), nullable=False),
        # Null = "latest" of that definition slug. Pinning to a
        # specific version makes the bundle deterministic across
        # platform updates.
        sa.Column("item_version", sa.String(length=32), nullable=True),
        sa.Column(
            "provisioning_hints_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ordering", sa.Integer(),
            nullable=False, server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_template_bundle_items_type",
        "template_bundle_items", _BUNDLE_ITEM_TYPE_CHECK,
    )
    op.create_unique_constraint(
        "uq_template_bundle_items_bundle_type_slug",
        "template_bundle_items",
        ["bundle_id", "item_type", "item_slug"],
    )
    op.create_index(
        "ix_template_bundle_items_bundle_ordering",
        "template_bundle_items", ["bundle_id", "ordering"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_template_bundle_items_bundle_ordering",
        table_name="template_bundle_items",
    )
    op.drop_constraint(
        "uq_template_bundle_items_bundle_type_slug",
        "template_bundle_items", type_="unique",
    )
    op.drop_constraint(
        "ck_template_bundle_items_type",
        "template_bundle_items", type_="check",
    )
    op.drop_table("template_bundle_items")

    op.drop_constraint(
        "ck_template_agent_defs_version_semver",
        "template_agent_definitions", type_="check",
    )
    op.drop_constraint(
        "ck_template_agent_defs_agent_type",
        "template_agent_definitions", type_="check",
    )
    op.drop_constraint(
        "uq_template_agent_defs_slug_version",
        "template_agent_definitions", type_="unique",
    )
    op.drop_table("template_agent_definitions")

    op.drop_constraint(
        "ck_template_category_defs_version_semver",
        "template_category_definitions", type_="check",
    )
    op.drop_constraint(
        "uq_template_category_defs_slug_version",
        "template_category_definitions", type_="unique",
    )
    op.drop_table("template_category_definitions")

    op.drop_constraint(
        "ck_template_team_defs_version_semver",
        "template_team_definitions", type_="check",
    )
    op.drop_constraint(
        "uq_template_team_defs_slug_version",
        "template_team_definitions", type_="unique",
    )
    op.drop_table("template_team_definitions")

    op.drop_index(
        "ix_template_bundles_category_state", table_name="template_bundles",
    )
    op.drop_index(
        "ix_template_bundles_published_recommended",
        table_name="template_bundles",
    )
    op.drop_constraint(
        "ck_template_bundles_version_semver",
        "template_bundles", type_="check",
    )
    op.drop_constraint(
        "ck_template_bundles_state", "template_bundles", type_="check",
    )
    op.drop_constraint(
        "uq_template_bundles_slug_version",
        "template_bundles", type_="unique",
    )
    op.drop_table("template_bundles")
