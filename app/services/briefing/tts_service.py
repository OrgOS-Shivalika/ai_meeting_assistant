"""Phase 12D — Text-to-Speech service.

Converts a `BriefingScript.full_text` into audio bytes ready to be
uploaded to S3/MinIO and pushed into a Recall.ai bot. Provider
abstraction: today only OpenAI tts-1-hd is implemented; ElevenLabs /
Azure / others slot in as new `_Provider` subclasses without touching
the public `TTSService` interface or call sites.

Caching
-------
Audio bytes are content-addressed (SHA256 of voice + model + text) and
cached on disk under `settings.TTS_CACHE_DIR`. Same script with the
same voice + model returns the cached bytes without re-billing OpenAI.
This is the latency trick that makes the closing-briefing feel snappy:
Phase 12E's orchestrator can pre-render on `meeting.winding_down` and
trust the cache to be hot on `meeting.ended`.

Failures
--------
- Missing OpenAI key      -> raises RuntimeError on first synthesize().
- Network / API error     -> raises after the SDK's built-in retries.
- Empty / whitespace text -> raises ValueError before any network call.
Callers (Phase 12E orchestrator) are expected to catch and degrade
gracefully (mark meeting `closing_briefing_status='failed'`).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Optional, Protocol

from app.config.settings import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class TTSResult:
    """Output of a successful synthesis call."""
    audio_bytes: bytes
    content_type: str            # 'audio/mpeg', 'audio/wav', etc.
    format: str                  # 'mp3' / 'wav' / 'opus' — short tag
    provider: str
    model: str
    voice: str
    char_count: int              # length of input text — used for cost audit
    cache_hit: bool
    cache_key: str


class _Provider(Protocol):
    """Adapter contract. Implementations must be thread-safe."""
    name: str
    default_format: str          # 'mp3' / 'wav' / ...
    default_content_type: str    # MIME type matching `default_format`

    def synthesize(self, text: str, voice: str, model: str) -> bytes:
        """Block on the network call. Return raw audio bytes."""
        ...


# ---------------------------------------------------------------------------
# OpenAI provider — uses the existing `_get_client()` factory from the
# transcript analyzer so we share connection pools and the lazy-init
# pattern (missing OPEN_API_KEY doesn't crash module import).
# ---------------------------------------------------------------------------

class _OpenAIProvider:
    name = "openai"
    default_format = "mp3"
    default_content_type = "audio/mpeg"

    def synthesize(self, text: str, voice: str, model: str) -> bytes:
        # Imported lazily so a misconfigured key only blows up at call time,
        # never on app boot. Mirrors the pattern in DecisionExtractor.
        from app.ai_agents.openAI_transcript_analyzer import _get_client
        client = _get_client()
        # OpenAI SDK >=1.0 returns a `BinaryAPIResponse` whose `.content`
        # is the raw audio. Voice / model / format are validated server-side.
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        # `.read()` works on both streaming and non-streaming responses
        # depending on SDK version; fall back to `.content` for safety.
        try:
            return response.read()
        except AttributeError:
            return response.content  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# TTSService — public surface.
# ---------------------------------------------------------------------------

class TTSService:
    """Singleton-style. State is just the provider registry + cache dir."""

    _providers: dict[str, _Provider] = {}

    @classmethod
    def register(cls, provider: _Provider) -> None:
        """Public hook so new provider modules can plug in via import."""
        cls._providers[provider.name] = provider

    def __init__(self, provider_name: Optional[str] = None) -> None:
        provider_name = provider_name or settings.TTS_PROVIDER
        # Lazy default registration — keeps the class importable even
        # when no provider modules have been explicitly imported elsewhere.
        if not TTSService._providers:
            TTSService.register(_OpenAIProvider())

        if provider_name not in TTSService._providers:
            raise ValueError(
                f"TTS provider {provider_name!r} not registered. "
                f"Available: {sorted(TTSService._providers)}"
            )
        self._provider = TTSService._providers[provider_name]
        self._cache_dir = settings.TTS_CACHE_DIR

    # --- Public API ----------------------------------------------------

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        model: Optional[str] = None,
    ) -> TTSResult:
        """Convert text to audio. Hits cache when possible.

        Caching key includes voice + model + provider + text so a voice
        change invalidates the cache for that script.
        """
        if not text or not text.strip():
            raise ValueError("TTSService.synthesize requires non-empty text")

        voice = voice or settings.TTS_VOICE
        model = model or settings.TTS_MODEL
        provider_name = self._provider.name

        cache_key = self._cache_key(provider_name, model, voice, text)
        cached = self._read_cache(cache_key)
        if cached is not None:
            logger.info(
                f"[TTS] cache HIT provider={provider_name} model={model} "
                f"voice={voice} key={cache_key[:12]}... chars={len(text)}"
            )
            return TTSResult(
                audio_bytes=cached,
                content_type=self._provider.default_content_type,
                format=self._provider.default_format,
                provider=provider_name,
                model=model,
                voice=voice,
                char_count=len(text),
                cache_hit=True,
                cache_key=cache_key,
            )

        logger.info(
            f"[TTS] cache MISS provider={provider_name} model={model} "
            f"voice={voice} chars={len(text)} — calling API"
        )
        audio_bytes = self._provider.synthesize(text=text, voice=voice, model=model)
        if not audio_bytes:
            raise RuntimeError(
                f"TTS provider {provider_name!r} returned empty audio bytes"
            )

        # Cache write is best-effort — a read-only disk should not break
        # the live briefing path.
        try:
            self._write_cache(cache_key, audio_bytes)
        except OSError as exc:
            logger.warning(f"[TTS] failed to write cache (continuing): {exc}")

        return TTSResult(
            audio_bytes=audio_bytes,
            content_type=self._provider.default_content_type,
            format=self._provider.default_format,
            provider=provider_name,
            model=model,
            voice=voice,
            char_count=len(text),
            cache_hit=False,
            cache_key=cache_key,
        )

    # --- Cache helpers -------------------------------------------------

    def _cache_key(self, provider: str, model: str, voice: str, text: str) -> str:
        h = hashlib.sha256()
        h.update(provider.encode())
        h.update(b"|")
        h.update(model.encode())
        h.update(b"|")
        h.update(voice.encode())
        h.update(b"|")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def _cache_path(self, key: str) -> str:
        # `.mp3` extension is purely informational — the file is read as
        # opaque bytes. Helps when someone ls's the cache dir.
        return os.path.join(
            self._cache_dir, f"{key}.{self._provider.default_format}"
        )

    def _read_cache(self, key: str) -> Optional[bytes]:
        path = self._cache_path(key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError as exc:
            logger.warning(f"[TTS] cache read failed for {path}: {exc}")
            return None

    def _write_cache(self, key: str, audio_bytes: bytes) -> None:
        os.makedirs(self._cache_dir, exist_ok=True)
        path = self._cache_path(key)
        tmp = path + ".tmp"
        # Atomic: write to tmp, fsync, rename. Otherwise a crash mid-write
        # leaves a corrupt cache file with the canonical name.
        with open(tmp, "wb") as f:
            f.write(audio_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
