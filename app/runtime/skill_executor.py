"""Phase 3 — Skill Execution Engine.

Responsible for executing modular cognition units (Skills).
Flow: Assembly -> Retrieval -> Execution -> Validation -> Events
"""
import logging
import json
from typing import Dict, Any, List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.skills.base import SkillDefinition, RetrievalConfig
from app.utils.logger import setup_logger
from app.services.behavior.resolver import ResolvedBehaviorProfile
# Use the same OpenAI client initialization as the transcript analyzer for consistency
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = setup_logger(__name__)

class SkillExecutor:
    """Executes modular capabilities represented by SkillDefinitions."""

    @classmethod
    def execute_skill(
        cls, 
        db: Session,
        skill: SkillDefinition, 
        transcript: str, 
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes a single skill end-to-end.
        """
        logger.info(f"⚙️  SkillExecutor: Starting execution for skill '{skill.id}' ({skill.name})")

        # 0. Governance (Phase 8 Permissions)
        if not cls._check_permissions(skill, profile):
            logger.warning(f"🚫 SkillExecutor: Governance gate blocked skill '{skill.id}' due to missing tool permissions.")
            return {"error": "Missing tool permissions", "skill_id": skill.id}

        # 1. Assembly (Prompts)
        system_prompt = cls._assemble_prompt(skill, profile)

        # 2. Retrieval (Phase 6)
        retrieval_context = cls._inject_retrieval(
            db, 
            profile.organization_id, 
            transcript, 
            skill.retrieval_config
        )

        # 3. Model Execution
        raw_output = cls._execute_model(system_prompt, transcript, retrieval_context)

        # 4. Output Validation
        validated_output = cls._validate_output(raw_output, skill.output_schema)

        # 5. Event Emission (Phase 7)
        cls._emit_events(db, skill.emits_events, validated_output, profile, meeting_id)

        logger.info(f"✅ SkillExecutor: Completed execution for skill '{skill.id}'")
        return validated_output

    @classmethod
    def _assemble_prompt(cls, skill: SkillDefinition, profile: ResolvedBehaviorProfile) -> str:
        """
        Assembles the layered system prompt.
        FINAL SYSTEM PROMPT = Global Prompt + Organization Intent + Agent Identity + Skill Prompt + Overrides 
        """
        from app.services.behavior.meeting_context import _format_dimensions
        
        # 1. Organization & Template Intent
        # _format_dimensions distills the merged BehaviorProfile into plain English guidance.
        workspace_context = _format_dimensions(profile.to_dict())

        # 2. Skill Specific Constraints
        skill_prompt = skill.system_prompt
        
        # 3. Output Schema Constraints
        schema_instruction = ""
        if skill.output_schema:
            schema_instruction = (
                f"\nYour output MUST exactly match the following JSON schema:\n"
                f"{json.dumps(skill.output_schema, indent=2)}\n"
            )

        # Assemble the layered prompt
        components = [
            "=== AI ORCHESTRATOR SYSTEM INSTRUCTIONS ===",
            "You are a specialized enterprise AI module executing a dedicated cognitive skill.",
            "",
            "--- SKILL MISSION ---",
            skill_prompt,
            ""
        ]

        if workspace_context:
            components.extend([
                "--- WORKSPACE INTENT & BEHAVIOR OVERRIDES ---",
                "The following guidelines take precedence over general AI behaviors:",
                workspace_context,
                ""
            ])

        components.extend([
            "--- OUTPUT CONSTRAINTS ---",
            "You must respond ONLY with valid JSON. Do not include markdown formatting or explanations.",
            schema_instruction
        ])

        return "\n".join(components).strip()

    @classmethod
    def _inject_retrieval(
        cls, 
        db: Session, 
        organization_id: UUID, 
        transcript: str, 
        config: RetrievalConfig
    ) -> str:
        """
        Injects memory/data based on the skill's retrieval_config.
        """
        # If no retrieval requested, skip
        if not config.sources and not config.search_bias:
            return ""

        logger.info(f"🔍 SkillExecutor: Performing skill-level retrieval (bias: {config.search_bias})")
        
        from app.services.rag.retrieval import retrieve
        from app.schemas.rag_schema import QueryPlan
        
        # Build a minimal QueryPlan for the skill
        plan = QueryPlan(
            query_type="factual",
            effective_scope_type="global", 
            effective_scope_id=None,
            detected_entity_names=[],
            confidence=1.0
        )
        
        # Map skill sources to retrieval filter
        sources_filter = "all"
        if config.sources:
            if "meeting_notes" in config.sources and "architecture_docs" not in config.sources:
                sources_filter = "meetings"
            elif "architecture_docs" in config.sources and "meeting_notes" not in config.sources:
                sources_filter = "documents"

        try:
            bundle = retrieve(
                db=db,
                organization_id=organization_id,
                query_text=config.search_bias or transcript[:500],
                plan=plan,
                top_k_final=config.top_k,
                sources=sources_filter
            )
            
            if not bundle.has_context:
                logger.debug("SkillExecutor: No context found during retrieval.")
                return ""

            # Format the bundle into a context string
            context_parts = []
            for i, chunk in enumerate(bundle.chunks):
                source = f"[{chunk.source_type} {chunk.meeting_title or chunk.document_name or 'Unknown'}]"
                context_parts.append(f"--- CONTEXT BLOCK {i+1} {source} ---\n{chunk.chunk_text}")
            
            logger.debug(f"SkillExecutor: Injected {len(bundle.chunks)} context blocks.")
            return "\n\n".join(context_parts)
        except Exception as e:
            logger.warning(f"Skill retrieval failed: {e}")
            return ""

    @classmethod
    def _execute_model(cls, system_prompt: str, user_input: str, retrieval_context: str) -> str:
        """Calls the LLM provider."""
        client = _get_client()
        
        user_content = user_input
        if retrieval_context:
            user_content = f"CONTEXT:\n{retrieval_context}\n\nINPUT:\n{user_input}"

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                response_format={"type": "json_object"},
                timeout=60
            )
            return response.choices[0].message.content or "{}"
        except Exception as e:
            logger.error(f"LLM execution failed: {str(e)}")
            raise

    @classmethod
    def _validate_output(cls, raw_output: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates the raw LLM output against the skill's output_schema.
        """
        try:
            parsed = json.loads(raw_output)
            # In a full implementation, we would validate `parsed` against the JSON schema
            # using something like jsonschema or dynamically generated Pydantic models.
            return parsed
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM output as JSON.")
            return {"error": "Invalid JSON output", "raw": raw_output}

    @classmethod
    def _emit_events(
        cls, 
        db: Session,
        events: List[str], 
        payload: Dict[str, Any],
        profile: ResolvedBehaviorProfile,
        meeting_id: Optional[int] = None
    ) -> None:
        """
        Emits runtime events for automations via the AutomationBus.
        """
        if not events:
            return

        from app.services.automation.bus import AutomationBus, AutomationEvent
        
        for event_type in events:
            logger.info(f"📡 SkillExecutor: Emitting event '{event_type}'")
            
            event = AutomationEvent(
                event_type=event_type,
                organization_id=profile.organization_id,
                meeting_id=meeting_id or -1,
                payload=payload
            )
            
            try:
                AutomationBus.emit(db, event, profile)
            except Exception as e:
                logger.error(f"SkillExecutor: Failed to emit event {event_type}: {e}")

    @classmethod
    def _check_permissions(cls, skill: SkillDefinition, profile: ResolvedBehaviorProfile) -> bool:
        """
        Verifies that the workspace has authorized all tools required by the skill.
        """
        if not skill.required_tools:
            return True

        # Extract allowed tools from profile
        tools_config = profile.tools_and_integrations or {}
        allowed_tools = tools_config.get("allowed_tools", [])
        
        # Check if all required tools are present in allowed list
        # Map skill tools to profile tool identifiers if necessary (e.g., 'jira' -> 'jira_create_issue')
        TOOL_MAP = {
            "jira": "jira_create_issue",
            "slack": "slack_post",
            "github": "github_pull_request" # Placeholder
        }

        for tool in skill.required_tools:
            # Check both the raw name and the mapped identifier
            authorized_name = TOOL_MAP.get(tool.lower(), tool)
            if authorized_name not in allowed_tools and tool not in allowed_tools:
                logger.debug(f"Permission denied: Tool '{tool}' ({authorized_name}) not in allowed list: {allowed_tools}")
                return False

        return True
