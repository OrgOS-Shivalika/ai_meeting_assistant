import os
from dotenv import load_dotenv
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

load_dotenv()


class Settings:
    # ---- Database ---------------------------------------------------------
    # Defaults match the previous hardcoded value so existing dev envs Just
    # Work. Override via DATABASE_URL in .env when needed.
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:8210682@localhost:5432/meeting_ai",
    )

    # ---- Auth -------------------------------------------------------------
    AUTH_SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "supersecret")
    ALGORITHM = "HS256"

    # ---- AI providers -----------------------------------------------------
    OPEN_API_KEY = os.getenv("OPEN_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # ---- Recall.ai --------------------------------------------------------
    RECALL_API_KEY = os.getenv("RECALL_API_KEY")
    BASE_URL = os.getenv("BASE_URL")

    # ---- Networking / CORS ------------------------------------------------
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")

    # ---- Google OAuth -----------------------------------------------------
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
    )
    APP_PUBLIC_URL = os.getenv("APP_PUBLIC_URL", "http://localhost:8000")

    # ---- Async infrastructure (Phase 1B) ---------------------------------
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
    # When set, /inject-bot dispatches the meeting pipeline via Celery.
    # When false (e.g. on a dev box without Redis), it falls back to the
    # in-process FastAPI BackgroundTasks path so local work isn't blocked.
    USE_CELERY = os.getenv("USE_CELERY", "false").lower() in {"1", "true", "yes"}

    # ---- Object storage (Phase 1C) ---------------------------------------
    # Optional. When unset, storage operations raise a clear error — the
    # rest of the app still boots so non-storage features keep working.
    S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")  # e.g. http://localhost:9000 for MinIO
    S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
    S3_BUCKET = os.getenv("S3_BUCKET", "meeting-ai-documents")
    S3_REGION = os.getenv("S3_REGION", "us-east-1")
    S3_USE_PATH_STYLE = os.getenv("S3_USE_PATH_STYLE", "true").lower() in {"1", "true", "yes"}

    # ---- Vector memory (Phase 2) -----------------------------------------
    # `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` must agree with the
    # `vector(N)` column on `meeting_chunks` — changing the dimension means
    # a follow-up migration. The chunker targets `CHUNK_SIZE_TOKENS` per
    # chunk with `CHUNK_OVERLAP_TOKENS` carried into the next chunk's head;
    # both are tokens under the embedding model's tokenizer (tiktoken
    # `cl100k_base` for OpenAI). `EMBEDDING_BATCH_SIZE` caps how many texts
    # are POSTed to OpenAI per call — OpenAI accepts up to 2048 but 100 is
    # a safer default for token-budget reasons.
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1536"))
    CHUNK_SIZE_TOKENS = int(os.getenv("CHUNK_SIZE_TOKENS", "800"))
    CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "100"))
    EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "100"))

    # ---- Graph extraction (Phase 3) --------------------------------------
    # `GRAPH_PROMPT_VERSION` selects which file under
    # app/ai_agents/prompts/graph/<version>.txt the extractor loads, and
    # gets persisted on every `graph_extraction_runs` row so a stale-prompt
    # backfill (3E) can target rows that need re-extraction. Use string
    # tags (`v1`, `v1-experimental`) not numbers — sortable, grep-friendly,
    # and supports non-linear iteration.
    GRAPH_PROMPT_VERSION = os.getenv("GRAPH_PROMPT_VERSION", "v1")
    GRAPH_EXTRACTION_MODEL = os.getenv("GRAPH_EXTRACTION_MODEL", "gpt-4o-mini")
    # Number of meeting chunks bundled into one LLM call. 5 is a balance
    # between prompt-overhead amortization and per-call latency.
    GRAPH_EXTRACTION_BATCH_SIZE = int(os.getenv("GRAPH_EXTRACTION_BATCH_SIZE", "5"))

    def __init__(self):
        if not self.OPEN_API_KEY:
            logger.warning("OPEN_API_KEY is not set in environment variables.")
        if not self.GEMINI_API_KEY:
            logger.warning(
                "GEMINI_API_KEY is not set in environment variables (Gemini fallback unavailable)."
            )
        if not self.RECALL_API_KEY:
            logger.warning("RECALL_API_KEY is not set in environment variables.")
        if not self.BASE_URL:
            logger.warning("BASE_URL is not set in environment variables.")
        if not self.GOOGLE_CLIENT_ID:
            logger.warning("GOOGLE_CLIENT_ID is not set in environment variables.")
        if not self.GOOGLE_CLIENT_SECRET:
            logger.warning("GOOGLE_CLIENT_SECRET is not set in environment variables.")


settings = Settings()
