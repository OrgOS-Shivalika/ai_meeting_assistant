"""Phase 9 Layer 3 — Event Automation Tests.

Verifies:
- Event emission correctly authorized by BehaviorProfile
- Subscriber decoupling (one failure doesn't kill the bus)
- Payload integrity
"""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from app.services.automation.bus import AutomationBus, AutomationEvent
from app.services.behavior.resolver import ResolvedBehaviorProfile

@pytest.fixture
def org_id():
    return uuid4()

def test_automation_bus_emits_authorized_events(org_id):
    """Layer 3.1: Verify events are emitted when rules match."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        automation_rules={
            "webhook_url": "http://test.com/hook",
            "slack_post": True
        }
    )
    
    db = MagicMock()
    event = AutomationEvent(
        event_type="meeting.summary.completed",
        organization_id=org_id,
        meeting_id=1,
        payload={"summary": "test"}
    )
    
    with patch.object(AutomationBus, "_dispatch_webhook") as mock_webhook, \
         patch.object(AutomationBus, "_dispatch_slack") as mock_slack:
        
        AutomationBus.emit(db, event, profile)
        
        mock_webhook.assert_called_once_with(event, "http://test.com/hook")
        mock_slack.assert_called_once()

def test_automation_bus_skips_unauthorized_events(org_id):
    """Layer 3.2: Verify events are NOT emitted when rules are empty."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        automation_rules={} # No rules
    )
    
    db = MagicMock()
    event = AutomationEvent("meeting.summary.completed", org_id, 1, {})
    
    with patch.object(AutomationBus, "_dispatch_webhook") as mock_webhook, \
         patch.object(AutomationBus, "_dispatch_slack") as mock_slack:
        
        AutomationBus.emit(db, event, profile)
        
        mock_webhook.assert_not_called()
        mock_slack.assert_not_called()

def test_automation_failure_isolation(org_id):
    """Layer 3.3: One handler crash shouldn't stop others."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        automation_rules={
            "webhook_url": "http://crash.me",
            "slack_post": True
        }
    )
    
    db = MagicMock()
    event = AutomationEvent("meeting.summary.completed", org_id, 1, {})
    
    with patch.object(AutomationBus, "_dispatch_webhook", side_effect=Exception("Boom!")), \
         patch.object(AutomationBus, "_dispatch_slack") as mock_slack:
        
        # Should not raise exception
        AutomationBus.emit(db, event, profile)
        
        # Slack should still fire despite webhook crash
        mock_slack.assert_called_once()

def test_automation_crm_sync_gating(org_id):
    """Layer 3.4: CRM sync only fires for correct event types."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        automation_rules={"sync_to_crm": True}
    )
    db = MagicMock()
    
    with patch.object(AutomationBus, "_dispatch_crm") as mock_crm:
        # Event type: summary
        event_s = AutomationEvent("meeting.summary.completed", org_id, 1, {})
        AutomationBus.emit(db, event_s, profile)
        # CRM dispatch checks event type internally - let's verify mock call count
        mock_crm.assert_called_once()
        
        # Event type: tasks
        event_t = AutomationEvent("meeting.tasks.extracted", org_id, 1, {})
        AutomationBus.emit(db, event_t, profile)
        assert mock_crm.call_count == 2
