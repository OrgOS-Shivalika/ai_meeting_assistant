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

logger = logging.getLogger(__name__)

class AgentGraphOrchestrator:
    """Orchestrates specialized agents based on BehaviorProfile capabilities."""

    @classmethod
    def run_meeting_analysis(
        cls, 
        db, 
        transcript: str, 
        profile: ResolvedBehaviorProfile
    ) -> ExtractionSummary:
        """The main entry point for orchestrated meeting cognition."""
        
        logger.info("🕸️  AgentGraphOrchestrator: Building execution graph...")
        
        # 1. Context Builder
        # Aggregates transcript + behavior profile preamble
        from app.services.behavior.meeting_context import _format_dimensions
        behavior_context = _format_dimensions(profile.to_dict())

        # 2. Graph Dispatch & Dependency Management
        # In Phase 9.6, we support a fixed graph that executes agents 
        # based on the `enabled_agents` list.
        
        enabled = profile.enabled_agents or []
        logger.info("🤖 Enabled Agents: %s", enabled)

        # For now, we use the monolithic TranscriptAnalyzer as the "Master Agent"
        # that handles Summary, Tasks, and Decisions. 
        # In a full 9.6 implementation, these would be separate fanned-out calls.
        
        # Consolidation Layer
        result: ExtractionSummary = TranscriptAnalyzer.analyze(
            transcript, 
            behavior_context, 
            contract_model=ExtractionSummary
        )

        # 3. Dependency-based Agent execution (Deterministic & Policy-Governed)
        if "crm-agent" in enabled:
            try:
                cls._run_crm_agent(result, profile)
            except Exception as e:
                logger.error("AgentGraph: crm-agent failed: %s", e)
        
        if "risk-analyzer" in enabled:
            try:
                cls._run_risk_agent(result, profile)
            except Exception as e:
                logger.error("AgentGraph: risk-analyzer failed: %s", e)

        return result

    @staticmethod
    def _run_crm_agent(extraction: ExtractionSummary, profile: ResolvedBehaviorProfile):
        """Specialized agent that depends on extracted summary/tasks."""
        logger.info("💼 CRM Agent: Syncing extracted data to CRM context...")
        # 9.6 logic: Map extraction.action_items to CRM leads/deals.

    @staticmethod
    def _run_risk_agent(extraction: ExtractionSummary, profile: ResolvedBehaviorProfile):
        """Specialized agent that analyzes extraction for project risks."""
        logger.info("⚠️ Risk Agent: Analyzing extractions for project blockers...")
        # 9.6 logic: Evaluate extraction.risks against historical patterns.
