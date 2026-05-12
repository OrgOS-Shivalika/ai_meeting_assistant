"""Phase 2E — embedding backfill.

Walks the `meetings` table for rows that should have vector memory but
don't yet, and dispatches `embed_meeting` for each. Eligibility:

  - `meetings.status = 'completed'`              (transcript is final)
  - `meetings.transcript_raw IS NOT NULL`        (something to embed)
  - one of:
      * `meetings.embedding_status` ∈ {'pending', 'processing', 'failed'}
        (never produced chunks, or the previous run crashed)
      * any chunk for this meeting has an `embedding_model` other than
        the currently-configured `settings.EMBEDDING_MODEL`
        (model upgrade — re-embed)

Usage:

    venv\\Scripts\\python.exe -m app.scripts.backfill_embeddings [flags]

Flags:
    --org-id <uuid>      Restrict to one organization.
    --limit N            Cap how many meetings we dispatch.
    --dry-run            Print the eligible meeting ids and exit.
    --inline             Run synchronously in this process (no Celery,
                         no broker required). Useful for small backfills
                         or when USE_CELERY is false.
    --no-include-failed  Skip meetings whose `embedding_status='failed'`.
    --no-include-stale   Skip the model-upgrade re-embed branch.

Exit codes: 0 on success (incl. dry-run), 1 if any dispatch raised.

Idempotent. A second run that overlaps the first will see fewer
eligible meetings (since the first run flipped them to `embedded`) but
won't corrupt any rows — `_embed_meeting_sync` is idempotent at the
chunk level via delete-then-insert.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Iterable

from sqlalchemy import exists, or_, select

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import Meeting, MeetingChunk
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _eligible_meeting_ids(
    db,
    *,
    org_id: uuid.UUID | None,
    include_failed: bool,
    include_stale: bool,
    current_model: str,
    limit: int | None,
) -> list[int]:
    """Return ids of meetings that need (re-)embedding under the given
    rules, in oldest-first order so a small `--limit` makes progress on
    the backlog instead of replaying the same head of the queue."""

    # The "needs embedding" disjunction. Each branch is independent;
    # the final WHERE OR-s the enabled ones.
    branches = []

    # Branch 1: never succeeded. `pending` covers meetings that finished
    # before Phase 2 even existed; `processing` covers crashes mid-run;
    # `failed` covers the explicit failure path.
    never_succeeded_states = ["pending", "processing"]
    if include_failed:
        never_succeeded_states.append("failed")
    branches.append(Meeting.embedding_status.in_(never_succeeded_states))

    # Branch 2: succeeded under a different (older) model. We use EXISTS
    # rather than a join so each meeting is evaluated once.
    if include_stale:
        stale_predicate = exists(
            select(1).where(
                MeetingChunk.meeting_id == Meeting.id,
                MeetingChunk.embedding_model != current_model,
            )
        )
        branches.append(stale_predicate)

    stmt = (
        select(Meeting.id)
        .where(
            Meeting.status == "completed",
            Meeting.transcript_raw.isnot(None),
            or_(*branches),
        )
        .order_by(Meeting.id.asc())
    )
    if org_id is not None:
        stmt = stmt.where(Meeting.organization_id == org_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    return [row[0] for row in db.execute(stmt).all()]


def _dispatch(meeting_ids: Iterable[int], *, inline: bool) -> tuple[int, int]:
    """Dispatch embed_meeting for every id. Returns (ok_count, err_count).

    `inline=True` runs `_embed_meeting_sync` synchronously here, opening
    one DB session per meeting so a single failure doesn't bleed into
    the next. `inline=False` calls `embed_meeting.delay(id)`; we don't
    wait for the worker."""
    ok = 0
    err = 0
    if inline:
        from app.celery_tasks.embedding_tasks import _embed_meeting_sync

        for mid in meeting_ids:
            db = SessionLocal()
            try:
                meeting = db.query(Meeting).filter(Meeting.id == mid).first()
                if not meeting:
                    logger.warning("backfill: meeting %s vanished mid-run", mid)
                    err += 1
                    continue
                result = _embed_meeting_sync(db, meeting)
                logger.info("backfill[inline] meeting=%s result=%s", mid, result.get("status"))
                if result.get("status") in ("embedded", "skipped"):
                    ok += 1
                else:
                    err += 1
            except Exception as e:
                logger.exception("backfill[inline] meeting=%s crashed: %s", mid, e)
                err += 1
            finally:
                db.close()
    else:
        from app.celery_tasks.embedding_tasks import embed_meeting

        for mid in meeting_ids:
            try:
                embed_meeting.delay(mid)
                logger.info("backfill[celery] dispatched meeting=%s", mid)
                ok += 1
            except Exception as e:
                logger.exception("backfill[celery] dispatch failed for meeting=%s: %s", mid, e)
                err += 1
    return ok, err


def run(
    *,
    org_id: uuid.UUID | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    inline: bool = False,
    include_failed: bool = True,
    include_stale: bool = True,
) -> dict:
    """Programmatic entry point — same semantics as the CLI. Returns a
    summary dict so callers (tests, ad-hoc scripts) can introspect."""
    current_model = settings.EMBEDDING_MODEL
    db = SessionLocal()
    try:
        ids = _eligible_meeting_ids(
            db,
            org_id=org_id,
            include_failed=include_failed,
            include_stale=include_stale,
            current_model=current_model,
            limit=limit,
        )
    finally:
        db.close()

    logger.info(
        "backfill: eligible=%d (org=%s, include_failed=%s, include_stale=%s, model=%s)",
        len(ids), org_id, include_failed, include_stale, current_model,
    )

    if dry_run or not ids:
        return {
            "eligible": len(ids),
            "meeting_ids": ids,
            "dispatched": 0,
            "errors": 0,
            "dry_run": dry_run,
            "inline": inline,
            "model": current_model,
        }

    ok, err = _dispatch(ids, inline=inline)
    return {
        "eligible": len(ids),
        "meeting_ids": ids,
        "dispatched": ok,
        "errors": err,
        "dry_run": False,
        "inline": inline,
        "model": current_model,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_embeddings",
        description="Embed meetings that don't have vector memory yet.",
    )
    p.add_argument("--org-id", type=str, default=None,
                   help="Restrict to one organization UUID.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap on meetings dispatched in this run.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print eligible ids and exit without dispatching.")
    p.add_argument("--inline", action="store_true",
                   help="Run synchronously without Celery.")
    p.add_argument("--no-include-failed", dest="include_failed", action="store_false",
                   help="Skip meetings with embedding_status='failed'.")
    p.add_argument("--no-include-stale", dest="include_stale", action="store_false",
                   help="Skip model-upgrade re-embed (only embed never-succeeded).")
    p.set_defaults(include_failed=True, include_stale=True)
    return p


def main(argv: list[str] | None = None) -> int:
    # Make CLI logs visible without depending on caller's log config.
    logging.getLogger().setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)

    args = _build_parser().parse_args(argv)
    org_id = uuid.UUID(args.org_id) if args.org_id else None
    summary = run(
        org_id=org_id,
        limit=args.limit,
        dry_run=args.dry_run,
        inline=args.inline,
        include_failed=args.include_failed,
        include_stale=args.include_stale,
    )

    print()
    print("=== backfill summary ===")
    for k in ("eligible", "dispatched", "errors", "dry_run", "inline", "model"):
        print(f"  {k}: {summary[k]}")
    if summary["dry_run"] and summary["meeting_ids"]:
        print("  meeting_ids:", summary["meeting_ids"])
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
