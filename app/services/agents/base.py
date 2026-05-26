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

# 1. Summary Agent: Focuses on recaps and highlights
summary_agent = AgentOrchestrator(
    id="summary-agent",
    name="Summary Orchestrator",
    description="Coordinates meeting summarization and highlight extraction.",
    skills=["meeting_summary"]
)

# 2. Risk Agent: Focuses on threats, outages, and blockers
risk_agent = AgentOrchestrator(
    id="risk-analyzer",
    name="Risk Orchestrator",
    description="Coordinates incident detection and technical risk analysis.",
    skills=["incident_detection", "risk_analysis"]
)

# 3. Technical Analyst Agent: Focuses on engineering depth
technical_analyst_agent = AgentOrchestrator(
    id="technical-analyst",
    name="Technical Engineering Orchestrator",
    description="Coordinates architecture reviews and API analysis.",
    skills=["architecture_review", "api_review", "dependency_mapping"]
)

# 4. Action Item Agent: Focuses on tasks and follow-ups
action_item_agent = AgentOrchestrator(
    id="action-item-manager",
    name="Action Item Orchestrator",
    description="Coordinates task extraction and owner assignment.",
    skills=["task_extraction"]
)

# ---------------------------------------------------------------------------
# Global Agent Registry
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, AgentOrchestrator] = {
    agent.id: agent for agent in [
        summary_agent, 
        risk_agent, 
        technical_analyst_agent, 
        action_item_agent
    ]
}
