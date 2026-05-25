"""Phase 9.3 — Compliance Runtime.

Governs data handling policies (PII, retention, restricted entities).
Acting as a gatekeeper before data hits any persistent store or outbound channel.
"""
from __future__ import annotations

import re
import logging
from typing import Any, Optional
from app.services.behavior.resolver import ResolvedBehaviorProfile

logger = logging.getLogger(__name__)

# Basic PII regex patterns
EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_RE = re.compile(r'\+?\d[\d\-\(\) ]{6,}\d')

class ComplianceRuntime:
    """Governs runtime data handling based on BehaviorProfile compliance rules."""

    def __init__(self, profile: ResolvedBehaviorProfile):
        self.profile = profile
        self.compliance = profile.compliance_and_guardrails or {}

    def apply_policies(self, data: Any) -> Any:
        """Apply all active compliance policies to the data."""
        if not data:
            return data

        if self.compliance.get("redact_pii"):
            data = self.redact_pii(data)
        
        # Future: restricted_entities, retention_policy, etc.
        return data

    def redact_pii(self, data: Any) -> Any:
        """Recursively redact PII from strings, lists, and dicts."""
        if isinstance(data, str):
            return self._redact_string(data)
        elif isinstance(data, list):
            return [self.redact_pii(item) for item in data]
        elif isinstance(data, dict):
            return {k: self.redact_pii(v) for k, v in data.items()}
        return data

    def _redact_string(self, text: str) -> str:
        """Mask emails and phone numbers in a string."""
        original = text
        text = EMAIL_RE.sub("[EMAIL REDACTED]", text)
        text = PHONE_RE.sub("[PHONE REDACTED]", text)
        
        if text != original:
            logger.info("ComplianceRuntime: Redacted PII from text block.")
            # 9.3 Observability/Explainability placeholder
            # Log the redaction event (which fields, why) to runtime_logs.
            
        return text

    @classmethod
    def apply_to_meeting(cls, db, meeting, profile: ResolvedBehaviorProfile):
        """Helper to apply policies to a Meeting model before commit."""
        runtime = cls(profile)
        
        if meeting.summary:
            meeting.summary = runtime.apply_policies(meeting.summary)
        
        if meeting.title:
            meeting.title = runtime.apply_policies(meeting.title)
            
        # Redact tasks
        if hasattr(meeting, 'tasks'):
            for task in meeting.tasks:
                task.task = runtime.apply_policies(task.task)
                if task.owner_name:
                    task.owner_name = runtime.apply_policies(task.owner_name)

        # Note: transcript_raw is generally left untouched as per plan 
        # (archival access), but summary/decisions/tasks are redacted.
        # transcript_text (cleaned) might also need redaction if it's 
        # exposed to standard retrieval.
        if meeting.transcript_text:
            meeting.transcript_text = runtime.apply_policies(meeting.transcript_text)
