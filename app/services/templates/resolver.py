"""Phase 8C — WorkspaceTemplateResolver (read helper).

NOT a runtime resolver. This is a small lookup layer the HTTP/UI
uses to enrich workspace entity responses with lineage metadata.
Pure read; no side effects.

Used by:
  - GET /agents/{id} response augmentation (planned)
  - GET /templates/links/{id} detail
  - Frontend LineageBadge component (Phase 8 frontend slice)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import WorkspaceTemplateLink


@dataclass(frozen=True)
class LineageInfo:
    """Compact lineage descriptor — what the UI's badge needs."""
    link_id: int
    source_template_kind: str
    source_template_slug: str
    source_template_version: str
    source_bundle_id: Optional[UUID]
    source_bundle_version: Optional[str]
    lineage_state: str
    diff_summary: dict
    provisioned_at: str
    last_diverged_at: Optional[str]


def _to_info(link: WorkspaceTemplateLink) -> LineageInfo:
    return LineageInfo(
        link_id=link.id,
        source_template_kind=link.source_template_kind,
        source_template_slug=link.source_template_slug,
        source_template_version=link.source_template_version,
        source_bundle_id=link.source_bundle_id,
        source_bundle_version=link.source_bundle_version,
        lineage_state=link.lineage_state,
        diff_summary=link.diff_summary_json or {},
        provisioned_at=link.provisioned_at.isoformat(),
        last_diverged_at=(
            link.last_diverged_at.isoformat() if link.last_diverged_at else None
        ),
    )


def lineage_for_agent_profile(
    db: Session, *,
    organization_id: UUID,
    agent_profile_id: UUID,
) -> Optional[LineageInfo]:
    """Returns lineage for the agent_profile, or None when the
    profile was hand-authored (no link row)."""
    link = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.organization_id == organization_id,
            WorkspaceTemplateLink.entity_type == "agent_profile",
            WorkspaceTemplateLink.entity_id_uuid == agent_profile_id,
        )
        .first()
    )
    return _to_info(link) if link else None


def lineage_for_category(
    db: Session, *,
    organization_id: UUID,
    category_id: int,
) -> Optional[LineageInfo]:
    link = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.organization_id == organization_id,
            WorkspaceTemplateLink.entity_type == "category",
            WorkspaceTemplateLink.entity_id_int == category_id,
        )
        .first()
    )
    return _to_info(link) if link else None
