"""Phase 7A: Agent Control Dashboard — profiles + scoped bindings + epoch counter.

Three new tables; no changes to existing tables in this slice.

Architectural notes:

  1. **`agent_profiles`** — reusable agent identities (e.g. `sales_copilot`,
     `sprint_assistant`). Owned by an organization. `agent_type` is the bridge
     to the existing services (`rag_synth`, `rag_planner`, `graph_extractor`,
     `transcript_analyzer`, `importance_scorer`, `summarizer`, plus
     `live_copilot` reserved for Phase 8). Sticky-active uniqueness on
     `(organization_id, slug)` lets admins archive a profile and re-create one
     with the same slug — same pattern Phase 6D uses for chunk archival.

  2. **`agent_prompt_configs`** — the binding table. One row per
     (agent_profile, scope) tuple. `scope_type` is one of
     `organization` | `category` | `team` | `meeting_specific`; the
     `meeting_specific` value is RESERVED for Phase 8 — the CHECK is
     relaxed now so the column space is reserved and we avoid a schema
     migration in Phase 8.

     The `active_version_id` column is added in Phase 7B once
     `prompt_versions` exists. It stays NULL throughout 7A.

  3. **`agent_config_epochs`** — tiny shared counter table. One row per
     (organization, agent_profile). Monotonic counter bumped on every
     publish/rollback. Resolver caches read this on every cache hit; an
     epoch change invalidates that cached entry across all workers.
     Composite PK keeps the lookup to a single index seek.

Tenancy:
  - All three tables are CASCADE-from-organizations.
  - The platform-owner org acts as the global-default tier (resolver Layer 5);
    no special schema for it — just a sentinel organization_id at app level.

Reversibility: all three tables are new — downgrade is a clean DROP.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "g8a1b2c3d4e5"
down_revision = "b6e2d4a8c517"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Enum-ish CHECK clauses. Kept as strings (matches Phase 6 conventions —
# we don't use Postgres ENUM types because they're a pain to migrate).
# ---------------------------------------------------------------------------

_AGENT_TYPE_CHECK = (
    "agent_type IN ("
    "'rag_synth','rag_planner','graph_extractor','transcript_analyzer',"
    "'importance_scorer','summarizer','live_copilot'"
    ")"
)

_AGENT_STATUS_CHECK = "status IN ('active','archived')"

# Phase 8 will allow 'meeting_specific' — we already permit it now so the
# CHECK doesn't have to migrate.
_SCOPE_TYPE_CHECK = (
    "scope_type IN ('organization','category','team','meeting_specific')"
)

# Scope id consistency:
#   - 'organization' / 'meeting_specific' → scope_id NULL (meeting uses
#     scope_uuid in Phase 8; that column doesn't exist yet, but the CHECK
#     here keeps scope_id NULL for both cases so the Phase 8 migration is
#     additive).
#   - 'category' / 'team' → scope_id NOT NULL (integer FK, but soft —
#     CASCADE handled at the org level only; deleting a Category/Team
#     doesn't auto-wipe its configs, lets admins recover from accidental
#     scope deletions).
_SCOPE_ID_CHECK = (
    "(scope_type IN ('organization','meeting_specific') AND scope_id IS NULL) "
    "OR (scope_type IN ('category','team') AND scope_id IS NOT NULL)"
)


def upgrade() -> None:
    # ----- agent_profiles -----
    op.create_table(
        "agent_profiles",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_type", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=16),
            nullable=False, server_default="active",
        ),
        # Optional starter template surfaced in the editor on profile
        # creation. 8 modular sections; empty {} until 7B writes a draft.
        sa.Column(
            "default_modular_prompt_json", postgresql.JSONB(astext_type=sa.Text()),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        # Phase 7H — eval-gated publish. Stays false until 7H ships;
        # the columns exist so 7B's publish flow doesn't need a schema
        # migration to know whether to run the gate.
        sa.Column(
            "eval_gate_required", sa.Boolean(),
            nullable=False, server_default=sa.text("false"),
        ),
        sa.Column(
            "eval_fixture_set_id", postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("eval_min_score", sa.Float(), nullable=True),
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
        "ck_agent_profiles_agent_type", "agent_profiles", _AGENT_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_profiles_status", "agent_profiles", _AGENT_STATUS_CHECK,
    )
    # Soft-active unique on slug — admin can archive `sales_copilot` and
    # spin up a fresh one with the same slug. Same pattern as 6D's
    # archive_status partial indexes.
    op.execute("""
        CREATE UNIQUE INDEX uq_agent_profiles_org_slug_active
        ON agent_profiles (organization_id, slug)
        WHERE status = 'active'
    """)
    op.create_index(
        "ix_agent_profiles_org_type_status", "agent_profiles",
        ["organization_id", "agent_type", "status"],
    )

    # ----- agent_prompt_configs -----
    op.create_table(
        "agent_prompt_configs",
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
            "agent_profile_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        # Integer for Category/Team (their PKs are Integer). For Phase 8's
        # meeting_specific we add a sibling scope_uuid column in that
        # migration; meetings have Integer PKs today but Phase 8 may move
        # to UUID — defer the decision.
        sa.Column("scope_id", sa.BigInteger(), nullable=True),
        # Active version pointer. NULL until 7B writes the first published
        # version. Adding the FK is deferred to 7B; we add the column now
        # with no FK so 7A is self-contained.
        sa.Column(
            "active_version_id", postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(length=16),
            nullable=False, server_default="active",
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
        "ck_agent_prompt_configs_scope_type",
        "agent_prompt_configs", _SCOPE_TYPE_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_prompt_configs_scope_id",
        "agent_prompt_configs", _SCOPE_ID_CHECK,
    )
    op.create_check_constraint(
        "ck_agent_prompt_configs_status",
        "agent_prompt_configs", _AGENT_STATUS_CHECK,
    )
    # Soft-active uniqueness: one active binding per (org, profile, scope)
    # tuple. Archived configs do NOT block creating a new one with the
    # same scope — same archive-then-re-create flow as agent_profiles.
    # COALESCE handles the NULL scope_id case (organization-scoped configs)
    # without two separate indexes.
    op.execute("""
        CREATE UNIQUE INDEX uq_agent_prompt_configs_org_profile_scope_active
        ON agent_prompt_configs (
            organization_id,
            agent_profile_id,
            scope_type,
            COALESCE(scope_id, -1)
        )
        WHERE status = 'active'
    """)
    # Drives the resolver query (§6.6 of the plan).
    op.create_index(
        "ix_agent_prompt_configs_resolution",
        "agent_prompt_configs",
        ["organization_id", "agent_profile_id", "scope_type", "scope_id"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ----- agent_config_epochs -----
    # Composite PK = no surrogate; epoch is bumped under advisory lock.
    op.create_table(
        "agent_config_epochs",
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_profile_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "epoch", sa.BigInteger(),
            nullable=False, server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "agent_profile_id",
            name="pk_agent_config_epochs",
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_config_epochs")
    op.drop_index(
        "ix_agent_prompt_configs_resolution",
        table_name="agent_prompt_configs",
    )
    op.execute("DROP INDEX IF EXISTS uq_agent_prompt_configs_org_profile_scope_active")
    op.drop_constraint(
        "ck_agent_prompt_configs_status", "agent_prompt_configs", type_="check",
    )
    op.drop_constraint(
        "ck_agent_prompt_configs_scope_id", "agent_prompt_configs", type_="check",
    )
    op.drop_constraint(
        "ck_agent_prompt_configs_scope_type", "agent_prompt_configs", type_="check",
    )
    op.drop_table("agent_prompt_configs")

    op.drop_index(
        "ix_agent_profiles_org_type_status", table_name="agent_profiles",
    )
    op.execute("DROP INDEX IF EXISTS uq_agent_profiles_org_slug_active")
    op.drop_constraint(
        "ck_agent_profiles_status", "agent_profiles", type_="check",
    )
    op.drop_constraint(
        "ck_agent_profiles_agent_type", "agent_profiles", type_="check",
    )
    op.drop_table("agent_profiles")
