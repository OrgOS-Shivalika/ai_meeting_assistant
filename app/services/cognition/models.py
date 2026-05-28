from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class CognitionFragment(BaseModel):
    """A normalized piece of intelligence emitted by a skill or agent."""
    type: Literal["summary", "title", "action_item", "decision", "risk", "modular_insight"]
    content: Any
    source_skill: str
    confidence: float = 1.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ModularInsight(BaseModel):
    """Extensible support for future cognition types."""
    category: str  # technical_debt, stakeholder_conflict, roadmap_risk, etc.
    label: str
    value: Any
    evidence: Optional[str] = None
    source_skills: List[str] = Field(default_factory=list)

class SynthesisTrace(BaseModel):
    """Traceability for merged insights."""
    source_fragments: List[str] = Field(default_factory=list) # List of skill IDs
    merge_reason: str
    confidence_score: float

SKILL_AUTHORITY = {
    "executive": 100,
    "compliance": 95,
    "engineering": 90,
    "product": 85,
    "scrum": 70,
    "generic": 10,
}

# Domain to Authority Category mapping
DOMAIN_TO_AUTHORITY = {
    "executive": "executive",
    "compliance": "compliance",
    "engineering": "engineering",
    "product": "product",
    "meetings": "scrum",
    "incidents": "engineering",
}

def get_skill_authority(skill_id: str) -> int:
    """Helper to get authority score based on skill domain."""
    # Default to generic
    category = "generic"
    for domain, auth_cat in DOMAIN_TO_AUTHORITY.items():
        if skill_id.startswith(domain):
            category = auth_cat
            break
            
    return SKILL_AUTHORITY.get(category, 10)
