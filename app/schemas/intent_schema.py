"""Simplified Intent-Driven Control Schemas.

These models abstract complex runtime internals (Top-K, Weights, Graph Depth)
into high-level user intents.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field

class AIBehaviorIntent(BaseModel):
    role_focus: str = Field(..., description="The primary role or focus of the AI.")
    custom_instructions: Optional[str] = Field(None, description="Specific behavioral rules.")
    communication_style: Literal["professional", "casual", "concise", "detailed", "empathetic"] = "professional"
    response_depth: Literal["brief", "standard", "comprehensive"] = "standard"

class CapabilitiesIntent(BaseModel):
    summaries: bool = True
    action_items: bool = True
    decisions: bool = True
    risk_detection: bool = False
    technical_analysis: bool = False
    architecture_review: bool = False
    incident_detection: bool = False
    follow_ups: bool = True

class AutomationsIntent(BaseModel):
    slack_summary: bool = False
    jira_tasks: bool = False
    high_risk_escalation: bool = False
    stakeholder_notification: bool = False

class KnowledgeAccessIntent(BaseModel):
    meeting_history: bool = True
    team_documents: bool = True
    past_decisions: bool = True
    architecture_docs: bool = False
    incidents_outages: bool = False

class PrivacySafetyIntent(BaseModel):
    redact_pii: bool = True
    restrict_external_sharing: bool = True
    require_approval_before_escalation: bool = False
    data_residency: Literal["default", "restricted"] = "default"

class ConnectedToolsIntent(BaseModel):
    slack_enabled: bool = False
    jira_enabled: bool = False
    github_enabled: bool = False
    notion_enabled: bool = False
    crm_enabled: bool = False

class IntentProfile(BaseModel):
    """The high-level intent profile presented to the user."""
    behavior: AIBehaviorIntent = Field(default_factory=lambda: AIBehaviorIntent(role_focus="General Assistant"))
    capabilities: CapabilitiesIntent = Field(default_factory=CapabilitiesIntent)
    automations: AutomationsIntent = Field(default_factory=AutomationsIntent)
    knowledge_access: KnowledgeAccessIntent = Field(default_factory=KnowledgeAccessIntent)
    privacy_safety: PrivacySafetyIntent = Field(default_factory=PrivacySafetyIntent)
    connected_tools: ConnectedToolsIntent = Field(default_factory=ConnectedToolsIntent)
