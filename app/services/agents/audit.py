"""Phase 7E — audit-event writer.

One-liner helper used by the agents + prompt-configs routers to
record non-publish mutations. Fire-and-forget: a write failure logs
a warning but never propagates back to the caller. The
`prompt_deployments` table is the audit surface for publish/rollback;
this is for everything else.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AgentAuditEvent

logger = logging.getLogger(__name__)


_ALLOWED_ENTITY_TYPES = {
    "agent_profile", "agent_prompt_config", "prompt_version",
}
_ALLOWED_ACTIONS = {
    "create", "update", "archive", "unarchive", "duplicate", "delete",
}


def write_event(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: Optional[UUID],
    entity_type: str,
    entity_id: UUID,
    action: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> Optional[int]:
    """Insert one `agent_audit_events` row in its own transaction.
    Returns the new id, or None on failure.

    The caller's main commit must run BEFORE this writer — otherwise
    a failed downstream commit would still leave an audit row
    suggesting the action succeeded. Order: do the work, commit, then
    write the audit row (which is its own transaction so a failure
    here doesn't undo the work).
    """
    if entity_type not in _ALLOWED_ENTITY_TYPES:
        logger.warning(
            "audit: refusing to write unknown entity_type=%s", entity_type,
        )
        return None
    if action not in _ALLOWED_ACTIONS:
        logger.warning(
            "audit: refusing to write unknown action=%s", action,
        )
        return None

    row = AgentAuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_json=before,
        after_json=after,
        metadata_json=metadata or {},
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as exc:
        logger.warning("audit: failed to write event: %s", exc)
        db.rollback()
        return None
