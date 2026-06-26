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
        enabled_agents = []
        unknown = []
        for aid in enabled_ids:
            agent = AGENT_REGISTRY.get(aid)
            if agent is None:
                unknown.append(aid)
            else:
                enabled_agents.append(agent)
        if unknown:
            # Loud-skip: previously these silently disappeared, so users
            # configured non-existent agents in Agent Control and never
            # heard back. Now the log line names them.
            logger.warning(
                "⚠️  Skipping unknown agent ids (not in AGENT_REGISTRY): %s",
                unknown,
            )

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

        # Lazy import — keeps audit dep off the legacy import path.
        from app.services.agents.tools import audit
        import time as _time

        skill_results = {}
        for skill in skills:
            # Generate a run_id BEFORE invocation so both the harness's
            # tool-call rows AND our skill_run summary row share it.
            # That way the observability page groups all rows under
            # one logical run per skill execution.
            run_id = audit.new_run_id()
            start = _time.monotonic()
            tokens_for_summary = None
            error_for_summary = None
            success_for_summary = True
            output: Any = None
            try:
                if harness_on and skill.required_tools:
                    logger.info("🛠️  Executing Skill via HARNESS: %s (run=%s)", skill.id, run_id)
                    output, tokens_for_summary = cls._run_skill_in_harness(
                        db, skill, transcript, profile, meeting_id, run_id=run_id,
                    )
                else:
                    logger.info("🚀 Executing Skill: %s (run=%s)", skill.id, run_id)
                    output = SkillExecutor.execute_skill(db, skill, transcript, profile, meeting_id)
                    # Pick up the token count the executor stashed
                    # during its LLM call. Without this, legacy skill
                    # sentinels showed total_tokens=0 on the
                    # observability page even though tokens were spent.
                    tokens_for_summary = SkillExecutor._last_tokens_used
                # SkillExecutor returns {"error": "..."} when it fails
                # internally instead of raising — flag that as a non-success.
                if isinstance(output, dict) and "error" in output and not output.get("skill_id"):
                    success_for_summary = False
                    error_for_summary = str(output.get("error"))[:500]
                skill_results[skill.id] = output
                logger.debug("Skill %s output: %s", skill.id, output)
            except Exception as e:
                success_for_summary = False
                error_for_summary = str(e)[:500]
                logger.error("Skill %s failed: %s", skill.id, str(e), exc_info=True)
            finally:
                # One row per skill execution, regardless of harness/legacy
                # path. Carries the skill_id, success, duration, and tokens
                # (when known from the harness). Same `run_id` as the tool
                # rows above so they all group together in the UI.
                try:
                    audit.record_skill_run(
                        db,
                        organization_id=profile.organization_id,
                        run_id=run_id,
                        skill_id=skill.id,
                        success=success_for_summary,
                        meeting_id=meeting_id,
                        result=output if success_for_summary else None,
                        error_message=error_for_summary,
                        duration_ms=int((_time.monotonic() - start) * 1000),
                        tokens_used=tokens_for_summary,
                    )
                    db.commit()
                except Exception as audit_err:
                    logger.warning("skill_run audit write failed: %s", audit_err)
                    db.rollback()

        return skill_results

    @classmethod
    def _run_skill_in_harness(
        cls,
        db,
        skill,
        transcript: str,
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int],
        run_id=None,
    ):
        """Bridge a SkillDefinition into the tool-calling harness.

        Returns `(output, tokens_used)` so the caller can include the
        token count on the skill_run summary row. The `output` matches
        skill.output_schema when the loop terminated by answering; falls
        back to {error: ...} when a rail tripped.
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
            run_id=run_id,
        )
        if result.stopped_reason != "answered":
            return (
                {
                    "error": f"harness stopped: {result.stopped_reason}",
                    "run_id": str(result.run_id),
                    "iterations": result.iterations,
                },
                result.tokens_used,
            )
        return result.output, result.tokens_used
