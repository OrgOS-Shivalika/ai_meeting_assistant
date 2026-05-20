"""Phase 8A (revised): template_behavior_profiles — the canonical AI cognition object.

This replaces the old `template_agent_definitions`,
`template_category_definitions`, `template_team_definitions` triad
with ONE table indexed by `scope_kind`. Each row carries the full
11-dimension BehaviorProfile.

scope_kind values:
  - 'global'   — platform-wide default. Exactly one row enforced via
                 partial unique index. Establishes the floor for every
                 dimension; everything else overlays on top.
  - 'category' — a category-level profile (e.g. 'engineering',
                 'sales'). Installed by a workspace to set defaults
                 for that category. Multiple slugs.
  - 'team'     — a team-level profile (e.g. 'devops', 'sdr').
                 Overlays on top of the category. Multiple slugs.

The 11 dimensions are stored as named JSONB columns rather than
one giant blob. Reasons:
  - GIN indexable per dimension if hot paths emerge
  - clearer schema + easier review
  - per-column NULL semantics (NULL = inherit from below) without
    confusing dict-vs-null heuristics

Why not Enums? Postgres ENUM types are awkward to migrate. A short
String + CHECK is sufficient.

This migration only CREATES the new table. The old three definition
tables stay alive until Phase 8F cleanup, so endpoints continue to
work while we transition.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "q8e5f6a7b8c9"
down_revision = "p7d4e5f6a7b8"
branch_labels = None
depends_on = None


_SCOPE_KIND_CHECK = "scope_kind IN ('global','category','team')"

_STATE_CHECK = "state IN ('draft','published','deprecated')"

_VERSION_FMT_CHECK = "version ~ '^\\d+\\.\\d+\\.\\d+$'"


def upgrade() -> None:
    op.create_table(
        "template_behavior_profiles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "state", sa.String(16), nullable=False,
            server_default="published",
        ),

        # ---- The 11 BehaviorProfile dimensions ----
        # All JSONB, all default empty dict. NULL is reserved for
        # "explicitly inherit" semantics (resolver: if NULL, do not
        # contribute to merge; let lower layer's value pass through).
        # Default '{}'::jsonb so a freshly-inserted profile doesn't
        # carry NULLs everywhere.
        sa.Column(
            "master_prompt", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "enabled_agents", postgresql.JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "retrieval_config", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "memory_config", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "output_config", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "extraction_rules", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "automation_rules", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evaluation_rules", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tone_and_personality", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "compliance_and_guardrails", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tools_and_integrations", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),

        # Manifest hash — covers all 11 dimension JSONs in canonical
        # serialization. Drift detector + seed-script idempotency
        # use this to decide whether the DB row matches the catalog.
        sa.Column("manifest_hash", sa.String(64), nullable=False),

        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),

        sa.CheckConstraint(_SCOPE_KIND_CHECK, name="bp_scope_kind_chk"),
        sa.CheckConstraint(_STATE_CHECK, name="bp_state_chk"),
        sa.CheckConstraint(_VERSION_FMT_CHECK, name="bp_version_fmt_chk"),
    )

    # (slug, version) is unique within each scope_kind. Two scope_kinds
    # can share a slug — but we prefer they don't. Enforce per-scope
    # uniqueness via a 3-column unique index that includes scope_kind.
    op.create_index(
        "ux_bp_scope_slug_version",
        "template_behavior_profiles",
        ["scope_kind", "slug", "version"],
        unique=True,
    )

    # Exactly one global profile at a time. Two-level enforcement:
    # the resolver picks the latest published, but we also guard via
    # a partial unique index on slug to keep things sane. The default
    # convention: scope_kind='global' rows all have slug='__default__'.
    # That single slug can have multiple versions, but only one
    # PUBLISHED row at a time.
    op.create_index(
        "ux_bp_global_published",
        "template_behavior_profiles",
        ["scope_kind", "slug"],
        unique=True,
        postgresql_where=sa.text(
            "scope_kind = 'global' AND state = 'published'"
        ),
    )

    # Hot read path: "latest published profile for (scope_kind, slug)".
    op.create_index(
        "ix_bp_lookup",
        "template_behavior_profiles",
        ["scope_kind", "slug", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_bp_lookup", "template_behavior_profiles")
    op.drop_index("ux_bp_global_published", "template_behavior_profiles")
    op.drop_index("ux_bp_scope_slug_version", "template_behavior_profiles")
    op.drop_table("template_behavior_profiles")
