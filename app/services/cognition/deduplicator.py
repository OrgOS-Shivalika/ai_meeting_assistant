import logging
from typing import List, Dict, Any, TypeVar, Callable
from app.services.cognition.models import CognitionFragment, get_skill_authority
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

class SemanticDeduplicator:
    """Handles semantic deduplication of tasks, risks, and decisions."""

    @classmethod
    def deduplicate(cls, fragments: List[CognitionFragment]) -> List[CognitionFragment]:
        """Groups fragments by type and deduplicates each group."""
        if not fragments:
            return []

        # 1. Group by type
        by_type: Dict[str, List[CognitionFragment]] = {}
        for f in fragments:
            if f.type not in by_type:
                by_type[f.type] = []
            by_type[f.type].append(f)

        deduplicated = []
        
        # 2. Process specific types that need semantic merging
        for ftype, items in by_type.items():
            if ftype in ["action_item", "risk", "decision"]:
                merged = cls._semantic_merge(ftype, items)
                deduplicated.extend(merged)
            elif ftype in ["title", "summary"]:
                # These are handled by Authority Resolver + Narrative Synthesizer
                deduplicated.extend(items)
            else:
                # Default: no special deduplication for modular_insights for now
                deduplicated.extend(items)

        return deduplicated

    @classmethod
    def _semantic_merge(cls, ftype: str, fragments: List[CognitionFragment]) -> List[CognitionFragment]:
        """Uses a lightweight LLM pass to deduplicate similar items."""
        if len(fragments) <= 1:
            return fragments

        # Extract content for the LLM
        # We group items to minimize token usage
        items_text = []
        for i, f in enumerate(fragments):
            items_text.append(f"ID:{i} | Content: {str(f.content)}")

        prompt = f"""
You are an expert at semantic deduplication for meeting AI outputs.
Below is a list of {ftype}s extracted from various sources. 
Identify items that are semantically identical or highly similar (e.g., "Fix auth bug" vs "Resolve authentication issue").

Input Items:
{"\n".join(items_text)}

Task:
1. Group the IDs that refer to the same concept.
2. For each group, pick the most descriptive and accurate version.
3. Return a JSON mapping of {{ "original_id": "kept_id" }} for items to merge.
4. If an item is unique, map it to itself.

Response Format:
{{
  "merges": {{
    "0": 0,
    "1": 0,
    "2": 2
  }}
}}
"""
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are a deduplication assistant."}, 
                          {"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                timeout=15
            )
            import json
            result = json.loads(response.choices[0].message.content)
            merges = result.get("merges", {})
            
            # Reconstruct fragments based on LLM decision
            kept_indices = set(merges.values())
            final_fragments = []
            
            for idx_str in kept_indices:
                idx = int(idx_str)
                base_fragment = fragments[idx]
                
                # Collect sources from all merged fragments for traceability
                sources = set()
                for orig_id_str, kept_id_str in merges.items():
                    if int(kept_id_str) == idx:
                        sources.add(fragments[int(orig_id_str)].source_skill)
                
                base_fragment.metadata["merged_from_skills"] = list(sources)
                final_fragments.append(base_fragment)
                
            return final_fragments

        except Exception as e:
            logger.error(f"Semantic deduplication failed for {ftype}: {e}")
            # Fallback to basic string deduplication if LLM fails
            return cls._basic_deduplicate(fragments)

    @classmethod
    def _basic_deduplicate(cls, fragments: List[CognitionFragment]) -> List[CognitionFragment]:
        """Fallback exact-match deduplication."""
        seen = set()
        unique = []
        for f in fragments:
            content_key = str(f.content).strip().lower()
            if content_key not in seen:
                seen.add(content_key)
                unique.append(f)
        return unique
