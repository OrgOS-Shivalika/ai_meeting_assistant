import logging
from typing import List, Dict, Any
from app.services.cognition.models import CognitionFragment, get_skill_authority

logger = logging.getLogger(__name__)

class ConflictResolver:
    """Resolves contradictions using Authority-weighted logic."""

    @classmethod
    def resolve(cls, fragments: List[CognitionFragment]) -> List[CognitionFragment]:
        """Resolves conflicts especially for singleton types like 'title'."""
        if not fragments:
            return []

        # 1. Group by type
        by_type: Dict[str, List[CognitionFragment]] = {}
        for f in fragments:
            if f.type not in by_type:
                by_type[f.type] = []
            by_type[f.type].append(f)

        resolved = []

        # 2. Process Singleton Types (Title)
        if "title" in by_type:
            resolved.append(cls._resolve_authority(by_type["title"]))
        
        # 3. Process Non-Singleton Types (Summary is a special case for NarrativeSynthesizer)
        # For now, we keep all summaries to pass to the Synthesizer
        if "summary" in by_type:
            resolved.extend(by_type["summary"])

        # 4. Other types (Action Items, Risks, etc.) are handled by Deduplicator
        # But we can resolve conflicts in metadata (e.g. owners) here if needed.
        for ftype in ["action_item", "decision", "risk", "modular_insight"]:
            if ftype in by_type:
                resolved.extend(by_type[ftype])

        return resolved

    @classmethod
    def _resolve_authority(cls, fragments: List[CognitionFragment]) -> CognitionFragment:
        """Picks the winner based on skill authority and confidence."""
        if len(fragments) == 1:
            return fragments[0]

        # Calculate scores: Authority * Confidence
        winner = fragments[0]
        max_score = -1.0

        for f in fragments:
            authority = get_skill_authority(f.source_skill)
            score = authority * f.confidence
            
            if score > max_score:
                max_score = score
                winner = f
        
        logger.debug(f"Authority winner for {winner.type}: {winner.source_skill} (score: {max_score})")
        return winner
