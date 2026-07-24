"""Phase 5 — backfill active org_memory_facts into mem0.

Warms mem0 after the MEMORY_BACKEND=mem0 flip: replays every *active* fact
from the legacy `org_memory_facts` table into mem0, one-for-one, mirroring
exactly what the distiller's mem0 branch writes (engine.py) + a couple of
backfill markers. Read-only on the source table; nothing native is mutated.

Idempotency: mem0 IS the source of truth. Before pushing an org, we read back
the `native_fact_id`s already stored in mem0 and skip them — so crash-resume
and re-runs never double-write, with no local state file to desync. (Managed
mem0 offers no cheap server-side dedup, hence the read-back.)

Run:
    python -m scripts.backfill_mem0 --dry-run            # counts only, no writes
    python -m scripts.backfill_mem0 --org-id <uuid>      # one org
    python -m scripts.backfill_mem0                      # all orgs

--dry-run is the runnable check: it exercises the DB query + per-org grouping +
mem0 read-back path and prints what WOULD be pushed, writing nothing.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from itertools import groupby

os.environ.setdefault("MEM0_TELEMETRY", "false")

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import OrgMemoryFact
from app.services.memory import mem0_backend as mem

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill_mem0")

_PAGE = 100  # managed get_all page size


def _existing_native_ids(org_id: str) -> set[str]:
    """native_fact_ids already in mem0 for this org (idempotency source of truth).

    Pages the raw client so we get ALL of them, not the facade's capped fetch —
    branching on mode because managed paginates (page/page_size) while OSS
    returns the set for a filter in one call.
    """
    client = mem._mem()
    ids: set[str] = set()

    def _collect(rows) -> int:
        batch = mem._unwrap(rows)
        for r in batch:
            nid = (r.get("metadata") or {}).get("native_fact_id")
            if nid:
                ids.add(str(nid))
        return len(batch)

    if mem._is_managed():
        page = 1
        while True:
            rows = client.get_all(filters={"user_id": org_id}, page=page, page_size=_PAGE)
            n = _collect(rows)
            if n < _PAGE:
                break
            page += 1
    else:
        # OSS: one filtered fetch; big top_k so nothing is silently capped.
        _collect(client.get_all(filters={"user_id": org_id}, top_k=1_000_000))
    return ids


def run(*, org_id: uuid.UUID | None = None, dry_run: bool = False,
        limit: int | None = None) -> int:
    if settings.MEMORY_BACKEND != "mem0":
        log.error("MEMORY_BACKEND=%s (not 'mem0') — backfill would warm a store "
                  "nothing reads. Aborting.", settings.MEMORY_BACKEND)
        return 1
    if not settings.OPEN_API_KEY:
        log.error("OPEN_API_KEY not set. Aborting.")
        return 1

    mode = "MANAGED" if mem._is_managed() else "OSS (self-hosted)"
    log.info("mem0 mode: %s | dry_run=%s | org=%s | limit=%s",
             mode, dry_run, org_id or "ALL", limit or "none")

    db = SessionLocal()
    try:
        q = db.query(OrgMemoryFact).filter(OrgMemoryFact.archive_status == "active")
        if org_id is not None:
            q = q.filter(OrgMemoryFact.organization_id == org_id)
        q = q.order_by(OrgMemoryFact.organization_id)
        if limit:
            q = q.limit(limit)
        facts = q.all()
    finally:
        db.close()

    if not facts:
        log.info("No active facts to backfill.")
        return 0

    facts.sort(key=lambda f: str(f.organization_id))
    totals = {"active": 0, "skipped": 0, "pushed": 0, "failed": 0}

    for org_str, grp in groupby(facts, key=lambda f: str(f.organization_id)):
        group = list(grp)
        # Read-back happens even in dry-run — it's read-only and makes the
        # preview's skipped-count honest.
        existing = _existing_native_ids(org_str)
        pushed_this_org: set[str] = set()
        o = {"active": 0, "skipped": 0, "pushed": 0, "failed": 0}

        for f in group:
            o["active"] += 1
            fid = str(f.id)
            if fid in existing or fid in pushed_this_org:
                o["skipped"] += 1
                continue
            if dry_run:
                o["pushed"] += 1  # would push
                continue
            try:
                mem.add_facts(
                    text_or_messages=f.fact,
                    org_id=f.organization_id,
                    category_id=f.category_id,
                    team_id=f.team_id,
                    meeting_id=f.source_meeting_id,
                    infer=False,  # facts are already grounded; store verbatim
                    extra_metadata={
                        "fact_type": f.fact_type,
                        "subject": f.subject,
                        "importance_score": f.importance_score,
                        "confidence_score": f.confidence_score,
                        "source_excerpt": f.source_excerpt,
                        "native_fact_id": fid,
                        "backfilled": True,
                    },
                )
                pushed_this_org.add(fid)
                o["pushed"] += 1
            except Exception as e:  # one bad fact never aborts the run
                o["failed"] += 1
                log.warning("  push failed (fact=%s): %s", fid, e)

        log.info("org %s: active=%d skipped=%d pushed=%d failed=%d%s",
                 org_str, o["active"], o["skipped"], o["pushed"], o["failed"],
                 " (would push)" if dry_run else "")
        for k in totals:
            totals[k] += o[k]

    log.info("TOTAL: active=%d skipped=%d pushed=%d failed=%d%s",
             totals["active"], totals["skipped"], totals["pushed"], totals["failed"],
             " (dry-run — nothing written)" if dry_run else "")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill active org_memory_facts into mem0.")
    ap.add_argument("--org-id", help="Only this organization (UUID).")
    ap.add_argument("--dry-run", action="store_true", help="Count only; write nothing.")
    ap.add_argument("--limit", type=int, help="Cap facts scanned (testing).")
    args = ap.parse_args()

    org_id = None
    if args.org_id:
        try:
            org_id = uuid.UUID(args.org_id)
        except ValueError:
            log.error("--org-id is not a valid UUID: %s", args.org_id)
            sys.exit(2)

    sys.exit(run(org_id=org_id, dry_run=args.dry_run, limit=args.limit))


if __name__ == "__main__":
    main()
