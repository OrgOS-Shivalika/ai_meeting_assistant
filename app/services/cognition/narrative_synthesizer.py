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

        # The previous prompt asked for an "executive report" in
        # "markdown format" — the model interpreted that as an invitation
        # to add a template header with placeholders like
        # "# Executive Meeting Summary Report / ## Date: [Insert Date]
        # / ### Attendees: [Insert Attendee Names]". Those placeholders
        # ended up in `meeting.summary` verbatim because we never inject
        # date or attendees into this prompt — there's nothing for the
        # model to fill them with.
        #
        # New prompt: ban headers, ban placeholders, demand a short
        # plain-prose paragraph grounded in the fragments. Same shape
        # the master analyzer's summary section asks for (2-3 sentences).
        prompt = f"""
You merge multiple meeting summary fragments into ONE short, faithful narrative.

Hard rules:
- 2-4 sentences. Plain prose. No more.
- NO headers, NO markdown (#, ##, ###), NO bullet lists, NO bold.
- NEVER use placeholder tokens like "[Insert Date]", "[Date]",
  "[Attendees]", "[Owner]", or any other fill-in-the-blank text.
  If a value isn't in the fragments, just don't mention that field.
- Do NOT invent facts. Only restate what the fragments say.
- Lead with the master/analyzer fragment; add specialized insights
  from other fragments only if they add new substance.
- Past tense, third person, no opening boilerplate ("The meeting was
  held to...", "Attendees gathered to discuss...").

Input Fragments:
{"\n".join(inputs)}

Output: just the paragraph. No preamble, no closing line.
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
