"""Phase 7D — idempotent default-agent seeder.

For a given organization, materializes:

  - One `agent_profile` per default agent_type (rag_synth, rag_planner,
    graph_extractor, transcript_analyzer, summarizer).
    Slugs are `default_<agent_type>`. `seeded_from_filesystem=True` is
    set on the resulting prompt_versions so the seeder can detect
    prior runs and stay no-op on re-execution.

  - One `agent_prompt_config` per profile, scope=organization.

  - One published `prompt_version` per profile, version_number=1,
    state=published. The modular_prompt's `system` section is sourced
    from the filesystem v1 prompt (split at the LLM-input marker;
    single-brace `{var}` converted to `{{var}}` so the composer
    interpolates correctly).

Idempotency: re-running on an org that already has a
seeded-from-filesystem profile is a no-op. We check by:

  - Looking up the profile by slug
  - Looking up the org-scoped config under that profile
  - If both exist AND the active version has `seeded_from_filesystem=True`,
    nothing to do for that profile.

Failure isolation: profiles seed independently. If `rag_synth` seeds
fine but `rag_planner` fails (missing filesystem file, etc.), the
function returns a partial-success summary; callers can re-run.

Used by:
  - the CLI `app/scripts/seed_default_agents.py` (per-org bootstrap)
  - 7D-era tests
  - future Celery hook on org-create
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import (
    AgentProfile, AgentPromptConfig, PromptVersion,
)
from app.services.agents.publish import (
    PublishError, create_draft, publish_version,
)
from app.services.agents.resolver import (
    _filesystem_floor,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalog of default profiles. Keep small in 7D — synth + planner cover
# the production hot path. graph_extractor / transcript_analyzer get
# seeded too (their LLM calls land in different code paths today, but
# the dashboard surface is already useful for them).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _DefaultProfile:
    slug: str
    display_name: str
    description: str
    agent_type: str


_DEFAULTS: tuple[_DefaultProfile, ...] = (
    _DefaultProfile(
        slug="default_synth",
        display_name="Default RAG Synthesizer",
        description="Seeded from filesystem v1. Generates cited answers from "
                    "retrieved context.",
        agent_type="rag_synth",
    ),
    _DefaultProfile(
        slug="default_planner",
        display_name="Default RAG Query Planner",
        description="Seeded from filesystem v1. Classifies query intent and "
                    "selects scope tier.",
        agent_type="rag_planner",
    ),
    _DefaultProfile(
        slug="default_graph_extractor",
        display_name="Default Graph Extractor",
        description="Seeded from filesystem v1. Pulls entities + relationships "
                    "from meeting/document text.",
        agent_type="graph_extractor",
    ),
    _DefaultProfile(
        slug="default_transcript_analyzer",
        display_name="Default Transcript Analyzer",
        description="Seeded from filesystem v1. Post-meeting summary + tasks "
                    "+ decisions.",
        agent_type="transcript_analyzer",
    ),
    _DefaultProfile(
        slug="default_summarizer",
        display_name="Default Summarizer",
        description="Seeded placeholder. Per-team summary overrides.",
        agent_type="summarizer",
    ),
)


@dataclass
class SeedResult:
    """Returned from `seed_default_agents_for_org`. Per-profile status
    so the caller can surface what happened."""
    organization_id: UUID
    profiles_created: list[str]
    profiles_already_seeded: list[str]
    profiles_failed: list[tuple[str, str]]  # (slug, error)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _floor_modular_prompt(agent_type: str) -> dict[str, str]:
    """Wrap the resolver's `_filesystem_floor` to surface just the
    modular dict. Returns {} for agent_types with no filesystem
    fallback (those get a profile but no published v1 in 7D — admins
    create the first draft manually)."""
    floor, _ = _filesystem_floor(agent_type)
    return floor


def _existing_seeded_version(
    db: Session, *, config_id: UUID,
) -> Optional[PromptVersion]:
    """Return the currently-active version on `config_id` if it was
    seeded from filesystem; else None. Used as the idempotency guard."""
    cfg = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.id == config_id,
    ).first()
    if cfg is None or cfg.active_version_id is None:
        return None
    v = db.query(PromptVersion).filter(
        PromptVersion.id == cfg.active_version_id,
    ).first()
    if v is None or not v.seeded_from_filesystem:
        return None
    return v


def _seed_one_profile(
    db: Session,
    *,
    organization_id: UUID,
    descriptor: _DefaultProfile,
    created_by: Optional[UUID],
) -> str:
    """Returns one of: 'created', 'already_seeded'. Raises on hard
    failures so the caller can record (slug, error).

    'created' means we materialized at least one row on this call
    ('already_seeded' means everything was already in place)."""
    did_anything_new = False

    # 1. Profile — find existing or create.
    profile = db.query(AgentProfile).filter(
        AgentProfile.organization_id == organization_id,
        AgentProfile.slug == descriptor.slug,
        AgentProfile.status == "active",
    ).first()
    if profile is None:
        profile = AgentProfile(
            organization_id=organization_id,
            slug=descriptor.slug,
            display_name=descriptor.display_name,
            description=descriptor.description,
            agent_type=descriptor.agent_type,
            status="active",
            default_modular_prompt_json=_floor_modular_prompt(descriptor.agent_type),
            created_by=created_by,
        )
        db.add(profile); db.commit(); db.refresh(profile)
        did_anything_new = True

    # 2. Config — org-scoped, find existing or create.
    cfg = db.query(AgentPromptConfig).filter(
        AgentPromptConfig.organization_id == organization_id,
        AgentPromptConfig.agent_profile_id == profile.id,
        AgentPromptConfig.scope_type == "organization",
        AgentPromptConfig.scope_id.is_(None),
        AgentPromptConfig.status == "active",
    ).first()
    if cfg is None:
        cfg = AgentPromptConfig(
            organization_id=organization_id,
            agent_profile_id=profile.id,
            scope_type="organization",
            scope_id=None,
            status="active",
            created_by=created_by,
        )
        db.add(cfg); db.commit(); db.refresh(cfg)
        did_anything_new = True

    # 3. Already-seeded? Idempotency guard.
    if _existing_seeded_version(db, config_id=cfg.id) is not None:
        return "already_seeded"

    # 4. Build the modular prompt from the filesystem floor. If the
    # agent_type has no floor (e.g. summarizer), we still create the
    # profile + config but skip publishing a version — admins can
    # draft the first one manually. Idempotency for the no-floor
    # path: if profile + config already existed, this is
    # 'already_seeded' (we can't do more without a floor).
    floor = _floor_modular_prompt(descriptor.agent_type)
    if not floor:
        if did_anything_new:
            logger.info(
                "seed_defaults: no filesystem floor for agent_type=%s; "
                "profile %s created with no published version.",
                descriptor.agent_type, descriptor.slug,
            )
            return "created"
        return "already_seeded"

    # 5. Draft + publish v1.
    v = create_draft(
        db,
        organization_id=organization_id,
        agent_prompt_config_id=cfg.id,
        label=f"{settings.RAG_SYNTH_PROMPT_VERSION}-seeded",
        modular_prompt_json=floor,
        variables_schema_json=[],
        retrieval_config_json={},
        model_config_json={},
        tool_permissions_json={"allowed": [], "denied": []},
        meta_json={"seed_source": "filesystem"},
        created_by=created_by,
        seeded_from_filesystem=True,
    )
    db.commit()
    publish_version(
        db,
        organization_id=organization_id,
        version_id=v.id,
        actor_user_id=created_by,
        reason="seed_from_filesystem",
    )
    return "created"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def seed_default_agents_for_org(
    db: Session,
    *,
    organization_id: UUID,
    created_by_user_id: Optional[UUID] = None,
) -> SeedResult:
    """Idempotent. Materializes (or confirms) every default profile +
    config + published v1 for one organization.

    Safe to re-run: already-seeded profiles are skipped without
    incident. Failures are logged + recorded per-profile; the caller
    receives a structured result so partial-success is observable.
    """
    created: list[str] = []
    already: list[str] = []
    failed: list[tuple[str, str]] = []

    for d in _DEFAULTS:
        try:
            status = _seed_one_profile(
                db, organization_id=organization_id,
                descriptor=d, created_by=created_by_user_id,
            )
            if status == "created":
                created.append(d.slug)
            elif status == "already_seeded":
                already.append(d.slug)
        except PublishError as exc:
            logger.error(
                "seed_defaults: publish failed for %s: %s", d.slug, exc,
            )
            failed.append((d.slug, str(exc)))
        except Exception as exc:
            logger.error(
                "seed_defaults: unexpected error for %s: %s", d.slug, exc,
                exc_info=True,
            )
            failed.append((d.slug, str(exc)))

    return SeedResult(
        organization_id=organization_id,
        profiles_created=created,
        profiles_already_seeded=already,
        profiles_failed=failed,
    )
