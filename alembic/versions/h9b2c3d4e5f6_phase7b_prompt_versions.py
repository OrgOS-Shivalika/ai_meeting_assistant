"""Phase 7B: Agent Control Dashboard — immutable prompt versions + deployment audit.

Two new tables; one new FK on `agent_prompt_configs`.

  1. **`prompt_versions`** — the immutable snapshot. Carries the 8
     modular prompt sections, retrieval/model/tool configs, declared
     variable schema, and lifecycle state. Once `state='published'` the
     body columns become immutable — enforced at the service layer AND
     by a Postgres trigger that raises on any UPDATE of those columns
     when the row is not in state 'draft'. (Belt + suspenders: the
     trigger catches bugs that bypass the service path.)

  2. **`prompt_deployments`** — append-only deployment audit. BIGSERIAL
     PK, no FK on `agent_prompt_config_id` so audit history survives
     even after a config is archived/cascaded out. Same shape as Phase
     6B access events.

  3. **FK on `agent_prompt_configs.active_version_id`** — the column
     was added in 7A; the FK is added here once `prompt_versions`
     exists. `ondelete='SET NULL'` so archiving a version doesn't
     break the binding row.

Version numbering: app-managed (no DB sequence). The service layer
acquires `pg_advisory_xact_lock(hash(agent_prompt_config_id))` before
inserting a new draft, reads `MAX(version_number) + 1`, and inserts.
Serialized per-config; concurrent draft creates on different configs
proceed in parallel.

State invariants:
  - draft     → editable; body columns mutable
  - published → frozen; body immutable (trigger-enforced)
  - archived  → frozen; cannot become active again (publish refuses)

The CHECK `(state='published') = (published_at IS NOT NULL)` keeps the
two attributes consistent.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "h9b2c3d4e5f6"
down_revision = "g8a1b2c3d4e5"
branch_labels = None
depends_on = None


_VERSION_STATE_CHECK = "state IN ('draft','published','archived')"
_VERSION_PUBLISHED_CONSISTENCY = (
    "(state = 'published' AND published_at IS NOT NULL) "
    "OR (state <> 'published' AND published_at IS NULL)"
)

_DEPLOYMENT_ACTION_CHECK = (
    "action IN ('publish','rollback','unpublish','eval_gate_failed')"
)


# Immutability trigger function. Fires BEFORE UPDATE on the body columns;
# raises if state is not 'draft'. Lets state transitions through (draft
# → published, published → archived) by allowing UPDATEs that don't
# touch the body columns. Whitelist-by-NEW/OLD compare is the simplest
# correct shape — no need to inspect the column list at runtime.
_IMMUTABILITY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION fn_prompt_versions_block_body_update()
RETURNS trigger AS $$
BEGIN
  IF NEW.state IS DISTINCT FROM OLD.state THEN
    -- State transition is allowed regardless of frozen state, but the
    -- body must not change in the same UPDATE. The check below covers
    -- that case too.
    NULL;
  END IF;

  IF OLD.state IN ('published', 'archived') THEN
    IF NEW.modular_prompt_json     IS DISTINCT FROM OLD.modular_prompt_json
    OR NEW.retrieval_config_json   IS DISTINCT FROM OLD.retrieval_config_json
    OR NEW.model_config_json       IS DISTINCT FROM OLD.model_config_json
    OR NEW.tool_permissions_json   IS DISTINCT FROM OLD.tool_permissions_json
    OR NEW.variables_schema_json   IS DISTINCT FROM OLD.variables_schema_json
    OR NEW.label                   IS DISTINCT FROM OLD.label
    OR NEW.meta_json               IS DISTINCT FROM OLD.meta_json
    THEN
      RAISE EXCEPTION
        'prompt_versions row % is in state % — body columns are immutable',
        OLD.id, OLD.state
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_prompt_versions_block_body_update
BEFORE UPDATE ON prompt_versions
FOR EACH ROW
EXECUTE FUNCTION fn_prompt_versions_block_body_update();
"""


def upgrade() -> None:
    # ----- prompt_versions -----
    op.create_table(
        "prompt_versions",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_prompt_config_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_prompt_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # App-managed monotonic counter. Service grabs an advisory lock
        # on agent_prompt_config_id and reads MAX(version_number) + 1.
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        # The 8 modular sections + the four config bundles. All JSONB
        # for free-text editing without a migration on every section
        # tweak. Defaults keep brand-new drafts valid.
        sa.Column(
            "modular_prompt_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "variables_schema_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "retrieval_config_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_config_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tool_permissions_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("""'{"allowed":[],"denied":[]}'::jsonb"""),
        ),
        sa.Column(
            "meta_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "state", sa.String(length=16),
            nullable=False, server_default="draft",
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Eval-gate fields, populated by 7H when eval runs against a
        # version. Stay NULL until then.
        sa.Column("eval_score", sa.Float(), nullable=True),
        sa.Column("eval_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        # 7D guard: distinguishes "the seed migration wrote this row"
        # from "a human authored it". Used by `seed_defaults.py` for
        # idempotency.
        sa.Column(
            "seeded_from_filesystem", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        "ck_prompt_versions_state", "prompt_versions", _VERSION_STATE_CHECK,
    )
    op.create_check_constraint(
        "ck_prompt_versions_published_consistency",
        "prompt_versions", _VERSION_PUBLISHED_CONSISTENCY,
    )
    op.create_unique_constraint(
        "uq_prompt_versions_config_version_number",
        "prompt_versions",
        ["agent_prompt_config_id", "version_number"],
    )
    # Drives "give me the active published version" + "give me the
    # version history" both off a single index.
    op.create_index(
        "ix_prompt_versions_config_state_version",
        "prompt_versions",
        ["agent_prompt_config_id", "state",
         sa.text("version_number DESC")],
    )

    # Immutability trigger.
    op.execute(_IMMUTABILITY_TRIGGER_SQL)

    # ----- FK on agent_prompt_configs.active_version_id -----
    # The column was added in 7A as a bare UUID. Add the FK now that
    # prompt_versions exists. SET NULL on delete so archiving a version
    # row (rare — archives are state changes, not row deletions, but
    # the FK semantics still matter) can't orphan the binding.
    op.create_foreign_key(
        "agent_prompt_configs_active_version_id_fkey",
        "agent_prompt_configs", "prompt_versions",
        ["active_version_id"], ["id"],
        ondelete="SET NULL",
    )

    # ----- prompt_deployments -----
    op.create_table(
        "prompt_deployments",
        sa.Column(
            "id", sa.BigInteger(), primary_key=True, autoincrement=True,
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NO FK on agent_prompt_config_id — audit history survives a
        # cascade. Same rationale as rag_chunk_access_events from 6B.
        sa.Column(
            "agent_prompt_config_id", postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=24), nullable=False),
        # SET NULL on prompt_versions delete — audit rows outlive
        # individual versions.
        sa.Column(
            "from_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_version_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_check_constraint(
        "ck_prompt_deployments_action",
        "prompt_deployments", _DEPLOYMENT_ACTION_CHECK,
    )
    op.create_index(
        "ix_prompt_deployments_org_config_created",
        "prompt_deployments",
        ["organization_id", "agent_prompt_config_id",
         sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_prompt_deployments_org_action_created",
        "prompt_deployments",
        ["organization_id", "action", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_prompt_deployments_org_action_created",
        table_name="prompt_deployments",
    )
    op.drop_index(
        "ix_prompt_deployments_org_config_created",
        table_name="prompt_deployments",
    )
    op.drop_constraint(
        "ck_prompt_deployments_action", "prompt_deployments", type_="check",
    )
    op.drop_table("prompt_deployments")

    op.drop_constraint(
        "agent_prompt_configs_active_version_id_fkey",
        "agent_prompt_configs", type_="foreignkey",
    )

    op.execute("DROP TRIGGER IF EXISTS trg_prompt_versions_block_body_update ON prompt_versions")
    op.execute("DROP FUNCTION IF EXISTS fn_prompt_versions_block_body_update()")

    op.drop_index(
        "ix_prompt_versions_config_state_version",
        table_name="prompt_versions",
    )
    op.drop_constraint(
        "uq_prompt_versions_config_version_number",
        "prompt_versions", type_="unique",
    )
    op.drop_constraint(
        "ck_prompt_versions_published_consistency",
        "prompt_versions", type_="check",
    )
    op.drop_constraint(
        "ck_prompt_versions_state", "prompt_versions", type_="check",
    )
    op.drop_table("prompt_versions")
