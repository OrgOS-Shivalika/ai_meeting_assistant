"""Allow 'intent' in workspace_behavior_overrides.dimension CHECK.

Python's BEHAVIOR_DIMENSIONS already lists 'intent'; the CHECK from
phase 8C didn't. PUT /behavior/intent died with IntegrityError.
"""
from alembic import op

revision = "y5g9c1d2e3f"
down_revision = "x4f8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE workspace_behavior_overrides DROP CONSTRAINT IF EXISTS behov_dimension_chk")
    op.execute(
        "ALTER TABLE workspace_behavior_overrides ADD CONSTRAINT behov_dimension_chk "
        "CHECK (dimension IN ("
        "'master_prompt','enabled_agents','retrieval_config',"
        "'memory_config','output_config','extraction_rules',"
        "'automation_rules','evaluation_rules',"
        "'tone_and_personality','compliance_and_guardrails',"
        "'tools_and_integrations','intent'"
        "))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workspace_behavior_overrides DROP CONSTRAINT IF EXISTS behov_dimension_chk")
    op.execute(
        "ALTER TABLE workspace_behavior_overrides ADD CONSTRAINT behov_dimension_chk "
        "CHECK (dimension IN ("
        "'master_prompt','enabled_agents','retrieval_config',"
        "'memory_config','output_config','extraction_rules',"
        "'automation_rules','evaluation_rules',"
        "'tone_and_personality','compliance_and_guardrails',"
        "'tools_and_integrations'"
        "))"
    )
