"""Phase 8C: workspace_behavior_overrides — sparse, hierarchical AI behavior.

Replaces the clone-and-diff model with override rows. A workspace
does NOT clone a template's full body. It points at the template via
`workspace_template_links` (8B) and stores only the deltas it wants
to customize as rows in this table.

The runtime resolver (8D) walks:

    global default
      → category template defaults (from catalog)
      → team template defaults     (from catalog)
      → category overrides         (THIS TABLE, scope_type='category')
      → team overrides             (THIS TABLE, scope_type='team')
      → workspace overrides        (THIS TABLE, scope_type='workspace')

and produces a fully-merged BehaviorProfile across all 11 dimensions.

Schema notes:

  - **Sparse**: zero overrides = workspace uses template defaults. We
    expect most workspaces to have <10 overrides per scope; this table
    stays small even at scale.

  - **(scope_type, scope_id, dimension, field) is the natural key.**
    Postgres enforces unique-per-org via partial unique index.

  - **dimension** is one of the 11 BehaviorProfile dimensions
    (master_prompt, enabled_agents, retrieval_config, memory_config,
    output_config, extraction_rules, automation_rules,
    evaluation_rules, tone_and_personality, compliance_and_guardrails,
    tools_and_integrations).

  - **field** is the sub-path within the dimension. For
    master_prompt.system → dimension='master_prompt', field='system'.
    For retrieval_config.top_k_vector → dimension='retrieval_config',
    field='top_k_vector'. For dimensions that are a single scalar
    (e.g. enabled_agents is a list), field can be the empty string ''
    meaning "the whole dimension's value".

  - **value** is JSONB. Handles strings, dicts, lists, scalars
    uniformly. NULL value column not allowed — `delete_override`
    deletes the row rather than nulling.

  - **workspace_template_link_id** is NULLable: workspace-level
    overrides (scope_type='workspace') don't have a link. Category-
    and team-level overrides reference their link.

Append/upsert semantics: `set_override` does INSERT ON CONFLICT
UPDATE keyed on (organization_id, scope_type, scope_id, dimension,
field). Cheap, atomic.

Cascade: delete an org → all its overrides go. Delete a link → only
that link's overrides go (workspace overrides survive).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "p7d4e5f6a7b8"
down_revision = "o6c3d4e5f6a7"
branch_labels = None
depends_on = None


_SCOPE_TYPE_CHECK = "scope_type IN ('workspace','category','team')"

_DIMENSION_CHECK = (
    "dimension IN ("
    "'master_prompt','enabled_agents','retrieval_config',"
    "'memory_config','output_config','extraction_rules',"
    "'automation_rules','evaluation_rules',"
    "'tone_and_personality','compliance_and_guardrails',"
    "'tools_and_integrations'"
    ")"
)

# Heterogeneous scope_id: workspace scope uses no id (NULL); category
# scope uses int (categories.id); team scope uses int (also a category
# row in this codebase — teams are top-level categories). We store
# both shapes as nullable columns + CHECK enforces shape per scope_type.
_SCOPE_ID_SHAPE_CHECK = (
    "(scope_type = 'workspace' "
    "  AND scope_id_uuid IS NULL AND scope_id_int IS NULL) "
    "OR (scope_type IN ('category','team') "
    "    AND scope_id_int IS NOT NULL "
    "    AND scope_id_uuid IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "workspace_behavior_overrides",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Link reference is OPTIONAL — workspace-level overrides have
        # no link. Cascade on delete: removing a link wipes only its
        # scoped overrides.
        sa.Column(
            "workspace_template_link_id", sa.BigInteger,
            sa.ForeignKey(
                "workspace_template_links.id", ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("scope_type", sa.String(16), nullable=False),
        # XOR pair — see _SCOPE_ID_SHAPE_CHECK above.
        sa.Column(
            "scope_id_uuid", postgresql.UUID(as_uuid=True), nullable=True,
        ),
        sa.Column("scope_id_int", sa.Integer, nullable=True),
        sa.Column("dimension", sa.String(40), nullable=False),
        sa.Column(
            "field", sa.String(80), nullable=False, server_default="",
        ),
        sa.Column(
            "value_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
        sa.Column(
            "created_by_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(_SCOPE_TYPE_CHECK, name="behov_scope_type_chk"),
        sa.CheckConstraint(_DIMENSION_CHECK, name="behov_dimension_chk"),
        sa.CheckConstraint(_SCOPE_ID_SHAPE_CHECK, name="behov_scope_id_chk"),
    )

    # Natural-key uniqueness — drives upsert in the service layer.
    # Two partial indexes because (scope_id_uuid IS NULL) and
    # (scope_id_int IS NULL) shapes coexist.
    op.create_index(
        "ux_behov_scope_workspace",
        "workspace_behavior_overrides",
        ["organization_id", "scope_type", "dimension", "field"],
        unique=True,
        postgresql_where=sa.text(
            "scope_type = 'workspace' "
            "AND scope_id_uuid IS NULL AND scope_id_int IS NULL"
        ),
    )
    op.create_index(
        "ux_behov_scope_int",
        "workspace_behavior_overrides",
        [
            "organization_id", "scope_type", "scope_id_int",
            "dimension", "field",
        ],
        unique=True,
        postgresql_where=sa.text("scope_id_int IS NOT NULL"),
    )

    # Hot-path lookup: "all overrides for this scope" (resolver).
    op.create_index(
        "ix_behov_scope_lookup",
        "workspace_behavior_overrides",
        ["organization_id", "scope_type", "scope_id_int", "dimension"],
    )

    # Lineage queries: "how many overrides under this link?"
    op.create_index(
        "ix_behov_link_lookup",
        "workspace_behavior_overrides",
        ["workspace_template_link_id"],
        postgresql_where=sa.text("workspace_template_link_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_behov_link_lookup", "workspace_behavior_overrides")
    op.drop_index("ix_behov_scope_lookup", "workspace_behavior_overrides")
    op.drop_index("ux_behov_scope_int", "workspace_behavior_overrides")
    op.drop_index("ux_behov_scope_workspace", "workspace_behavior_overrides")
    op.drop_table("workspace_behavior_overrides")
