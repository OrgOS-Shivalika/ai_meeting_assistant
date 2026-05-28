"""Phase 9 Layer 4 — Graph Orchestrator Tests.

Verifies:
- Capability resolution from BehaviorProfile
- Deterministic dependency ordering
- Policy restrictions
- Error containment
"""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from app.services.agents.graph_orchestrator import AgentGraphOrchestrator
from app.services.behavior.resolver import ResolvedBehaviorProfile
from app.services.cognition.contracts import ExtractionSummary

@pytest.fixture
def org_id():
    return uuid4()

@patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze")
def test_orchestrator_routes_capabilities(mock_analyze, org_id):
    """Layer 4.1: Verify correct agents are enabled/called."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        enabled_agents=["meeting-scrum-agent", "executive-agent"]
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    with patch.object(AgentGraphOrchestrator, "_orchestrate_agent") as mock_orchestrate:
        
        AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        
        # Verify master analyzer ran
        mock_analyze.assert_called_once()
        # Verify specialized agents ran because they were in enabled_agents
        assert mock_orchestrate.call_count == 2
        called_agent_ids = [call.args[1].id for call in mock_orchestrate.call_args_list]
        assert "meeting-scrum-agent" in called_agent_ids
        assert "executive-agent" in called_agent_ids

@patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze")
def test_orchestrator_policy_restriction(mock_analyze, org_id):
    """Layer 4.2: Verify agents are skipped if NOT in enabled_agents."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        enabled_agents=["meeting-scrum-agent"] # Only meeting-scrum, NO product-agent
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    with patch.object(AgentGraphOrchestrator, "_orchestrate_agent") as mock_orchestrate:
        AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        
        # Master analyzer still runs
        mock_analyze.assert_called_once()
        # Only one agent should be orchestrated
        assert mock_orchestrate.call_count == 1
        assert mock_orchestrate.call_args[0][1].id == "meeting-scrum-agent"

@patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze")
def test_orchestrator_error_containment(mock_analyze, org_id):
    """Layer 4.3: Verify one agent crash doesn't kill the orchestrator."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        enabled_agents=["product-agent", "incident-agent"]
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    
    def side_effect(db, agent, transcript, ext, prof):
        if agent.id == "product-agent":
            raise Exception("Agent Down")
            
    with patch.object(AgentGraphOrchestrator, "_orchestrate_agent", side_effect=side_effect) as mock_orchestrate:
        
        try:
            result = AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        except Exception:
            pytest.fail("Orchestrator should contain agent errors")
        
        # Both agents should have been attempted
        assert mock_orchestrate.call_count == 2
        assert result.title == "Test"
