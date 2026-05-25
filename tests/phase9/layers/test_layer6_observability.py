"""Phase 9 Layer 6 — Observability Tests.

Verifies that the runtime emits the correct signals (logs) for:
- Contract validation failures
- Compliance redactions
- Automation dispatches
- Orchestrator graph execution
"""
import logging
import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from app.services.cognition.contracts import ExtractionContractRuntime, ExtractionSummary
from app.services.compliance.runtime import ComplianceRuntime
from app.services.automation.bus import AutomationBus, AutomationEvent
from app.services.behavior.resolver import ResolvedBehaviorProfile

def test_observability_contract_failure_logs(caplog):
    """Layer 6.1: Verify contract failures are logged for tracing."""
    caplog.set_level(logging.WARNING)
    
    # Passing invalid dict to force ValidationError internally in validate_and_parse
    # but I want to test the repair_output call which logs the warning.
    ExtractionContractRuntime.repair_output(ExtractionSummary, '{"raw": "data"}', Exception("Validation Error"))
    
    assert "Contract validation failed for ExtractionSummary" in caplog.text

def test_observability_compliance_redaction_logs(caplog):
    """Layer 6.2: Verify PII redactions are logged."""
    caplog.set_level(logging.INFO)
    profile = ResolvedBehaviorProfile(
        organization_id=uuid4(),
        compliance_and_guardrails={"redact_pii": True}
    )
    runtime = ComplianceRuntime(profile)
    runtime.apply_policies("Contact john@doe.com")
    
    assert "ComplianceRuntime: Redacted PII from text block" in caplog.text

def test_observability_automation_dispatch_logs(caplog):
    """Layer 6.3: Verify automation dispatches are logged."""
    caplog.set_level(logging.INFO)
    profile = ResolvedBehaviorProfile(
        organization_id=uuid4(),
        automation_rules={"webhook_url": "http://test.com"}
    )
    event = AutomationEvent("test.event", profile.organization_id, 1, {})
    
    AutomationBus.emit(MagicMock(), event, profile)
    
    assert "AutomationBus: Emitting test.event" in caplog.text
    assert "Dispatching Webhook to http://test.com" in caplog.text

def test_observability_orchestrator_logs(caplog):
    """Layer 6.4: Verify orchestrator execution signals."""
    caplog.set_level(logging.INFO)
    from app.services.agents.graph_orchestrator import AgentGraphOrchestrator
    
    profile = ResolvedBehaviorProfile(
        organization_id=uuid4(),
        enabled_agents=["crm-agent"]
    )
    
    with patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze") as mock_analyze:
        mock_analyze.return_value = ExtractionSummary(title="T", summary="S")
        AgentGraphOrchestrator.run_meeting_analysis(MagicMock(), "transcript", profile)
    
    assert "AgentGraphOrchestrator: Building execution graph" in caplog.text
    assert "Enabled Agents: ['crm-agent']" in caplog.text
    assert "CRM Agent: Syncing extracted data" in caplog.text
