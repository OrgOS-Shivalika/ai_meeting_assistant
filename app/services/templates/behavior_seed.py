"""Phase 8A (revised) — seed script for template_behavior_profiles.

Idempotent: re-running on a populated DB inserts nothing new IF the
catalog manifest hashes match what's already stored. If a profile's
hash differs (i.e. content changed in catalog.py but version wasn't
bumped), seed reports drift and refuses to overwrite — bump the
profile's version and re-run.

This is the single write path into `template_behavior_profiles`.
Future admin-tooling endpoints can call `publish_profile_version`
directly, but the catalog code is the canonical content source.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import TemplateBehaviorProfile
from app.services.templates.behavior_catalog import (
    CATALOG_PROFILES, BehaviorProfileDef, manifest_hash, manifest_payload,
)

logger = logging.getLogger(__name__)


@dataclass
class SeedReport:
    """Summary returned by seed_catalog. Drives the CLI output + the
    drift-detection test."""
    inserted: int = 0
    matched: int = 0       # hash equal — nothing to do
    drifted: list[str] = None  # slugs whose hash differs from DB
    dry_run: bool = False

    def __post_init__(self):
        if self.drifted is None:
            self.drifted = []


def seed_catalog(
    db: Session, *, dry_run: bool = False,
) -> SeedReport:
    """Apply CATALOG_PROFILES to the DB.

    For each catalog profile:
      - If no DB row exists for (scope_kind, slug, version): INSERT
      - If a DB row exists and its manifest_hash matches: do nothing
      - If a DB row exists but its hash differs: record drift,
        do NOT overwrite. Bump the catalog version + re-run.

    dry_run=True: report what would happen without writing.
    """
    report = SeedReport(dry_run=dry_run)
    now = datetime.now(timezone.utc)
    for prof in CATALOG_PROFILES:
        existing = (
            db.query(TemplateBehaviorProfile)
            .filter(
                TemplateBehaviorProfile.scope_kind == prof.scope_kind,
                TemplateBehaviorProfile.slug == prof.slug,
                TemplateBehaviorProfile.version == prof.version,
            )
            .first()
        )
        new_hash = manifest_hash(prof)
        if existing is not None:
            if existing.manifest_hash == new_hash:
                report.matched += 1
            else:
                report.drifted.append(
                    f"{prof.scope_kind}/{prof.slug}@{prof.version}"
                )
                logger.warning(
                    "catalog drift: %s/%s@%s differs from DB. Bump "
                    "version in catalog.py + re-run.",
                    prof.scope_kind, prof.slug, prof.version,
                )
            continue

        if dry_run:
            report.inserted += 1
            continue

        row = TemplateBehaviorProfile(
            scope_kind=prof.scope_kind,
            slug=prof.slug,
            version=prof.version,
            display_name=prof.display_name,
            description=prof.description,
            state="published",
            parent_category_slug=prof.parent_category_slug,
            master_prompt=dict(prof.master_prompt),
            enabled_agents=list(prof.enabled_agents),
            retrieval_config=dict(prof.retrieval_config),
            memory_config=dict(prof.memory_config),
            output_config=dict(prof.output_config),
            extraction_rules=dict(prof.extraction_rules),
            automation_rules=dict(prof.automation_rules),
            evaluation_rules=dict(prof.evaluation_rules),
            tone_and_personality=dict(prof.tone_and_personality),
            compliance_and_guardrails=dict(prof.compliance_and_guardrails),
            tools_and_integrations=dict(prof.tools_and_integrations),
            intent=dict(prof.intent),
            manifest_hash=new_hash,
            published_at=now,
        )
        db.add(row)
        report.inserted += 1

    if not dry_run and report.inserted:
        db.commit()
    return report
