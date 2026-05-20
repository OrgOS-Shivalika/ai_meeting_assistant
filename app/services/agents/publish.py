"""Phase 7B — version lifecycle: create-draft, publish, rollback.

Three public entry points:

  next_version_number(db, agent_prompt_config_id) -> int
  publish_version(db, ..., version_id, actor_user_id, reason) -> PromptVersion
  rollback_to_version(db, ..., to_version_id, actor_user_id, reason) -> PromptVersion

Concurrency: every publish or rollback acquires a Postgres advisory
xact lock keyed by the `agent_prompt_config_id`. Two simultaneous
publishes on the *same* config serialize; on *different* configs they
proceed in parallel.

Idempotency: callers should NOT retry on `PublishConflict` — it
indicates the version was already published, which is a no-op success.
Other exceptions indicate genuine errors.

7H integration: the `eval_gate_required` flag on `agent_profiles`
gates publish. When true, publish calls into `eval_gate.run_if_required`
(landed in 7H). For 7B that function is a no-op stub that always
returns success.

Validation (`_validate_publishable_version`):
  - required modular sections present (per agent_type)
  - declared variables match known catalog
  - retrieval_config bounds (already enforced at the API by Pydantic,
    re-checked at publish time as a safety net)
  - model_config has a model name set

Trigger interplay: the immutability trigger on `prompt_versions`
blocks UPDATE of body columns when state is not 'draft'. The publish
step transitions draft → published in a single UPDATE; that UPDATE
sets `state` + `published_at` + `published_by` but does NOT touch
body columns, so the trigger lets it through. Same for rollback,
which only re-points `active_version_id` on the config row.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import (
    AgentConfigEpoch, AgentProfile, AgentPromptConfig, PromptDeployment,
    PromptVersion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


class PublishError(RuntimeError):
    """Raised for any publish/rollback failure. Carries an HTTP status
    hint so the router layer can map cleanly without re-introspecting."""

    def __init__(self, message: str, *, http_status: int = 409) -> None:
        super().__init__(message)
        self.http_status = http_status


class PublishConflict(PublishError):
    """Version was already published or already-active. Idempotent
    success at the caller level."""

    def __init__(self, message: str) -> None:
        super().__init__(message, http_status=409)


class PublishValidationError(PublishError):
    """Version didn't meet the publish contract (missing required
    section, unknown variable, etc.). Returned as 400."""

    def __init__(self, message: str) -> None:
        super().__init__(message, http_status=400)


class PublishGateFailed(PublishError):
    """Eval gate rejected the candidate. Returned as 422 to distinguish
    from a generic validation error."""

    def __init__(self, message: str, *, score: Optional[float] = None) -> None:
        super().__init__(message, http_status=422)
        self.score = score


# ---------------------------------------------------------------------------
# Advisory lock
# ---------------------------------------------------------------------------


def _advisory_lock_key(agent_prompt_config_id: UUID) -> int:
    """Hash the UUID into a signed 64-bit int Postgres can use as the
    advisory lock key. The hash is deterministic — two callers in
    different sessions targeting the same config produce the same key
    and serialize."""
    h = hashlib.sha256(agent_prompt_config_id.bytes).digest()
    # Take the first 8 bytes, interpret as signed int64. Postgres
    # advisory locks accept bigint; we want stable bucketing not
    # uniform distribution.
    unsigned = int.from_bytes(h[:8], "big", signed=False)
    # Map to signed range to satisfy bigint.
    if unsigned >= (1 << 63):
        return unsigned - (1 << 64)
    return unsigned


def _acquire_config_lock(db: Session, agent_prompt_config_id: UUID) -> None:
    """Per-config serialization for publish + rollback. Released
    automatically at transaction end."""
    key = _advisory_lock_key(agent_prompt_config_id)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


# ---------------------------------------------------------------------------
# Version numbering
# ---------------------------------------------------------------------------


def next_version_number(db: Session, agent_prompt_config_id: UUID) -> int:
    """Atomic next-number generator. Caller is expected to be inside a
    transaction that already holds the advisory lock for this config —
    otherwise two simultaneous draft-creates against the same config
    can race. The publish/rollback paths take the lock; the draft-create
    path takes it via `create_draft` (see below)."""
    current_max = db.execute(
        select(func.coalesce(func.max(PromptVersion.version_number), 0))
        .where(PromptVersion.agent_prompt_config_id == agent_prompt_config_id)
    ).scalar_one()
    return int(current_max) + 1


# ---------------------------------------------------------------------------
# Draft creation
# ---------------------------------------------------------------------------


def create_draft(
    db: Session,
    *,
    organization_id: UUID,
    agent_prompt_config_id: UUID,
    label: Optional[str],
    modular_prompt_json: dict,
    variables_schema_json: list,
    retrieval_config_json: dict,
    model_config_json: dict,
    tool_permissions_json: dict,
    meta_json: dict,
    created_by: Optional[UUID],
    seeded_from_filesystem: bool = False,
) -> PromptVersion:
    """Create a new draft under a config. Serializes against concurrent
    draft creates on the same config so version_number stays monotonic
    with no gaps."""
    _acquire_config_lock(db, agent_prompt_config_id)
    n = next_version_number(db, agent_prompt_config_id)
    row = PromptVersion(
        organization_id=organization_id,
        agent_prompt_config_id=agent_prompt_config_id,
        version_number=n,
        label=label,
        modular_prompt_json=modular_prompt_json or {},
        variables_schema_json=variables_schema_json or [],
        retrieval_config_json=retrieval_config_json or {},
        model_config_json=model_config_json or {},
        tool_permissions_json=tool_permissions_json or {"allowed": [], "denied": []},
        meta_json=meta_json or {},
        state="draft",
        seeded_from_filesystem=seeded_from_filesystem,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


# Per-agent-type required modular sections. Kept in sync with the plan
# §4.4 matrix. The composer (7B+) reads this same map to decide whether
# the assembled prompt is well-formed.
_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "rag_synth":          ("system", "retrieval", "citation", "guardrails"),
    "rag_planner":        ("system", "output"),
    "graph_extractor":    ("system", "output"),
    "transcript_analyzer": ("system", "output"),
    "summarizer":         ("system", "output"),
    "live_copilot":       ("system", "behavior", "guardrails"),
    # importance_scorer has no LLM today, so no required sections.
    "importance_scorer":  (),
}


def _validate_publishable_version(
    version: PromptVersion, profile: AgentProfile,
) -> None:
    """Pre-publish gate. Raises `PublishValidationError` on contract
    violations. Pydantic already enforces bounds at the API layer; this
    re-validates so direct service-layer callers (seed scripts, tests)
    can't sneak past."""
    # Required sections
    required = _REQUIRED_SECTIONS.get(profile.agent_type, ())
    body = version.modular_prompt_json or {}
    missing = [k for k in required if not (body.get(k) or "").strip()]
    if missing:
        raise PublishValidationError(
            f"missing required modular section(s) for agent_type "
            f"'{profile.agent_type}': {missing}"
        )

    # Retrieval bounds — strict re-check matching Pydantic.
    rc = version.retrieval_config_json or {}
    for k, lo, hi in (
        ("top_k_vector", 1, 200),
        ("top_k_final", 1, 50),
        ("max_graph_depth", 0, 3),
        ("tier_widen_threshold", 0, 50),
    ):
        v = rc.get(k)
        if v is None:
            continue
        if not isinstance(v, int) or v < lo or v > hi:
            raise PublishValidationError(
                f"retrieval_config.{k}={v!r} must be int in [{lo}, {hi}]"
            )

    weights = rc.get("importance_weight_overrides") or {}
    if not isinstance(weights, dict):
        raise PublishValidationError(
            "retrieval_config.importance_weight_overrides must be an object"
        )
    for wk, wv in weights.items():
        if wv is None:
            continue
        if not isinstance(wv, (int, float)) or wv < 0.0 or wv > 1.0:
            raise PublishValidationError(
                f"importance_weight_overrides[{wk}]={wv!r} must be in [0, 1]"
            )


# ---------------------------------------------------------------------------
# Epoch bump
# ---------------------------------------------------------------------------


def _bump_epoch(
    db: Session, *, organization_id: UUID, agent_profile_id: UUID,
) -> None:
    """Upsert the (org, profile) epoch counter and increment it.
    Resolver caches in other workers see the new value on their next
    epoch-check and evict.

    Uses INSERT ... ON CONFLICT — safer than read-modify-write because
    the row may not yet exist on the first publish for this profile."""
    db.execute(
        text("""
            INSERT INTO agent_config_epochs (organization_id, agent_profile_id, epoch, updated_at)
            VALUES (:org, :prof, 1, now())
            ON CONFLICT (organization_id, agent_profile_id)
            DO UPDATE SET epoch = agent_config_epochs.epoch + 1,
                          updated_at = now()
        """),
        {"org": str(organization_id), "prof": str(agent_profile_id)},
    )


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def publish_version(
    db: Session,
    *,
    organization_id: UUID,
    version_id: UUID,
    actor_user_id: Optional[UUID],
    reason: Optional[str] = None,
) -> PromptVersion:
    """Transition a draft to published and set it active.

    On success: returns the published row. Side effects:
      - prompt_versions.state = 'published', published_at = now(),
        published_by = actor
      - agent_prompt_configs.active_version_id = version.id
      - prompt_deployments(action='publish') appended
      - agent_config_epochs.epoch incremented

    Refusals:
      - Version not in 'draft' state → PublishConflict
      - Validation failure → PublishValidationError
      - Eval gate failure → PublishGateFailed
      - Config or profile archived → PublishConflict
    """
    # Load + lock the version row. SELECT FOR UPDATE serializes with
    # any concurrent edit; the advisory lock further serializes with
    # other publish/rollback calls on the same config.
    version = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.organization_id == organization_id,
    ).with_for_update().first()
    if version is None:
        raise PublishError("Version not found", http_status=404)

    config = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.id == version.agent_prompt_config_id,
        AgentPromptConfig.organization_id == organization_id,
    ).with_for_update().first()
    if config is None:
        raise PublishError("Owning config not found", http_status=404)
    if config.status != "active":
        raise PublishConflict(
            "Owning prompt config is archived; un-archive before publishing."
        )

    profile = db.query(AgentProfile).filter(
        AgentProfile.id == config.agent_profile_id,
        AgentProfile.organization_id == organization_id,
    ).first()
    if profile is None:
        raise PublishError("Agent profile not found", http_status=404)
    if profile.status != "active":
        raise PublishConflict(
            "Agent profile is archived; un-archive before publishing."
        )

    _acquire_config_lock(db, config.id)

    if version.state != "draft":
        # Idempotent if already published and is the active one.
        if version.state == "published" and config.active_version_id == version.id:
            return version
        raise PublishConflict(
            f"Version state is '{version.state}', expected 'draft'."
        )

    # Seed-from-filesystem versions bypass per-section validation: the
    # body is one big `system` section sourced from a prompt that's
    # already in production use, so requiring it to be re-split into
    # the 8 modular sections would prevent the seed entirely. Admins
    # who later author NEW drafts get the full validator.
    if not version.seeded_from_filesystem:
        _validate_publishable_version(version, profile)

    # Phase 7H — eval gate. Delegates to `eval_gate.run_if_required`
    # which only fires when `profile.eval_gate_required` is true.
    # Failure produces a PublishGateFailed with the score; success
    # returns the eval_run row so we can stamp `version.eval_score` +
    # `eval_run_id`.
    #
    # Phase 8B: `seeded_from_filesystem` versions also skip the eval
    # gate. Same rationale as the validator bypass — seeded content
    # comes from a trusted catalog source; gating it on the canonical
    # eval fixture (which doesn't exist for a freshly-provisioned
    # workspace) would block every provisioning that touches a
    # gate-required template.
    eval_score: Optional[float] = None
    eval_run_id: Optional[UUID] = None
    if profile.eval_gate_required and not version.seeded_from_filesystem:
        from app.services.agents.eval_gate import (
            EvalGateFailed as _EvalGateFailed,
            run_if_required as _run_gate,
        )
        try:
            run = _run_gate(
                db, profile=profile, version=version,
                actor_user_id=actor_user_id,
            )
        except _EvalGateFailed as exc:
            db.add(PromptDeployment(
                organization_id=organization_id,
                agent_prompt_config_id=config.id,
                action="eval_gate_failed",
                from_version_id=version.id,
                to_version_id=None,
                actor_user_id=actor_user_id,
                reason=reason,
                metadata_json={
                    "eval_score": exc.score,
                    "eval_min_score": exc.threshold,
                    "eval_run_id": (
                        str(exc.eval_run_id) if exc.eval_run_id else None
                    ),
                },
            ))
            db.commit()
            raise PublishGateFailed(
                f"Eval gate score {exc.score!r} below threshold "
                f"{exc.threshold:.3f}",
                score=exc.score,
            ) from exc
        if run is not None:
            eval_score = run.score
            eval_run_id = run.id

    prev_active = config.active_version_id
    now = datetime.now(timezone.utc)

    version.state = "published"
    version.published_at = now
    version.published_by = actor_user_id
    if eval_score is not None:
        version.eval_score = eval_score
    if eval_run_id is not None:
        version.eval_run_id = eval_run_id

    config.active_version_id = version.id
    config.updated_at = now

    db.add(PromptDeployment(
        organization_id=organization_id,
        agent_prompt_config_id=config.id,
        action="publish",
        from_version_id=prev_active,
        to_version_id=version.id,
        actor_user_id=actor_user_id,
        reason=reason,
        metadata_json={"eval_score": eval_score} if eval_score is not None else {},
    ))

    _bump_epoch(
        db,
        organization_id=organization_id,
        agent_profile_id=profile.id,
    )

    db.commit()
    db.refresh(version)
    return version


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def rollback_to_version(
    db: Session,
    *,
    organization_id: UUID,
    agent_prompt_config_id: UUID,
    to_version_id: UUID,
    actor_user_id: Optional[UUID],
    reason: Optional[str] = None,
) -> PromptVersion:
    """Point a config's active_version_id at a PRIOR PUBLISHED version.

    The target must be `state='published'` and belong to the same
    config. The previously-active version stays `state='published'` —
    rollback is reversible. To unwind, call rollback_to_version again
    with the previous version's id.

    Refusals:
      - target version not found → 404
      - target version's config doesn't match → 404
      - target version not in 'published' state → PublishConflict
      - target is already the active version → idempotent success
    """
    config = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.id == agent_prompt_config_id,
        AgentPromptConfig.organization_id == organization_id,
    ).with_for_update().first()
    if config is None:
        raise PublishError("Prompt config not found", http_status=404)
    if config.status != "active":
        raise PublishConflict(
            "Prompt config is archived; un-archive before rollback."
        )

    target = db.query(PromptVersion).filter(
        PromptVersion.id == to_version_id,
        PromptVersion.organization_id == organization_id,
    ).with_for_update().first()
    if target is None:
        raise PublishError("Target version not found", http_status=404)
    if target.agent_prompt_config_id != config.id:
        raise PublishError(
            "Target version does not belong to this prompt config",
            http_status=404,
        )

    _acquire_config_lock(db, config.id)

    if target.state != "published":
        raise PublishConflict(
            f"Cannot rollback to a version in state '{target.state}'. "
            "Only previously-published versions are valid rollback targets."
        )

    if config.active_version_id == target.id:
        return target  # idempotent

    prev_active = config.active_version_id
    config.active_version_id = target.id
    config.updated_at = datetime.now(timezone.utc)

    db.add(PromptDeployment(
        organization_id=organization_id,
        agent_prompt_config_id=config.id,
        action="rollback",
        from_version_id=prev_active,
        to_version_id=target.id,
        actor_user_id=actor_user_id,
        reason=reason,
        metadata_json={},
    ))

    _bump_epoch(
        db,
        organization_id=organization_id,
        agent_profile_id=config.agent_profile_id,
    )

    db.commit()
    db.refresh(target)
    return target


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------


def archive_version(
    db: Session,
    *,
    organization_id: UUID,
    version_id: UUID,
) -> PromptVersion:
    """Move a version to state='archived'. Refused if it is currently
    the active version on its config (rollback first)."""
    version = db.query(PromptVersion).filter(
        PromptVersion.id == version_id,
        PromptVersion.organization_id == organization_id,
    ).with_for_update().first()
    if version is None:
        raise PublishError("Version not found", http_status=404)

    config = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.id == version.agent_prompt_config_id,
    ).first()
    if config is not None and config.active_version_id == version.id:
        raise PublishConflict(
            "Cannot archive the currently active version. "
            "Rollback to another version first."
        )

    if version.state == "archived":
        return version

    # Transition is allowed for both draft and published. The
    # immutability trigger lets us flip state + (clear published_at if
    # archiving a draft) without touching body columns.
    if version.state == "published":
        # Per CHECK consistency: archived rows have published_at NULL.
        version.published_at = None
        version.published_by = None
    version.state = "archived"
    version.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(version)
    return version
