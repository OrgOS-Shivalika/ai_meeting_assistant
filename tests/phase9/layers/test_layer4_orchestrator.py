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
        enabled_agents=["summary-agent", "crm-agent", "risk-analyzer"]
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    with patch.object(AgentGraphOrchestrator, "_run_crm_agent") as mock_crm, \
         patch.object(AgentGraphOrchestrator, "_run_risk_agent") as mock_risk:
        
        AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        
        # Verify master analyzer ran
        mock_analyze.assert_called_once()
        # Verify specialized agents ran because they were in enabled_agents
        mock_crm.assert_called_once()
        mock_risk.assert_called_once()

@patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze")
def test_orchestrator_policy_restriction(mock_analyze, org_id):
    """Layer 4.2: Verify agents are skipped if NOT in enabled_agents."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        enabled_agents=["summary-agent"] # Only summary, NO crm-agent
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    with patch.object(AgentGraphOrchestrator, "_run_crm_agent") as mock_crm:
        AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        
        # Master analyzer still runs
        mock_analyze.assert_called_once()
        # CRM agent should be skipped
        mock_crm.assert_not_called()

@patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze")
def test_orchestrator_error_containment(mock_analyze, org_id):
    """Layer 4.3: Verify one agent crash doesn't kill the orchestrator."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        enabled_agents=["crm-agent", "risk-analyzer"]
    )
    
    mock_analyze.return_value = ExtractionSummary(title="Test", summary="test")
    
    db = MagicMock()
    with patch.object(AgentGraphOrchestrator, "_run_crm_agent", side_effect=Exception("CRM Down")), \
         patch.object(AgentGraphOrchestrator, "_run_risk_agent") as mock_risk:
        
        # Should not raise exception (orchestrator should handle agent failures)
        # Note: In the current implementation 9.6, we haven't added explicit 
        # try/except around individual agent calls in the placeholder. 
        # Let's adjust the orchestrator if this fails.
        try:
            AgentGraphOrchestrator.run_meeting_analysis(db, "transcript", profile)
        except Exception:
            pytest.fail("Orchestrator should contain agent errors")
        
        # Risk agent should still have been called (if parallel or handled)
        # In the current sequential placeholder, it might stop if not handled.
        mock_risk.assert_called_once()
