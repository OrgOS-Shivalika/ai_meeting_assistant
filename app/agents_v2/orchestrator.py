"""Agents v2 orchestrator — thin router.

Four jobs:
  1. ROUTE     — find the agents_v2 row for (org, cat, team)
  2. RESOLVE   — merge DB overrides with manifest defaults
  3. KNOWLEDGE — package prior memory/summaries/tasks into a
                 KnowledgeContext
  4. INVOKE    — call the agent module's run(...)

The orchestrator knows almost nothing about what agents DO. Each agent
owns its own execution logic in its folder's execution.py.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.agents_v2 import registry
from app.agents_v2.shared.schemas.knowledge_context import (
    KnowledgeContext, LongTermMeetingSummary, OpenTask,
)
from app.db.models import AgentV2, Meeting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def has_agent_for_scope(db: Session, meeting: Meeting) -> bool:
    """Feature-flag check. True → route this meeting through agents_v2.

    Called by meeting_pipeline BEFORE invoking the legacy orchestrator.
    Absence of a row = fall through to the legacy path unchanged.
    """
    return _route(
        db,
        meeting.organization_id,
        meeting.category_id,
        meeting.team_id,
    ) is not None


def run_meeting_analysis(db: Session, transcript: str, meeting: Meeting):
    """Route the meeting to its scoped agent and invoke it.

    Returns whatever the agent's run() returns — must be an
    ExtractionSummary so meeting_pipeline's downstream code
    (save_tasks, memory distill, etc.) works identically to the legacy
    path.
    """
    row = _route(
        db,
        meeting.organization_id,
        meeting.category_id,
        meeting.team_id,
    )
    if not row:
        raise RuntimeError(
            f"agents_v2: no agent for scope org={meeting.organization_id} "
            f"cat={meeting.category_id} team={meeting.team_id} — "
            "meeting_pipeline should have checked has_agent_for_scope first."
        )

    module = registry.get_agent_module(row.slug)
    if not module:
        raise RuntimeError(
            f"agents_v2: DB has agent row for slug={row.slug!r} but no "
            "matching folder is registered. Did you deploy the code?"
        )

    # Build effective config by merging DB overrides onto manifest defaults.
    effective = _merge_manifest_with_row(module.MANIFEST, row)

    # Build the KnowledgeContext for THIS meeting's scope.
    knowledge = _build_knowledge(db, meeting)

    context = {
        "meeting_id": meeting.id,
        "organization_id": meeting.organization_id,
        "category_id": meeting.category_id,
        "team_id": meeting.team_id,
        "agent_row_id": row.id,
        "agent_slug": row.slug,
    }

    logger.info(
        "agents_v2: routing meeting %s to agent %r (model=%s, harness=%s, "
        "knowledge: %d facts, %d summaries, %d open tasks)",
        meeting.id, row.slug, effective["model"], effective["harness_enabled"],
        len(knowledge.prior_facts), len(knowledge.recent_summaries),
        len(knowledge.open_tasks),
    )

    return module.run(
        transcript=transcript,
        knowledge=knowledge,
        effective_config=effective,
        context=context,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _route(
    db: Session,
    organization_id: UUID,
    category_id: Optional[int],
    team_id: Optional[int],
) -> Optional[AgentV2]:
    """Find the most-specific active agent for the scope.

    Precedence: (org, cat, team) > (org, cat) > (org, null, null).
    Returns None if no agent is registered for any level.
    """
    # 1. Try team-scoped
    if category_id is not None and team_id is not None:
        row = (
            db.query(AgentV2)
            .filter(
                AgentV2.organization_id == organization_id,
                AgentV2.category_id == category_id,
                AgentV2.team_id == team_id,
                AgentV2.status == "active",
            )
            .first()
        )
        if row:
            return row

    # 2. Try category-scoped
    if category_id is not None:
        row = (
            db.query(AgentV2)
            .filter(
                AgentV2.organization_id == organization_id,
                AgentV2.category_id == category_id,
                AgentV2.team_id.is_(None),
                AgentV2.status == "active",
            )
            .first()
        )
        if row:
            return row

    # 3. Try org-scoped
    row = (
        db.query(AgentV2)
        .filter(
            AgentV2.organization_id == organization_id,
            AgentV2.category_id.is_(None),
            AgentV2.team_id.is_(None),
            AgentV2.status == "active",
        )
        .first()
    )
    return row


def _merge_manifest_with_row(manifest: dict[str, Any], row: AgentV2) -> dict[str, Any]:
    """DB overrides win when non-empty. Empty DB field = use manifest default."""
    return {
        "slug": row.slug,
        "name": row.name or manifest.get("name", row.slug),
        "master_prompt": manifest.get("master_prompt", "prompts/master.md"),
        "model": row.model or manifest.get("model", "gpt-4o-mini"),
        "max_tokens": row.max_tokens or manifest.get("max_tokens", 4000),
        "harness_enabled": row.harness_enabled if row.harness_enabled is not None
        else manifest.get("harness_enabled", False),
        "allowed_skills": (
            list(row.allowed_skills) if row.allowed_skills
            else [s.id for s in manifest.get("skills", []) if hasattr(s, "id")]
        ),
        "allowed_tools": (
            list(row.allowed_tools) if row.allowed_tools
            else list(manifest.get("tools", []))
        ),
    }


def _build_knowledge(db: Session, meeting: Meeting) -> KnowledgeContext:
    """Pull short-term facts + long-term summaries + open tasks for scope.

    All three lookups are wrapped so a memory-layer failure doesn't
    kill the meeting analysis — knowledge just comes back partial.
    """
    facts: list[str] = []
    summaries: list[LongTermMeetingSummary] = []
    tasks: list[OpenTask] = []

    try:
        from app.services.memory.access import MemoryAccess
        prior_facts = MemoryAccess.search_for_meeting(
            db, meeting_id=meeting.id, query="", limit=10, bump=False,
        )
        facts = [f.fact for f in prior_facts]
    except Exception as exc:
        logger.warning("knowledge: short-term facts fetch failed: %s", exc)

    try:
        from app.services.memory.long_term import LongTermMemory
        recent = LongTermMemory.recent_summaries(
            db,
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id,
            limit=5,
        )
        summaries = [
            LongTermMeetingSummary(title=s.title, when=s.when, summary=s.summary)
            for s in recent
        ]

        open_tasks = LongTermMemory.tasks_in_scope(
            db,
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id,
            only_open=True,
            limit=20,
        )
        tasks = [
            OpenTask(
                task=t.task,
                owner=t.owner_name,
                due=t.due_date.date().isoformat() if t.due_date else None,
                status=t.status,
            )
            for t in open_tasks
        ]
    except Exception as exc:
        logger.warning("knowledge: long-term fetch failed: %s", exc)

    return KnowledgeContext(
        prior_facts=facts,
        recent_summaries=summaries,
        open_tasks=tasks,
    )
