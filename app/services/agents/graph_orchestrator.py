"""Phase 9.6 — Agent Graph Orchestrator.

Capability-based execution managed by a deterministic graph.
Moves beyond monolithic prompts to specialized agents that consume typed 
context and produce structured results.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID
from app.services.behavior.resolver import ResolvedBehaviorProfile
from app.services.cognition.contracts import ExtractionSummary
from app.ai_agents.transcript_analyzer import TranscriptAnalyzer
from app.services.agents.base import AGENT_REGISTRY, AgentOrchestrator
from app.runtime.skill_executor import SkillExecutor
from app.utils.logger import setup_logger
from app.services.cognition.merger import UnifiedCognitionMerger

logger = setup_logger(__name__)

class AgentGraphOrchestrator:
    """Orchestrates specialized agents and their modular skills."""

    @classmethod
    def run_meeting_analysis(
        cls, 
        db, 
        transcript: str, 
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int] = None
    ) -> ExtractionSummary:
        """The main entry point for orchestrated meeting cognition."""
        
        logger.info("🕸️  AgentGraphOrchestrator: Resolving execution graph...")
        
        # 1. Identity & Capability Check
        enabled_ids = profile.enabled_agents or []
        enabled_agents = [
            AGENT_REGISTRY[aid] for sid, aid in enumerate(enabled_ids) 
            if aid in AGENT_REGISTRY
        ]
        
        logger.info("🤖 Enabled Agents: %s", [a.id for a in enabled_agents])

        # 2. Context Builder
        from app.services.behavior.meeting_context import _format_dimensions
        behavior_context = _format_dimensions(profile.to_dict())

        # 3. Master Execution (Phase 2 Hybrid)
        # We still rely on TranscriptAnalyzer as the primary runner for core schema
        # to prevent regressions while we migrate entirely to skills.
        # Phase 8E — model + max_tokens come from the resolved profile.
        # `or "gpt-4o-mini"` (not `.get(..., default)`) because templates
        # can carry an empty-string model that we must NOT pass through
        # to OpenAI — OpenAI returns 400 "you must provide a model".
        tools = profile.tools_and_integrations or {}
        master_result: ExtractionSummary = TranscriptAnalyzer.analyze(
            transcript,
            behavior_context,
            contract_model=ExtractionSummary,
            model=tools.get("model") or "gpt-4o-mini",
            max_tokens=(profile.output_config or {}).get("max_tokens"),
        )

        # 4. Orchestrated Skill Execution
        # We pass the transcript to the specialized agents
        all_skill_results = {}
        for agent in enabled_agents:
            try:
                agent_results = cls._orchestrate_agent(db, agent, transcript, master_result, profile, meeting_id)
                if agent_results:
                    all_skill_results.update(agent_results)
            except Exception as e:
                logger.error("Error executing agent %s: %s", agent.id, str(e), exc_info=True)

        # 5. Unified Cognition Synthesis (Phase 10)
        final_result = UnifiedCognitionMerger.synthesize(
            master_result, 
            all_skill_results,
            meeting_id=meeting_id
        )

        return final_result

    @classmethod
    def _orchestrate_agent(
        cls, 
        db,
        agent: AgentOrchestrator, 
        transcript: str,
        extraction: ExtractionSummary, 
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Coordinates the skills for a specific agent orchestrator."""
        skills = agent.get_resolved_skills()
        if not skills:
            return {}

        logger.info("🎯 Agent %s orchestrating skills: %s", agent.id, [s.id for s in skills])
        
        # Piece 1 — harness opt-in. If `tools_and_integrations.harness_enabled`
        # is "on" AND the skill declares required_tools, run inside the
        # tool-calling loop. Otherwise fall back to the single-shot
        # SkillExecutor. Skills with no required_tools always use the
        # legacy path — no tools means no harness benefit.
        tools_cfg = (profile.tools_and_integrations or {})
        harness_flag = str(tools_cfg.get("harness_enabled", "off")).lower()
        harness_on = harness_flag in ("on", "true", "1", "yes")

        skill_results = {}
        for skill in skills:
            try:
                if harness_on and skill.required_tools:
                    logger.info("🛠️  Executing Skill via HARNESS: %s", skill.id)
                    output = cls._run_skill_in_harness(db, skill, transcript, profile, meeting_id)
                else:
                    logger.info("🚀 Executing Skill: %s", skill.id)
                    output = SkillExecutor.execute_skill(db, skill, transcript, profile, meeting_id)
                skill_results[skill.id] = output

                logger.debug("Skill %s output: %s", skill.id, output)
            except Exception as e:
                logger.error("Skill %s failed: %s", skill.id, str(e), exc_info=True)

        return skill_results

    @classmethod
    def _run_skill_in_harness(
        cls,
        db,
        skill,
        transcript: str,
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int],
    ) -> Dict[str, Any]:
        """Bridge a SkillDefinition into the tool-calling harness.

        Returns the harness's structured `output` (matching skill.output_schema)
        when the loop terminated by answering; falls back to {error: ...}
        when a rail tripped so downstream merger doesn't get a None.
        """
        # Lazy import — keeps harness off the import path for legacy runs.
        from app.services.agents.harness import run_loop
        # Side-effect import so every built-in tool is registered before
        # the registry is queried. Cheap (only fires the first time).
        from app.services.agents.tools import builtin  # noqa: F401

        tools_cfg = profile.tools_and_integrations or {}
        model = tools_cfg.get("model") or "gpt-4o-mini"

        result = run_loop(
            db=db,
            skill=skill,
            user_input=transcript,
            organization_id=profile.organization_id,
            meeting_id=meeting_id,
            model=model,
        )
        if result.stopped_reason != "answered":
            return {
                "error": f"harness stopped: {result.stopped_reason}",
                "run_id": str(result.run_id),
                "iterations": result.iterations,
            }
        return result.output
