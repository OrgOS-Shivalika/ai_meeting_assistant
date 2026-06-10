from openai import OpenAI
from app.config.settings import settings
from app.processors.transcript_processor import TranscriptProcessor
from app.utils.logger import setup_logger
from app.ai_agents.prompts.openAI_transcript_analyzer_prompt import prompt as analyzer_prompt

logger = setup_logger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily build the OpenAI client so missing keys don't crash imports."""
    global _client
    if _client is None:
        if not settings.OPEN_API_KEY:
            raise RuntimeError("OPEN_API_KEY is not set")
        _client = OpenAI(api_key=settings.OPEN_API_KEY)
    return _client


class OpenAITranscriptAnalyzer:

    @staticmethod
    def analyze(transcript: str, behavior_context: str = "") -> str:
        """Run analysis. `behavior_context` is the workspace-resolved
        BehaviorProfile preamble (Phase 9.2). Empty string = analyzer
        runs with its default hardcoded behavior."""
        client = _get_client()

        # logger.info("original transcript length: %d characters", len(transcript))
        # if transcript.strip():
        #     print(transcript[:500])  # Print the first 500 characters of the original transcript for debugging
        # else:
        #     logger.warning("Transcript is empty or whitespace only.")


        logger.info("Starting analysis of transcript with OpenAI...")

        
        # Use the imported prompt and inject the transcript
        # Note: The prompt template uses {transcript} as the placeholder
        # org_transcript = TranscriptProcessor.format(transcript)
        # formatted_transcript = TranscriptProcessor.format(test_transcript)

        

        # if not formatted_transcript.strip():
        #     raise ValueError("Transcript is empty, skipping analysis")

        # Phase 13D revised — inject today's ISO date so the LLM can
        # convert relative deadlines ("by Friday", "कल तक", "Friday tak")
        # into concrete ISO 8601 due_date values. Falls back to "" if
        # the placeholder isn't present in the prompt template
        # (.replace is a no-op for missing tokens).
        from datetime import datetime as _dt, timezone as _tz
        _today = _dt.now(_tz.utc).date()
        _day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                      "Friday", "Saturday", "Sunday"]
        formatted_prompt = (
            analyzer_prompt
            .replace("{behavior_context}", behavior_context or "")
            .replace("{transcript}", transcript)
            .replace("{current_date_iso}", _today.isoformat())
            .replace("{current_day_of_week}", _day_names[_today.weekday()])
        )

        print("FORMATTED TRANSCRIPT:\n", transcript)

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": "You are a strict JSON generator."},
                          {"role": "user", "content": formatted_prompt}],
                response_format={"type": "json_object"},
                timeout=60
            )
            logger.info("OpenAI analysis completed successfully.")
            print("OPENAI RESPONSE:\n", response.choices[0].message.content)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error during OpenAI analysis: {str(e)}")
            raise
