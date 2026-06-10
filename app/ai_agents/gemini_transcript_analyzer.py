from app.config.settings import settings
from app.utils.logger import setup_logger
from app.ai_agents.prompts.openAI_transcript_analyzer_prompt import prompt as analyzer_prompt

logger = setup_logger(__name__)


class GeminiTranscriptAnalyzer:
    """Gemini-backed analyzer with the same contract as OpenAITranscriptAnalyzer:
    `analyze(transcript, behavior_context='') -> str` returning JSON."""

    @staticmethod
    def analyze(transcript: str, behavior_context: str = "") -> str:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set; Gemini fallback unavailable")

        # Imported lazily so the module loads even if the SDK isn't installed
        # in environments that only use OpenAI.
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)

        # Phase 13D revised — inject today's date for relative-deadline
        # normalization, same as the OpenAI analyzer path.
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

        logger.info("Starting analysis of transcript with Gemini (%s)...", settings.GEMINI_MODEL)

        model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            system_instruction="You are a strict JSON generator.",
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )

        try:
            response = model.generate_content(formatted_prompt, request_options={"timeout": 60})
            text = response.text or ""
            if not text.strip():
                raise RuntimeError("Gemini returned an empty response")
            logger.info("Gemini analysis completed successfully.")
            return text
        except Exception as e:
            logger.error(f"Error during Gemini analysis: {str(e)}")
            raise
