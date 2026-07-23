"""Database logic for Phase 7A/7B — scoped prompt-config bindings and
prompt versions.

Extracted from ``app/api/prompt_configs_router.py`` so the router stays a
thin transport layer. Functions take the SQLAlchemy ``Session`` plus the
current user (or explicit ``organization_id``) and raise ``HTTPException``
for ownership / integrity failures — this mirrors the existing convention
(see ``category_service``) and keeps behaviour identical to the previous
in-router helpers.

Publish/rollback/archive domain errors (``PublishError``) are raised by the
``app.services.agents.publish`` helpers and propagate OUT of these functions;
the router translates them to HTTP responses.
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
    AgentProfile, AgentPromptConfig, Category, PromptDeployment,
    PromptVersion, Team,
)
from app.services.agents.audit import write_event as _audit
from app.services.agents.diff import diff_versions as _diff_versions
from app.services.agents.publish import (
    archive_version, create_draft, publish_version, rollback_to_version,
)


# ---------------------------------------------------------------------------
# Ownership / validation helpers
# ---------------------------------------------------------------------------


def get_owned_config(
    db: Session, *, config_id: UUID, organization_id: UUID,
) -> AgentPromptConfig:
    row = (
        db.query(AgentPromptConfig)
        .filter(
            AgentPromptConfig.id == config_id,
            AgentPromptConfig.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt config not found")
    return row


def validate_scope_target(
    db: Session, *, organization_id: UUID, scope_type: str, scope_id: Optional[int],
) -> None:
    """For category/team scopes, confirm the target row exists AND
    belongs to the requester's org. 404 (not 403) on tenant mismatch —
    matches existing routers."""
    if scope_type == "category":
        cat = (
            db.query(Category)
            .filter(
                Category.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
        if cat is None:
            raise HTTPException(status_code=404, detail="Category not found")
    elif scope_type == "team":
        # Team is keyed under Category; org filter follows the category JOIN.
        team = (
            db.query(Team)
            .join(Category, Team.category_id == Category.id)
            .filter(
                Team.id == scope_id,
                Category.organization_id == organization_id,
            )
            .first()
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
    # organization scope has scope_id NULL; nothing to validate.


def get_owned_version(
    db: Session, *, config_id: UUID, version_id: UUID,
    organization_id: UUID,
) -> PromptVersion:
    """Fetch a version that belongs to the given config + org. 404 on
    any mismatch (matches consolidation_router's convention)."""
    cfg = get_owned_config(
        db, config_id=config_id, organization_id=organization_id,
    )
    row = (
        db.query(PromptVersion)
        .filter(
            PromptVersion.id == version_id,
            PromptVersion.agent_prompt_config_id == cfg.id,
            PromptVersion.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return row


def recompute_lineage_for_config(
    db: Session, *, organization_id: UUID, agent_prompt_config_id: UUID,
) -> None:
    """Phase 8F: divergence service was removed (replaced by sparse
    overrides). Old call sites left in place but reduced to a no-op
    so we don't have to rewire every PATCH/publish path in this
    cleanup slice. Phase 9 will remove the call sites entirely."""
    return None


# ---------------------------------------------------------------------------
# Config read / write
# ---------------------------------------------------------------------------


def list_prompt_configs(
    db: Session, *, organization_id: UUID,
    agent_profile_id: Optional[UUID], scope_type: Optional[str],
    status: Optional[str], limit: int,
) -> List[AgentPromptConfig]:
    """List prompt-config bindings for the user's org. Filterable by
    agent_profile, scope_type, status. Default returns active bindings,
    newest first."""
    q = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.organization_id == organization_id,
    )
    if agent_profile_id is not None:
        q = q.filter(AgentPromptConfig.agent_profile_id == agent_profile_id)
    if scope_type is not None:
        q = q.filter(AgentPromptConfig.scope_type == scope_type)
    if status is not None:
        q = q.filter(AgentPromptConfig.status == status)
    else:
        q = q.filter(AgentPromptConfig.status == "active")
    return q.order_by(desc(AgentPromptConfig.created_at)).limit(limit).all()


def create_prompt_config(db: Session, user, payload) -> AgentPromptConfig:
    """Create a scoped binding for an agent profile. The binding starts
    with `active_version_id` NULL; publishing the first version lands
    in Phase 7B.

    Order of validation:
      1. agent_profile exists in user's org and is active
      2. scope_type + scope_id consistency (handled by Pydantic model)
      3. scope target (Category/Team) exists in user's org
      4. soft-active uniqueness on (org, profile, scope) — INSERT-time check
    """
    # 1. Profile owned and active
    profile = (
        db.query(AgentProfile)
        .filter(
            AgentProfile.id == payload.agent_profile_id,
            AgentProfile.organization_id == user.organization_id,
        )
        .first()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    if profile.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Agent profile is archived; cannot create new bindings.",
        )

    # 2. Scope-type/scope-id consistency already enforced by Pydantic.
    # 3. Tenant-correct scope target.
    validate_scope_target(
        db,
        organization_id=user.organization_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
    )

    row = AgentPromptConfig(
        organization_id=user.organization_id,
        agent_profile_id=payload.agent_profile_id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        active_version_id=None,
        status="active",
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Most likely the soft-active uniqueness was violated.
        raise HTTPException(
            status_code=409,
            detail=(
                "An active binding already exists for this profile at this scope. "
                "Archive the existing binding first, or edit it instead."
            ),
        ) from e
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_prompt_config", entity_id=row.id, action="create",
        after={"agent_profile_id": str(row.agent_profile_id),
               "scope_type": row.scope_type, "scope_id": row.scope_id},
    )
    return row


def archive_prompt_config(db: Session, user, config_id: UUID) -> AgentPromptConfig:
    """Soft-archive a binding. Future requests at this scope will fall
    through to the next resolution layer (once the resolver lands in
    7C). Versions attached to this binding (7B+) are preserved — they
    are no longer active but can be diffed and audited."""
    row = get_owned_config(
        db, config_id=config_id, organization_id=user.organization_id,
    )
    if row.status == "archived":
        return row  # idempotent
    row.status = "archived"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    _audit(
        db, organization_id=user.organization_id, actor_user_id=user.id,
        entity_type="agent_prompt_config", entity_id=row.id, action="archive",
        before={"status": "active"}, after={"status": "archived"},
    )
    return row


# ---------------------------------------------------------------------------
# Version read / write
# ---------------------------------------------------------------------------


def list_prompt_versions(
    db: Session, *, organization_id: UUID, config_id: UUID,
    state: Optional[str], limit: int,
) -> List[PromptVersion]:
    """List versions for a config, newest version_number first.
    Filterable by state. Returns slim summaries — fetch one to read
    body."""
    cfg = get_owned_config(
        db, config_id=config_id, organization_id=organization_id,
    )
    q = db.query(PromptVersion).filter(
        PromptVersion.agent_prompt_config_id == cfg.id,
        PromptVersion.organization_id == organization_id,
    )
    if state is not None:
        q = q.filter(PromptVersion.state == state)
    return q.order_by(desc(PromptVersion.version_number)).limit(limit).all()


def create_prompt_version(
    db: Session, user, config_id: UUID, payload,
) -> PromptVersion:
    """Create a new draft version. version_number auto-increments per
    config under an advisory lock so concurrent draft-creates against
    the same config produce monotonic numbers with no gaps."""
    cfg = get_owned_config(
        db, config_id=config_id, organization_id=user.organization_id,
    )
    if cfg.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Cannot add versions to an archived config.",
        )

    # Flatten the Pydantic payload into the column-shaped dicts the
    # service expects. None payload-keys fall back to defaults.
    modular = (
        payload.modular_prompt.to_modular_prompt().to_dict()
        if payload.modular_prompt is not None
        else {}
    )
    retr = (
        payload.retrieval_config.model_dump(exclude_none=True)
        if payload.retrieval_config is not None
        else {}
    )
    mdl = (
        payload.model_cfg.model_dump(exclude_none=True)
        if payload.model_cfg is not None
        else {}
    )
    tools = (
        payload.tool_permissions.model_dump()
        if payload.tool_permissions is not None
        else {"allowed": [], "denied": []}
    )
    var_schema = [v.model_dump() for v in (payload.variables_schema or [])]

    row = create_draft(
        db,
        organization_id=user.organization_id,
        agent_prompt_config_id=cfg.id,
        label=payload.label,
        modular_prompt_json=modular,
        variables_schema_json=var_schema,
        retrieval_config_json=retr,
        model_config_json=mdl,
        tool_permissions_json=tools,
        meta_json=payload.meta or {},
        created_by=user.id,
    )
    db.commit()
    db.refresh(row)
    return row


def patch_prompt_version(
    db: Session, user, config_id: UUID, version_id: UUID, payload,
) -> PromptVersion:
    """Edit a DRAFT version. Each partial field replaces the existing
    one entirely (modular_prompt is a full 8-section replace, not a
    per-key merge). 409 if the version isn't in draft state."""
    row = get_owned_version(
        db, config_id=config_id, version_id=version_id,
        organization_id=user.organization_id,
    )
    if row.state != "draft":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot edit a version in state '{row.state}'. "
                "Create a new draft (or rollback) instead."
            ),
        )
    if payload.label is not None:
        row.label = payload.label
    if payload.modular_prompt is not None:
        row.modular_prompt_json = (
            payload.modular_prompt.to_modular_prompt().to_dict()
        )
    if payload.variables_schema is not None:
        row.variables_schema_json = [
            v.model_dump() for v in payload.variables_schema
        ]
    if payload.retrieval_config is not None:
        row.retrieval_config_json = payload.retrieval_config.model_dump(
            exclude_none=True,
        )
    if payload.model_cfg is not None:
        row.model_config_json = payload.model_cfg.model_dump(exclude_none=True)
    if payload.tool_permissions is not None:
        row.tool_permissions_json = payload.tool_permissions.model_dump()
    if payload.meta is not None:
        row.meta_json = payload.meta
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    # Phase 8C — refresh template lineage. Fire-and-forget.
    recompute_lineage_for_config(
        db, organization_id=user.organization_id,
        agent_prompt_config_id=row.agent_prompt_config_id,
    )
    return row


def publish_prompt_version(
    db: Session, user, config_id: UUID, version_id: UUID, payload,
) -> PromptVersion:
    """Transition draft → published and set active on the config.

    Side effects: prompt_deployments row appended, agent_config_epochs
    epoch incremented. Raises ``PublishError`` (mapped to HTTP by the
    router) on domain failures.
    """
    # Confirm tenancy + ownership first; service raises domain errors
    # the router maps.
    get_owned_version(
        db, config_id=config_id, version_id=version_id,
        organization_id=user.organization_id,
    )
    row = publish_version(
        db,
        organization_id=user.organization_id,
        version_id=version_id,
        actor_user_id=user.id,
        reason=payload.reason,
    )
    # Phase 8C — refresh template lineage post-publish.
    recompute_lineage_for_config(
        db, organization_id=user.organization_id,
        agent_prompt_config_id=row.agent_prompt_config_id,
    )
    return row


def rollback_prompt_config(
    db: Session, user, config_id: UUID, payload,
) -> PromptVersion:
    """Re-point the config's active_version at a prior PUBLISHED
    version. The previously-active version stays published — rollback
    is reversible. Raises ``PublishError`` (mapped by the router)."""
    get_owned_config(
        db, config_id=config_id, organization_id=user.organization_id,
    )
    return rollback_to_version(
        db,
        organization_id=user.organization_id,
        agent_prompt_config_id=config_id,
        to_version_id=payload.to_version_id,
        actor_user_id=user.id,
        reason=payload.reason,
    )


def archive_prompt_version(
    db: Session, user, config_id: UUID, version_id: UUID,
) -> PromptVersion:
    """Archive a version. Refused if it's currently the active
    version on its config — rollback first. Raises ``PublishError``
    (mapped by the router)."""
    get_owned_version(
        db, config_id=config_id, version_id=version_id,
        organization_id=user.organization_id,
    )
    return archive_version(
        db,
        organization_id=user.organization_id,
        version_id=version_id,
    )


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def diff_prompt_versions(
    db: Session, *, organization_id: UUID, config_id: UUID,
    version_id: UUID, against: UUID,
) -> dict:
    """Diff two versions of the same config. `version_id` is the
    "from" side; `against` is the "to" side. The dashboard typically
    passes (older, newer) so additions render as `+` lines. Both
    versions must belong to the same config and same org."""
    a = get_owned_version(
        db, config_id=config_id, version_id=version_id,
        organization_id=organization_id,
    )
    b = get_owned_version(
        db, config_id=config_id, version_id=against,
        organization_id=organization_id,
    )
    body = _diff_versions(a, b)
    body["from_version_id"] = a.id
    body["to_version_id"] = b.id
    return body


# ---------------------------------------------------------------------------
# Deployment audit
# ---------------------------------------------------------------------------


def list_prompt_deployments(
    db: Session, *, organization_id: UUID, config_id: UUID, limit: int,
) -> List[PromptDeployment]:
    """Deployment history for one config. Newest first.
    `prompt_deployments` is append-only — these rows outlive cascades."""
    get_owned_config(
        db, config_id=config_id, organization_id=organization_id,
    )
    return (
        db.query(PromptDeployment)
        .filter(
            PromptDeployment.organization_id == organization_id,
            PromptDeployment.agent_prompt_config_id == config_id,
        )
        .order_by(desc(PromptDeployment.created_at))
        .limit(limit)
        .all()
    )
