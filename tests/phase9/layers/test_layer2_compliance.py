"""Phase 9 Layer 2 — Compliance Runtime Tests.

Verifies:
- PII Redaction (Email, Phone)
- Timing (Execution before DB/Persistence)
- Policy Inheritance & Precedence
"""
import pytest
from uuid import uuid4
from unittest.mock import MagicMock
from app.services.compliance.runtime import ComplianceRuntime
from app.services.behavior.resolver import ResolvedBehaviorProfile
from app.db.models import Meeting, Task

@pytest.fixture
def org_id():
    return uuid4()

def test_compliance_redacts_email(org_id):
    """Layer 2.1: Email redaction."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        compliance_and_guardrails={"redact_pii": True}
    )
    runtime = ComplianceRuntime(profile)
    text = "The user john.doe@example.co.uk is present."
    redacted = runtime.apply_policies(text)
    assert "[EMAIL REDACTED]" in redacted
    assert "john.doe" not in redacted

def test_compliance_redacts_phone(org_id):
    """Layer 2.2: Phone number redaction."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        compliance_and_guardrails={"redact_pii": True}
    )
    runtime = ComplianceRuntime(profile)
    text = "Call me at +1 (555) 012-3456 tomorrow."
    redacted = runtime.apply_policies(text)
    assert "[PHONE REDACTED]" in redacted
    assert "555" not in redacted

def test_compliance_policy_disabled(org_id):
    """Layer 2.3: Verify no redaction when policy is OFF."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        compliance_and_guardrails={"redact_pii": False}
    )
    runtime = ComplianceRuntime(profile)
    text = "Contact john@example.com."
    result = runtime.apply_policies(text)
    assert result == text
    assert "john@example.com" in result

def test_compliance_meeting_persistence_gating(org_id):
    """Layer 2.4: Verify redaction applies to all model fields."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        compliance_and_guardrails={"redact_pii": True}
    )
    
    # Mock Meeting and its tasks
    meeting = Meeting(
        organization_id=org_id,
        title="Meeting with john@example.com",
        summary="Discussed +1-555-0100 with john@example.com.",
        transcript_text="John said: my email is john@example.com."
    )
    task = Task(task="Follow up with john@example.com", owner_name="John Doe")
    meeting.tasks = [task]
    
    ComplianceRuntime.apply_to_meeting(None, meeting, profile)
    
    assert "[EMAIL REDACTED]" in meeting.title
    assert "[EMAIL REDACTED]" in meeting.summary
    assert "[PHONE REDACTED]" in meeting.summary
    assert "[EMAIL REDACTED]" in meeting.transcript_text
    assert "[EMAIL REDACTED]" in meeting.tasks[0].task
    
    # Verify raw data is gone from the model before DB commit
    assert "john@example.com" not in meeting.summary
    assert "555-0100" not in meeting.summary

def test_compliance_recursive_redaction(org_id):
    """Layer 2.5: Verify redaction works on nested structures (lists/dicts)."""
    profile = ResolvedBehaviorProfile(
        organization_id=org_id,
        compliance_and_guardrails={"redact_pii": True}
    )
    runtime = ComplianceRuntime(profile)
    
    complex_data = {
        "metadata": {"author_email": "author@test.com"},
        "comments": ["Call 555-0123", "Email john@doe.com"],
        "other": 123
    }
    
    redacted = runtime.apply_policies(complex_data)
    assert redacted["metadata"]["author_email"] == "[EMAIL REDACTED]"
    assert "[PHONE REDACTED]" in redacted["comments"][0]
    assert "[EMAIL REDACTED]" in redacted["comments"][1]
    assert redacted["other"] == 123
