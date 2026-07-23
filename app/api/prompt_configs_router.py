"""Phase 7A — Agent Control Dashboard: scoped binding (prompt_configs) CRUD.

Endpoints:

  GET    /prompt-configs                    — list bindings (filterable)
  GET    /prompt-configs/{id}               — single binding
  POST   /prompt-configs                    — create a binding shell
  POST   /prompt-configs/{id}/archive       — soft-archive

Versioning endpoints (POST /prompt-configs/{id}/versions, publish,
rollback, diff) land in Phase 7B once `prompt_versions` exists.

Scope validation mirrors the DB CHECK exactly:
  - organization scope → scope_id MUST be null
  - category/team scope → scope_id MUST be set + must reference a row
    that belongs to the same organization
  - meeting_specific → rejected at the API (reserved for Phase 8) even
    though the column space is reserved
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.dependencies.auth import get_current_user
from app.schemas.agent_api_schema import (
    AgentPromptConfigCreateRequest, AgentPromptConfigResponse,
    PromptConfigRollbackRequest, PromptDeploymentResponse,
    PromptVersionCreateRequest, PromptVersionPatchRequest,
    PromptVersionPublishRequest, PromptVersionResponse,
    PromptVersionSummary, VersionDiffResponse,
)
from app.services import prompt_config_service
from app.services.agents.publish import PublishError
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/prompt-configs", tags=["Prompt Configs"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _publish_error_to_http(exc: PublishError) -> HTTPException:
    """Map service-layer publish errors to HTTPException. Keeps the
    router layer thin — the service raises domain errors, the router
    translates."""
    return HTTPException(status_code=exc.http_status, detail=str(exc))


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=List[AgentPromptConfigResponse])
def list_prompt_configs(
    agent_profile_id: Optional[UUID] = Query(default=None),
    scope_type: Optional[str] = Query(
        default=None, regex="^(organization|category|team|meeting_specific)$",
    ),
    status: Optional[str] = Query(default=None, regex="^(active|archived)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List prompt-config bindings for the user's org. Filterable by
    agent_profile, scope_type, status. Default returns active bindings,
    newest first."""
    return prompt_config_service.list_prompt_configs(
        db, organization_id=user.organization_id,
        agent_profile_id=agent_profile_id, scope_type=scope_type,
        status=status, limit=limit,
    )


@router.get("/{config_id}", response_model=AgentPromptConfigResponse)
def get_prompt_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.get_owned_config(
        db, config_id=config_id, organization_id=user.organization_id,
    )


# ---------------------------------------------------------------------------
# Write endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=AgentPromptConfigResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_prompt_config(
    payload: AgentPromptConfigCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.create_prompt_config(db, user, payload)


@router.post(
    "/{config_id}/archive",
    response_model=AgentPromptConfigResponse,
)
def archive_prompt_config(
    config_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.archive_prompt_config(db, user, config_id)


# ===========================================================================
# Phase 7B — Prompt versions
#
# All endpoints below are nested under /prompt-configs/{config_id}/...
# The config_id is validated for tenancy on every request via
# `get_owned_config`. Versions inherit the config's tenancy.
# ===========================================================================


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get(
    "/{config_id}/versions",
    response_model=List[PromptVersionSummary],
)
def list_prompt_versions(
    config_id: UUID,
    state: Optional[str] = Query(
        default=None, regex="^(draft|published|archived)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List versions for a config, newest version_number first.
    Filterable by state. Returns slim summaries — fetch one to read
    body."""
    return prompt_config_service.list_prompt_versions(
        db, organization_id=user.organization_id, config_id=config_id,
        state=state, limit=limit,
    )


@router.get(
    "/{config_id}/versions/{version_id}",
    response_model=PromptVersionResponse,
)
def get_prompt_version(
    config_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.get_owned_version(
        db, config_id=config_id, version_id=version_id,
        organization_id=user.organization_id,
    )


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

@router.post(
    "/{config_id}/versions",
    response_model=PromptVersionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def create_prompt_version(
    config_id: UUID,
    payload: PromptVersionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.create_prompt_version(
        db, user, config_id, payload,
    )


@router.patch(
    "/{config_id}/versions/{version_id}",
    response_model=PromptVersionResponse,
)
def patch_prompt_version(
    config_id: UUID,
    version_id: UUID,
    payload: PromptVersionPatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return prompt_config_service.patch_prompt_version(
        db, user, config_id, version_id, payload,
    )


@router.post(
    "/{config_id}/versions/{version_id}/publish",
    response_model=PromptVersionResponse,
)
def publish_prompt_version(
    config_id: UUID,
    version_id: UUID,
    payload: PromptVersionPublishRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return prompt_config_service.publish_prompt_version(
            db, user, config_id, version_id, payload,
        )
    except PublishError as exc:
        raise _publish_error_to_http(exc) from exc


@router.post(
    "/{config_id}/rollback",
    response_model=PromptVersionResponse,
)
def rollback_prompt_config(
    config_id: UUID,
    payload: PromptConfigRollbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return prompt_config_service.rollback_prompt_config(
            db, user, config_id, payload,
        )
    except PublishError as exc:
        raise _publish_error_to_http(exc) from exc


@router.post(
    "/{config_id}/versions/{version_id}/archive",
    response_model=PromptVersionResponse,
)
def archive_prompt_version(
    config_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return prompt_config_service.archive_prompt_version(
            db, user, config_id, version_id,
        )
    except PublishError as exc:
        raise _publish_error_to_http(exc) from exc


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

@router.get(
    "/{config_id}/versions/{version_id}/diff",
    response_model=VersionDiffResponse,
)
def diff_prompt_versions(
    config_id: UUID,
    version_id: UUID,
    against: UUID = Query(..., description="The other version_id to diff against."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Diff two versions of the same config. `version_id` is the
    "from" side; `against` (query param) is the "to" side. The dashboard
    typically passes (older, newer) so additions render as `+` lines.
    Both versions must belong to the same config and same org."""
    return prompt_config_service.diff_prompt_versions(
        db, organization_id=user.organization_id, config_id=config_id,
        version_id=version_id, against=against,
    )


# ---------------------------------------------------------------------------
# Deployment audit
# ---------------------------------------------------------------------------

@router.get(
    "/{config_id}/deployments",
    response_model=List[PromptDeploymentResponse],
)
def list_prompt_deployments(
    config_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deployment history for one config. Newest first.
    `prompt_deployments` is append-only — these rows outlive cascades."""
    return prompt_config_service.list_prompt_deployments(
        db, organization_id=user.organization_id, config_id=config_id,
        limit=limit,
    )
