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

    # Phase 5 — RAG. Same versioning + model convention as the graph
    # extractor: tagged prompt versions stored in
    # `rag_query_runs.{planner,synth}_prompt_version`, so prompt
    # iteration in 5F has full ground truth without re-running the model.
    RAG_PLANNER_MODEL = os.getenv("RAG_PLANNER_MODEL", "gpt-4o-mini")
    RAG_PLANNER_PROMPT_VERSION = os.getenv("RAG_PLANNER_PROMPT_VERSION", "v1")
    RAG_SYNTH_MODEL = os.getenv("RAG_SYNTH_MODEL", "gpt-4o-mini")
    RAG_SYNTH_PROMPT_VERSION = os.getenv("RAG_SYNTH_PROMPT_VERSION", "v1")
    # Retrieval defaults — overridable per-request from the API layer.
    RAG_TOP_K_VECTOR = int(os.getenv("RAG_TOP_K_VECTOR", "20"))   # primary vector recall
    RAG_TOP_K_FINAL = int(os.getenv("RAG_TOP_K_FINAL", "10"))     # after merge + rerank
    RAG_MAX_GRAPH_DEPTH = int(os.getenv("RAG_MAX_GRAPH_DEPTH", "1"))
    RAG_TIER_WIDEN_THRESHOLD = int(os.getenv("RAG_TIER_WIDEN_THRESHOLD", "3"))
    # Rerank weights — Phase 5 ships hand-tuned defaults. 5F's eval
    # harness learns better values; Phase 6 replaces these with a
    # learned scorer.
    RAG_RERANK_W_SIMILARITY = float(os.getenv("RAG_RERANK_W_SIMILARITY", "0.7"))
    RAG_RERANK_W_ANCHOR = float(os.getenv("RAG_RERANK_W_ANCHOR", "0.2"))
    RAG_RERANK_W_RECENCY = float(os.getenv("RAG_RERANK_W_RECENCY", "0.1"))

    # ---------------------------------------------------------------------
    # Phase 6 — Importance scoring + reranking
    # ---------------------------------------------------------------------
    # Algorithm provenance. Bump when the formula changes; lands in
    # `importance_runs.algorithm_version` for replayability.
    IMPORTANCE_ALGORITHM_VERSION = os.getenv("IMPORTANCE_ALGORITHM_VERSION", "v1")

    # Coefficients shared by chunks / entities / relationships. Each
    # column is normalized to [0,1] before weighted sum so coefficients
    # are directly comparable. 6F's backfill runs a grid sweep against
    # the eval harness to validate these defaults.
    IMPORTANCE_W_ACCESS = float(os.getenv("IMPORTANCE_W_ACCESS", "0.30"))
    IMPORTANCE_W_CITATION = float(os.getenv("IMPORTANCE_W_CITATION", "0.30"))
    IMPORTANCE_W_RECENCY = float(os.getenv("IMPORTANCE_W_RECENCY", "0.15"))
    IMPORTANCE_W_CONFIDENCE = float(os.getenv("IMPORTANCE_W_CONFIDENCE", "0.10"))
    IMPORTANCE_W_ANCHOR_DENSITY = float(os.getenv("IMPORTANCE_W_ANCHOR_DENSITY", "0.10"))
    # Graph centrality: stubbed to 0.0 in 6A; 6C wires in the real
    # PageRank-style score. Coefficient lives here so the scorer
    # interface freezes now.
    IMPORTANCE_W_CENTRALITY = float(os.getenv("IMPORTANCE_W_CENTRALITY", "0.05"))

    # Recency: exp(-age_days / IMPORTANCE_RECENCY_DECAY_DAYS).
    # 30 = a 1-month-old chunk has 37% of a brand-new chunk's recency
    # weight. Reasonable for meeting/doc churn rates we've seen.
    IMPORTANCE_RECENCY_DECAY_DAYS = float(os.getenv("IMPORTANCE_RECENCY_DECAY_DAYS", "30"))

    # log1p saturation point for count signals. Counts ≥ this are
    # treated as fully-saturated (1.0 after norm). Prevents a single
    # 1000-citation outlier from monopolizing the importance scale.
    IMPORTANCE_COUNT_SATURATION = int(os.getenv("IMPORTANCE_COUNT_SATURATION", "20"))

    # Reranking strategy. Phase 6C ships 'importance_aware'; 6A leaves
    # the default as Phase 5's 'legacy_weighted' so importance scores
    # populate without changing user-facing ranking yet.
    RAG_RERANK_STRATEGY = os.getenv("RAG_RERANK_STRATEGY", "legacy_weighted")

    # ---------------------------------------------------------------------
    # Phase 6D — Consolidation (archive + merge suggestion thresholds)
    # ---------------------------------------------------------------------
    # A chunk/entity/rel is a candidate for archival when ALL of:
    #   - age > CONSOLIDATION_MIN_AGE_DAYS
    #   - access_count == 0
    #   - importance_score < CONSOLIDATION_MAX_IMPORTANCE
    # Defaults are conservative — fresh content + anything cited/important
    # is safe by default. Tune per-org in Phase 7+ if customer profiles diverge.
    CONSOLIDATION_MIN_AGE_DAYS = float(os.getenv("CONSOLIDATION_MIN_AGE_DAYS", "180"))
    CONSOLIDATION_MAX_IMPORTANCE = float(os.getenv("CONSOLIDATION_MAX_IMPORTANCE", "0.2"))
    # Merge suggestion threshold. SequenceMatcher ratio in [0, 1] of
    # canonical_name + sorted aliases. 1.0 = identical text; we exclude
    # those because the upsert dedup already covers them. 0.6-0.85 is
    # the suggestion sweet spot (high enough to be a real candidate;
    # low enough to surface genuine variants like "Helios" vs "Helios Initiative").
    CONSOLIDATION_MERGE_MIN_SIMILARITY = float(
        os.getenv("CONSOLIDATION_MERGE_MIN_SIMILARITY", "0.85"),
    )
    CONSOLIDATION_MERGE_MAX_PAIRS_PER_RUN = int(
        os.getenv("CONSOLIDATION_MERGE_MAX_PAIRS_PER_RUN", "100"),
    )

    # Phase 6C — importance-aware rerank coefficients (additive on top
    # of the legacy weighted score). These are conservative defaults;
    # 6F's coefficient sweep tunes them against the eval harness.
    RAG_RERANK_W_CHUNK_IMP = float(os.getenv("RAG_RERANK_W_CHUNK_IMP", "0.30"))
    RAG_RERANK_W_ENTITY_IMP = float(os.getenv("RAG_RERANK_W_ENTITY_IMP", "0.20"))
    RAG_RERANK_W_ACCESS = float(os.getenv("RAG_RERANK_W_ACCESS_RERANK", "0.10"))

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
