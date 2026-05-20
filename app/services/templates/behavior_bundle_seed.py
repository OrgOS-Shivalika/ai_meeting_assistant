"""Phase 8G+ — bundle seeder built from the current behavior catalog.

A bundle is a curated installable set of category + team profiles. The
recommended-on-signup `all-in-starter` bundle fans out every
department + every sub-team so a new workspace lands ready to use.

This seeder is idempotent: it wipes obsolete bundle items (slugs not
in the current catalog) and re-inserts the canonical set.

Why not write SQL inline in the migration? Two reasons:
  - The catalog content is Python code (behavior_catalog.py). The
    seeder reads it dynamically so the bundle stays current across
    catalog edits.
  - This script runs alongside `behavior_seed.py` from the CLI; a
    single command rebuilds both behavior_profiles and bundles.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import TemplateBundle, TemplateBundleItem
from app.services.templates.behavior_catalog import (
    all_category_profiles, all_team_profiles, teams_under,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BundleDef:
    slug: str
    display_name: str
    description: str
    category_tag: Optional[str]
    is_recommended_on_signup: bool
    # If None, the seeder includes EVERY category + every team
    # (the "all-in-starter" shape). Otherwise the listed category
    # slugs + each of their teams are added.
    category_slugs: Optional[list[str]] = None
    version: str = "1.0.0"


# Curated bundle definitions. Slugs of categories are looked up in the
# catalog at seed time — the seeder skips any that aren't present.
_BUNDLES: tuple[_BundleDef, ...] = (
    _BundleDef(
        slug="all-in-starter",
        display_name="Everything (recommended)",
        description="Installs every department + every sub-team. "
                    "Best for new workspaces that want the full set.",
        category_tag="general",
        is_recommended_on_signup=True,
        category_slugs=None,  # everything
    ),
    _BundleDef(
        slug="engineering-starter",
        display_name="Engineering Starter",
        description="Engineering department + backend, frontend, devops, "
                    "qa, mobile, platform, data, ml-engineering teams.",
        category_tag="engineering",
        is_recommended_on_signup=False,
        category_slugs=["engineering"],
    ),
    _BundleDef(
        slug="sales-starter",
        display_name="Sales Starter",
        description="Sales department + SDR, AE, enterprise, "
                    "sales-engineering, channel, sales-ops teams.",
        category_tag="sales",
        is_recommended_on_signup=False,
        category_slugs=["sales"],
    ),
    _BundleDef(
        slug="customer-success-starter",
        display_name="Customer Success Starter",
        description="CS department + CSM, support tiers, onboarding, "
                    "customer education teams.",
        category_tag="customer-success",
        is_recommended_on_signup=False,
        category_slugs=["customer-success"],
    ),
    _BundleDef(
        slug="hr-starter",
        display_name="HR Starter",
        description="HR department + recruiting, people-ops, L&D, DEI teams.",
        category_tag="hr",
        is_recommended_on_signup=False,
        category_slugs=["hr"],
    ),
    _BundleDef(
        slug="executive-starter",
        display_name="Executive Starter",
        description="Executive department + leadership, board relations, "
                    "chief-of-staff, communications teams.",
        category_tag="executive",
        is_recommended_on_signup=False,
        category_slugs=["executive"],
    ),
    _BundleDef(
        slug="go-to-market-starter",
        display_name="Go-to-Market Starter",
        description="Sales + Marketing + Customer Success departments + "
                    "their teams. A complete revenue org install.",
        category_tag="general",
        is_recommended_on_signup=False,
        category_slugs=["sales", "marketing", "customer-success"],
    ),
    _BundleDef(
        slug="tech-org-starter",
        display_name="Tech Org Starter",
        description="Engineering + Product + Data Science + Security + IT "
                    "departments + their teams. A complete tech-org install.",
        category_tag="general",
        is_recommended_on_signup=False,
        category_slugs=["engineering", "product", "data-science", "security", "it"],
    ),
    _BundleDef(
        slug="back-office-starter",
        display_name="Back-Office Starter",
        description="HR + Finance + Legal + Operations + IT departments + "
                    "their teams. The corporate / operating-functions stack.",
        category_tag="general",
        is_recommended_on_signup=False,
        category_slugs=["hr", "finance", "legal", "operations", "it"],
    ),
)


@dataclass
class BundleSeedReport:
    bundles_created: int = 0
    bundles_updated: int = 0
    bundles_unchanged: int = 0
    items_inserted: int = 0
    items_removed: int = 0
    skipped_slugs: list[str] = field(default_factory=list)


def _bundle_manifest_hash(
    bundle: _BundleDef, items: list[tuple[str, str, int]],
) -> str:
    """Hash includes bundle metadata + ordered (item_type, item_slug)
    tuples. Used for drift detection."""
    payload = {
        "slug": bundle.slug,
        "version": bundle.version,
        "display_name": bundle.display_name,
        "description": bundle.description,
        "is_recommended_on_signup": bundle.is_recommended_on_signup,
        "items": [
            {"item_type": t, "item_slug": s, "ordering": o}
            for t, s, o in items
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _resolve_items(bundle: _BundleDef) -> list[tuple[str, str, int]]:
    """Expand a bundle def into [(item_type, item_slug, ordering), ...].

    ordering reflects install order: categories first, then their
    teams. Teams within a category are sorted by slug for determinism.
    Items pointing at slugs the catalog doesn't ship are silently
    dropped (returned in report.skipped_slugs by caller)."""
    catalog_cats = {p.slug: p for p in all_category_profiles()}
    catalog_teams = {p.slug: p for p in all_team_profiles()}

    if bundle.category_slugs is None:
        target_cats = sorted(catalog_cats.keys())
    else:
        target_cats = [s for s in bundle.category_slugs if s in catalog_cats]

    items: list[tuple[str, str, int]] = []
    ordering = 0
    for cat_slug in target_cats:
        items.append(("category", cat_slug, ordering))
        ordering += 1
        teams_here = sorted(
            teams_under(cat_slug), key=lambda p: p.slug,
        )
        for team in teams_here:
            if team.slug in catalog_teams:
                items.append(("team", team.slug, ordering))
                ordering += 1
    return items


def seed_bundles(db: Session, *, dry_run: bool = False) -> BundleSeedReport:
    """Sync template_bundles + template_bundle_items to the current
    catalog. Idempotent.

    Behavior per bundle:
      - missing in DB     → INSERT row + items
      - hash matches DB   → no-op (counted as unchanged)
      - hash differs      → replace items (delete-then-insert),
                            update metadata, bump manifest_hash
    """
    report = BundleSeedReport()
    now = datetime.now(timezone.utc)
    catalog_cats = {p.slug for p in all_category_profiles()}
    catalog_teams = {p.slug for p in all_team_profiles()}

    for bundle in _BUNDLES:
        # Skip bundles that reference no real catalog content
        if bundle.category_slugs is not None:
            missing = [
                s for s in bundle.category_slugs if s not in catalog_cats
            ]
            if missing:
                report.skipped_slugs.append(
                    f"{bundle.slug}:missing_categories={missing}"
                )
                logger.warning(
                    "skipping bundle %s: missing categories %s",
                    bundle.slug, missing,
                )
                continue

        items = _resolve_items(bundle)
        new_hash = _bundle_manifest_hash(bundle, items)

        existing = (
            db.query(TemplateBundle)
            .filter(
                TemplateBundle.slug == bundle.slug,
                TemplateBundle.version == bundle.version,
            )
            .first()
        )

        if existing is None:
            if dry_run:
                report.bundles_created += 1
                report.items_inserted += len(items)
                continue
            row = TemplateBundle(
                slug=bundle.slug, version=bundle.version,
                display_name=bundle.display_name,
                description=bundle.description,
                category=bundle.category_tag,
                state="published",
                published_at=now,
                manifest_hash=new_hash,
                is_recommended_on_signup=bundle.is_recommended_on_signup,
            )
            db.add(row); db.commit(); db.refresh(row)
            for item_type, slug, ordering in items:
                db.add(TemplateBundleItem(
                    bundle_id=row.id,
                    item_type=item_type, item_slug=slug,
                    ordering=ordering,
                ))
            db.commit()
            report.bundles_created += 1
            report.items_inserted += len(items)
            continue

        if existing.manifest_hash == new_hash:
            report.bundles_unchanged += 1
            continue

        # Hash differs — replace items, update metadata.
        if dry_run:
            report.bundles_updated += 1
            continue
        removed = (
            db.query(TemplateBundleItem)
            .filter(TemplateBundleItem.bundle_id == existing.id)
            .delete(synchronize_session=False)
        )
        report.items_removed += int(removed)
        existing.display_name = bundle.display_name
        existing.description = bundle.description
        existing.category = bundle.category_tag
        existing.state = "published"
        existing.is_recommended_on_signup = bundle.is_recommended_on_signup
        existing.manifest_hash = new_hash
        existing.published_at = now
        existing.updated_at = now
        db.commit()
        for item_type, slug, ordering in items:
            db.add(TemplateBundleItem(
                bundle_id=existing.id,
                item_type=item_type, item_slug=slug,
                ordering=ordering,
            ))
        db.commit()
        report.bundles_updated += 1
        report.items_inserted += len(items)

    # Also: drop any legacy bundles that no longer appear in _BUNDLES.
    # They'd otherwise sit in the catalog with broken item lists.
    canonical_slugs = {b.slug for b in _BUNDLES}
    legacy = (
        db.query(TemplateBundle)
        .filter(~TemplateBundle.slug.in_(canonical_slugs))
        .all()
    )
    for b in legacy:
        if dry_run:
            continue
        # Items cascade via FK.
        db.delete(b)
    if not dry_run and legacy:
        db.commit()

    return report
