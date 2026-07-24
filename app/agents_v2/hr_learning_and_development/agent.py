"""HR Team Agent — entry point.

The orchestrator calls run(). This file stays a thin dispatcher; the
real work happens in execution._execute().
"""
from __future__ import annotations

from typing import Any

from app.agents_v2.shared.schemas.extraction_summary import ExtractionSummary
from app.agents_v2.shared.schemas.knowledge_context import KnowledgeContext

from .config import CONFIG
from .execution import _execute
from .manifest import MANIFEST


def run(
    *,
    transcript: str,
    knowledge: KnowledgeContext,
    effective_config: dict[str, Any],
    context: dict[str, Any],
) -> ExtractionSummary:
    """Entry point invoked by app.agents_v2.orchestrator.run_meeting_analysis.

    Args:
        transcript: The formatted meeting transcript (speaker: text\n...)
        knowledge: Prior facts, recent summaries, open tasks in scope.
        effective_config: DB-row overrides merged onto MANIFEST defaults.
        context: {meeting_id, organization_id, category_id, team_id, ...}

    Returns:
        ExtractionSummary — the canonical output shape every agent must
        produce. meeting_pipeline saves title/summary/tasks from this.
    """
    return _execute(
        transcript=transcript,
        knowledge=knowledge,
        effective=effective_config,
        context=context,
        config=CONFIG,
    )
