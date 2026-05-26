"""Phase 1 Verification: Skill Foundation.

Tests the SkillDefinition contract and the SkillRegistry lookup.
"""
import pytest
from app.skills.registry import SkillRegistry
from app.skills.base import SkillDefinition

# Trigger registrations by importing the skill modules
import app.skills.meetings.summaries
import app.skills.engineering.architecture_review
import app.skills.incidents.incident_detection

def test_skill_registration():
    """Verify that skills are correctly registered and retrievable."""
    skill = SkillRegistry.get("meeting_summary")
    assert skill is not None
    assert skill.name == "Meeting Summarization"
    assert "Summaries" in skill.capabilities

def test_capability_resolution():
    """Verify that high-level capabilities resolve to multiple specialized skills."""
    # "Risk Detection" should resolve to both 'risk_analysis' (not implemented yet) 
    # and 'incident_detection' (implemented).
    # Since risk_analysis isn't registered yet, we expect at least incident_detection.
    resolved = SkillRegistry.resolve_skills_for_capabilities(["Risk Detection"])
    skill_ids = [s.id for s in resolved]
    
    assert "incident_detection" in skill_ids
    # Check "Summaries"
    resolved_sum = SkillRegistry.resolve_skills_for_capabilities(["Summaries"])
    assert any(s.id == "meeting_summary" for s in resolved_sum)

def test_registry_validation():
    """Verify that the registry detects missing skill definitions."""
    # We know 'risk_analysis' is missing because we haven't registered it yet
    assert SkillRegistry.validate_registry() is False
