"""Phase 8G — allow entity_type='team' on workspace_template_links.

The new department/team hierarchy puts category templates into the
existing `categories` table (top-level) and team templates into the
existing `teams` table (parent = a category row). The link table's
entity_type CHECK needs 'team' added so a team link can point at a
teams.id via entity_id_int.
"""
from alembic import op
import sqlalchemy as sa


revision = "t1b9c0d1e2f3"
down_revision = "s0a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres requires drop+recreate to change a CHECK definition.
    op.drop_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links",
    )
    op.create_check_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links",
        "entity_type IN ('category','team','agent_profile',"
        "'prompt_config','prompt_version')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links",
    )
    op.create_check_constraint(
        "ck_workspace_template_links_entity_type",
        "workspace_template_links",
        "entity_type IN ('category','agent_profile',"
        "'prompt_config','prompt_version')",
    )
