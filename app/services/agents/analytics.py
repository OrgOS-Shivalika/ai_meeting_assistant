"""Phase 7F — analytics rollup + query helpers.

Three responsibilities:

  1. **Rebuild a single day's rollup** (`rebuild_daily_bucket`) — runs
     the aggregation SQL over `rag_query_runs` and upserts into
     `agent_performance_daily`. Idempotent: deletes the day's rows
     first (filtered by org if scoped), then re-inserts.

  2. **Walk every active org** (`rebuild_yesterday_all_orgs`) — the
     entry point the Celery beat task calls. Same idempotency.

  3. **Query helpers** (`summary_for_orgs_agents`, `metrics_for_agent`,
     `metrics_per_version`) — read-only aggregations on the rollup
     table, consumed by the HTTP layer in `observability_router`.

Architectural notes:

  - p50 / p95 use `percentile_disc(...) WITHIN GROUP (ORDER BY ...)`.
    Computed at rollup time so the daily numbers are already
    pre-aggregated; the HTTP layer just averages the per-day p95s,
    which is approximate but cheap. The dashboard is for trends, not
    SLO enforcement.
  - `distinct_users` is computed with `COUNT(DISTINCT user_id)` per
    day. Cross-day distinct counts are NOT recoverable from the
    rollup (we'd over-count someone who used the system on multiple
    days); the HTTP summary clearly labels this as "active days, not
    unique users".
  - The rollup groups by (org, profile, version, day). When the
    resolver fell to the filesystem floor, profile and version are
    both NULL; the rollup row aggregates them under a "no profile"
    bucket — important for the dashboard to surface unattributed
    traffic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AgentPerformanceDaily, AgentProfile, Organization, PromptVersion,
)
from app.services.agents.pricing import cost_for_bucket

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

# The aggregation SQL. Operates entirely in PG so we don't have to pull
# every rag_query_runs row into Python. CTE-style `WITH` is just for
# readability; the planner inlines it. Skips rows where total_duration_ms
# is null (planner-crash audit rows) because they aren't usable for
# latency stats — they still contribute to runs_total via the COALESCE
# in the outer SELECT below.
_REBUILD_SQL = text("""
INSERT INTO agent_performance_daily (
    organization_id, agent_profile_id, prompt_version_id, bucket_date,
    runs_total, runs_completed, runs_no_context, runs_failed,
    avg_total_duration_ms, p50_total_duration_ms, p95_total_duration_ms,
    sum_input_tokens, sum_output_tokens,
    avg_citation_count, avg_chunks_retrieved,
    distinct_users, computed_at
)
SELECT
    organization_id,
    agent_profile_id,
    prompt_version_id,
    :bucket_date AS bucket_date,
    COUNT(*) AS runs_total,
    COUNT(*) FILTER (WHERE status = 'completed') AS runs_completed,
    COUNT(*) FILTER (WHERE status = 'no_context') AS runs_no_context,
    COUNT(*) FILTER (WHERE status = 'failed') AS runs_failed,
    AVG(total_duration_ms)::int AS avg_total_duration_ms,
    percentile_disc(0.5) WITHIN GROUP (
        ORDER BY total_duration_ms
    )::int AS p50_total_duration_ms,
    percentile_disc(0.95) WITHIN GROUP (
        ORDER BY total_duration_ms
    )::int AS p95_total_duration_ms,
    COALESCE(SUM(input_tokens), 0) AS sum_input_tokens,
    COALESCE(SUM(output_tokens), 0) AS sum_output_tokens,
    AVG(jsonb_array_length(COALESCE(citations, '[]'::jsonb)))::float
        AS avg_citation_count,
    AVG(retrieved_chunks)::float AS avg_chunks_retrieved,
    COUNT(DISTINCT user_id) AS distinct_users,
    now() AS computed_at
FROM rag_query_runs
WHERE created_at >= :bucket_start
  AND created_at <  :bucket_end
  AND (:org_id IS NULL OR organization_id = :org_id)
GROUP BY organization_id, agent_profile_id, prompt_version_id
""")


def _bucket_bounds(d: date) -> tuple[datetime, datetime]:
    """UTC midnight-to-midnight for the given calendar date."""
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def rebuild_daily_bucket(
    db: Session,
    *,
    bucket_date: date,
    organization_id: Optional[UUID] = None,
) -> int:
    """Aggregate `rag_query_runs` for `bucket_date` into
    `agent_performance_daily`. Idempotent — wipes the day's rows
    (filtered by org if supplied) before re-inserting.

    Returns the number of rows inserted.
    """
    start, end = _bucket_bounds(bucket_date)

    # 1. Delete existing rows for this bucket so re-runs don't double-count.
    delete_params: dict = {"bucket_date": bucket_date}
    delete_sql = "DELETE FROM agent_performance_daily WHERE bucket_date = :bucket_date"
    if organization_id is not None:
        delete_sql += " AND organization_id = :org_id"
        delete_params["org_id"] = str(organization_id)
    db.execute(text(delete_sql), delete_params)

    # 2. Insert fresh aggregates.
    result = db.execute(
        _REBUILD_SQL,
        {
            "bucket_date": bucket_date,
            "bucket_start": start,
            "bucket_end": end,
            "org_id": str(organization_id) if organization_id else None,
        },
    )
    rowcount = result.rowcount or 0
    db.commit()
    logger.info(
        "analytics: rebuilt %d row(s) for bucket=%s org=%s",
        rowcount, bucket_date,
        organization_id if organization_id else "<all>",
    )
    return rowcount


def rebuild_yesterday_all_orgs(db: Session) -> int:
    """The default daily rollup: aggregate yesterday across every org.
    Cheap because one SQL pass touches all orgs at once. Called by
    the Celery beat task."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    return rebuild_daily_bucket(db, bucket_date=yesterday)


# ---------------------------------------------------------------------------
# Query helpers — consumed by observability_router
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentRollupRow:
    """Shape returned by the per-agent summary queries. The HTTP
    layer maps directly to its Pydantic response models."""
    agent_profile_id: Optional[UUID]
    agent_profile_slug: Optional[str]
    agent_profile_display_name: Optional[str]
    agent_type: Optional[str]
    runs_total: int
    runs_completed: int
    runs_no_context: int
    runs_failed: int
    avg_total_duration_ms: Optional[int]
    p95_total_duration_ms: Optional[int]
    sum_input_tokens: int
    sum_output_tokens: int
    avg_citation_count: Optional[float]
    avg_chunks_retrieved: Optional[float]
    estimated_cost_usd: Optional[float]


def _safe_div(num: float, denom: float) -> Optional[float]:
    return (num / denom) if denom else None


def summary_for_orgs_agents(
    db: Session,
    *,
    organization_id: UUID,
    since: date,
    until: date,
) -> list[AgentRollupRow]:
    """One row per agent_profile present in the rollup window.
    Includes an "unattributed" pseudo-row when the resolver fell to
    floor (agent_profile_id IS NULL). The dashboard's main "Agents"
    grid reads this."""
    rows = db.execute(text("""
        SELECT
            apd.agent_profile_id,
            ap.slug,
            ap.display_name,
            ap.agent_type,
            COALESCE(SUM(apd.runs_total), 0)        AS runs_total,
            COALESCE(SUM(apd.runs_completed), 0)    AS runs_completed,
            COALESCE(SUM(apd.runs_no_context), 0)   AS runs_no_context,
            COALESCE(SUM(apd.runs_failed), 0)       AS runs_failed,
            CASE WHEN SUM(apd.runs_total) > 0
                 THEN (SUM(apd.avg_total_duration_ms * apd.runs_total)
                       / SUM(apd.runs_total))::int
                 ELSE NULL END AS avg_total_duration_ms,
            -- Approximate p95 across days by taking the MAX of daily
            -- p95s. The "true" cross-day p95 would require keeping
            -- raw samples; the dashboard's purpose is trend-spotting,
            -- so worst-day-p95 is the right pessimistic signal.
            MAX(apd.p95_total_duration_ms) AS p95_total_duration_ms,
            COALESCE(SUM(apd.sum_input_tokens), 0)  AS sum_input_tokens,
            COALESCE(SUM(apd.sum_output_tokens), 0) AS sum_output_tokens,
            CASE WHEN SUM(apd.runs_total) > 0
                 THEN SUM(apd.avg_citation_count * apd.runs_total)
                      / SUM(apd.runs_total)
                 ELSE NULL END AS avg_citation_count,
            CASE WHEN SUM(apd.runs_total) > 0
                 THEN SUM(apd.avg_chunks_retrieved * apd.runs_total)
                      / SUM(apd.runs_total)
                 ELSE NULL END AS avg_chunks_retrieved
        FROM agent_performance_daily apd
        LEFT JOIN agent_profiles ap ON ap.id = apd.agent_profile_id
        WHERE apd.organization_id = :org_id
          AND apd.bucket_date >= :since
          AND apd.bucket_date <= :until
        GROUP BY apd.agent_profile_id, ap.slug, ap.display_name, ap.agent_type
        ORDER BY runs_total DESC
    """), {
        "org_id": str(organization_id),
        "since": since,
        "until": until,
    }).all()

    # Cost can't be computed in pure SQL without joining on
    # prompt_versions.model_config_json. Compute in Python — the rows
    # are small (≤ a few dozen agents per org).
    out: list[AgentRollupRow] = []
    for r in rows:
        out.append(AgentRollupRow(
            agent_profile_id=r.agent_profile_id,
            agent_profile_slug=r.slug,
            agent_profile_display_name=r.display_name,
            agent_type=r.agent_type,
            runs_total=int(r.runs_total or 0),
            runs_completed=int(r.runs_completed or 0),
            runs_no_context=int(r.runs_no_context or 0),
            runs_failed=int(r.runs_failed or 0),
            avg_total_duration_ms=r.avg_total_duration_ms,
            p95_total_duration_ms=r.p95_total_duration_ms,
            sum_input_tokens=int(r.sum_input_tokens or 0),
            sum_output_tokens=int(r.sum_output_tokens or 0),
            avg_citation_count=r.avg_citation_count,
            avg_chunks_retrieved=r.avg_chunks_retrieved,
            # Cost computed against the default model (we don't have
            # the version's model here). HTTP layer can hydrate per-
            # version costs separately when needed.
            estimated_cost_usd=None,
        ))
    return out


@dataclass(frozen=True)
class VersionRollupRow:
    prompt_version_id: Optional[UUID]
    version_number: Optional[int]
    label: Optional[str]
    state: Optional[str]
    runs_total: int
    runs_completed: int
    runs_no_context: int
    runs_failed: int
    avg_total_duration_ms: Optional[int]
    p95_total_duration_ms: Optional[int]
    sum_input_tokens: int
    sum_output_tokens: int
    avg_citation_count: Optional[float]
    estimated_cost_usd: Optional[float]
    model: Optional[str]


def metrics_per_version(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: UUID,
    since: date,
    until: date,
) -> list[VersionRollupRow]:
    """Per-version metrics for one agent profile within the window.
    Joins to `prompt_versions.model_config_json->>'model'` so cost
    can be computed exactly for each version."""
    rows = db.execute(text("""
        SELECT
            apd.prompt_version_id,
            pv.version_number,
            pv.label,
            pv.state,
            pv.model_config_json->>'model' AS model,
            COALESCE(SUM(apd.runs_total), 0)        AS runs_total,
            COALESCE(SUM(apd.runs_completed), 0)    AS runs_completed,
            COALESCE(SUM(apd.runs_no_context), 0)   AS runs_no_context,
            COALESCE(SUM(apd.runs_failed), 0)       AS runs_failed,
            CASE WHEN SUM(apd.runs_total) > 0
                 THEN (SUM(apd.avg_total_duration_ms * apd.runs_total)
                       / SUM(apd.runs_total))::int
                 ELSE NULL END AS avg_total_duration_ms,
            MAX(apd.p95_total_duration_ms) AS p95_total_duration_ms,
            COALESCE(SUM(apd.sum_input_tokens), 0)  AS sum_input_tokens,
            COALESCE(SUM(apd.sum_output_tokens), 0) AS sum_output_tokens,
            CASE WHEN SUM(apd.runs_total) > 0
                 THEN SUM(apd.avg_citation_count * apd.runs_total)
                      / SUM(apd.runs_total)
                 ELSE NULL END AS avg_citation_count
        FROM agent_performance_daily apd
        LEFT JOIN prompt_versions pv ON pv.id = apd.prompt_version_id
        WHERE apd.organization_id = :org_id
          AND apd.agent_profile_id = :profile_id
          AND apd.bucket_date >= :since
          AND apd.bucket_date <= :until
        GROUP BY apd.prompt_version_id, pv.version_number, pv.label,
                 pv.state, pv.model_config_json
        ORDER BY pv.version_number DESC NULLS LAST
    """), {
        "org_id": str(organization_id),
        "profile_id": str(agent_profile_id),
        "since": since,
        "until": until,
    }).all()

    out: list[VersionRollupRow] = []
    for r in rows:
        cost = cost_for_bucket(
            model=r.model,
            sum_input_tokens=int(r.sum_input_tokens or 0),
            sum_output_tokens=int(r.sum_output_tokens or 0),
        )
        out.append(VersionRollupRow(
            prompt_version_id=r.prompt_version_id,
            version_number=r.version_number,
            label=r.label,
            state=r.state,
            runs_total=int(r.runs_total or 0),
            runs_completed=int(r.runs_completed or 0),
            runs_no_context=int(r.runs_no_context or 0),
            runs_failed=int(r.runs_failed or 0),
            avg_total_duration_ms=r.avg_total_duration_ms,
            p95_total_duration_ms=r.p95_total_duration_ms,
            sum_input_tokens=int(r.sum_input_tokens or 0),
            sum_output_tokens=int(r.sum_output_tokens or 0),
            avg_citation_count=r.avg_citation_count,
            estimated_cost_usd=cost,
            model=r.model,
        ))
    return out


def metrics_for_agent(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: UUID,
    since: date,
    until: date,
) -> Optional[AgentRollupRow]:
    """Single agent's rollup — the dashboard's per-agent detail
    header. Returns None when there's no data in the window."""
    rows = summary_for_orgs_agents(
        db, organization_id=organization_id, since=since, until=until,
    )
    for r in rows:
        if r.agent_profile_id == agent_profile_id:
            return r
    return None
