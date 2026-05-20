"""Phase 8B (refactored) — link-only template provisioning.

Installing a template into a workspace creates:
  - A `categories` row (workspace-owned, scope_id_int target)
  - A `workspace_template_links` row pinning that category to
    (scope_kind, slug, version) in `template_behavior_profiles`.

That's it. No `prompt_versions` cloning. No `agent_prompt_configs`.
No `agent_profiles`. The runtime resolver reads the template
defaults directly from `template_behavior_profiles` via the link,
and merges any `workspace_behavior_overrides` on top.

Provisioning is:
  - **Idempotent** — re-running an install on a workspace that
    already has the link returns items_created=0, items_skipped=N.
    Idempotency is keyed on (organization_id, scope_kind, slug);
    versions can change without producing duplicate rows.
  - **Atomic per item** — one failed item doesn't roll back the
    others. The job row records per-item failure detail.
  - **Concurrency-safe** — an advisory transactional lock keyed on
    `organization_id` serializes multiple concurrent installs for
    the same org. Different orgs install in parallel.

Two public entry points:

    install_profile(db, *, organization_id, scope_kind, slug,
                    version='latest', triggered_by='manual',
                    triggered_by_user_id=None)
        -> InstallReport

    install_bundle(db, *, organization_id, bundle_slug,
                   bundle_version='latest', triggered_by='manual',
                   triggered_by_user_id=None)
        -> InstallReport   (loops install_profile per bundle item)

A signup-time helper `auto_install_starter(db, organization_id,
user_id)` lives below.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Category, Team, TemplateBehaviorProfile, TemplateBundle,
    TemplateBundleItem, TemplateProvisioningJob, WorkspaceTemplateLink,
)
from app.services.templates.behavior_registry import get_profile

logger = logging.getLogger(__name__)


# Advisory lock domain — keyed on organization_id's first 4 bytes.
# Same idiom as Phase 8B v1; using a stable constant key class so
# we don't collide with other consumers of pg_try_advisory_xact_lock.
_LOCK_CLASS_ID = 8003  # arbitrary but stable


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class InstallItem:
    scope_kind: str  # 'category' or 'team'
    slug: str
    version: str = "latest"


@dataclass
class InstallReport:
    job_id: UUID
    status: str
    items_created: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    workspace_link_ids: list[int] = field(default_factory=list)
    failure_details: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProvisioningError(RuntimeError):
    """Raised on contract violations (unknown bundle slug, etc.)."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _take_org_lock(db: Session, organization_id: UUID) -> None:
    """Per-org transactional advisory lock. Two concurrent installs
    for the same org serialize; different orgs parallel."""
    # The lock key derives from the UUID's first 32 bits. Stable +
    # collision-tolerant (one extra wait is fine).
    key = int(organization_id.int >> 96) & 0x7FFFFFFF
    db.execute(
        sql_text("SELECT pg_advisory_xact_lock(:cls, :key)"),
        {"cls": _LOCK_CLASS_ID, "key": key},
    )


def _existing_link(
    db: Session, *, organization_id: UUID, scope_kind: str, slug: str,
) -> Optional[WorkspaceTemplateLink]:
    """Find a non-version-specific link for (org, scope_kind, slug).
    Used for idempotency: 'is this profile already installed?'"""
    return (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.organization_id == organization_id,
            WorkspaceTemplateLink.source_template_kind == scope_kind,
            WorkspaceTemplateLink.source_template_slug == slug,
        )
        .order_by(WorkspaceTemplateLink.provisioned_at.desc())
        .first()
    )


def _find_parent_category_id(
    db: Session, *, organization_id: UUID, parent_template_slug: str,
) -> Optional[int]:
    """When installing a team profile, look up which workspace category
    row corresponds to its parent category template. The categories row
    must have been created earlier (when the parent template was
    installed). Returns None if missing — caller decides what to do."""
    link = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.organization_id == organization_id,
            WorkspaceTemplateLink.source_template_kind == "category",
            WorkspaceTemplateLink.source_template_slug == parent_template_slug,
        )
        .order_by(WorkspaceTemplateLink.provisioned_at.desc())
        .first()
    )
    return link.entity_id_int if link is not None else None


def _create_workspace_category_row(
    db: Session, *, organization_id: UUID, user_id: UUID,
    profile: TemplateBehaviorProfile,
) -> int:
    """Create a `categories` row for a top-level category (department).
    Returns categories.id. Only used for scope_kind='category'."""
    cat = Category(
        organization_id=organization_id,
        user_id=user_id,
        name=profile.display_name,
        description=profile.description or "",
    )
    db.add(cat); db.commit(); db.refresh(cat)
    return cat.id


def _create_workspace_team_row(
    db: Session, *, parent_category_id: int,
    profile: TemplateBehaviorProfile,
) -> int:
    """Create a `teams` row for a sub-team under a category. Returns
    teams.id. Only used for scope_kind='team'."""
    team = Team(
        category_id=parent_category_id,
        name=profile.display_name,
        description=profile.description or "",
    )
    db.add(team); db.commit(); db.refresh(team)
    return team.id


def _make_link(
    db: Session, *, organization_id: UUID, entity_id_int: int,
    entity_type: str,
    profile: TemplateBehaviorProfile, job_id: Optional[UUID],
) -> WorkspaceTemplateLink:
    """entity_type is 'category' for top-level categories, 'team' for
    sub-teams. entity_id_int points at the appropriate workspace row
    (categories.id or teams.id)."""
    link = WorkspaceTemplateLink(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id_int=entity_id_int,
        source_template_kind=profile.scope_kind,
        source_template_slug=profile.slug,
        source_template_version=profile.version,
        provisioning_job_id=job_id,
        provisioned_at=datetime.now(timezone.utc),
        lineage_state="pristine",  # historical column; resolver doesn't read it
    )
    db.add(link); db.commit(); db.refresh(link)
    return link


# ---------------------------------------------------------------------------
# Public — install a single profile
# ---------------------------------------------------------------------------


def install_profile(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    scope_kind: str,
    slug: str,
    version: str = "latest",
    triggered_by: str = "manual",
    triggered_by_user_id: Optional[UUID] = None,
    job_id: Optional[UUID] = None,
) -> tuple[Optional[WorkspaceTemplateLink], str]:
    """Install one profile into a workspace.

    Returns (link, status). status ∈ {'created', 'skipped', 'failed'}.

    'created' — new link + category row inserted.
    'skipped' — link already exists for (org, scope_kind, slug).
                The caller should treat this as success.
    'failed'  — IntegrityError or unknown profile. Caller logs.

    This function is meant to be called from `install_bundle` or
    directly. It does NOT take the org lock — the caller does, so
    a bundle install holds one lock for the whole batch.
    """
    profile = get_profile(
        db, scope_kind=scope_kind, slug=slug, version=version,
    )
    if profile is None:
        return None, "failed"

    # Idempotency check.
    existing = _existing_link(
        db, organization_id=organization_id,
        scope_kind=scope_kind, slug=slug,
    )
    if existing is not None:
        return existing, "skipped"

    # For team profiles: resolve the parent category's workspace row
    # so the teams row's category_id FK points correctly. Auto-install
    # the parent category if it's missing rather than failing.
    parent_category_id: Optional[int] = None
    if profile.scope_kind == "team":
        parent_slug = profile.parent_category_slug
        if not parent_slug:
            logger.warning(
                "team profile %s has no parent_category_slug; failing install",
                profile.slug,
            )
            return None, "failed"
        parent_category_id = _find_parent_category_id(
            db, organization_id=organization_id,
            parent_template_slug=parent_slug,
        )
        if parent_category_id is None:
            # Auto-install the parent (recursive). Caller still holds
            # the per-org advisory lock from install_bundle.
            _, parent_status = install_profile(
                db, organization_id=organization_id, user_id=user_id,
                scope_kind="category", slug=parent_slug, version="latest",
                triggered_by=triggered_by,
                triggered_by_user_id=triggered_by_user_id,
                job_id=job_id,
            )
            if parent_status == "failed":
                return None, "failed"
            parent_category_id = _find_parent_category_id(
                db, organization_id=organization_id,
                parent_template_slug=parent_slug,
            )
            if parent_category_id is None:
                return None, "failed"

    try:
        if profile.scope_kind == "category":
            entity_id = _create_workspace_category_row(
                db, organization_id=organization_id, user_id=user_id,
                profile=profile,
            )
            link = _make_link(
                db, organization_id=organization_id,
                entity_id_int=entity_id, entity_type="category",
                profile=profile, job_id=job_id,
            )
        else:
            # team
            entity_id = _create_workspace_team_row(
                db, parent_category_id=parent_category_id, profile=profile,
            )
            link = _make_link(
                db, organization_id=organization_id,
                entity_id_int=entity_id, entity_type="team",
                profile=profile, job_id=job_id,
            )
        return link, "created"
    except IntegrityError as exc:
        logger.warning("install_profile failed: %s", exc)
        db.rollback()
        return None, "failed"


# ---------------------------------------------------------------------------
# Public — install a bundle
# ---------------------------------------------------------------------------


def install_bundle(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    bundle_slug: str,
    bundle_version: str = "latest",
    triggered_by: str = "manual",
    triggered_by_user_id: Optional[UUID] = None,
) -> InstallReport:
    """Install every item in a bundle. Returns a structured report.

    Holds the per-org advisory lock for the whole batch — concurrent
    installs for the same org serialize. Different orgs run in parallel.

    Skipped items (already installed) are not failures; the link is
    captured in `workspace_link_ids` regardless of created vs skipped.
    """
    # Resolve bundle
    bundle_q = db.query(TemplateBundle).filter(
        TemplateBundle.slug == bundle_slug,
    )
    if bundle_version != "latest":
        bundle = bundle_q.filter(
            TemplateBundle.version == bundle_version,
        ).first()
    else:
        bundle = (
            bundle_q.filter(TemplateBundle.state == "published")
            .order_by(TemplateBundle.created_at.desc())
            .first()
        )
        if bundle is None:
            bundle = bundle_q.order_by(
                TemplateBundle.created_at.desc(),
            ).first()
    if bundle is None:
        raise ProvisioningError(f"bundle {bundle_slug!r} not found")

    # Open the audit job up front so per-item statuses can write to it.
    job = TemplateProvisioningJob(
        organization_id=organization_id,
        bundle_id=bundle.id,
        bundle_slug=bundle.slug,
        bundle_version=bundle.version,
        mode="bundle",
        status="in_progress",
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
        started_at=datetime.now(timezone.utc),
        requested_items_json=[],
    )
    db.add(job); db.commit(); db.refresh(job)

    _take_org_lock(db, organization_id)

    items = (
        db.query(TemplateBundleItem)
        .filter(TemplateBundleItem.bundle_id == bundle.id)
        .order_by(TemplateBundleItem.ordering.asc())
        .all()
    )

    report = InstallReport(job_id=job.id, status="in_progress")

    for item in items:
        # Old bundles may carry item_type='agent' from the pre-refactor
        # catalog. Those are obsolete — agents are folded into category
        # profiles now. Skip silently.
        if item.item_type not in ("category", "team"):
            report.items_skipped += 1
            continue
        link, status = install_profile(
            db, organization_id=organization_id, user_id=user_id,
            scope_kind=item.item_type, slug=item.item_slug,
            version=item.item_version or "latest",
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            job_id=job.id,
        )
        if status == "created":
            report.items_created += 1
            if link is not None:
                report.workspace_link_ids.append(link.id)
        elif status == "skipped":
            report.items_skipped += 1
            if link is not None:
                report.workspace_link_ids.append(link.id)
        else:
            report.items_failed += 1
            report.failure_details.append({
                "scope_kind": item.item_type,
                "slug": item.item_slug,
                "reason": "install_profile returned failed",
            })

    final_status = (
        "completed" if report.items_failed == 0
        else "partial" if report.items_created + report.items_skipped > 0
        else "failed"
    )
    job.status = final_status
    job.items_created = report.items_created
    job.items_skipped = report.items_skipped
    job.items_failed = report.items_failed
    job.failure_details_json = report.failure_details
    job.completed_at = datetime.now(timezone.utc)
    db.commit()
    report.status = final_status
    return report


# ---------------------------------------------------------------------------
# Public — auto-install (signup hook)
# ---------------------------------------------------------------------------


def auto_install_starter(
    db: Session,
    *,
    organization_id: UUID,
    user_id: UUID,
    bundle_slug: str,
) -> Optional[InstallReport]:
    """Called from /auth/register after the org is created. Empty
    bundle_slug = noop (signup-time auto-install disabled). Failures
    log + write a failed job row but DO NOT raise — signup must
    proceed regardless."""
    if not bundle_slug:
        return None
    try:
        return install_bundle(
            db, organization_id=organization_id, user_id=user_id,
            bundle_slug=bundle_slug,
            triggered_by="auto_signup",
            triggered_by_user_id=user_id,
        )
    except Exception as exc:
        logger.warning(
            "auto_install_starter failed for org=%s: %s",
            organization_id, exc,
        )
        db.rollback()
        return None
