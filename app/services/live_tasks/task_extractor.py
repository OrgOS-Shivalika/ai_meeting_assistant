import logging
import json
from datetime import datetime, timezone
from typing import List
from app.services.live_tasks.live_task_models import LiveTask
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = logging.getLogger(__name__)


# Day-of-week helper used to anchor relative deadlines like
# "by Friday" / "अगले सोमवार" to a concrete ISO date in the prompt.
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

class TaskExtractor:
    """Uses LLM to extract tasks from a live transcript segment."""

    @classmethod
    def extract_from_chunk(
        cls,
        chunk: LiveTranscriptChunk,
        rolling_context: str
    ) -> List[LiveTask]:
        """Performs incremental task extraction."""

        # Anchor for relative-date normalization. UTC is fine; the LLM
        # is matching speech to a calendar day, not a wall-clock minute.
        now = datetime.now(timezone.utc)
        current_date_iso = now.date().isoformat()
        current_day_of_week = _DAY_NAMES[now.weekday()]

        prompt = f"""
You are a FAITHFUL real-time task detection engine for meetings.
Your single job is to extract tasks that were ACTUALLY SAID in the CURRENT CHUNK.
You DO NOT invent. You DO NOT pattern-match against typical PM meetings.
You ONLY surface tasks that a human listening to the chunk would clearly hear.

ANTI-HALLUCINATION (CRITICAL — read before anything else):
- If you cannot point to a specific phrase in the CURRENT CHUNK that
  established a task, DO NOT include it.
- DO NOT generate boilerplate PM tasks (customer interviews, OKR updates,
  onboarding docs, engagement surveys, "follow up with X") unless those
  specific words appear in the chunk.
- DO NOT invent owner names. If no name was spoken, set owner = null.
  Common Western names (Fabian, Karina, Jessica, John, Sarah) are
  TEMPLATE EXAMPLES from your training data — never use them unless
  spoken in this specific chunk.
- DO NOT use the book name "Inspired" (or any other PM-book reference)
  unless the speaker explicitly mentions it.
- An empty `tasks` array is the CORRECT output when nothing was said.
- When in doubt, leave it out.

LANGUAGE HANDLING:
- The transcript may be in English, Hindi (Devanagari script), or Hinglish (mixed Hindi+English).
- ALWAYS OUTPUT THE `task` FIELD IN ENGLISH. If the input is Hindi or
  Hinglish, translate the task description into clear, concise English.
- ALWAYS TRANSLITERATE Hindi owner names into Roman/Latin script:
    "रवि"   -> "Ravi"
    "साहिल" -> "Sahil"
    "प्रिया" -> "Priya"
    "अमित"  -> "Amit"
    "खुशी"  -> "Khushi"
    "ऋषभ"   -> "Rishabh"
  Names already in Roman script (English names like "Sarah", or
  transliterated Hindi like "Pranav") stay as-is. Never output a name
  in Devanagari — the dashboard, Slack, Jira, and notification tools
  all expect Roman script.
- Examples:
    Hindi input "रवि कल तक रिपोर्ट बनाएगा"
      -> task: "Prepare the report by tomorrow", owner: "Ravi"
    Hinglish input "Sarah will deadline tak deploy karegi"
      -> task: "Deploy by the deadline", owner: "Sarah"
    Hindi input "साहिल और प्रिया मिलकर बग ठीक करेंगे"
      -> task: "Fix the bug together", owner: "Sahil and Priya"
    English input "John will fix the bug by Friday"
      -> task: "Fix the bug by Friday", owner: "John"
- Deadlines: normalize to natural English where possible
  ("कल तक" -> "by tomorrow", "शुक्रवार तक" -> "by Friday").
- If no clear owner is mentioned, owner = null.

ROLLING CONTEXT (Past discussion for reference ONLY):
{rolling_context}

CURRENT CHUNK (Extract tasks from here ONLY):
Speaker: {chunk.speaker_name}
Text: {chunk.text}

CURRENT DATE CONTEXT:
- Today is {current_date_iso} ({current_day_of_week}).
- Use this to resolve relative date phrases ("tomorrow", "next Monday",
  "this Friday", "in 3 days") into concrete ISO 8601 dates in the
  `due_date` field. Do NOT guess if the speaker didn't give a clear
  temporal anchor — leave `due_date` as null.

NAME EXTRACTION (be thorough, but only from what was actually said):
- The CURRENT CHUNK's speaker is "{chunk.speaker_name}". When the
  speaker uses first person ("I'll do X", "I can take this",
  "मैं करूँगा"), the owner is THIS SPEAKER NAME — not null.
- When the speaker addresses someone directly ("Ravi, can you do X?",
  "Sarah, please handle Y", "रवि, क्या तुम कर सकते हो?"), the owner is
  the named person.
- When the speaker references a third party ("ask Ravi to...", "I'll
  have Priya look at this", "Sarah needs to..."), the owner is that
  third party.
- When the speaker says "let's", "we need to", "someone should" without
  a name, owner = null (unassigned_task).

DEADLINE EXTRACTION (capture every time reference you can):
- ALL time anchors qualify: explicit dates ("September 15th",
  "2026-06-15"), weekdays ("Friday", "next Monday"), relative
  ("tomorrow", "next week", "in 3 days"), Hindi ("कल", "शुक्रवार तक",
  "अगले हफ्ते"), Hinglish ("Friday tak", "kal", "next week tak").
- Output BOTH fields when possible:
    `deadline`: the speaker's natural phrasing, preserved as-said
                ("by Friday", "कल तक", "next week tak")
    `due_date`: ISO 8601 YYYY-MM-DD anchored to today's date
                ({current_date_iso}). Null if no specific date can be
                resolved from the chunk.
- Examples (assume today is {current_date_iso}, a {current_day_of_week}):
    "by Friday"     -> deadline="by Friday",  due_date=<the next Friday in ISO>
    "tomorrow"      -> deadline="tomorrow",   due_date=<today + 1 day>
    "next Monday"   -> deadline="next Monday",due_date=<that Monday's ISO>
    "कल तक"         -> deadline="by tomorrow",due_date=<today + 1 day>
    "शुक्रवार तक"   -> deadline="by Friday",  due_date=<next Friday's ISO>
    "next quarter"  -> deadline="next quarter", due_date=null (too vague)
    no time mentioned -> deadline=null, due_date=null

Rules:
1. Extract ONLY tasks where the speaker EXPLICITLY says someone will do
   something, OR commits to doing it themselves, OR states that something
   needs to be done. The phrase must be present verbatim or near-verbatim
   in the CURRENT CHUNK.
2. Use the ROLLING CONTEXT purely for background and to resolve pronouns
   (e.g., if CURRENT CHUNK says "I'll do it", find what "it" refers to).
   DO NOT extract tasks that are ONLY mentioned in ROLLING CONTEXT.
3. Identify the owner using the NAME EXTRACTION rules above.
4. Identify the type:
   - "assigned_task": A direct request to another person.
   - "self_assigned_task": A first-person verbal commitment by the speaker.
   - "unassigned_task": A general need without a named owner.
5. Extract deadlines using the DEADLINE EXTRACTION rules above.
6. Confidence scale (0.0 - 1.0) — STRICT:
   - 0.9+: explicit commitment with owner AND date ("Ravi will do X by Friday")
   - 0.7-0.9: clear commitment with owner OR date (not both)
   - 0.5-0.7: implied need, ambiguous owner/date
   - Below 0.5: DO NOT EMIT.
7. If the chunk is small talk, filler, repetition, or topic exploration
   without a commitment, return {{"tasks": []}}.

Response Format:
{{
  "tasks": [
    {{
      "task": "Send the load test report",
      "owner": "Sarah",
      "type": "assigned_task",
      "deadline": "by Friday",
      "due_date": "2026-06-13",
      "confidence": 0.92
    }}
  ]
}}
"""
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a FAITHFUL real-time task extractor. "
                            "Your ONLY job is to surface tasks that were "
                            "literally said in the chunk provided. You NEVER "
                            "invent tasks or owner names based on context, "
                            "topic, or your training data. Empty array is "
                            "the correct answer when nothing was said. "
                            "Always respond with valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                timeout=10
            )
            
            result = json.loads(response.choices[0].message.content)
            extracted_raw = []
            
            for t in result.get("tasks", []):
                extracted_raw.append({
                    "task": t["task"],
                    "owner": t.get("owner"),
                    "type": t.get("type", "unassigned_task"),
                    "deadline": t.get("deadline"),
                    # Phase 13D revised — new field. ISO 8601 due_date
                    # if the LLM resolved a relative date against
                    # `current_date_iso`. None otherwise. Downstream
                    # persistence (LiveTaskPersistence) prefers this
                    # when populating the DB `tasks.due_date` column
                    # because it's already a parseable date string.
                    "due_date": t.get("due_date"),
                    "confidence": t.get("confidence", 0.0),
                    "source_speaker": chunk.speaker_name,
                    "source_timestamp": chunk.timestamp,
                    "transcript_chunk_id": chunk.sequence_number
                })
                
            return extracted_raw

        except Exception as e:
            logger.error(f"Live task extraction failed: {e}")
            return []
