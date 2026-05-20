"""Phase 8F (post-refactor) — templates HTTP layer.

Lean. Templates are the distribution mechanism only. The real product
runs in Agent Control (8E rebuild). This router exposes:

  Catalog browse (read-only, open to any authenticated user):
    GET  /templates/profiles                — list all BehaviorProfiles
    GET  /templates/profiles/{scope}/{slug} — one profile
    GET  /templates/bundles                 — list bundles
    GET  /templates/bundles/{slug}          — bundle detail
    GET  /templates/bundles/{slug}/preview  — expanded items

  Install (org_admin):
    POST /templates/install                 — install one profile OR a bundle

  Workspace links (read-only):
    GET  /templates/links                   — installed links for the org
    GET  /templates/links/summary           — counts by scope_kind
    GET  /templates/links/{id}              — one link

Dropped in 8F:
  - /templates/teams|categories|agents      (replaced by /profiles)
  - /templates/links/{id}/diff              (divergence service removed)
  - /templates/links/{id}/reset             (replaced by overrides delete in 8E)
  - /templates/upgrade-proposals/*          (3-way-diff system removed)
  - /templates/metrics                      (will be rebuilt in 8E)
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func as sa_func
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import (
    TemplateBundle, TemplateBundleItem, TemplateProvisioningJob, User,
    WorkspaceTemplateLink,
)
from app.dependencies.auth import get_current_user, require_org_admin
from app.services.behavior.provisioning import (
    ProvisioningError, install_bundle, install_profile,
)
from app.services.templates.behavior_registry import (
    get_profile, list_profiles, profile_to_dimensions_dict,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/templates", tags=["Templates"])


# ---------------------------------------------------------------------------
# Profile read endpoints
# ---------------------------------------------------------------------------


class ProfileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scope_kind: str
    slug: str
    version: str
    display_name: str
    description: Optional[str]
    state: str


class ProfileDetail(ProfileSummary):
    master_prompt: dict
    enabled_agents: list
    retrieval_config: dict
    memory_config: dict
    output_config: dict
    extraction_rules: dict
    automation_rules: dict
    evaluation_rules: dict
    tone_and_personality: dict
    compliance_and_guardrails: dict
    tools_and_integrations: dict


@router.get("/profiles", response_model=List[ProfileSummary])
def list_template_profiles(
    scope_kind: Optional[Literal["global", "category", "team"]] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Browse catalog. Returns latest version per (scope_kind, slug).
    Filter by scope_kind to narrow."""
    rows = list_profiles(db, scope_kind=scope_kind)
    return [
        ProfileSummary(
            id=r.id, scope_kind=r.scope_kind, slug=r.slug,
            version=r.version, display_name=r.display_name,
            description=r.description, state=r.state,
        )
        for r in rows
    ]


@router.get(
    "/profiles/{scope_kind}/{slug}", response_model=ProfileDetail,
)
def get_template_profile(
    scope_kind: Literal["global", "category", "team"],
    slug: str,
    version: str = "latest",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = get_profile(db, scope_kind=scope_kind, slug=slug, version=version)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    dims = profile_to_dimensions_dict(row)
    return ProfileDetail(
        id=row.id, scope_kind=row.scope_kind, slug=row.slug,
        version=row.version, display_name=row.display_name,
        description=row.description, state=row.state,
        **dims,
    )


# ---------------------------------------------------------------------------
# Bundles (existing tables — slim presentation, no agent items in new flow)
# ---------------------------------------------------------------------------


class BundleSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    description: Optional[str]
    category: Optional[str]
    version: str
    state: str
    is_recommended_on_signup: bool
    published_at: Optional[datetime]
    created_at: datetime


class BundleItemSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: str
    item_slug: str
    item_version: Optional[str]
    ordering: int


class BundleDetailResponse(BundleSummaryResponse):
    items: list[BundleItemSummary]


@router.get("/bundles", response_model=List[BundleSummaryResponse])
def list_bundles(
    recommended_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(TemplateBundle).filter(
        TemplateBundle.state == "published",
    )
    if recommended_only:
        q = q.filter(TemplateBundle.is_recommended_on_signup.is_(True))
    return q.order_by(TemplateBundle.display_name.asc()).all()


@router.get("/bundles/{slug}", response_model=BundleDetailResponse)
def get_bundle(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bundle = (
        db.query(TemplateBundle)
        .filter(TemplateBundle.slug == slug)
        .order_by(desc(TemplateBundle.created_at))
        .first()
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    items = (
        db.query(TemplateBundleItem)
        .filter(TemplateBundleItem.bundle_id == bundle.id)
        .order_by(TemplateBundleItem.ordering.asc())
        .all()
    )
    # Filter out item_type='agent' — those are obsolete in the new
    # behavior-profile model.
    visible_items = [it for it in items if it.item_type in ("category", "team")]
    return BundleDetailResponse(
        id=bundle.id, slug=bundle.slug,
        display_name=bundle.display_name,
        description=bundle.description, category=bundle.category,
        version=bundle.version, state=bundle.state,
        is_recommended_on_signup=bundle.is_recommended_on_signup,
        published_at=bundle.published_at, created_at=bundle.created_at,
        items=[BundleItemSummary(
            item_type=it.item_type, item_slug=it.item_slug,
            item_version=it.item_version, ordering=it.ordering,
        ) for it in visible_items],
    )


class BundlePreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_type: Literal["category", "team"]
    item_slug: str
    item_version: Optional[str]
    ordering: int
    resolved: bool
    profile: Optional[dict] = None


class BundlePreviewResponse(BundleSummaryResponse):
    items: list[BundlePreviewItem]
    counts: dict


@router.get("/bundles/{slug}/preview", response_model=BundlePreviewResponse)
def preview_bundle(
    slug: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Expanded view of bundle items — each resolved to its full
    BehaviorProfile so the install confirmation screen can show
    'you're about to install N categories + M teams with these
    behavior dimensions.'"""
    bundle = (
        db.query(TemplateBundle)
        .filter(TemplateBundle.slug == slug)
        .order_by(desc(TemplateBundle.created_at))
        .first()
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    raw_items = (
        db.query(TemplateBundleItem)
        .filter(TemplateBundleItem.bundle_id == bundle.id)
        .order_by(TemplateBundleItem.ordering.asc())
        .all()
    )
    expanded: list[BundlePreviewItem] = []
    counts = {"category": 0, "team": 0, "unresolved": 0}
    for it in raw_items:
        if it.item_type not in ("category", "team"):
            # obsolete agent item — skip silently
            continue
        prof = get_profile(
            db, scope_kind=it.item_type, slug=it.item_slug,
            version=it.item_version or "latest",
        )
        resolved = prof is not None
        if resolved:
            counts[it.item_type] += 1
        else:
            counts["unresolved"] += 1
        expanded.append(BundlePreviewItem(
            item_type=it.item_type, item_slug=it.item_slug,
            item_version=it.item_version, ordering=it.ordering,
            resolved=resolved,
            profile=({
                "id": str(prof.id),
                "slug": prof.slug,
                "display_name": prof.display_name,
                "description": prof.description,
                **profile_to_dimensions_dict(prof),
            } if prof else None),
        ))
    return BundlePreviewResponse(
        id=bundle.id, slug=bundle.slug,
        display_name=bundle.display_name,
        description=bundle.description, category=bundle.category,
        version=bundle.version, state=bundle.state,
        is_recommended_on_signup=bundle.is_recommended_on_signup,
        published_at=bundle.published_at, created_at=bundle.created_at,
        items=expanded, counts=counts,
    )


# ---------------------------------------------------------------------------
# Install endpoint (org_admin)
# ---------------------------------------------------------------------------


class InstallRequest(BaseModel):
    """Exactly one of {bundle_slug, profile_slug + scope_kind} required."""
    model_config = ConfigDict(extra="forbid")

    bundle_slug: Optional[str] = Field(default=None, max_length=64)
    profile_slug: Optional[str] = Field(default=None, max_length=64)
    scope_kind: Optional[Literal["category", "team"]] = None
    version: str = "latest"


class InstallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    job_id: Optional[UUID] = None
    items_created: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    workspace_link_ids: list[int] = Field(default_factory=list)


@router.post("/install", response_model=InstallResponse)
def post_install(
    payload: InstallRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_org_admin),
):
    if payload.bundle_slug and payload.profile_slug:
        raise HTTPException(400, "pass bundle_slug OR profile_slug, not both")
    if not payload.bundle_slug and not (
        payload.profile_slug and payload.scope_kind
    ):
        raise HTTPException(
            400, "bundle_slug, or (profile_slug + scope_kind), required",
        )
    if payload.bundle_slug:
        try:
            report = install_bundle(
                db, organization_id=user.organization_id,
                user_id=user.id, bundle_slug=payload.bundle_slug,
                bundle_version=payload.version,
                triggered_by="manual",
                triggered_by_user_id=user.id,
            )
        except ProvisioningError as exc:
            raise HTTPException(404, str(exc))
        return InstallResponse(
            status=report.status, job_id=report.job_id,
            items_created=report.items_created,
            items_skipped=report.items_skipped,
            items_failed=report.items_failed,
            workspace_link_ids=report.workspace_link_ids,
        )
    # Single-profile install path
    link, status = install_profile(
        db, organization_id=user.organization_id, user_id=user.id,
        scope_kind=payload.scope_kind, slug=payload.profile_slug,
        version=payload.version,
        triggered_by="manual",
        triggered_by_user_id=user.id,
    )
    if status == "failed":
        raise HTTPException(
            404, f"profile {payload.scope_kind}/{payload.profile_slug} not found",
        )
    return InstallResponse(
        status=status,
        items_created=1 if status == "created" else 0,
        items_skipped=1 if status == "skipped" else 0,
        workspace_link_ids=[link.id] if link else [],
    )


# ---------------------------------------------------------------------------
# Workspace links — read endpoints
# ---------------------------------------------------------------------------


class WorkspaceLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    entity_id_int: Optional[int]
    source_template_kind: str
    source_template_slug: str
    source_template_version: str
    provisioned_at: datetime


class WorkspaceLinkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    by_source_template_kind: dict


@router.get("/links/summary", response_model=WorkspaceLinkSummary)
def get_links_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(
            WorkspaceTemplateLink.source_template_kind,
            sa_func.count().label("n"),
        )
        .filter(WorkspaceTemplateLink.organization_id == user.organization_id)
        .group_by(WorkspaceTemplateLink.source_template_kind)
        .all()
    )
    by_kind = {k: int(n) for k, n in rows}
    total = sum(by_kind.values())
    return WorkspaceLinkSummary(total=total, by_source_template_kind=by_kind)


@router.get("/links", response_model=List[WorkspaceLinkResponse])
def list_links(
    source_template_kind: Optional[Literal["category", "team"]] = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(WorkspaceTemplateLink).filter(
        WorkspaceTemplateLink.organization_id == user.organization_id,
    )
    if source_template_kind is not None:
        q = q.filter(
            WorkspaceTemplateLink.source_template_kind == source_template_kind,
        )
    return q.order_by(desc(WorkspaceTemplateLink.provisioned_at)).limit(limit).all()


@router.get("/links/{link_id}", response_model=WorkspaceLinkResponse)
def get_link(
    link_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.id == link_id,
            WorkspaceTemplateLink.organization_id == user.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return row


# ---------------------------------------------------------------------------
# Provisioning jobs — audit read
# ---------------------------------------------------------------------------


class ProvisioningJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bundle_slug: Optional[str]
    bundle_version: Optional[str]
    mode: str
    status: str
    items_created: int
    items_skipped: int
    items_failed: int
    triggered_by: str
    triggered_by_user_id: Optional[UUID]
    started_at: datetime
    completed_at: Optional[datetime]


@router.get(
    "/provisioning-jobs", response_model=List[ProvisioningJobSummary],
)
def list_provisioning_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        db.query(TemplateProvisioningJob)
        .filter(TemplateProvisioningJob.organization_id == user.organization_id)
        .order_by(desc(TemplateProvisioningJob.created_at))
        .limit(limit)
        .all()
    )
    return rows
