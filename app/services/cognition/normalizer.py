from typing import Dict, Any, List
from app.services.cognition.models import CognitionFragment

class CognitionNormalizer:
    """Translates raw skill outputs and agent results into standardized CognitionFragments."""

    @classmethod
    def normalize_skill_results(cls, skill_results: Dict[str, Any]) -> List[CognitionFragment]:
        """Iterates through skill results and creates fragments."""
        fragments = []
        for skill_id, result in skill_results.items():
            if not result or not isinstance(result, dict):
                continue
            
            # Map standard keys found in skill outputs
            # Most skills follow a similar pattern: { "summary": "...", "action_items": [...], etc. }
            
            if "summary" in result:
                fragments.append(CognitionFragment(
                    type="summary",
                    content=result["summary"],
                    source_skill=skill_id
                ))
            
            if "title" in result:
                fragments.append(CognitionFragment(
                    type="title",
                    content=result["title"],
                    source_skill=skill_id
                ))

            if "action_items" in result:
                for item in result["action_items"]:
                    fragments.append(CognitionFragment(
                        type="action_item",
                        content=item,
                        source_skill=skill_id
                    ))

            if "decisions" in result:
                for item in result["decisions"]:
                    fragments.append(CognitionFragment(
                        type="decision",
                        content=item,
                        source_skill=skill_id
                    ))

            if "risks" in result:
                for item in result["risks"]:
                    fragments.append(CognitionFragment(
                        type="risk",
                        content=item,
                        source_skill=skill_id
                    ))
                    
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
        # Usually master_result is an ExtractionSummary or similar
        # If it's a dict or Pydantic model
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
            fragments.append(CognitionFragment(type="action_item", content=item, source_skill=source))
        for item in data.get("decisions") or []:
            fragments.append(CognitionFragment(type="decision", content=item, source_skill=source))
        for item in data.get("risks") or []:
            fragments.append(CognitionFragment(type="risk", content=item, source_skill=source))
            
        return fragments
