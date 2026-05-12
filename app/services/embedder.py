"""Phase 2 embedding service.

Thin wrapper over the OpenAI embeddings API with:
- Lazy client construction (a missing OPEN_API_KEY doesn't crash imports).
- Automatic batching up to `EMBEDDING_BATCH_SIZE` per HTTP request.
- Exponential backoff on `RateLimitError` and 5xx responses.
- Input-order preservation across batches.

Phase 2 stays OpenAI-only on purpose — Gemini's embedding model has a
different dimensionality and would force a column change. We can add a
provider abstraction later if/when we need it; for now, keep it boring."""
from __future__ import annotations

import logging
import time
from typing import Sequence

from openai import OpenAI, APIError, RateLimitError, APIConnectionError, APITimeoutError

from app.config.settings import settings

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily construct the OpenAI client. Mirrors the analyzer pattern
    so a missing key only errors when someone actually tries to embed."""
    global _client
    if _client is None:
        if not settings.OPEN_API_KEY:
            raise RuntimeError("OPEN_API_KEY is not set — cannot embed")
        _client = OpenAI(api_key=settings.OPEN_API_KEY)
    return _client


class Embedder:
    """Embeds lists of texts. Reuse one instance across requests — it
    holds no per-call state and the underlying client is shared anyway."""

    # Errors we'll retry through. APIError covers most server-side
    # failures including 5xx; we narrow further by status_code in the
    # retry loop so a 4xx (e.g. bad model name) fails fast.
    _RETRYABLE = (RateLimitError, APIConnectionError, APITimeoutError)

    def __init__(
        self,
        *,
        model: str | None = None,
        dimensions: int | None = None,
        batch_size: int | None = None,
        max_retries: int = 5,
        initial_backoff: float = 1.0,
    ):
        self.model = model or settings.EMBEDDING_MODEL
        self.dimensions = dimensions or settings.EMBEDDING_DIMENSIONS
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text, in the same order.
        Raises after `max_retries` consecutive retryable failures."""
        if not texts:
            return []

        # Treat all-whitespace inputs as a programmer bug — the chunker
        # should have stripped them. Log and continue with the original
        # list rather than silently injecting padding vectors.
        for i, t in enumerate(texts):
            if not t or not t.strip():
                raise ValueError(f"embed: text at index {i} is empty/whitespace")

        out: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            logger.info(
                "Embedding batch %d/%d (size=%d, model=%s)",
                (start // self.batch_size) + 1,
                (total + self.batch_size - 1) // self.batch_size,
                len(batch),
                self.model,
            )
            out.extend(self._embed_one_batch(batch))
        return out

    # ----------------------------------------------------------------- internals
    def _embed_one_batch(self, batch: list[str]) -> list[list[float]]:
        client = _get_client()
        backoff = self.initial_backoff
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = client.embeddings.create(
                    model=self.model,
                    input=batch,
                    # `dimensions` is supported by text-embedding-3-* models
                    # and ignored by older models. Sending it keeps the
                    # column width contract explicit.
                    dimensions=self.dimensions,
                )
                # The response preserves input order; rely on the SDK's
                # ordering rather than `data[i].index` so it's a single
                # surface to verify.
                vectors = [item.embedding for item in resp.data]
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"embed: provider returned {len(vectors)} vectors for "
                        f"{len(batch)} inputs"
                    )
                if getattr(resp, "usage", None):
                    logger.info(
                        "Embedding usage: prompt_tokens=%s total_tokens=%s",
                        getattr(resp.usage, "prompt_tokens", "?"),
                        getattr(resp.usage, "total_tokens", "?"),
                    )
                return vectors
            except self._RETRYABLE as e:
                last_exc = e
                if attempt >= self.max_retries:
                    break
                wait = backoff
                logger.warning(
                    "Embedder retryable error (%s), sleeping %.1fs before retry %d/%d",
                    type(e).__name__, wait, attempt + 1, self.max_retries,
                )
                time.sleep(wait)
                backoff *= 2
            except APIError as e:
                # 5xx → retry; everything else (4xx auth/bad request) → raise.
                status = getattr(e, "status_code", None)
                if status is not None and 500 <= int(status) < 600 and attempt < self.max_retries:
                    last_exc = e
                    wait = backoff
                    logger.warning(
                        "Embedder server error %s, sleeping %.1fs before retry %d/%d",
                        status, wait, attempt + 1, self.max_retries,
                    )
                    time.sleep(wait)
                    backoff *= 2
                    continue
                raise
        assert last_exc is not None
        raise last_exc
