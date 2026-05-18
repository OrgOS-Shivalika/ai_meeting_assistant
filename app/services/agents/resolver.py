"""Phase 7C — the hierarchical runtime configuration resolver.

The single public entry point used by every LLM-driven service that
becomes overridable in 7D:

  resolve_agent_runtime_config(
      db, *, organization_id, agent_type, ...,
  ) -> ResolvedAgentConfig

Never raises. On total failure (no profile, no configs, no
filesystem floor) returns a `ResolvedAgentConfig` with
`is_default_fallback=True` and an empty modular prompt — same
defensive posture as `query_planner._default_plan`.

Resolution precedence (lower index wins; higher layers fill missing
keys from lower layers):

  1. meeting_specific override   (Phase 8 — relaxed CHECK, no row today)
  2. team override               (scope_type='team', scope_id=team_id)
  3. category override           (scope_type='category', scope_id=category_id)
  4. organization override       (scope_type='organization', scope_id NULL)
  5. global default              (organization-scoped row in the sentinel
                                  platform-owner org — opt-in, NULL today)
  6. filesystem fallback         (load_planner_prompt / load_synth_prompt)

Implementation notes:

  - Caching: in-process LRU + epoch check. See `cache.py` for the
    transport; the resolver owns the policy. Cache key includes every
    input that affects the result.

  - DB read: one indexed query returns all applicable rows, sorted by
    priority. Merge in Python — cheap, easy to test.

  - Composition: NOT done here. The resolver returns the merged
    `modular_prompts` dict; the synthesizer (in 7D) calls
    `composition.compose_system_message` with the runtime variables.

  - Shadow mode: setting `AGENT_RESOLVER_SHADOW_MODE=true` is a
    SETTING-LEVEL flag, not a resolver-level one — the resolver
    always runs the same. Callers decide whether to *use* the result.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.ai_agents.prompts.rag import (
    load_planner_prompt, load_synth_prompt,
)
from app.config.settings import settings
from app.db.models import (
    AgentConfigEpoch, AgentProfile, AgentPromptConfig, PromptVersion,
)
from app.schemas.agent_schema import (
    ModelConfig, ModularPrompt, RetrievalConfig, ToolPermissions,
)
from app.services.agents.cache import resolver_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ResolutionStep:
    """One entry in the resolution audit trail. Recorded for every
    layer that contributed to the final bundle."""
    layer: str           # 'filesystem' | 'organization' | 'category' | 'team'
    scope_type: Optional[str] = None
    scope_id: Optional[int] = None
    prompt_version_id: Optional[str] = None
    version_number: Optional[int] = None
    fields_contributed: list[str] = field(default_factory=list)


@dataclass
class ResolvedAgentConfig:
    """The merged runtime configuration. Mutable dataclass — easy to
    serialize, easy to introspect in tests."""
    agent_profile_id: Optional[UUID]
    agent_type: str
    prompt_version_id: Optional[UUID]
    version_number: Optional[int]
    label: Optional[str]

    modular_prompts: dict[str, str]
    variables_used: list[str]
    retrieval_config: RetrievalConfig
    model_config: ModelConfig
    tool_permissions: ToolPermissions

    resolution_path: list[ResolutionStep]
    config_hash: str
    is_default_fallback: bool
    warnings: list[str] = field(default_factory=list)

    def to_observability_dict(self) -> dict:
        """Compact dict for the runtime-log row. Drops the bulky
        modular_prompts; the log records *which* version produced the
        config (via prompt_version_id) so the body can be re-fetched
        on demand."""
        return {
            "agent_profile_id": str(self.agent_profile_id) if self.agent_profile_id else None,
            "prompt_version_id": str(self.prompt_version_id) if self.prompt_version_id else None,
            "version_number": self.version_number,
            "label": self.label,
            "retrieval_config": asdict(self.retrieval_config),
            "model_config": asdict(self.model_config),
            "tool_permissions": asdict(self.tool_permissions),
            "resolution_path": [asdict(s) for s in self.resolution_path],
            "config_hash": self.config_hash,
            "is_default_fallback": self.is_default_fallback,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Filesystem floor — Layer 6
#
# Loads the existing filesystem prompts so 7D's flip-the-switch
# behavior on an un-seeded org matches today's exactly. Failure to
# load (missing version file, IO error) produces an empty floor + a
# warning; the resolver never raises.
# ---------------------------------------------------------------------------


def _split_at_context_marker(text: str) -> str:
    """The filesystem v1 prompts (synth + planner) put their LLM-input
    contract — context blocks, question, scope params — AFTER a
    `=== CONTEXT ===`-style marker. The pre-marker block is the
    "system content" that becomes the prompt's behavior+rules. Phase 7D
    keeps the LLM contract (post-marker) as a per-agent-type user-
    message template owned by the consuming service, and feeds the
    pre-marker content through the modular `system` section.

    Returns just the pre-marker text, with trailing whitespace stripped.
    If the marker isn't present, returns the input unchanged.

    The synth's v1.txt uses `=== CONTEXT ===`; the planner's uses
    `USER CONTEXT`. Both start a line. We split at the first match of
    either to be tolerant of future variations.
    """
    for marker in ("=== CONTEXT ===", "USER CONTEXT", "QUESTION\n"):
        idx = text.find(marker)
        if idx >= 0:
            return text[:idx].rstrip()
    return text.rstrip()


def _to_double_brace_vars(text: str) -> str:
    """Convert filesystem single-brace placeholders to the composer's
    `{{var}}` syntax. Only converts known variable names — leaves
    arbitrary `{...}` text (e.g. JSON-schema-shaped braces in the
    planner prompt) intact.

    Known variables on the filesystem prompts today:
      synth:   {org_name}, {context_blocks}, {query_text}
      planner: {org_name}, {requested_scope_type}, {requested_scope_id},
               {query_text}

    `{context_blocks}` and `{query_text}` belong to the post-marker
    user-message template — they shouldn't appear in pre-marker text.
    We still defensively convert them so a misformatted prompt
    doesn't blow up at composition time.
    """
    for name in (
        "org_name", "requested_scope_type", "requested_scope_id",
        "context_blocks", "query_text",
    ):
        text = text.replace("{" + name + "}", "{{" + name + "}}")
    return text


def _filesystem_floor(agent_type: str) -> tuple[dict[str, str], list[str]]:
    """Return `(modular_prompts, warnings)` for the floor tier.

    Splits the filesystem v1 prompt at its LLM-input marker so the
    composer can produce an output that, combined with the per-agent
    user-message template (owned by the synth/planner), reconstructs
    the exact prompt today's code sends.

    Single-brace `{var}` placeholders are converted to the composer's
    `{{var}}` syntax so variable interpolation works the same as the
    legacy `.replace()` path.
    """
    warnings: list[str] = []
    try:
        if agent_type == "rag_synth":
            txt = load_synth_prompt(settings.RAG_SYNTH_PROMPT_VERSION)
            pre = _split_at_context_marker(txt)
            return {"system": _to_double_brace_vars(pre)}, warnings
        if agent_type == "rag_planner":
            txt = load_planner_prompt(settings.RAG_PLANNER_PROMPT_VERSION)
            pre = _split_at_context_marker(txt)
            return {"system": _to_double_brace_vars(pre)}, warnings
    except Exception as exc:
        warnings.append(f"filesystem_floor_load_failed:{exc}")
    # Other agent_types have no filesystem fallback today.
    return {}, warnings


# ---------------------------------------------------------------------------
# DB layer query
# ---------------------------------------------------------------------------


def _fetch_db_layers(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: UUID,
    team_id: Optional[int],
    category_id: Optional[int],
) -> list[dict]:
    """Single indexed query — returns at most three rows (one per scope
    layer present), ordered by ascending priority (org → category →
    team → meeting). Merge consumer iterates and overlays.

    Index used: `ix_agent_prompt_configs_resolution` from the 7A
    migration. Plan §6.6.
    """
    rows = db.execute(
        select(
            AgentPromptConfig.id.label("config_id"),
            AgentPromptConfig.scope_type,
            AgentPromptConfig.scope_id,
            PromptVersion.id.label("version_id"),
            PromptVersion.version_number,
            PromptVersion.label,
            PromptVersion.modular_prompt_json,
            PromptVersion.retrieval_config_json,
            PromptVersion.model_config_json,
            PromptVersion.tool_permissions_json,
            PromptVersion.variables_schema_json,
        )
        .join(PromptVersion, PromptVersion.id == AgentPromptConfig.active_version_id)
        .where(
            AgentPromptConfig.organization_id == organization_id,
            AgentPromptConfig.agent_profile_id == agent_profile_id,
            AgentPromptConfig.status == "active",
            PromptVersion.state == "published",
        )
    ).all()

    # Filter applicability + assign priority. We do this in Python
    # rather than in SQL CASE so a future scope type doesn't force a
    # query rewrite. The query already narrowed to org+profile, so
    # there are ≤ ~10 rows in practice.
    out: list[dict] = []
    for r in rows:
        priority: Optional[int] = None
        if r.scope_type == "organization" and r.scope_id is None:
            priority = 4
        elif r.scope_type == "category" and category_id is not None and r.scope_id == category_id:
            priority = 3
        elif r.scope_type == "team" and team_id is not None and r.scope_id == team_id:
            priority = 2
        # 'meeting_specific' is Phase 8 — skip for now.
        if priority is None:
            continue
        out.append({
            "priority": priority,
            "scope_type": r.scope_type,
            "scope_id": r.scope_id,
            "version_id": r.version_id,
            "version_number": r.version_number,
            "label": r.label,
            "modular_prompt": r.modular_prompt_json or {},
            "retrieval_config": r.retrieval_config_json or {},
            "model_config": r.model_config_json or {},
            "tool_permissions": r.tool_permissions_json or {"allowed": [], "denied": []},
            "variables_schema": r.variables_schema_json or [],
        })
    # Ascending priority — lowest first so the merge applies floor →
    # higher layers in order.
    out.sort(key=lambda x: -x["priority"])  # 4 (org) first, 2 (team) last
    return out


# ---------------------------------------------------------------------------
# Profile resolution (slug → id, with org-scoped lookup)
# ---------------------------------------------------------------------------


def _resolve_profile(
    db: Session,
    *,
    organization_id: UUID,
    agent_type: str,
    agent_profile_id: Optional[UUID],
    agent_profile_slug: Optional[str],
) -> Optional[AgentProfile]:
    """Find an active profile matching id/slug + agent_type in this
    org. Returns None when:
      - neither `agent_profile_id` nor `agent_profile_slug` is given
        (caller didn't request a specific profile — fall back to
        filesystem); OR
      - the requested profile doesn't exist / is archived / has
        the wrong agent_type (returning the floor is the safe move).

    This is the conservative semantics for 7C shadow mode: the
    resolver only "engages" when the caller explicitly names a
    profile. 7D's seed migration ensures each org has one
    well-known profile per agent_type; callers pass its slug.
    """
    if agent_profile_id is None and agent_profile_slug is None:
        return None
    q = db.query(AgentProfile).filter(
        AgentProfile.organization_id == organization_id,
        AgentProfile.agent_type == agent_type,
        AgentProfile.status == "active",
    )
    if agent_profile_id is not None:
        q = q.filter(AgentProfile.id == agent_profile_id)
    if agent_profile_slug is not None:
        q = q.filter(AgentProfile.slug == agent_profile_slug)
    return q.order_by(AgentProfile.created_at.desc()).first()


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------


def _merge_modular(
    floor: dict[str, str], layers: list[dict],
    path: list[ResolutionStep],
) -> dict[str, str]:
    """Apply layers in priority order. A layer overrides a section
    only when its value is non-empty — an explicit empty string IS
    treated as "clear at this scope" (the admin can opt to blank a
    section). For 7C/7D simplicity: any non-None entry from the
    layer replaces the floor's value for that key, even empty
    strings. The composer skips empty sections at render time, so
    this acts as a "clear" in practice.

    `path` is appended in place — one entry per layer present in the
    DB, whether or not its content differs from the floor.
    `fields_contributed` is the list of keys whose value actually
    changed (so admins can see "this layer ran but didn't override
    anything" as an empty `fields_contributed`).
    """
    result: dict[str, str] = dict(floor or {})
    for layer in layers:
        contributed: list[str] = []
        mp = layer["modular_prompt"] or {}
        for k in ModularPrompt.section_keys():
            if k in mp:
                v = mp[k]
                if v is None:
                    continue
                # Allow empty string as an explicit override (clears
                # the inherited section).
                if v != result.get(k, ""):
                    result[k] = v
                    contributed.append(k)
        # Always record the layer's presence — even when nothing
        # changed. The admin needs to see "this org-level config IS
        # active; it happens to match floor" vs "no DB config at all".
        path.append(ResolutionStep(
            layer=layer["scope_type"],
            scope_type=layer["scope_type"],
            scope_id=layer["scope_id"],
            prompt_version_id=str(layer["version_id"]),
            version_number=layer["version_number"],
            fields_contributed=contributed,
        ))
    return result


def _merge_retrieval(layers: list[dict]) -> RetrievalConfig:
    """Higher-priority layer's explicit value wins. None means "not
    set at this layer; defer to lower priority"."""
    rc = RetrievalConfig()
    rc_keys = (
        "top_k_vector", "top_k_final", "max_graph_depth",
        "tier_widen_threshold", "rerank_strategy", "sources_filter",
        "include_archived", "citation_strictness",
        "entity_expansion_enabled", "embedding_model",
    )
    for layer in layers:
        cfg = layer["retrieval_config"] or {}
        for k in rc_keys:
            v = cfg.get(k)
            if v is not None:
                setattr(rc, k, v)
        weights = cfg.get("importance_weight_overrides") or {}
        if weights:
            # Per-key dict merge — higher priority wins per key.
            merged = dict(rc.importance_weight_overrides)
            for wk, wv in weights.items():
                if wv is not None:
                    merged[wk] = wv
            rc.importance_weight_overrides = merged
    return rc


def _merge_model_config(layers: list[dict]) -> ModelConfig:
    mc = ModelConfig()
    mc_keys = ("model", "temperature", "max_tokens", "response_format")
    for layer in layers:
        cfg = layer["model_config"] or {}
        for k in mc_keys:
            v = cfg.get(k)
            if v is not None:
                setattr(mc, k, v)
    return mc


def _merge_tool_permissions(layers: list[dict]) -> ToolPermissions:
    """Allowed is union across all layers; denied is also union (a
    tool denied at ANY layer is denied). Plan §6.4."""
    allowed: set[str] = set()
    denied: set[str] = set()
    for layer in layers:
        tp = layer["tool_permissions"] or {}
        allowed |= set(tp.get("allowed") or [])
        denied  |= set(tp.get("denied")  or [])
    return ToolPermissions(allowed=sorted(allowed), denied=sorted(denied))


# ---------------------------------------------------------------------------
# Config hash
# ---------------------------------------------------------------------------


def _canonical_hash(
    modular_prompts: dict[str, str],
    retrieval_config: RetrievalConfig,
    model_config: ModelConfig,
    tool_permissions: ToolPermissions,
) -> str:
    """Deterministic sha256 over the final bundle. Keys sorted so two
    runs that produce structurally-equal configs map to the same hash.
    `agent_runtime_logs.resolved_config_hash` reads this; counting
    distinct hashes per day ≈ counting distinct configs."""
    payload = {
        "modular_prompts": modular_prompts or {},
        "retrieval_config": asdict(retrieval_config),
        "model_config": asdict(model_config),
        "tool_permissions": asdict(tool_permissions),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def _cache_key(
    *,
    organization_id: UUID,
    agent_type: str,
    agent_profile_id: Optional[UUID],
    agent_profile_slug: Optional[str],
    team_id: Optional[int],
    category_id: Optional[int],
) -> tuple:
    """Hashable cache key. Order matters; align with `_read_epoch`
    which keys on (org, profile_id)."""
    return (
        str(organization_id),
        agent_type,
        str(agent_profile_id) if agent_profile_id else None,
        agent_profile_slug,
        team_id,
        category_id,
    )


def _read_epoch(
    db: Session, *, organization_id: UUID, agent_profile_id: UUID,
) -> int:
    """One indexed PK lookup. Returns 0 when the row doesn't exist —
    that's the "never published" case, matches the cache's initial
    snapshot of 0 so the first-ever publish bumps to 1 and invalidates."""
    row = db.execute(
        select(AgentConfigEpoch.epoch).where(
            AgentConfigEpoch.organization_id == organization_id,
            AgentConfigEpoch.agent_profile_id == agent_profile_id,
        )
    ).first()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def resolve_agent_runtime_config(
    db: Session,
    *,
    organization_id: UUID,
    agent_type: str,
    agent_profile_id: Optional[UUID] = None,
    agent_profile_slug: Optional[str] = None,
    team_id: Optional[int] = None,
    category_id: Optional[int] = None,
    current_user_id: Optional[UUID] = None,  # reserved for Phase 8 user scope
) -> ResolvedAgentConfig:
    """Resolve the runtime config for a single agent invocation.

    Never raises. Always returns a `ResolvedAgentConfig`. On total
    failure (no profile, no configs, no filesystem) the result has
    `is_default_fallback=True` and warnings explaining why.

    See plan §6 for the design contract.
    """
    started = time.monotonic()

    # 1. Resolve the profile — needed for cache key + epoch.
    profile = _resolve_profile(
        db,
        organization_id=organization_id,
        agent_type=agent_type,
        agent_profile_id=agent_profile_id,
        agent_profile_slug=agent_profile_slug,
    )

    # 2. Cache lookup. Cache key uses the *resolved* profile id when
    # available so slug + id variants share an entry.
    key = _cache_key(
        organization_id=organization_id,
        agent_type=agent_type,
        agent_profile_id=profile.id if profile else None,
        agent_profile_slug=agent_profile_slug,
        team_id=team_id,
        category_id=category_id,
    )

    if profile is not None:
        live_epoch = _read_epoch(
            db, organization_id=organization_id, agent_profile_id=profile.id,
        )
        cached = resolver_cache.get(key)
        if cached is not None:
            snap_epoch, value = cached
            if snap_epoch >= live_epoch:
                # Stamp cache_hit + duration on the returned copy so
                # the caller's log row reflects "this was served from
                # cache". We don't mutate the cached object — copy
                # what we need.
                value = _copy_with_meta(
                    value, cache_hit=True,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                return value

        # Cache miss — serialize on the per-key lock so concurrent
        # misses on the same key don't all hammer the DB.
        with resolver_cache.locked(key):
            # Double-check after acquiring the lock.
            cached = resolver_cache.get(key)
            if cached is not None:
                snap_epoch, value = cached
                if snap_epoch >= live_epoch:
                    value = _copy_with_meta(
                        value, cache_hit=True,
                        duration_ms=int((time.monotonic() - started) * 1000),
                    )
                    return value

            resolved = _compute(
                db,
                organization_id=organization_id,
                agent_type=agent_type,
                profile=profile,
                team_id=team_id,
                category_id=category_id,
            )
            resolver_cache.put(key, live_epoch, resolved)

            resolved = _copy_with_meta(
                resolved, cache_hit=False,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return resolved

    # No matching profile — pure filesystem floor. Don't cache; the
    # filesystem load is itself cached by the prompts module.
    floor, warnings = _filesystem_floor(agent_type)
    path = [ResolutionStep(
        layer="filesystem",
        fields_contributed=sorted(floor.keys()),
    )] if floor else []
    rc = RetrievalConfig()
    mc = ModelConfig()
    tp = ToolPermissions()
    return ResolvedAgentConfig(
        agent_profile_id=None,
        agent_type=agent_type,
        prompt_version_id=None,
        version_number=None,
        label=None,
        modular_prompts=floor,
        variables_used=[],
        retrieval_config=rc,
        model_config=mc,
        tool_permissions=tp,
        resolution_path=path,
        config_hash=_canonical_hash(floor, rc, mc, tp),
        is_default_fallback=True,
        warnings=warnings + [
            "no_agent_profile_matched" if agent_profile_id or agent_profile_slug
            else "no_agent_profile_lookup",
        ],
    )


def _compute(
    db: Session,
    *,
    organization_id: UUID,
    agent_type: str,
    profile: AgentProfile,
    team_id: Optional[int],
    category_id: Optional[int],
) -> ResolvedAgentConfig:
    """Cache-miss path. Pure function of (db state, inputs)."""
    floor, warnings = _filesystem_floor(agent_type)
    path: list[ResolutionStep] = []
    if floor:
        path.append(ResolutionStep(
            layer="filesystem",
            fields_contributed=sorted(floor.keys()),
        ))

    layers = _fetch_db_layers(
        db,
        organization_id=organization_id,
        agent_profile_id=profile.id,
        team_id=team_id,
        category_id=category_id,
    )

    merged_modular = _merge_modular(floor, layers, path)
    retrieval_config = _merge_retrieval(layers)
    model_config = _merge_model_config(layers)
    tool_permissions = _merge_tool_permissions(layers)

    # The "active" version_id stamped on the result is the
    # HIGHEST-priority layer's version_id (the one that "won" the
    # composition). If no DB layer applied, it stays None — the
    # filesystem floor isn't a version.
    top_version_id: Optional[UUID] = None
    top_version_number: Optional[int] = None
    top_label: Optional[str] = None
    if layers:
        top = layers[-1]  # last in ascending-priority order = highest
        top_version_id = top["version_id"]
        top_version_number = top["version_number"]
        top_label = top["label"]

    config_hash = _canonical_hash(
        merged_modular, retrieval_config, model_config, tool_permissions,
    )

    return ResolvedAgentConfig(
        agent_profile_id=profile.id,
        agent_type=agent_type,
        prompt_version_id=top_version_id,
        version_number=top_version_number,
        label=top_label,
        modular_prompts=merged_modular,
        variables_used=[],
        retrieval_config=retrieval_config,
        model_config=model_config,
        tool_permissions=tool_permissions,
        resolution_path=path,
        config_hash=config_hash,
        is_default_fallback=not layers and not floor,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Caller-meta stamping
# ---------------------------------------------------------------------------


@dataclass
class _ResolutionMeta:
    """Per-call metadata stitched onto a ResolvedAgentConfig copy.
    Lets the caller (ask_stream + the debug endpoint) attach
    cache-hit / duration without mutating the cached object."""
    cache_hit: bool = False
    duration_ms: int = 0


# We attach `_meta` as an attribute on the returned ResolvedAgentConfig
# *copy*, not on the cached source. dataclasses don't natively allow
# new attrs after construction, but since they're plain Python objects
# we can set them anyway. The log writer reads `getattr(cfg, '_meta',
# _ResolutionMeta())`.


def _copy_with_meta(
    cfg: ResolvedAgentConfig, *, cache_hit: bool, duration_ms: int,
) -> ResolvedAgentConfig:
    """Shallow copy + attach `_meta`. The dataclass fields are kept
    by reference (safe — they're either immutable Pydantic-style
    objects or frozen primitives)."""
    copy = ResolvedAgentConfig(
        agent_profile_id=cfg.agent_profile_id,
        agent_type=cfg.agent_type,
        prompt_version_id=cfg.prompt_version_id,
        version_number=cfg.version_number,
        label=cfg.label,
        modular_prompts=cfg.modular_prompts,
        variables_used=cfg.variables_used,
        retrieval_config=cfg.retrieval_config,
        model_config=cfg.model_config,
        tool_permissions=cfg.tool_permissions,
        resolution_path=cfg.resolution_path,
        config_hash=cfg.config_hash,
        is_default_fallback=cfg.is_default_fallback,
        warnings=list(cfg.warnings),
    )
    copy._meta = _ResolutionMeta(cache_hit=cache_hit, duration_ms=duration_ms)  # type: ignore[attr-defined]
    return copy


def cache_hit(cfg: ResolvedAgentConfig) -> bool:
    return getattr(cfg, "_meta", _ResolutionMeta()).cache_hit


def resolve_duration_ms(cfg: ResolvedAgentConfig) -> int:
    return getattr(cfg, "_meta", _ResolutionMeta()).duration_ms


# ---------------------------------------------------------------------------
# Runtime log writer (shadow-mode + production)
# ---------------------------------------------------------------------------


def log_resolution(
    db: Session,
    *,
    organization_id: UUID,
    resolved: ResolvedAgentConfig,
    rag_query_run_id: Optional[UUID] = None,
    requested_scope_type: Optional[str] = None,
    requested_scope_id: Optional[int] = None,
) -> Optional[int]:
    """Insert one `agent_runtime_logs` row. Fire-and-forget: any error
    is logged and swallowed so a logging failure can never affect the
    /rag/ask response."""
    from app.db.models import AgentRuntimeLog
    try:
        row = AgentRuntimeLog(
            organization_id=organization_id,
            rag_query_run_id=rag_query_run_id,
            agent_profile_id=resolved.agent_profile_id,
            prompt_version_id=resolved.prompt_version_id,
            agent_type=resolved.agent_type,
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            resolution_path_json=[asdict(s) for s in resolved.resolution_path],
            resolved_config_hash=resolved.config_hash,
            cache_hit=cache_hit(resolved),
            resolve_duration_ms=resolve_duration_ms(resolved),
            warnings_json=list(resolved.warnings),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    except Exception as exc:
        db.rollback()
        logger.warning("log_resolution: failed to persist row: %s", exc)
        return None
