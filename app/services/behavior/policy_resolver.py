"""Policy Resolver: Mapping high-level user Intents to low-level Runtime Dimensions.

This service acts as the 'brain' that translates what the user *wants* (Intents)
into what the system *executes* (11-dim BehaviorProfile).
"""
from __future__ import annotations
import logging
from app.schemas.intent_schema import IntentProfile
from app.services.behavior.resolver import ResolvedBehaviorProfile
from uuid import UUID

logger = logging.getLogger(__name__)

class PolicyResolver:
    """Orchestrates the mapping from Intent-Driven UX to deep Runtime bindings."""

    @staticmethod
    def map_intent_to_resolved_profile(
        organization_id: UUID, 
        intent: IntentProfile
    ) -> ResolvedBehaviorProfile:
        """Translates a simplified IntentProfile into the full 11-dimension runtime profile."""
        
        # Initialize an empty profile
        profile = ResolvedBehaviorProfile(organization_id=organization_id)

        # 1. AI Behavior -> master_prompt, tone_and_personality
        profile.tone_and_personality = {
            "formality": intent.behavior.communication_style if intent.behavior.communication_style != "empathetic" else "professional",
            "verbosity": intent.behavior.communication_style if intent.behavior.communication_style in ["concise", "detailed"] else "standard"
        }
        
        # Note: In a full implementation, this would use Jinja templates for prompts
        # 1. Behavior -> master_prompt
        profile.master_prompt = {
            "system": f"You are the {intent.behavior.role_focus}.",
            "behavior": intent.behavior.custom_instructions or "Focus on accuracy and conciseness.",
            "citation": "Every factual claim MUST be followed by one or more [N] tags pointing to the source block(s) that support it.",
            "retrieval": "Use ONLY the numbered context blocks provided in the input.",
            "output": f"Depth: {intent.behavior.response_depth}",
            "guardrails": "Do NOT speculate, guess, or fall back to general knowledge. If the context is insufficient, state so clearly."
        }
        # 2. Capabilities -> enabled_agents, extraction_rules, output_config
        agents = ["action-item-manager"] # Legacy default alias for backward compatibility
        extractions = ["person", "decision", "action_item"]
        sections = []

        if intent.capabilities.summaries or intent.capabilities.action_items or intent.capabilities.decisions:
            agents.append("meeting-scrum-agent")
            if intent.capabilities.summaries:
                sections.append("summary")
            if intent.capabilities.action_items:
                sections.append("action_items")
            if intent.capabilities.decisions:
                sections.append("decisions")

        if intent.capabilities.risk_detection or intent.capabilities.incident_detection:
            agents.append("incident-agent")
            extractions.append("risk")
            extractions.append("incident")
            sections.append("risks")
            sections.append("incidents")
            # Legacy aliases
            if intent.capabilities.risk_detection:
                agents.append("risk-analyzer")
            if intent.capabilities.incident_detection:
                agents.append("incident-investigator")

        if intent.capabilities.technical_analysis or intent.capabilities.architecture_review:
            agents.append("engineering-agent")
            extractions.append("technical_blocker")
            # Legacy alias
            if intent.capabilities.technical_analysis:
                agents.append("technical-analyst")

        # In Phase 5, the frontend's unified toggles now resolve to our modular Skill Orchestrators
        profile.enabled_agents = list(set(agents))
        profile.extraction_rules = {
            "entities": extractions,
            "extract_action_items": intent.capabilities.action_items,
            "extract_decisions": intent.capabilities.decisions
        }
        profile.output_config = {"sections": sections}

        # 3. Knowledge Access -> retrieval_config, memory_config
        # System-managed defaults driven by intent
        profile.retrieval_config = {
            "top_k_vector": 20 if intent.knowledge_access.meeting_history else 0,
            "max_graph_depth": 2 if intent.knowledge_access.past_decisions else 1,
            "rerank_strategy": "importance_aware" if intent.knowledge_access.team_documents else "default"
        }
        profile.memory_config = {
            "consolidation_enabled": intent.knowledge_access.meeting_history
        }

        # 4. Privacy & Safety -> compliance_and_guardrails
        profile.compliance_and_guardrails = {
            "redact_pii": intent.privacy_safety.redact_pii,
            "data_residency": intent.privacy_safety.data_residency,
            "restrict_external_sharing": intent.privacy_safety.restrict_external_sharing,
            "require_manual_review": intent.privacy_safety.require_approval_before_escalation
        }

        # 5. Automations -> automation_rules
        profile.automation_rules = {
            "post_meeting_summary": intent.automations.slack_summary,
            "sync_to_crm": intent.automations.jira_tasks,
            "escalation_alert": intent.automations.high_risk_escalation,
            "notify_stakeholders": intent.automations.stakeholder_notification
        }

        # 6. Connected Tools -> tools_and_integrations
        allowed = ["search_knowledge_base"]
        if intent.connected_tools.slack_enabled: allowed.append("slack_post")
        if intent.connected_tools.jira_enabled: allowed.append("jira_create_issue")
        
        profile.tools_and_integrations = {
            "allowed_tools": allowed,
            "denied_tools": [],
            "temperature": 0.3 # System-managed
        }

        return profile
