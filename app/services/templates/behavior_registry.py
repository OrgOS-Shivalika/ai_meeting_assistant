"""Phase 8A (revised) — read service for template_behavior_profiles.

Read-only. The seed script writes; the provisioning service + the
resolver read. Runtime never writes here.

Lookups by (scope_kind, slug, version='latest') resolve to the
highest-semver published row. Missing slugs return None (callers
decide whether to 404 or soft-skip).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import TemplateBehaviorProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Semver helper
# ---------------------------------------------------------------------------


def _semver_key(version: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = version.split(".")
        return (int(major), int(minor), int(patch))
    except ValueError:
        return (0, 0, 0)


def _latest(rows: list) -> Optional[TemplateBehaviorProfile]:
    if not rows:
        return None
    return max(rows, key=lambda r: _semver_key(r.version))


# ---------------------------------------------------------------------------
# Public reads
# ---------------------------------------------------------------------------


def get_profile(
    db: Session,
    *,
    scope_kind: str,
    slug: str,
    version: str = "latest",
) -> Optional[TemplateBehaviorProfile]:
    """Resolve one profile by (scope_kind, slug, version). `latest`
    walks the published rows and picks highest semver. If nothing is
    published, falls back to the highest-semver row regardless of
    state — keeps the seed script's first-write flow alive."""
    q = db.query(TemplateBehaviorProfile).filter(
        TemplateBehaviorProfile.scope_kind == scope_kind,
        TemplateBehaviorProfile.slug == slug,
    )
    if version != "latest":
        return q.filter(TemplateBehaviorProfile.version == version).first()
    published = q.filter(
        TemplateBehaviorProfile.state == "published",
    ).all()
    if published:
        return _latest(published)
    return _latest(q.all())


def get_global_default(db: Session) -> Optional[TemplateBehaviorProfile]:
    """The platform-wide floor. Convention: scope_kind='global',
    slug='__default__'."""
    return get_profile(
        db, scope_kind="global", slug="__default__", version="latest",
    )


def list_profiles(
    db: Session, *, scope_kind: Optional[str] = None,
) -> list[TemplateBehaviorProfile]:
    """List all profiles (latest version per slug, scoped). Used by
    the catalog browse UI + the platform-admin catalog audit."""
    q = db.query(TemplateBehaviorProfile)
    if scope_kind is not None:
        q = q.filter(TemplateBehaviorProfile.scope_kind == scope_kind)
    rows = q.all()
    # Collapse to latest per (scope_kind, slug)
    by_key: dict[tuple[str, str], TemplateBehaviorProfile] = {}
    for r in rows:
        key = (r.scope_kind, r.slug)
        existing = by_key.get(key)
        if existing is None or _semver_key(r.version) > _semver_key(existing.version):
            by_key[key] = r
    return sorted(
        by_key.values(),
        key=lambda r: (r.scope_kind, r.display_name),
    )


def profile_to_dimensions_dict(
    profile: TemplateBehaviorProfile,
) -> dict[str, object]:
    """Return the 11 dimensions of a profile as a flat dict. Used by
    the resolver as one layer in the merge."""
    return {
        "master_prompt": profile.master_prompt or {},
        "enabled_agents": profile.enabled_agents or [],
        "retrieval_config": profile.retrieval_config or {},
        "memory_config": profile.memory_config or {},
        "output_config": profile.output_config or {},
        "extraction_rules": profile.extraction_rules or {},
        "automation_rules": profile.automation_rules or {},
        "evaluation_rules": profile.evaluation_rules or {},
        "tone_and_personality": profile.tone_and_personality or {},
        "compliance_and_guardrails": profile.compliance_and_guardrails or {},
        "tools_and_integrations": profile.tools_and_integrations or {},
        "intent": getattr(profile, "intent", {}),
    }
