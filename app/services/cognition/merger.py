import logging
from typing import List, Dict, Any, Optional
from app.services.cognition.models import CognitionFragment
from app.services.cognition.normalizer import CognitionNormalizer
from app.services.cognition.conflict_resolver import ConflictResolver
from app.services.cognition.deduplicator import SemanticDeduplicator
from app.services.cognition.narrative_synthesizer import NarrativeSynthesizer
from app.services.cognition.contracts import ExtractionSummary

logger = logging.getLogger(__name__)

class UnifiedCognitionMerger:
    """
    Unified Cognition Synthesis Engine.
    Orchestrates the multi-layered synthesis pipeline.
    """

    @classmethod
    def synthesize(
        cls, 
        master_result: Any, 
        skill_results: Dict[str, Any],
        meeting_id: Optional[int] = None
    ) -> ExtractionSummary:
        """
        Transforms distributed fragments into a single coherent ExtractionSummary.
        """
        logger.info("🧠 UnifiedCognitionMerger: Starting cognition synthesis...")

        # Layer 1: Normalization
        fragments = CognitionNormalizer.normalize_master_result(master_result)
        fragments.extend(CognitionNormalizer.normalize_skill_results(skill_results))
        
        # --- NEW: Inject Live Memory fragments ---
        if meeting_id:
            try:
                from app.services.meeting_memory.meeting_state_store import state_store
                live_state = state_store.get_state(str(meeting_id))
                if live_state and live_state.active_tasks:
                    live_fragments = CognitionNormalizer.normalize_live_tasks(
                        list(live_state.active_tasks.values())
                    )
                    logger.info(f"Injecting {len(live_fragments)} live memory fragments into synthesis.")
                    fragments.extend(live_fragments)
            except Exception as e:
                logger.error(f"Failed to inject live memory into synthesis: {e}")

        logger.debug(f"Normalized {len(fragments)} fragments.")

        # Layer 2: Conflict Resolution (Title Authority)
        resolved_fragments = ConflictResolver.resolve(fragments)
        
        # Layer 3: Semantic Deduplication (Action Items, Risks, Decisions)
        deduplicated_fragments = SemanticDeduplicator.deduplicate(resolved_fragments)
        
        # Layer 4: Narrative Synthesis (Summary Synthesis)
        final_summary_fragment = NarrativeSynthesizer.synthesize(deduplicated_fragments)
        
        # Build final object
        final_title = next((f.content for f in deduplicated_fragments if f.type == "title"), "Meeting Analysis")
        
        # Filter items for standard schema
        action_items = [f.content for f in deduplicated_fragments if f.type == "action_item"]
        decisions = [f.content for f in deduplicated_fragments if f.type == "decision"]
        risks = [f.content for f in deduplicated_fragments if f.type == "risk"]
        
        # Future-proofing: modular insights
        modular_insights = [f.content for f in deduplicated_fragments if f.type == "modular_insight"]

        logger.info(f"Synthesis complete: {len(action_items)} tasks, {len(risks)} risks.")

        return ExtractionSummary(
            title=final_title,
            summary=final_summary_fragment.content,
            action_items=action_items,
            decisions=decisions,
            risks=risks
        )
