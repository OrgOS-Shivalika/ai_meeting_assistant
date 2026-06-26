import logging
from typing import Dict, Any, List, Optional
from app.services.cognition.models import CognitionFragment

logger = logging.getLogger(__name__)


class CognitionNormalizer:
    """Translates raw skill outputs and agent results into standardized CognitionFragments."""

    @classmethod
    def _map_keys(cls, data: Dict[str, Any], mapping: Dict[str, List[str]]) -> Dict[str, Any]:
        """Maps varied keys from LLM output to standard schema keys."""
        if not isinstance(data, dict):
            return data

        out = data.copy()
        for target_key, variants in mapping.items():
            if target_key in out and out[target_key]:
                continue # Already has the correct key

            for variant in variants:
                if variant in out and out[variant]:
                    out[target_key] = out[variant]
                    break
        return out

    @classmethod
    def _ensure_required_field(
        cls,
        item: Dict[str, Any],
        required_key: str,
        skill_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Last-resort coercion when a skill returned a dict that's
        missing the required field even after _map_keys.

        Strategy: take the first non-empty string value in the dict
        and use it as the required field's value. If no string-ish
        value exists, drop the fragment entirely — better to lose one
        item than crash the whole pipeline on pydantic validation.

        Was added after a `decisions` skill run returned dicts shaped
        like {proposal, status}, {focus, status}, {replication_issue,
        status} — none of which matched DECISION_MAP variants, so the
        ExtractionSummary build crashed with "decision: Field required".
        """
        if required_key in item and item[required_key]:
            return item
        for key, value in item.items():
            if key == required_key:
                continue
            if isinstance(value, str) and value.strip():
                logger.warning(
                    "normalizer: skill=%s missing %r, coerced from %r=%r",
                    skill_id, required_key, key, value[:80],
                )
                coerced = dict(item)
                coerced[required_key] = value
                return coerced
        logger.warning(
            "normalizer: skill=%s dropped malformed item (no usable string field): %r",
            skill_id, list(item.keys()),
        )
        return None

    @classmethod
    def normalize_skill_results(cls, skill_results: Dict[str, Any]) -> List[CognitionFragment]:
        """Iterates through skill results and creates fragments."""
        fragments = []
        
        # Define variant mappings based on observed validation errors
        DECISION_MAP = {"decision": ["description", "topic", "summary", "text"]}
        TASK_MAP = {"task": ["description", "action", "item", "action_item", "title", "text"]}
        RISK_MAP = {"risk": ["description", "issue", "threat", "text"]}

        for skill_id, result in skill_results.items():
            if not result or not isinstance(result, dict):
                continue
            
            # Map standard keys found in skill outputs
            if "summary" in result:
                fragments.append(CognitionFragment(type="summary", content=result["summary"], source_skill=skill_id))
            
            if "title" in result:
                fragments.append(CognitionFragment(type="title", content=result["title"], source_skill=skill_id))

            if "action_items" in result and isinstance(result["action_items"], list):
                for item in result["action_items"]:
                    mapped_item = cls._map_keys(item, TASK_MAP) if isinstance(item, dict) else {"task": str(item)}
                    mapped_item = cls._ensure_required_field(mapped_item, "task", skill_id) if isinstance(mapped_item, dict) else mapped_item
                    if mapped_item is None:
                        continue
                    fragments.append(CognitionFragment(type="action_item", content=mapped_item, source_skill=skill_id))

            if "decisions" in result and isinstance(result["decisions"], list):
                for item in result["decisions"]:
                    mapped_item = cls._map_keys(item, DECISION_MAP) if isinstance(item, dict) else {"decision": str(item)}
                    mapped_item = cls._ensure_required_field(mapped_item, "decision", skill_id) if isinstance(mapped_item, dict) else mapped_item
                    if mapped_item is None:
                        continue
                    fragments.append(CognitionFragment(type="decision", content=mapped_item, source_skill=skill_id))

            if "risks" in result and isinstance(result["risks"], list):
                for item in result["risks"]:
                    mapped_item = cls._map_keys(item, RISK_MAP) if isinstance(item, dict) else {"risk": str(item)}
                    mapped_item = cls._ensure_required_field(mapped_item, "risk", skill_id) if isinstance(mapped_item, dict) else mapped_item
                    if mapped_item is None:
                        continue
                    fragments.append(CognitionFragment(type="risk", content=mapped_item, source_skill=skill_id))

                    
            # Extensible insights
            if "insights" in result and isinstance(result["insights"], list):
                for insight in result["insights"]:
                    fragments.append(CognitionFragment(
                        type="modular_insight",
                        content=insight,
                        source_skill=skill_id
                    ))
        
        return fragments

    @classmethod
    def normalize_live_tasks(cls, tasks: List[Any]) -> List[CognitionFragment]:
        """Normalizes stabilized LiveTask objects from temporal memory."""
        fragments = []
        source = "live_detection"
        
        for t in tasks:
            # We only want to persist confirmed or assigned tasks in the final report
            if hasattr(t, "status") and t.status in ["confirmed", "assigned", "completed"]:
                fragments.append(CognitionFragment(
                    type="action_item",
                    content={
                        "task": t.task,
                        "owner": t.owner,
                        "deadline": t.deadline,
                        "status": t.status
                    },
                    source_skill=source,
                    confidence=t.confidence,
                    metadata={"live_id": t.id, "mention_count": t.mention_count}
                ))
        return fragments

    @classmethod
    def normalize_master_result(cls, master_result: Any) -> List[CognitionFragment]:
        """Normalizes the result from the Master Analyzer (TranscriptAnalyzer)."""
        fragments = []
        
        # Define variant mappings
        DECISION_MAP = {"decision": ["description", "topic", "summary", "text"]}
        TASK_MAP = {"task": ["description", "action", "item", "action_item", "title", "text"]}
        RISK_MAP = {"risk": ["description", "issue", "threat", "text"]}

        # Usually master_result is an ExtractionSummary or similar
        data = master_result
        if hasattr(master_result, "model_dump"):
            data = master_result.model_dump()
        elif not isinstance(master_result, dict):
            return []

        source = "master_analyzer"
        
        if data.get("title"):
            fragments.append(CognitionFragment(type="title", content=data["title"], source_skill=source))
        if data.get("summary"):
            fragments.append(CognitionFragment(type="summary", content=data["summary"], source_skill=source))
        
        for item in data.get("action_items") or []:
            mapped_item = cls._map_keys(item, TASK_MAP) if isinstance(item, dict) else {"task": str(item)}
            mapped_item = cls._ensure_required_field(mapped_item, "task", source) if isinstance(mapped_item, dict) else mapped_item
            if mapped_item is None:
                continue
            fragments.append(CognitionFragment(type="action_item", content=mapped_item, source_skill=source))

        for item in data.get("decisions") or []:
            mapped_item = cls._map_keys(item, DECISION_MAP) if isinstance(item, dict) else {"decision": str(item)}
            mapped_item = cls._ensure_required_field(mapped_item, "decision", source) if isinstance(mapped_item, dict) else mapped_item
            if mapped_item is None:
                continue
            fragments.append(CognitionFragment(type="decision", content=mapped_item, source_skill=source))

        for item in data.get("risks") or []:
            mapped_item = cls._map_keys(item, RISK_MAP) if isinstance(item, dict) else {"risk": str(item)}
            mapped_item = cls._ensure_required_field(mapped_item, "risk", source) if isinstance(mapped_item, dict) else mapped_item
            if mapped_item is None:
                continue
            fragments.append(CognitionFragment(type="risk", content=mapped_item, source_skill=source))
            
        return fragments
