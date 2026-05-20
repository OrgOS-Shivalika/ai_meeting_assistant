"""Phase 8D — the cognition resolver.

ONE function, one purpose:

    resolve_behavior_profile(db, *, organization_id,
                             category_id=None, team_id=None)
        -> ResolvedBehaviorProfile

Merges 5 layers in order (later wins per-field):

    1. Global default                (template_behavior_profiles, scope='global')
    2. Category template default     (linked via workspace_template_links)
    3. Team template default         (linked via workspace_template_links)
    4. Workspace category overrides  (workspace_behavior_overrides, scope='category')
    5. Workspace team overrides      (workspace_behavior_overrides, scope='team')

Returns a fully-resolved BehaviorProfile with all 11 dimensions
populated. Every meeting-time AI call should drive its behavior
from this object — no peeking at lower layers, no manual merging
elsewhere.

Merge semantics per dimension type:

    - dict dimensions (master_prompt, retrieval_config, ...):
        shallow merge — later layer's keys overwrite earlier's;
        keys not present in later pass through from earlier.
        Empty-dict layer ({}) is treated as "no contribution".

    - list dimension (enabled_agents):
        union of all layers (de-duplicated, order-preserving).
        A category profile that adds 'sales-coach' does NOT remove
        the global default's 'action-item-manager'. To explicitly
        disable an inherited agent, set an override with a special
        '!disable' marker (future). For now: union.

This file is the single source of truth for behavior at runtime.
The old Phase 7 resolver remains alive until 8F removes it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import WorkspaceTemplateLink
from app.services.behavior.overrides import (
    BEHAVIOR_DIMENSIONS, get_all_overrides_for_org,
)
from app.services.templates.behavior_registry import (
    get_global_default, get_profile, profile_to_dimensions_dict,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public type — the unified runtime cognition object
# ---------------------------------------------------------------------------


@dataclass
class ResolutionTrace:
    """One layer's contribution to the final merge. The resolver
    returns these for debugging + the Agent Control UI's "where
    did this value come from?" tooltip."""
    layer: str           # 'global' | 'workspace_override' |
                         # 'category_template' | 'team_template' |
                         # 'category_override' | 'team_override'
    source_id: Optional[str] = None  # profile id / link id / None for global
    source_slug: Optional[str] = None
    source_version: Optional[str] = None


@dataclass
class ResolvedBehaviorProfile:
    """The final runtime cognition object. All 11 dimensions are
    populated. Callers (agents, retrieval, output formatters) read
    only this — they never reach back into templates or overrides
    directly."""
    organization_id: UUID
    category_id: Optional[int] = None
    team_id: Optional[int] = None

    master_prompt: dict = field(default_factory=dict)
    enabled_agents: list = field(default_factory=list)
    retrieval_config: dict = field(default_factory=dict)
    memory_config: dict = field(default_factory=dict)
    output_config: dict = field(default_factory=dict)
    extraction_rules: dict = field(default_factory=dict)
    automation_rules: dict = field(default_factory=dict)
    evaluation_rules: dict = field(default_factory=dict)
    tone_and_personality: dict = field(default_factory=dict)
    compliance_and_guardrails: dict = field(default_factory=dict)
    tools_and_integrations: dict = field(default_factory=dict)

    # Audit trail of which layers contributed. Per-dimension is
    # noisy; we record per-layer instead.
    trace: list[ResolutionTrace] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Flat dict shape used by the agent runtime + the HTTP API."""
        out: dict[str, Any] = {
            "organization_id": str(self.organization_id),
            "category_id": self.category_id,
            "team_id": self.team_id,
        }
        for dim in BEHAVIOR_DIMENSIONS:
            out[dim] = getattr(self, dim)
        out["trace"] = [
            {
                "layer": t.layer,
                "source_id": t.source_id,
                "source_slug": t.source_slug,
                "source_version": t.source_version,
            }
            for t in self.trace
        ]
        return out


# ---------------------------------------------------------------------------
# Merge primitives
# ---------------------------------------------------------------------------


def _merge_dict(base: dict, overlay: dict) -> dict:
    """Shallow merge: later wins per-key. Empty overlay returns base
    unchanged. Both inputs are treated immutably; returns a new dict."""
    if not overlay:
        return dict(base)
    out = dict(base)
    for k, v in overlay.items():
        out[k] = v
    return out


def _merge_list_union(base: list, overlay: list) -> list:
    """Order-preserving de-duplicated union. Used only for
    enabled_agents. The empty overlay returns base unchanged."""
    if not overlay:
        return list(base)
    seen = set()
    out: list = []
    for v in list(base) + list(overlay):
        # Hashable check — agents are strings today, but be defensive.
        key = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _apply_layer(
    profile: ResolvedBehaviorProfile, layer_data: dict[str, Any],
) -> None:
    """In-place merge of one layer's dimensions onto the profile.
    Mutates the profile."""
    for dim in BEHAVIOR_DIMENSIONS:
        if dim not in layer_data:
            continue
        existing = getattr(profile, dim)
        incoming = layer_data[dim]
        if dim == "enabled_agents":
            merged = _merge_list_union(existing or [], incoming or [])
        else:
            merged = _merge_dict(existing or {}, incoming or {})
        setattr(profile, dim, merged)


# ---------------------------------------------------------------------------
# Layer loaders
# ---------------------------------------------------------------------------


def _load_global_layer(db: Session) -> Optional[dict[str, Any]]:
    """Layer 1 — the platform default. Returns the dimensions dict +
    a trace entry built outside this fn."""
    glob = get_global_default(db)
    if glob is None:
        return None
    return {
        "dimensions": profile_to_dimensions_dict(glob),
        "trace": ResolutionTrace(
            layer="global", source_id=str(glob.id),
            source_slug=glob.slug, source_version=glob.version,
        ),
    }


def _load_template_layer(
    db: Session,
    *,
    organization_id: UUID,
    entity_id_int: int,
    layer_name: str,
) -> Optional[dict[str, Any]]:
    """Look up the workspace_template_links row pinning this
    category/team and resolve to a BehaviorProfile. Returns None if
    the scope has no link.

    layer_name == 'category_template' → look up entity_type='category'
                                        (workspace row is a categories.id)
    layer_name == 'team_template'     → look up entity_type='team'
                                        (workspace row is a teams.id)
    """
    entity_type = "team" if layer_name == "team_template" else "category"
    link = (
        db.query(WorkspaceTemplateLink)
        .filter(
            WorkspaceTemplateLink.organization_id == organization_id,
            WorkspaceTemplateLink.entity_id_int == entity_id_int,
            WorkspaceTemplateLink.entity_type == entity_type,
        )
        .order_by(WorkspaceTemplateLink.provisioned_at.desc())
        .first()
    )
    if link is None:
        return None
    # source_template_kind tells us which scope_kind to query.
    scope_kind = link.source_template_kind  # 'category' or 'team'
    if scope_kind not in ("category", "team"):
        return None
    prof = get_profile(
        db, scope_kind=scope_kind,
        slug=link.source_template_slug,
        version=link.source_template_version,
    )
    if prof is None:
        return None
    return {
        "dimensions": profile_to_dimensions_dict(prof),
        "trace": ResolutionTrace(
            layer=layer_name, source_id=str(prof.id),
            source_slug=prof.slug, source_version=prof.version,
        ),
    }


def _load_override_layer(
    overrides_by_scope: dict, *, scope_type: str,
    scope_id: Optional[int], layer_name: str,
) -> Optional[dict[str, Any]]:
    """Pull pre-loaded overrides for a (scope_type, scope_id) bucket
    and shape them into a dimensions dict the merger expects.

    `overrides_by_scope` is the output of
    `get_all_overrides_for_org` — single-query batched load.
    """
    bucket = overrides_by_scope.get((scope_type, scope_id))
    if not bucket:
        return None
    # bucket shape: {dimension: {field: value}}
    # Need to convert to layer shape: {dimension: <merged_value>}
    #
    # For dict dimensions with multiple fields: the overlay IS a
    # partial dict to shallow-merge.
    # For enabled_agents (list dimension), field='' carries the
    # whole list; we expose it as the dimension's value.
    layer_dims: dict[str, Any] = {}
    for dim, fields in bucket.items():
        if dim == "enabled_agents":
            # Field-less override carries the whole list.
            if "" in fields:
                layer_dims[dim] = fields[""]
        else:
            # Shallow merge dict — drop empty-field keys.
            shaped: dict[str, Any] = {}
            for fname, value in fields.items():
                if fname == "":
                    # Whole-dimension override: replace.
                    if isinstance(value, dict):
                        shaped.update(value)
                    else:
                        # Non-dict whole-dimension override is weird
                        # for a dict dim; skip to keep the merge clean.
                        logger.warning(
                            "non-dict whole-dim override for %s: %r",
                            dim, value,
                        )
                else:
                    shaped[fname] = value
            layer_dims[dim] = shaped
    if not layer_dims:
        return None
    return {
        "dimensions": layer_dims,
        "trace": ResolutionTrace(
            layer=layer_name, source_id=str(scope_id) if scope_id else None,
        ),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_behavior_profile(
    db: Session,
    *,
    organization_id: UUID,
    category_id: Optional[int] = None,
    team_id: Optional[int] = None,
) -> ResolvedBehaviorProfile:
    """Compose the runtime BehaviorProfile for a (org, category?, team?)
    context. Never raises. Missing layers contribute nothing.

    Order:
      1. global default
      2. category template (via link from categories.id)
      3. team template (via link from team's categories.id)
      4. category overrides (scope='category', scope_id=category_id)
      5. team overrides (scope='team', scope_id=team_id)
    """
    profile = ResolvedBehaviorProfile(
        organization_id=organization_id,
        category_id=category_id,
        team_id=team_id,
    )

    # Pre-load all of the org's overrides in one query — saves N
    # round-trips per dimension.
    overrides_by_scope = get_all_overrides_for_org(
        db, organization_id=organization_id,
    )

    # Layer 1 — global default.
    layer = _load_global_layer(db)
    if layer is not None:
        _apply_layer(profile, layer["dimensions"])
        profile.trace.append(layer["trace"])
    else:
        logger.warning(
            "no global default profile found for org=%s — "
            "ResolvedBehaviorProfile will be sparse",
            organization_id,
        )

    # Layer 1.5 — workspace-scope overrides ("Workspace Defaults").
    # Workspace policy applies to every resolution regardless of which
    # category/team the meeting is in. Lives between global and the
    # per-scope template layers so categories can still override
    # workspace policy where the user explicitly sets a category-level
    # value, but unset category fields pick up workspace defaults.
    layer = _load_override_layer(
        overrides_by_scope, scope_type="workspace",
        scope_id=None, layer_name="workspace_override",
    )
    if layer is not None:
        _apply_layer(profile, layer["dimensions"])
        profile.trace.append(layer["trace"])

    # Layer 2 — category template.
    if category_id is not None:
        layer = _load_template_layer(
            db, organization_id=organization_id,
            entity_id_int=category_id, layer_name="category_template",
        )
        if layer is not None:
            _apply_layer(profile, layer["dimensions"])
            profile.trace.append(layer["trace"])

    # Layer 3 — team template.
    if team_id is not None:
        layer = _load_template_layer(
            db, organization_id=organization_id,
            entity_id_int=team_id, layer_name="team_template",
        )
        if layer is not None:
            _apply_layer(profile, layer["dimensions"])
            profile.trace.append(layer["trace"])

    # Layer 4 — category overrides.
    if category_id is not None:
        layer = _load_override_layer(
            overrides_by_scope, scope_type="category",
            scope_id=category_id, layer_name="category_override",
        )
        if layer is not None:
            _apply_layer(profile, layer["dimensions"])
            profile.trace.append(layer["trace"])

    # Layer 5 — team overrides.
    if team_id is not None:
        layer = _load_override_layer(
            overrides_by_scope, scope_type="team",
            scope_id=team_id, layer_name="team_override",
        )
        if layer is not None:
            _apply_layer(profile, layer["dimensions"])
            profile.trace.append(layer["trace"])

    return profile
