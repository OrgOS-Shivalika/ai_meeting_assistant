from typing import Dict, Any, List
from app.services.cognition.models import CognitionFragment

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
                    # Robust key mapping for tasks
                    mapped_item = cls._map_keys(item, TASK_MAP) if isinstance(item, dict) else {"task": str(item)}
                    fragments.append(CognitionFragment(type="action_item", content=mapped_item, source_skill=skill_id))

            if "decisions" in result and isinstance(result["decisions"], list):
                for item in result["decisions"]:
                    # Robust key mapping for decisions
                    mapped_item = cls._map_keys(item, DECISION_MAP) if isinstance(item, dict) else {"decision": str(item)}
                    fragments.append(CognitionFragment(type="decision", content=mapped_item, source_skill=skill_id))

            if "risks" in result and isinstance(result["risks"], list):
                for item in result["risks"]:
                    # Robust key mapping for risks
                    mapped_item = cls._map_keys(item, RISK_MAP) if isinstance(item, dict) else {"risk": str(item)}
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
            fragments.append(CognitionFragment(type="action_item", content=mapped_item, source_skill=source))
            
        for item in data.get("decisions") or []:
            mapped_item = cls._map_keys(item, DECISION_MAP) if isinstance(item, dict) else {"decision": str(item)}
            fragments.append(CognitionFragment(type="decision", content=mapped_item, source_skill=source))
            
        for item in data.get("risks") or []:
            mapped_item = cls._map_keys(item, RISK_MAP) if isinstance(item, dict) else {"risk": str(item)}
            fragments.append(CognitionFragment(type="risk", content=mapped_item, source_skill=source))
            
        return fragments
