import logging
import json
from typing import List
from app.services.live_tasks.live_task_models import LiveTask
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.ai_agents.openAI_transcript_analyzer import _get_client

logger = logging.getLogger(__name__)

class TaskExtractor:
    """Uses LLM to extract tasks from a live transcript segment."""

    @classmethod
    def extract_from_chunk(
        cls, 
        chunk: LiveTranscriptChunk, 
        rolling_context: str
    ) -> List[LiveTask]:
        """Performs incremental task extraction."""
        
        prompt = f"""
You are an aggressive real-time task detection engine for meetings.
Analyze the ROLLING CONTEXT to understand the discussion, then extract tasks from the CURRENT CHUNK.

ROLLING CONTEXT (Past discussion for reference):
{rolling_context}

CURRENT CHUNK (Extract tasks from here):
Speaker: {chunk.speaker_name}
Text: {chunk.text}

Rules:
1. Extract any actionable commitment, assignment, requirement, or meeting governance action mentioned in the CURRENT CHUNK.
2. INCLUDE procedural tasks such as: moving motions, seconding, confirming minutes, organizing future meetings, or inviting guests.
3. Use the ROLLING CONTEXT to resolve pronouns (e.g., if CURRENT CHUNK says "I'll do it", find what "it" refers to in the context).
4. Identify the owner:
   - "assigned_task": A direct request to another person.
   - "self_assigned_task": A verbal commitment like "I'll handle", "I can do", "I'm on it".
   - "unassigned_task": General needs like "Someone should", "We need to", or procedural group tasks.
5. Extract deadlines and assign a confidence score (0.0 - 1.0). Be liberal with extraction; if it sounds like a task or an administrative move, capture it.

Response Format:
{{
  "tasks": [
    {{
      "task": "Confirm February minutes",
      "owner": "Meeting Chair",
      "type": "unassigned_task",
      "deadline": "today",
      "confidence": 0.95
    }}
  ]
}}
"""
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a real-time task extractor. You must always respond with valid JSON."}, 
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
                    "confidence": t.get("confidence", 0.0),
                    "source_speaker": chunk.speaker_name,
                    "source_timestamp": chunk.timestamp,
                    "transcript_chunk_id": chunk.sequence_number
                })
                
            return extracted_raw

        except Exception as e:
            logger.error(f"Live task extraction failed: {e}")
            return []
