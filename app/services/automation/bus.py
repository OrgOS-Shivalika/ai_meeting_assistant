"""Phase 9.5 — Event Automation Layer.

Decouples the meeting pipeline from external side-effects (Slack, Jira, Webhooks).
The pipeline emits normalized events; the bus dispatches them to handlers
authorized by the BehaviorProfile.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List
from uuid import UUID
from app.services.behavior.resolver import ResolvedBehaviorProfile

logger = logging.getLogger(__name__)

class AutomationEvent:
    """A normalized runtime event."""
    def __init__(self, event_type: str, organization_id: UUID, meeting_id: int, payload: Any):
        self.event_type = event_type
        self.organization_id = organization_id
        self.meeting_id = meeting_id
        self.payload = payload

class AutomationBus:
    """Decoupled event dispatcher for organizational side-effects."""

    _handlers: Dict[str, List[Callable]] = {}

    @classmethod
    def subscribe(cls, event_type: str, handler: Callable):
        if event_type not in cls._handlers:
            cls._handlers[event_type] = []
        cls._handlers[event_type].append(handler)

    @classmethod
    def emit(cls, db, event: AutomationEvent, profile: ResolvedBehaviorProfile):
        """Dispatches an event to all authorized handlers."""
        rules = profile.automation_rules or {}
        
        logger.info(
            "📢 AutomationBus: Emitting %s for meeting=%s (org=%s)",
            event.event_type, event.meeting_id, event.organization_id
        )

        # 1. Webhook Automation
        if rules.get("webhook_url"):
            try:
                cls._dispatch_webhook(event, rules["webhook_url"])
            except Exception as e:
                logger.error("AutomationBus: Webhook dispatch failed: %s", e)

        # 2. Slack Automation
        if rules.get("slack_post") or rules.get("post_meeting_summary"):
            try:
                cls._dispatch_slack(event, rules)
            except Exception as e:
                logger.error("AutomationBus: Slack dispatch failed: %s", e)

        # 3. CRM Sync (Jira/Salesforce placeholder)
        if rules.get("sync_to_crm"):
            try:
                cls._dispatch_crm(event, rules)
            except Exception as e:
                logger.error("AutomationBus: CRM sync failed: %s", e)

    @staticmethod
    def _dispatch_webhook(event: AutomationEvent, url: str):
        logger.info("🔗 Dispatching Webhook to %s", url)
        # 9.5 Placeholder: In a real implementation, this would be a 
        # background Celery task (dispatch_webhook_task.delay(url, payload)).
        try:
            # import requests
            # requests.post(url, json=event.__dict__, timeout=5)
            pass
        except Exception as e:
            logger.error("Webhook dispatch failed: %s", e)

    @staticmethod
    def _dispatch_slack(event: AutomationEvent, rules: dict):
        # 9.5 Placeholder: Integration with Slack API.
        if event.event_type == "meeting.summary.completed":
            logger.info("💬 Posting summary to Slack (authorized by BehaviorProfile)")

    @staticmethod
    def _dispatch_crm(event: AutomationEvent, rules: dict):
        # 9.5 Placeholder: Integration with Jira/Salesforce.
        if event.event_type == "meeting.tasks.extracted":
            logger.info("🎟️ Syncing action items to CRM/Jira (authorized by BehaviorProfile)")


# ---------------------------------------------------------------------------
# Standard Event Types
# ---------------------------------------------------------------------------
# - meeting.summary.completed
# - meeting.tasks.extracted
# - meeting.decisions.created
# - meeting.risk.detected
