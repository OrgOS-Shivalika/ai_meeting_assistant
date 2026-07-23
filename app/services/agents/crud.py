"""Database logic for agent-profile CRUD (Phase 7A) and the eval-run
version resolution used by the eval-gate endpoints (Phase 7H).

Extracted from ``app/api/agents_router.py`` so the router stays a thin
transport layer. Functions take the SQLAlchemy ``Session`` and raise
``HTTPException`` for ownership / integrity failures — mirroring the
convention in ``category_service`` / ``audit``. Behaviour is identical
to the previous in-router helpers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AgentProfile, AgentPromptConfig, PromptVersion, User,
)
from app.schemas.agent_api_schema import (
    AgentProfileCreateRequest, AgentProfileDuplicateRequest,
    AgentProfilePatchRequest,
)
from app.services.agents.audit import write_event as _audit


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------

def get_owned_profile(
    db: Session, *, profile_id: UUID, organization_id: UUID,
) -> AgentProfile:
    row = (
        db.query(AgentProfile)
        .filter(
            AgentProfile.id == profile_id,
            AgentProfile.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return row


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def list_profiles(
    db: Session, *, organization_id: UUID,
    agent_type: Optional[str], status: Optional[str], limit: int,
) -> List[AgentProfile]:
    """List agent profiles for the org. Default returns active profiles,
    newest first. Pass `status=archived` to see archived ones."""
    q = db.query(AgentProfile).filter(
        AgentProfile.organization_id == organization_id,
    )
    if agent_type is not None:
        q = q.filter(AgentProfile.agent_type == agent_type)
    if status is not None:
        q = q.filter(AgentProfile.status == status)
    else:
        q = q.filter(AgentProfile.status == "active")
    return q.order_by(desc(AgentProfile.created_at)).limit(limit).all()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def create_profile(
    db: Session, *, user: User, payload: AgentProfileCreateRequest,
) -> AgentProfile:
    """Create a draft profile. Subsequent slices (7B) add prompt
    versions; 7A only persists the profile shell."""
    default_prompt = {}
    if payload.default_modular_prompt is not None:
        default_prompt = payload.default_modular_prompt.to_modular_prompt().to_dict()

    row = AgentProfile(
        organization_id=user.organization_id,
        slug=payload.slug,
        display_name=payload.display_name,
        description=payload.description,
        agent_type=payload.agent_type,
        status="active",
        default_modular_prompt_json=default_prompt,
        eval_gate_required=payload.eval_gate_required,
        eval_fixture_set_id=payload.eval_fixture_set_id,
        eval_min_score=payload.eval_min_score,
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # The soft-active unique on (org, slug) is the most likely cause.
        raise HTTPException(
            status_code=409,
            detail="An active agent profile with this slug already exists.",
        ) from e
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="create",
        after={"slug": row.slug, "agent_type": row.agent_type,
               "display_name": row.display_name},
    )
    return row


def patch_profile(
    db: Session, *, user: User, profile_id: UUID,
    payload: AgentProfilePatchRequest,
) -> AgentProfile:
    """Partial update. Slug and agent_type are immutable post-create —
    duplicate the profile if you need a new slug."""
    row = get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    if row.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot edit an archived profile. Duplicate it first.",
        )

    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.description is not None:
        row.description = payload.description
    if payload.default_modular_prompt is not None:
        row.default_modular_prompt_json = (
            payload.default_modular_prompt.to_modular_prompt().to_dict()
        )
    if payload.eval_gate_required is not None:
        row.eval_gate_required = payload.eval_gate_required
    if payload.eval_fixture_set_id is not None:
        row.eval_fixture_set_id = payload.eval_fixture_set_id
    if payload.eval_min_score is not None:
        row.eval_min_score = payload.eval_min_score

    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="update",
        after={"display_name": row.display_name,
               "description": row.description,
               "eval_gate_required": row.eval_gate_required},
    )
    return row


def archive_profile(
    db: Session, *, user: User, profile_id: UUID,
) -> AgentProfile:
    """Soft-archive a profile. Its `prompt_configs` are NOT cascaded —
    they stay active until 7B's deactivation flow handles them. For 7A
    the archive is profile-only; admins archiving a profile mid-7B
    workflow should re-archive bindings explicitly."""
    row = get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    if row.status == "archived":
        return row  # idempotent
    row.status = "archived"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=row.id, action="archive",
        before={"status": "active"}, after={"status": "archived"},
    )
    return row


def duplicate_profile(
    db: Session, *, user: User, profile_id: UUID,
    payload: AgentProfileDuplicateRequest,
) -> AgentProfile:
    """Clone a profile under a new slug. Copies the default modular
    prompt + eval settings, but NOT scope bindings or prompt versions
    (those land in 7B). The duplicate starts fresh — a clean editing
    surface for experimentation."""
    src = get_owned_profile(
        db, profile_id=profile_id, organization_id=user.organization_id,
    )
    new_row = AgentProfile(
        organization_id=user.organization_id,
        slug=payload.new_slug,
        display_name=payload.new_display_name,
        description=src.description,
        agent_type=src.agent_type,
        status="active",
        default_modular_prompt_json=dict(src.default_modular_prompt_json or {}),
        eval_gate_required=src.eval_gate_required,
        eval_fixture_set_id=src.eval_fixture_set_id,
        eval_min_score=src.eval_min_score,
        created_by=user.id,
    )
    db.add(new_row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An active agent profile with this slug already exists.",
        ) from e
    db.refresh(new_row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_profile", entity_id=new_row.id, action="duplicate",
        after={"slug": new_row.slug, "duplicated_from": str(src.id)},
    )
    return new_row


# ---------------------------------------------------------------------------
# Eval-gate support (Phase 7H)
# ---------------------------------------------------------------------------

def resolve_eval_version_id(
    db: Session, *, organization_id: UUID, agent_profile_id: UUID,
    requested_version_id: Optional[UUID],
) -> UUID:
    """Pick + tenancy-check the prompt version for an eval run.

    If the request didn't specify one, use the profile's first
    org-scoped binding's active_version_id. Then sanity-check tenancy
    on the version (rejects cross-org or cross-profile version_ids).
    """
    version_id = requested_version_id
    if version_id is None:
        cfg = (
            db.query(AgentPromptConfig)
            .filter(
                AgentPromptConfig.organization_id == organization_id,
                AgentPromptConfig.agent_profile_id == agent_profile_id,
                AgentPromptConfig.scope_type == "organization",
                AgentPromptConfig.status == "active",
            )
            .first()
        )
        if cfg is None or cfg.active_version_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No active version found for this profile. Pass "
                    "prompt_version_id explicitly or publish a version first."
                ),
            )
        version_id = cfg.active_version_id

    ver = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.organization_id == organization_id,
    ).first()
    if ver is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return version_id
