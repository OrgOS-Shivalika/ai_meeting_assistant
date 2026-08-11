"""Database logic for Phase 8F — templates catalog / workspace links.

Extracted from ``app/api/templates_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` plus an explicit
``organization_id`` (or slug/id) and raise ``HTTPException`` for lookup
failures — mirroring the existing ``category_service`` convention.

Profile lookups (``list_profiles``/``get_profile``) and install actions
(``install_bundle``/``install_profile``) already live in
``app.services.templates.behavior_registry`` and
``app.services.behavior.provisioning``; the router keeps calling those
directly. This module owns the remaining raw table reads (bundles,
workspace links, provisioning jobs).
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.db.models import (
    TemplateBundle, TemplateBundleItem, TemplateProvisioningJob,
    WorkspaceTemplateLink,
)


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


def list_published_bundles(
    db: Session, *, recommended_only: bool,
) -> List[TemplateBundle]:
    q = db.query(TemplateBundle).filter(
        TemplateBundle.state == "published",
    )
    if recommended_only:
        q = q.filter(TemplateBundle.is_recommended_on_signup.is_(True))
    return q.order_by(TemplateBundle.display_name.asc()).all()


def get_bundle_by_slug(db: Session, *, slug: str) -> TemplateBundle:
    bundle = (
        db.query(TemplateBundle)
        .filter(TemplateBundle.slug == slug)
        .order_by(desc(TemplateBundle.created_at))
        .first()
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return bundle


def list_bundle_items(
    db: Session, *, bundle_id: UUID,
) -> List[TemplateBundleItem]:
    return (
        db.query(TemplateBundleItem)
        .filter(TemplateBundleItem.bundle_id == bundle_id)
        .order_by(TemplateBundleItem.ordering.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# Workspace links
# ---------------------------------------------------------------------------


def get_links_summary(
    db: Session, *, organization_id: UUID,
) -> Tuple[int, dict]:
    """Return (total, by_source_template_kind) counts for the org."""
    rows = (
        db.query(
            WorkspaceTemplateLink.source_template_kind,
            sa_func.count().label("n"),
        )
        .filter(WorkspaceTemplateLink.organization_id == organization_id)
        .group_by(WorkspaceTemplateLink.source_template_kind)
        .all()
    )
    by_kind = {k: int(n) for k, n in rows}
    total = sum(by_kind.values())
    return total, by_kind


def list_workspace_links(
    db: Session, *, organization_id: UUID,
    source_template_kind: Optional[str], limit: int,
) -> List[WorkspaceTemplateLink]:
    q = db.query(WorkspaceTemplateLink).filter(
        WorkspaceTemplateLink.organization_id == organization_id,
    )
    if source_template_kind is not None:
        q = q.filter(
            WorkspaceTemplateLink.source_template_kind == source_template_kind,
        )
    return q.order_by(desc(WorkspaceTemplateLink.provisioned_at)).limit(limit).all()


def get_workspace_link(
    db: Session, *, link_id: int, organization_id: UUID,
) -> WorkspaceTemplateLink:
    row = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.id == link_id,
            WorkspaceTemplateLink.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return row


# ---------------------------------------------------------------------------
# Provisioning jobs — audit read
# ---------------------------------------------------------------------------


def list_provisioning_jobs(
    db: Session, *, organization_id: UUID, limit: int,
) -> List[TemplateProvisioningJob]:
    return (
        db.query(TemplateProvisioningJob)
        .filter(TemplateProvisioningJob.organization_id == organization_id)
        .order_by(desc(TemplateProvisioningJob.created_at))
        .limit(limit)
        .all()
    )
