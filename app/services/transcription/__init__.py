"""Phase 13A — Transcription provider abstraction.

Recall.ai routes audio through a third-party transcription provider.
Each provider has a different shape for both the bot-config payload
(what we send to Recall) and the webhook event payload (what Recall
sends back to us — provider-specific metadata under `provider_data`).

This package factors that variation behind a stable interface:

    from app.services.transcription import get_active_provider
    provider = get_active_provider()          # respects settings.TRANSCRIPTION_PROVIDER
    config = provider.build_recording_config(language="hi")
    # -> goes into Recall create_bot payload under
    #    recording_config.transcript.provider.<provider_name>

    lang = provider.extract_language_code(webhook_payload)
    # -> reads the provider's specific language hint from a transcript event

Adding a new provider (e.g. Sarvam AI, Google STT, Gladia):
    1. Subclass `TranscriptionProvider` in a new module
    2. Implement `build_recording_config` + `extract_language_code`
    3. Register it in `registry.py`
"""

from app.services.transcription.base import TranscriptionProvider
from app.services.transcription.registry import (
    get_active_provider,
    get_provider_by_name,
    register_provider,
)

__all__ = [
    "TranscriptionProvider",
    "get_active_provider",
    "get_provider_by_name",
    "register_provider",
]
