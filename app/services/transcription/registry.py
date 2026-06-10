"""Phase 13A — Provider registry.

One source of truth for "which transcription provider is active." Reads
`settings.TRANSCRIPTION_PROVIDER` at lookup time (not at import time)
so tests + runtime config changes take effect immediately.

Adding a new provider:
    register_provider(SarvamProvider())
…anywhere during module import time. The default providers below
register on this module's import.
"""
from __future__ import annotations

from typing import Dict, Optional

from app.config.settings import settings
from app.services.transcription.assemblyai_provider import AssemblyAIProvider
from app.services.transcription.base import TranscriptionProvider
from app.services.transcription.deepgram_provider import DeepgramProvider
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


_REGISTRY: Dict[str, TranscriptionProvider] = {}


def register_provider(provider: TranscriptionProvider) -> None:
    """Public hook so new provider modules can self-register at import."""
    _REGISTRY[provider.name] = provider


def get_provider_by_name(name: str) -> TranscriptionProvider:
    """Lookup by short name. Raises ValueError with available options
    listed when the name is unknown — better failure mode than silent
    fallback (would silently use the wrong provider for months)."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown transcription provider {name!r}. "
            f"Available: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def get_active_provider() -> TranscriptionProvider:
    """Return the provider selected by settings.TRANSCRIPTION_PROVIDER.
    Read at call time so changes to the setting (e.g. via test
    fixtures) take effect immediately."""
    return get_provider_by_name(settings.TRANSCRIPTION_PROVIDER)


# ---------------------------------------------------------------------------
# Defaults — registered on package import. Order doesn't matter; lookup
# is dict-based by name.
# ---------------------------------------------------------------------------
register_provider(AssemblyAIProvider())
register_provider(DeepgramProvider())
