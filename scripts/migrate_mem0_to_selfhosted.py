"""Copy every mem0 memory from the MANAGED platform into the OSS
(self-hosted) store, so `MEM0_API_KEY` can be removed without losing facts.

Why this exists rather than just re-running `backfill_mem0.py`:
`MeetingMemoryEngine.distill_for_meeting` returns EARLY when
`MEMORY_BACKEND=mem0` — it writes the facts to mem0 and never touches
`org_memory_facts`. So the native table is a snapshot frozen at the moment
mem0 was switched on, and every fact distilled since exists ONLY in mem0's
cloud. Backfilling from Postgres would silently drop those.
Measured 2026-08-03: 112 in managed vs 99 active in `org_memory_facts`.

Direction: managed -> OSS. Run this BEFORE unsetting MEM0_API_KEY, because
the key is what authenticates the read side.

Both clients are constructed directly rather than through
`mem0_backend._mem()`, whose singleton picks exactly one mode per process —
this needs both at once.

Metadata is copied VERBATIM. `mem0_backend._post_scope` filters on
`metadata.category_id` / `metadata.team_id`, and `MemFact.from_mem0` reads
`fact_type` / `subject` / `importance_score` / `confidence_score` off it, so
dropping metadata would silently un-scope every fact and blank the
structured fields.

Idempotency is keyed on NORMALIZED FACT TEXT, not on any id. mem0 mints its
own ids per store, and with `infer=False` it dedups identical text into a
pre-existing memory and keeps ITS metadata — so a copied-id marker would not
survive the merge. Same reasoning as `backfill_mem0.py`.

Usage:
    python scripts/migrate_mem0_to_selfhosted.py --dry-run
    python scripts/migrate_mem0_to_selfhosted.py
    python scripts/migrate_mem0_to_selfhosted.py --org-id <uuid> --limit 10
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlalchemy as sa  # noqa: E402

from app.config.settings import settings  # noqa: E402
from app.services.memory import mem0_backend as mb  # noqa: E402


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace — the dedup key."""
    return " ".join((text or "").split()).lower()


def _items(res) -> list:
    """mem0 returns {'results': [...]} or a bare list depending on
    mode/version."""
    if isinstance(res, dict):
        return res.get("results") or []
    return res or []


def _orgs(org_filter: str | None) -> list[tuple[str, str]]:
    engine = sa.create_engine(settings.DATABASE_URL)
    sql = "select id, name from organizations"
    params = {}
    if org_filter:
        sql += " where id = :oid"
        params["oid"] = org_filter
    sql += " order by name"
    with engine.connect() as c:
        return [(str(r[0]), r[1]) for r in c.execute(sa.text(sql), params)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied, write nothing")
    ap.add_argument("--org-id", default=None, help="restrict to one organization")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap memories copied per org (smoke testing)")
    args = ap.parse_args()

    # Guard the read side. Without the key `MemoryClient` cannot authenticate
    # and this would silently become a no-op that looks like success.
    if not settings.MEM0_API_KEY:
        print("ERROR: MEM0_API_KEY is not set — nothing to migrate FROM.")
        print("       Run this BEFORE switching to the self-hosted store.")
        return 2
    if settings.MEMORY_BACKEND != "mem0":
        print(f"ERROR: MEMORY_BACKEND={settings.MEMORY_BACKEND!r}, expected 'mem0'.")
        return 2

    from mem0 import Memory, MemoryClient
    src = MemoryClient(api_key=settings.MEM0_API_KEY)
    dst = Memory.from_config(mb._build_oss_config())
    print(f"source: mem0 MANAGED    ->  dest: OSS pgvector "
          f"collection={settings.MEM0_COLLECTION!r}")
    print(f"mode  : {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    totals = {"read": 0, "copied": 0, "skipped": 0, "failed": 0}

    for org_id, org_name in _orgs(args.org_id):
        try:
            source_rows = _items(src.get_all(filters={"user_id": org_id},
                                            page_size=1000))
        except Exception as exc:
            print(f"  {org_name[:30]:30s} READ FAILED: {str(exc)[:70]}")
            totals["failed"] += 1
            continue

        if not source_rows:
            continue

        # Pre-load the destination once per org — one round trip instead of
        # one per fact.
        #
        # `top_k` is NOT optional here. The OSS signature is
        # `get_all(*, filters=None, top_k=20, ...)` — it takes top_k, not
        # `limit`, and defaults to 20. Omitting it made this set see only the
        # first 20 facts per org, so everything past that looked absent and
        # got copied a second time: a re-run wrote 54 duplicates instead of
        # skipping 112. Keep it far above any real org's fact count.
        try:
            existing = {
                _normalize(r.get("memory") or r.get("text") or "")
                for r in _items(dst.get_all(filters={"user_id": org_id},
                                            top_k=100_000))
            }
        except Exception as exc:
            # Failing open here would duplicate the whole org, so make the
            # degradation visible instead of silent.
            print(f"    ! dest pre-load failed for {org_name[:24]}: "
                  f"{str(exc)[:60]} — skipping org to avoid duplicates")
            totals["failed"] += 1
            continue

        if args.limit:
            source_rows = source_rows[: args.limit]

        copied = skipped = failed = 0
        for row in source_rows:
            text = row.get("memory") or row.get("text") or ""
            if not text.strip():
                continue
            totals["read"] += 1

            if _normalize(text) in existing:
                skipped += 1
                continue

            if args.dry_run:
                copied += 1
                continue

            try:
                # infer=False: the text is already a distilled fact. With
                # mem0's default infer=True the managed/OSS LLM would
                # rephrase it, merge it into other memories, and strip the
                # run_id/metadata scoping.
                dst.add(
                    text,
                    user_id=org_id,
                    infer=False,
                    metadata=row.get("metadata") or {},
                )
                existing.add(_normalize(text))
                copied += 1
            except Exception as exc:
                failed += 1
                print(f"    ! {str(exc)[:80]}  ({text[:45]}...)")

        totals["copied"] += copied
        totals["skipped"] += skipped
        totals["failed"] += failed
        print(f"  {org_name[:30]:30s} read={len(source_rows):<4} "
              f"copied={copied:<4} skipped={skipped:<4} failed={failed}")

    print()
    print(f"TOTAL read={totals['read']} copied={totals['copied']} "
          f"skipped={totals['skipped']} failed={totals['failed']}")
    if args.dry_run:
        print("(dry run — nothing was written)")
    else:
        print("Next: comment out MEM0_API_KEY in .env, then verify with")
        print("      python scripts/smoke_mem0.py")
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
