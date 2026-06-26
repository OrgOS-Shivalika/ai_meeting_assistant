"""Phase 2 — Modular Agent Orchestrators.

Defines the AgentOrchestrator contract. Agents are now pure managers of skills.
"""
from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.skills.registry import SkillRegistry
from app.skills.base import SkillDefinition

logger = logging.getLogger(__name__)

class AgentOrchestrator(BaseModel):
    """A pure orchestrator that coordinates modular skills."""
    id: str = Field(..., description="Unique slug for the agent (e.g. 'technical-analyst')")
    name: str = Field(..., description="Human-readable agent name")
    description: str = Field(..., description="What this agent manages")
    
    # The set of skills this agent can coordinate
    skills: List[str] = Field(default_factory=list)
    
    def get_resolved_skills(self) -> List[SkillDefinition]:
        """Fetch the full definitions for all skills managed by this agent."""
        return [SkillRegistry.get(sid) for sid in self.skills if SkillRegistry.get(sid)]

    def resolve_conflicts(self, outputs: Dict[str, Any]) -> Any:
        """Future: Resolve overlapping or conflicting skill outputs."""
        return outputs

# ---------------------------------------------------------------------------
# Core Agent Definitions (The Refactor)
# ---------------------------------------------------------------------------

engineering_agent = AgentOrchestrator(
    id="engineering-agent",
    name="Engineering Orchestrator",
    description="Coordinates architecture, code quality, dependency, and performance analysis.",
    skills=["architecture_review", "code_review", "dependency_mapping", "api_review", "security_audit", "performance_profiling"]
)

incident_agent = AgentOrchestrator(
    id="incident-agent",
    name="Incident Orchestrator",
    description="Coordinates incident detection, RCA, postmortems, and mitigation planning.",
    skills=["incident_detection", "root_cause_analysis", "postmortem_generator", "impact_assessment", "mitigation_planning"]
)

meeting_scrum_agent = AgentOrchestrator(
    id="meeting-scrum-agent",
    name="Meeting Scrum Orchestrator",
    description="Coordinates context research, summaries, action items, decisions, and agenda tracking.",
    # `meeting_context_researcher` runs first so its brief is available
    # to downstream skills via the harness audit log. It declares
    # required_tools, so under harness_enabled=on it routes through
    # run_loop() and writes invocations to agent_tool_invocations.
    skills=["meeting_context_researcher", "summaries", "action_items", "decisions", "sentiment_analysis", "agenda_tracking"]
)

product_agent = AgentOrchestrator(
    id="product-agent",
    name="Product Orchestrator",
    description="Coordinates feature extraction, pain points, competitor analysis, and success metrics.",
    skills=["feature_extraction", "user_pain_points", "competitor_analysis", "roadmap_alignment", "success_metrics"]
)

executive_agent = AgentOrchestrator(
    id="executive-agent",
    name="Executive Orchestrator",
    description="Coordinates strategic alignment, risk rollup, budget, and executive briefings.",
    skills=["strategic_alignment", "risk_rollup", "investment_areas", "blocker_escalation", "key_takeaways"]
)

compliance_agent = AgentOrchestrator(
    id="compliance-agent",
    name="Compliance Orchestrator",
    description="Coordinates PII detection, policy checks, regulatory audits, and access controls.",
    skills=["pii_detection", "policy_violation", "regulatory_audit", "access_control", "data_retention"]
)

# Keep legacy IDs mapping to the new agents to preserve database entries or tests, or just replace them entirely.
# Let's replace them entirely since this is a refactoring phase.

# --- LEGACY AGENT ALIASES FOR BACKWARD COMPATIBILITY ---
summary_agent = AgentOrchestrator(
    id="summary-agent",
    name="Summary Orchestrator",
    description="Legacy alias for summaries.",
    skills=["summaries"]
)

risk_agent = AgentOrchestrator(
    id="risk-analyzer",
    name="Risk Orchestrator",
    description="Legacy alias for risk detection.",
    skills=["incident_detection", "risk_rollup", "impact_assessment"]
)

technical_analyst_agent = AgentOrchestrator(
    id="technical-analyst",
    name="Technical Engineering Orchestrator",
    description="Legacy alias for engineering.",
    skills=["architecture_review", "api_review", "dependency_mapping"]
)

action_item_agent = AgentOrchestrator(
    id="action-item-manager",
    name="Action Item Orchestrator",
    # Legacy alias kept so workspaces with this id in enabled_agents
    # don't break, but its skill list is now empty — action_items now
    # lives under meeting-scrum-agent only, otherwise the harness path
    # would create tasks twice (once per agent) for the same skill.
    description="Legacy alias for action items (de-duplicated — action_items now lives under meeting-scrum-agent).",
    skills=[]
)

# ---------------------------------------------------------------------------
# Global Agent Registry
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, AgentOrchestrator] = {
    agent.id: agent for agent in [
        engineering_agent,
        incident_agent,
        meeting_scrum_agent,
        product_agent,
        executive_agent,
        compliance_agent,
        summary_agent,
        risk_agent,
        technical_analyst_agent,
        action_item_agent
    ]
}
