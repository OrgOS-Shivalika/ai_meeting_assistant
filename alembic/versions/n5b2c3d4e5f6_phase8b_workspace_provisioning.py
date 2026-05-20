"""Phase 8B: workspace provisioning — links + jobs.

Two new tables. Both per-org (CASCADE from organizations).

  1. **`workspace_template_links`** — one row per provisioned
     workspace entity (Category, AgentProfile, etc.). Carries the
     source template's kind + slug + version, the provisioning job
     that created it, and the lineage state (8C populates this).

     Heterogeneous entity ids: agent_profile / prompt_config /
     prompt_version use UUID PKs; category uses Integer PKs. Stored
     as two nullable columns with a CHECK that exactly one is set.

  2. **`template_provisioning_jobs`** — append-only audit. One row
     per provisioning invocation. Records the bundle, item counts,
     status, and failure details.

The link table's per-entity UNIQUE index prevents double-provisioning
the same workspace row. The (org, kind, slug) lookup index drives
idempotency checks during provisioning.

No changes to existing tables. Lineage is entirely additive.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "n5b2c3d4e5f6"
down_revision = "m4a1b2c3d4e5"
branch_labels = None
depends_on = None


_LINK_ENTITY_TYPE_CHECK = (
    "entity_type IN ("
    "'category','agent_profile','prompt_config','prompt_version'"
    ")"
)

_LINK_SOURCE_KIND_CHECK = (
    "source_template_kind IN ('team','category','agent')"
)

_LINK_LINEAGE_STATE_CHECK = (
    "lineage_state IN ('pristine','modified','heavily_modified','forked')"
)

# Exactly one of entity_id_uuid / entity_id_int must be set.
_LINK_ENTITY_ID_CHECK = (
    "(entity_id_uuid IS NOT NULL AND entity_id_int IS NULL) "
    "OR (entity_id_uuid IS NULL AND entity_id_int IS NOT NULL)"
)

_JOB_STATUS_CHECK = (
    "status IN ('pending','in_progress','completed','partial','failed')"
)
_JOB_MODE_CHECK = "mode IN ('bundle','item_list','auto_signup')"
_JOB_TRIGGER_CHECK = (
    "triggered_by IN ('auto_signup','manual','admin_api','celery')"
)


def upgrade() -> None:
    # ----- template_provisioning_jobs -----
    op.create_table(
        "template_provisioning_jobs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL on bundle delete — historical jobs survive bundle
        # cleanup. Bundle slug/version are denormalized on the job row
        # below so the audit is still readable.
        sa.Column(
            "bundle_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_bundles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("bundle_slug", sa.String(length=64), nullable=True),
        sa.Column("bundle_version", sa.String(length=32), nullable=True),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column(
            "requested_items_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "items_created", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "items_skipped", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "items_failed", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "failure_details_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(length=24), nullable=False),
        sa.Column(
            "triggered_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "completed_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_template_provisioning_jobs_status",
        "template_provisioning_jobs", _JOB_STATUS_CHECK,
    )
    op.create_check_constraint(
        "ck_template_provisioning_jobs_mode",
        "template_provisioning_jobs", _JOB_MODE_CHECK,
    )
    op.create_check_constraint(
        "ck_template_provisioning_jobs_trigger",
        "template_provisioning_jobs", _JOB_TRIGGER_CHECK,
    )
    op.create_index(
        "ix_template_provisioning_jobs_org_created",
        "template_provisioning_jobs",
        ["organization_id", sa.text("created_at DESC")],
    )

    # ----- workspace_template_links -----
    op.create_table(
        "workspace_template_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        # Heterogeneous PKs — UUID for Phase 7 entities, Integer for
        # Category. Exactly one is set; CHECK enforces it.
        sa.Column(
            "entity_id_uuid", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("entity_id_int", sa.BigInteger(), nullable=True),
        sa.Column(
            "source_template_kind", sa.String(length=16), nullable=False,
        ),
        sa.Column(
            "source_template_slug", sa.String(length=64), nullable=False,
        ),
        sa.Column(
            "source_template_version", sa.String(length=32), nullable=False,
        ),
        sa.Column(
            "source_bundle_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("template_bundles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_bundle_version", sa.String(length=32), nullable=True,
        ),
        sa.Column(
            "provisioning_job_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "template_provisioning_jobs.id", ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "provisioned_at", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "lineage_state", sa.String(length=24),
            nullable=False, server_default="pristine",
        ),
        sa.Column(
            "diff_summary_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "last_diverged_at", sa.DateTime(timezone=True), nullable=True,
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
    op.create_check_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links", _LINK_ENTITY_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_workspace_template_links_source_kind",
        "workspace_template_links", _LINK_SOURCE_KIND_CHECK,
    )
    op.create_check_constraint(
        "ck_workspace_template_links_lineage_state",
        "workspace_template_links", _LINK_LINEAGE_STATE_CHECK,
    )
    op.create_check_constraint(
        "ck_workspace_template_links_entity_id_exclusive",
        "workspace_template_links", _LINK_ENTITY_ID_CHECK,
    )
    # One link row per workspace entity. Uses COALESCE to dedupe
    # across the two-column entity_id representation.
    op.execute("""
        CREATE UNIQUE INDEX uq_workspace_template_links_entity
        ON workspace_template_links (
            entity_type,
            COALESCE(entity_id_uuid::text, ''),
            COALESCE(entity_id_int::text, '')
        )
    """)
    op.create_index(
        "ix_workspace_template_links_org_kind_slug",
        "workspace_template_links",
        ["organization_id", "source_template_kind", "source_template_slug"],
    )
    op.create_index(
        "ix_workspace_template_links_org_lineage_state",
        "workspace_template_links",
        ["organization_id", "lineage_state"],
        postgresql_where=sa.text("lineage_state <> 'pristine'"),
    )
    op.create_index(
        "ix_workspace_template_links_bundle",
        "workspace_template_links",
        ["source_bundle_id", "source_template_version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workspace_template_links_bundle",
        table_name="workspace_template_links",
    )
    op.drop_index(
        "ix_workspace_template_links_org_lineage_state",
        table_name="workspace_template_links",
    )
    op.drop_index(
        "ix_workspace_template_links_org_kind_slug",
        table_name="workspace_template_links",
    )
    op.execute("DROP INDEX IF EXISTS uq_workspace_template_links_entity")
    op.drop_constraint(
        "ck_workspace_template_links_entity_id_exclusive",
        "workspace_template_links", type_="check",
    )
    op.drop_constraint(
        "ck_workspace_template_links_lineage_state",
        "workspace_template_links", type_="check",
    )
    op.drop_constraint(
        "ck_workspace_template_links_source_kind",
        "workspace_template_links", type_="check",
    )
    op.drop_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links", type_="check",
    )
    op.drop_table("workspace_template_links")

    op.drop_index(
        "ix_template_provisioning_jobs_org_created",
        table_name="template_provisioning_jobs",
    )
    op.drop_constraint(
        "ck_template_provisioning_jobs_trigger",
        "template_provisioning_jobs", type_="check",
    )
    op.drop_constraint(
        "ck_template_provisioning_jobs_mode",
        "template_provisioning_jobs", type_="check",
    )
    op.drop_constraint(
        "ck_template_provisioning_jobs_status",
        "template_provisioning_jobs", type_="check",
    )
    op.drop_table("template_provisioning_jobs")
