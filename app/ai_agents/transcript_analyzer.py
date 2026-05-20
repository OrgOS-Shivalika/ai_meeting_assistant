"""Provider-agnostic transcript analyzer with OpenAI primary + Gemini fallback.

The pipeline calls `TranscriptAnalyzer.analyze(transcript)`, which:
  1. Tries OpenAI (`OpenAITranscriptAnalyzer`) when `OPEN_API_KEY` is configured.
  2. Falls back to Gemini (`GeminiTranscriptAnalyzer`) when OpenAI is unavailable —
     either because the key is missing or because the call raised.

If neither provider is available, the original failure is re-raised so callers
see the same exception shape they used to.
"""

from app.config.settings import settings
from app.utils.logger import setup_logger
from app.ai_agents.openAI_transcript_analyzer import OpenAITranscriptAnalyzer
from app.ai_agents.gemini_transcript_analyzer import GeminiTranscriptAnalyzer

logger = setup_logger(__name__)


class TranscriptAnalyzer:
    @staticmethod
    def analyze(transcript: str, behavior_context: str = "") -> str:
        """Run the transcript analyzer with optional behavior_context.

        `behavior_context` is the workspace-resolved BehaviorProfile
        preamble built by `app.services.behavior.meeting_context.
        build_meeting_behavior_context`. Empty string = analyzer runs
        with its hardcoded default behavior (zero regression vs prior
        runs). The same string is passed through to whichever LLM
        provider handles the call."""
        openai_available = bool(settings.OPEN_API_KEY)
        gemini_available = bool(settings.GEMINI_API_KEY)

        if openai_available:
            try:
                return OpenAITranscriptAnalyzer.analyze(transcript, behavior_context)
            except Exception as primary_err:
                if not gemini_available:
                    logger.error(
                        "OpenAI analysis failed and Gemini fallback is unavailable (GEMINI_API_KEY not set)."
                    )
                    raise
                logger.warning(
                    "OpenAI analysis failed (%s); falling back to Gemini.", str(primary_err)
                )
                try:
                    return GeminiTranscriptAnalyzer.analyze(transcript, behavior_context)
                except Exception as fallback_err:
                    logger.error(
                        "Both OpenAI and Gemini failed. OpenAI error: %s; Gemini error: %s",
                        str(primary_err), str(fallback_err),
                    )
                    raise fallback_err

        if gemini_available:
            logger.info("OPEN_API_KEY not set — using Gemini directly.")
            return GeminiTranscriptAnalyzer.analyze(transcript, behavior_context)

        raise RuntimeError(
            "No transcript analyzer available: set OPEN_API_KEY and/or GEMINI_API_KEY."
        )
