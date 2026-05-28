import logging
from typing import List, Dict, Any
from app.services.cognition.models import CognitionFragment, get_skill_authority
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = logging.getLogger(__name__)

class NarrativeSynthesizer:
    """Synthesizes multiple summary fragments into a cohesive executive narrative."""

    @classmethod
    def synthesize(cls, fragments: List[CognitionFragment]) -> CognitionFragment:
        """
        Combines multiple summaries into one.
        Final output feels human-written, concise, and executive-ready.
        """
        summaries = [f for f in fragments if f.type == "summary"]
        if not summaries:
            return CognitionFragment(type="summary", content="", source_skill="synthesizer")
        
        if len(summaries) == 1:
            return summaries[0]

        # Order summaries by authority to give the LLM context on importance
        summaries.sort(key=lambda x: get_skill_authority(x.source_skill), reverse=True)

        inputs = []
        for s in summaries:
            inputs.append(f"Skill: {s.source_skill} (Authority: {get_skill_authority(s.source_skill)}) | Content: {s.content}")

        prompt = f"""
You are a senior executive assistant. Your task is to synthesize multiple meeting summary fragments into a single, cohesive, high-quality executive report.

Rules:
1. Do NOT just concatenate the summaries.
2. Use the "Master Analyzer" or high-authority skills as the primary narrative thread.
3. Inject specialized domain insights from technical or compliance skills where relevant.
4. Maintain a consistent, professional, and concise tone.
5. The final output must be a single cohesive narrative (markdown format).

Input Fragments:
{"\n".join(inputs)}

Output:
Provide only the final synthesized narrative.
"""
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are a narrative synthesizer."}, 
                          {"role": "user", "content": prompt}],
                temperature=0.3,
                timeout=30
            )
            
            content = response.choices[0].message.content.strip()
            
            return CognitionFragment(
                type="summary",
                content=content,
                source_skill="narrative_synthesizer",
                metadata={"merged_from_skills": [s.source_skill for s in summaries]}
            )

        except Exception as e:
            logger.error(f"Narrative synthesis failed: {e}")
            # Fallback: Just concatenate if LLM fails
            concatenated = "\n\n".join([f"## {s.source_skill}\n{s.content}" for s in summaries])
            return CognitionFragment(type="summary", content=concatenated, source_skill="synthesizer_fallback")
