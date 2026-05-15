"""Phase 6C: rerank_strategy column on rag_query_runs.

The audit row must record WHICH reranker produced a query's ranking,
so A/B comparisons and eval diffs are possible. Phase 5 / 6A / 6B
always used `legacy_weighted`; 6C introduces `importance_aware` and
makes the choice per-run (settings default + AskRequest override).

Backfill behavior: existing rows have `rerank_strategy = NULL`. The
6C audit writer interprets NULL as `legacy_weighted` since that was
the only strategy when those rows landed. We don't backfill — historical
data isn't worth a one-time UPDATE; the NULL is the marker.
"""
from alembic import op
import sqlalchemy as sa


revision = "a9c5e1f2d731"
down_revision = "f4d8c2b6e913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rag_query_runs",
        sa.Column("rerank_strategy", sa.String(length=24), nullable=True),
    )
    op.create_check_constraint(
        "ck_rag_query_runs_rerank_strategy",
        "rag_query_runs",
        "rerank_strategy IS NULL "
        "OR rerank_strategy IN ('legacy_weighted','importance_aware')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_rag_query_runs_rerank_strategy",
        "rag_query_runs",
        type_="check",
    )
    op.drop_column("rag_query_runs", "rerank_strategy")
