"""Phase 7D — default-agent seeder CLI.

One-shot per-org bootstrap. Materializes the default `agent_profiles`,
their org-scoped `agent_prompt_configs`, and a published v1
`prompt_versions` row whose modular `system` section is the
filesystem v1 prompt body (split + `{var}` → `{{var}}` converted).

Usage:

    venv\\Scripts\\python.exe -m app.scripts.seed_default_agents [flags]

Flags:
    --org-id <uuid>     Restrict to one org. Default: all active orgs.
    --dry-run           Print what would be seeded; make no DB changes.
    --limit N           Cap on orgs processed.

Exit codes: 0 on success (incl. dry-run + already-seeded); 1 if any
profile in any org failed to seed.

Idempotent. Re-running on a seeded org is a no-op per profile.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Iterable

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import Organization
from app.services.agents.seed_defaults import seed_default_agents_for_org
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _select_orgs(*, org_id: str | None, limit: int | None) -> list[uuid.UUID]:
    """Resolve the org list. Single-org targeting validates the UUID
    + existence; whole-batch mode pulls every row."""
    db = SessionLocal()
    try:
        if org_id is not None:
            try:
                oid = uuid.UUID(org_id)
            except ValueError:
                print(f"ERROR: --org-id is not a valid UUID: {org_id}")
                sys.exit(2)
            row = db.query(Organization).filter(
                Organization.id == oid,
            ).first()
            if row is None:
                print(f"ERROR: no organization with id {oid}")
                sys.exit(2)
            return [oid]
        q = select(Organization.id).order_by(Organization.created_at.asc())
        if limit is not None:
            q = q.limit(limit)
        return [row[0] for row in db.execute(q).all()]
    finally:
        db.close()


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Phase 7D — seed default agent profiles per organization.",
    )
    p.add_argument("--org-id", default=None, help="Restrict to a single org id (UUID).")
    p.add_argument("--dry-run", action="store_true", help="Don't write — just report.")
    p.add_argument("--limit", type=int, default=None, help="Cap on orgs processed.")
    args = p.parse_args(list(argv) if argv is not None else None)

    org_ids = _select_orgs(org_id=args.org_id, limit=args.limit)
    if not org_ids:
        print("No organizations to seed.")
        return 0

    if args.dry_run:
        print(f"Would seed defaults for {len(org_ids)} org(s):")
        for oid in org_ids:
            print(f"  - {oid}")
        return 0

    failures = 0
    for oid in org_ids:
        db = SessionLocal()
        try:
            result = seed_default_agents_for_org(db, organization_id=oid)
            if result.profiles_failed:
                failures += len(result.profiles_failed)
                print(
                    f"[{oid}] created={result.profiles_created} "
                    f"already_seeded={result.profiles_already_seeded} "
                    f"FAILED={result.profiles_failed}"
                )
            else:
                print(
                    f"[{oid}] created={result.profiles_created} "
                    f"already_seeded={result.profiles_already_seeded}"
                )
        finally:
            db.close()

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
