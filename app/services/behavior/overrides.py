"""Phase 8C — sparse BehaviorProfile overrides.

CRUD on `workspace_behavior_overrides`. A workspace stores zero or
more override rows per scope; the runtime resolver (8D) merges them
on top of catalog defaults.

Sparse contract: zero rows = workspace uses defaults. Setting an
override is upsert (idempotent). Deleting an override re-exposes
the default underneath.

This file is small on purpose. The override layer is the entire
substitute for the old clone-and-diff architecture; complexity lives
in the resolver (where layering is interesting), not here.

Public API:

    BEHAVIOR_DIMENSIONS                # the 11 canonical dimensions
    is_valid_dimension(dim) -> bool

    get_overrides_for_scope(db, *, organization_id,
                            scope_type, scope_id=None)
        -> dict[dimension, dict[field, value]]

    set_override(db, *, organization_id, scope_type, dimension,
                 field, value, scope_id=None,
                 workspace_template_link_id=None,
                 actor_user_id=None)
        -> WorkspaceBehaviorOverride

    delete_override(db, *, organization_id, scope_type, dimension,
                    field, scope_id=None) -> bool

    delete_all_overrides_for_scope(db, *, organization_id,
                                   scope_type, scope_id=None) -> int

    count_overrides_for_link(db, *, link_id) -> int
    count_overrides_for_scope(db, *, organization_id,
                              scope_type, scope_id=None) -> int
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func as sa_func
from sqlalchemy.orm import Session

from app.db.models import WorkspaceBehaviorOverride

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The 11 BehaviorProfile dimensions — the canonical AI cognition object.
# Mirrored exactly in the migration's CHECK constraint.
# ---------------------------------------------------------------------------

BEHAVIOR_DIMENSIONS: tuple[str, ...] = (
    "master_prompt",
    "enabled_agents",
    "retrieval_config",
    "memory_config",
    "output_config",
    "extraction_rules",
    "automation_rules",
    "evaluation_rules",
    "tone_and_personality",
    "compliance_and_guardrails",
    "tools_and_integrations",
    "intent",
)

# Scope types — same as the migration CHECK.
SCOPE_TYPES: tuple[str, ...] = ("workspace", "category", "team")


def is_valid_dimension(dimension: str) -> bool:
    return dimension in BEHAVIOR_DIMENSIONS


def is_valid_scope_type(scope_type: str) -> bool:
    return scope_type in SCOPE_TYPES


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OverrideError(ValueError):
    """Raised on contract violations (bogus dimension, malformed
    scope shape, etc.). HTTP routers can map to 400."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate(scope_type: str, scope_id: Optional[int], dimension: str) -> None:
    """Single validation pass — keeps the public API ergonomic."""
    if not is_valid_dimension(dimension):
        raise OverrideError(
            f"unknown dimension {dimension!r}; "
            f"valid: {BEHAVIOR_DIMENSIONS}"
        )
    if not is_valid_scope_type(scope_type):
        raise OverrideError(
            f"unknown scope_type {scope_type!r}; valid: {SCOPE_TYPES}"
        )
    if scope_type == "workspace":
        if scope_id is not None:
            raise OverrideError(
                "scope_type='workspace' requires scope_id=None",
            )
    else:  # category | team
        if scope_id is None:
            raise OverrideError(
                f"scope_type={scope_type!r} requires scope_id (int)",
            )


def _scope_filter(scope_type: str, scope_id: Optional[int]):
    """Return the SQLAlchemy filter clauses for a scope lookup.
    Validated; pass scope_id=None only for workspace scope."""
    clauses = [WorkspaceBehaviorOverride.scope_type == scope_type]
    if scope_type == "workspace":
        clauses.append(WorkspaceBehaviorOverride.scope_id_int.is_(None))
        clauses.append(WorkspaceBehaviorOverride.scope_id_uuid.is_(None))
    else:
        clauses.append(WorkspaceBehaviorOverride.scope_id_int == scope_id)
    return clauses


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_overrides_for_scope(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> dict[str, dict[str, Any]]:
    """Return `{dimension: {field: value}}` for one scope. Sparse:
    only dimensions/fields that have actual rows appear. Used by
    the resolver to overlay this scope's deltas on top of lower
    layers."""
    _validate(scope_type, scope_id, "master_prompt")  # dimension irrelevant here

    rows = (
        db.query(WorkspaceBehaviorOverride)
        .filter(
            WorkspaceBehaviorOverride.organization_id == organization_id,
            *_scope_filter(scope_type, scope_id),
        )
        .all()
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out.setdefault(r.dimension, {})[r.field or ""] = r.value_json
    return out


def get_all_overrides_for_org(
    db: Session, *, organization_id: UUID,
) -> dict[tuple[str, Optional[int]], dict[str, dict[str, Any]]]:
    """Return `{(scope_type, scope_id): {dimension: {field: value}}}`
    for one org, single query. Used by the resolver to load every
    relevant layer in one trip when resolving a meeting context."""
    rows = (
        db.query(WorkspaceBehaviorOverride)
        .filter(WorkspaceBehaviorOverride.organization_id == organization_id)
        .all()
    )
    out: dict[tuple[str, Optional[int]], dict[str, dict[str, Any]]] = {}
    for r in rows:
        scope_id: Optional[int] = (
            None if r.scope_type == "workspace" else r.scope_id_int
        )
        bucket = out.setdefault((r.scope_type, scope_id), {})
        bucket.setdefault(r.dimension, {})[r.field or ""] = r.value_json
    return out


def count_overrides_for_link(db: Session, *, link_id: int) -> int:
    """Drift metric: how many overrides exist under this template link.
    Replaces the old 4-state lineage machine — UI shows the number
    directly ("3 overrides") instead of a categorical state."""
    return (
        db.query(sa_func.count(WorkspaceBehaviorOverride.id))
        .filter(WorkspaceBehaviorOverride.workspace_template_link_id == link_id)
        .scalar()
    ) or 0


def count_overrides_for_scope(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> int:
    _validate(scope_type, scope_id, "master_prompt")
    return (
        db.query(sa_func.count(WorkspaceBehaviorOverride.id))
        .filter(
            WorkspaceBehaviorOverride.organization_id == organization_id,
            *_scope_filter(scope_type, scope_id),
        )
        .scalar()
    ) or 0


# ---------------------------------------------------------------------------
# Writes — upsert + delete
# ---------------------------------------------------------------------------


def set_override(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    dimension: str,
    field: str,
    value: Any,
    scope_id: Optional[int] = None,
    workspace_template_link_id: Optional[int] = None,
    actor_user_id: Optional[UUID] = None,
) -> WorkspaceBehaviorOverride:
    """Upsert. (org, scope, dimension, field) is the natural key.
    If a row already exists, updates its value + updated_at. If not,
    inserts. Returns the live row.

    `field` may be the empty string for whole-dimension overrides
    (e.g. enabled_agents = ['planner', 'extractor'] — no sub-field).
    """
    _validate(scope_type, scope_id, dimension)
    field = field or ""

    existing = (
        db.query(WorkspaceBehaviorOverride)
        .filter(
            WorkspaceBehaviorOverride.organization_id == organization_id,
            WorkspaceBehaviorOverride.dimension == dimension,
            WorkspaceBehaviorOverride.field == field,
            *_scope_filter(scope_type, scope_id),
        )
        .first()
    )
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.value_json = value
        existing.updated_at = now
        # Don't change created_by_user_id; track only the most recent
        # author via updated_at + a future audit table if needed.
        db.commit()
        db.refresh(existing)
        return existing

    row = WorkspaceBehaviorOverride(
        organization_id=organization_id,
        workspace_template_link_id=workspace_template_link_id,
        scope_type=scope_type,
        scope_id_int=scope_id if scope_type != "workspace" else None,
        scope_id_uuid=None,
        dimension=dimension,
        field=field,
        value_json=value,
        created_by_user_id=actor_user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_override(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    dimension: str,
    field: str,
    scope_id: Optional[int] = None,
) -> bool:
    """Remove a single override row. Returns True if a row was
    deleted, False if no matching row existed (idempotent)."""
    _validate(scope_type, scope_id, dimension)
    field = field or ""

    row = (
        db.query(WorkspaceBehaviorOverride)
        .filter(
            WorkspaceBehaviorOverride.organization_id == organization_id,
            WorkspaceBehaviorOverride.dimension == dimension,
            WorkspaceBehaviorOverride.field == field,
            *_scope_filter(scope_type, scope_id),
        )
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def delete_all_overrides_for_scope(
    db: Session,
    *,
    organization_id: UUID,
    scope_type: str,
    scope_id: Optional[int] = None,
) -> int:
    """Reset a scope back to inheriting everything from below.
    Returns count deleted. Equivalent of the old `reset.py` —
    one statement, no version-shuffling, no Phase 7B publish dance."""
    _validate(scope_type, scope_id, "master_prompt")
    n = (
        db.query(WorkspaceBehaviorOverride)
        .filter(
            WorkspaceBehaviorOverride.organization_id == organization_id,
            *_scope_filter(scope_type, scope_id),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(n)
