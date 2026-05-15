"""Phase 6D — archive cold knowledge.

Flags chunks/entities/relationships as `archive_status='archived'`
when ALL three conditions hold:

  - age > CONSOLIDATION_MIN_AGE_DAYS              (default 180)
  - access_count == 0                              (truly unused)
  - importance_score < CONSOLIDATION_MAX_IMPORTANCE (default 0.2)

Non-destructive: rows stay in the table. Retrieval queries are the
gatekeeper — they filter `archive_status='active'`. The rehydrate
endpoint flips the status back if a user wants the content surfaced
again.

Returns counts per target_kind for the Celery summary.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import DocumentChunk, Entity, MeetingChunk, Relationship

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveThresholds:
    min_age_days: float
    max_importance: float

    @classmethod
    def from_settings(cls) -> "ArchiveThresholds":
        return cls(
            min_age_days=settings.CONSOLIDATION_MIN_AGE_DAYS,
            max_importance=settings.CONSOLIDATION_MAX_IMPORTANCE,
        )


def _archive_for_model(
    db: Session, *, model, organization_id: UUID,
    thresholds: ArchiveThresholds, now: datetime,
) -> int:
    """Bulk-flip archive_status='archived' for rows that meet the
    cold-content criteria. Returns the count updated."""
    age_cutoff = now - timedelta(days=thresholds.min_age_days)
    # Only flip rows that are currently 'active' — never re-archive
    # something already merged-into / archived (idempotency).
    result = (
        db.query(model)
        .filter(
            model.organization_id == organization_id,
            model.archive_status == "active",
            model.created_at < age_cutoff,
            model.access_count == 0,
            # importance_score may be NULL for never-scored rows; treat
            # NULL as "low importance" so archival doesn't get blocked.
            (model.importance_score.is_(None))
            | (model.importance_score < thresholds.max_importance),
        )
        .update(
            {"archive_status": "archived"},
            synchronize_session=False,
        )
    )
    db.commit()
    return int(result)


def run_archive(
    db: Session, *, organization_id: UUID,
    thresholds: ArchiveThresholds | None = None,
) -> dict[str, int]:
    """Run an archive pass over every knowledge-tier table in the org.

    Returns {target_kind: rows_archived}. Idempotent: a second run
    immediately after produces zero new archives (the rows are now
    already 'archived').
    """
    thresholds = thresholds or ArchiveThresholds.from_settings()
    now = datetime.now(timezone.utc)
    out: dict[str, int] = {}
    for kind, model in [
        ("meeting_chunk", MeetingChunk),
        ("document_chunk", DocumentChunk),
        ("entity", Entity),
        ("relationship", Relationship),
    ]:
        n = _archive_for_model(
            db, model=model, organization_id=organization_id,
            thresholds=thresholds, now=now,
        )
        out[kind] = n
    logger.info(
        "archive: org=%s archived=%s (min_age=%.0fd max_imp=%.2f)",
        organization_id, out,
        thresholds.min_age_days, thresholds.max_importance,
    )
    return out


def rehydrate(
    db: Session, *, organization_id: UUID, model, row_id,
) -> bool:
    """Flip a single archived row back to 'active'. Returns True on
    success, False when the row isn't archived (or doesn't exist).

    Multi-tenant safe — org_id is in the WHERE clause.
    """
    result = (
        db.query(model)
        .filter(
            model.id == row_id,
            model.organization_id == organization_id,
            model.archive_status == "archived",
        )
        .update(
            {"archive_status": "active"},
            synchronize_session=False,
        )
    )
    db.commit()
    return result > 0
