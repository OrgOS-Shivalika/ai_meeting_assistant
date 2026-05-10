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
    def analyze(transcript: str) -> str:
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

        formatted_prompt = analyzer_prompt.replace("{transcript}", transcript)

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
