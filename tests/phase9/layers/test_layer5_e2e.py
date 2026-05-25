"""Phase 9 Layer 5 — End-to-End Runtime Tests.

Verifies the entire deterministic cognition pipeline in integrated scenarios.
"""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from app.pipelines.meeting_pipeline import MeetingPipeline
from app.db.models import Meeting, Organization, User
from app.services.cognition.contracts import ExtractionSummary
from app.services.behavior.resolver import ResolvedBehaviorProfile

@pytest.fixture
def e2e_fixtures():
    org_id = uuid4()
    user_id = uuid4()
    org = Organization(id=org_id, name="E2E Org")
    user = User(id=user_id, organization_id=org_id, email="e2e@test.com")
    
    meeting = Meeting(
        id=1,
        organization_id=org_id,
        user_id=user_id,
        meeting_url="http://test.com",
        status="pending"
    )
    meeting.user = user # For relationship lookups
    return {"meeting": meeting, "org": org, "user": user}

@patch("app.services.recall_ai_service.RecallService.create_bot")
@patch("app.services.recall_ai_service.RecallService.wait_for_transcript")
@patch("requests.get")
@patch("app.services.agents.graph_orchestrator.AgentGraphOrchestrator.run_meeting_analysis")
def test_e2e_standard_meeting_flow(mock_run_analysis, mock_get, mock_wait, mock_create, e2e_fixtures):
    """Layer 5.1: Standard meeting E2E."""
    db = MagicMock()
    meeting = e2e_fixtures["meeting"]
    
    # Mock external services
    mock_create.return_value = {"id": "bot_123"}
    mock_wait.return_value = "http://transcript.com"
    mock_get.return_value.json.return_value = [] # Empty transcript
    
    # Mock Orchestrated Analysis output (Contract-First)
    mock_run_analysis.return_value = ExtractionSummary(
        title="E2E Standard",
        summary="Everything worked.",
        action_items=[{"task": "Verify E2E", "owner": "AI"}]
    )
    
    pipeline = MeetingPipeline()
    # Mock save_participants and broadcast to keep it simple
    with patch.object(pipeline, "save_participants"), \
         patch.object(pipeline, "save_tasks"), \
         patch("app.services.behavior.resolver.resolve_behavior_profile") as mock_resolve, \
         patch("app.services.compliance.runtime.ComplianceRuntime.apply_to_meeting") as mock_compliance, \
         patch("app.services.automation.bus.AutomationBus.emit") as mock_emit:
        
        mock_resolve.return_value = ResolvedBehaviorProfile(organization_id=meeting.organization_id)
        
        pipeline.run(db, meeting)
        
        # Verify layer progression
        assert meeting.status == "completed"
        assert meeting.title == "E2E Standard"
        
        # Verify Orchestrator was used
        mock_run_analysis.assert_called_once()
        
        # Verify Compliance Gating ran
        mock_compliance.assert_called_once()
        
        # Verify Automation Events were emitted
        assert mock_emit.call_count >= 1

@patch("app.services.recall_ai_service.RecallService.create_bot")
@patch("app.services.recall_ai_service.RecallService.wait_for_transcript")
@patch("requests.get")
@patch("app.services.agents.graph_orchestrator.AgentGraphOrchestrator.run_meeting_analysis")
def test_e2e_sensitive_data_protection(mock_run_analysis, mock_get, mock_wait, mock_create, e2e_fixtures):
    """Layer 5.2: Sensitive data protection E2E."""
    db = MagicMock()
    meeting = e2e_fixtures["meeting"]
    
    mock_create.return_value = {"id": "bot_123"}
    mock_wait.return_value = "http://transcript.com"
    mock_get.return_value.json.return_value = []
    
    # AI returns raw PII (simulating a "soft" prompt failure or just a normal extraction)
    mock_run_analysis.return_value = ExtractionSummary(
        title="Sensitive Meeting",
        summary="Contact john@leak.com at 555-0000.",
        action_items=[]
    )
    
    pipeline = MeetingPipeline()
    
    # Enable PII redaction in profile
    profile = ResolvedBehaviorProfile(
        organization_id=meeting.organization_id,
        compliance_and_guardrails={"redact_pii": True}
    )
    
    with patch.object(pipeline, "save_participants"), \
         patch.object(pipeline, "save_tasks"), \
         patch("app.services.behavior.resolver.resolve_behavior_profile", return_value=profile), \
         patch("app.services.automation.bus.AutomationBus.emit") as mock_emit:
        
        pipeline.run(db, meeting)
        
        # Verify the meeting summary in DB is redacted BEFORE persistence
        # (Actually pipeline calls db.commit() twice, once for raw AI output, 
        # then ComplianceRuntime.apply_to_meeting calls db.commit() again).
        assert "[EMAIL REDACTED]" in meeting.summary
        assert "john@leak.com" not in meeting.summary
        
        # Verify that outbound automation events ALSO contain redacted data
        # Because we emit events AFTER redaction in the pipeline.
        event_call = mock_emit.call_args_list[0]
        event_payload = event_call[0][1].payload
        assert "[EMAIL REDACTED]" in event_payload["summary"]
