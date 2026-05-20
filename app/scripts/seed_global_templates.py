"""Phase 8A (refactored) — behavior-profile seeder CLI.

Reads `app/services/templates/behavior_catalog.py` and writes to
`template_behavior_profiles`. Idempotent — re-running with an
unchanged catalog is a no-op.

Usage:

    venv\\Scripts\\python.exe -m app.scripts.seed_global_templates [flags]

Flags:
    --dry-run    Print what would change; make no DB writes.

Exit codes: 0 on success or dry-run; 1 if drift was detected
(an existing version row's manifest hash differs from the catalog
— bump the profile's version in code and re-run).
"""
from __future__ import annotations

import argparse
import sys

from app.db.database import SessionLocal
from app.services.templates.behavior_seed import seed_catalog
from app.services.templates.behavior_bundle_seed import seed_bundles


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Seed the behavior-profile catalog + bundles.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Compute the plan; make no DB writes.",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    db = SessionLocal()
    exit_code = 0
    try:
        report = seed_catalog(db, dry_run=args.dry_run)
        print()
        print("=== behavior_profiles seed result ===")
        print(f"inserted : {report.inserted}")
        print(f"matched  : {report.matched}")
        print(f"drifted  : {len(report.drifted)}")
        if report.drifted:
            print()
            print("DRIFT (bump version in behavior_catalog.py + re-run):")
            for slug in report.drifted:
                print(f"  - {slug}")
            exit_code = 1

        # Bundles depend on profiles existing — run AFTER.
        b_report = seed_bundles(db, dry_run=args.dry_run)
        print()
        print("=== bundles seed result ===")
        print(f"created   : {b_report.bundles_created}")
        print(f"updated   : {b_report.bundles_updated}")
        print(f"unchanged : {b_report.bundles_unchanged}")
        print(f"items inserted: {b_report.items_inserted}")
        print(f"items removed : {b_report.items_removed}")
        if b_report.skipped_slugs:
            print("\nSkipped bundles (missing catalog content):")
            for s in b_report.skipped_slugs:
                print(f"  - {s}")
        return exit_code
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
