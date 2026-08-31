"""Phase 13A — TranscriptionProvider abstract interface.

Each provider implementation owns:
- `name`              — short string id used in settings.TRANSCRIPTION_PROVIDER
- `recall_provider_key` — the key Recall.ai expects in
                          recording_config.transcript.provider.<key>
- `default_format`    — audio container Recall asks the provider for
- Language-normalization logic — every provider expects a different
  language code format ("hi-IN" vs "hi" vs "multi" vs "auto")
"""
from __future__ import annotations

from typing import Optional, Protocol


class TranscriptionProvider(Protocol):
    """Adapter contract. Implementations must be stateless and
    thread-safe — a single instance is shared process-wide."""

    name: str  # e.g. "assemblyai", "deepgram"
    recall_provider_key: str  # e.g. "assembly_ai_v3_streaming", "deepgram_streaming"

    # Can this provider separate distinct voices inside one audio stream?
    # Declared rather than inferred from `name`, so adding a fourth provider
    # cannot silently make in-room capture look supported when it isn't.
    # `create_bot` reads this to warn when an in-room meeting is about to be
    # recorded by a provider that will return a single speaker.
    supports_diarization: bool

    def build_recording_config(
        self, language: str = "auto", *, diarize: bool = False,
    ) -> dict:
        """Return the dict that goes under
        `recording_config.transcript.provider.<recall_provider_key>` in
        the Recall.ai create_bot payload.

        `language` is OUR normalized code ('auto' | 'hi' | 'en' | etc.).
        The adapter translates that into the provider's expected format
        — e.g. AssemblyAI uses `language_detection: True`, Deepgram uses
        `language: "multi"`.

        `diarize` asks the provider to separate distinct VOICES within one
        audio stream. Only needed for in-room capture, where N people share
        one meeting account and the platform roster therefore names the
        account rather than the speaker. Default False: for a normal online
        meeting Recall's per-participant attribution is exact, and
        diarization would replace real names with anonymous indices.

        Not every provider supports it. An adapter that cannot must IGNORE
        the flag rather than raise — the caller has no way to know which
        provider is active, and a failed bot creation loses the meeting.
        """
        ...

    def extract_language_code(self, webhook_payload: dict) -> Optional[str]:
        """Pull the detected language code from a transcript webhook
        event. Each provider exposes this differently; we normalize to
        a short string (e.g. 'en', 'hi') or None when not present.

        Called by the webhook handler purely for logging — the language
        is NOT used for routing.
        """
        ...
