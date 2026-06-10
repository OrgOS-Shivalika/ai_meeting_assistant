"""Phase 13A — Deepgram provider adapter.

Uses Deepgram's Nova-3 model via Recall.ai's `deepgram_streaming`
provider key. Nova-3 is the only Deepgram model with full Hindi
support + multilingual code-switching (`language=multi`).

Why Deepgram for Hindi:
- Real-time streaming (Phase 11/12 live cognition keeps working)
- Hindi + 35 other languages supported
- Code-switching ("English words inside Hindi sentences") handled
  natively — important for Indian business meetings where Hinglish is
  the norm
- Cheapest provider on Recall ($0.0043/min ≈ $0.26/hour)

Auth: Recall holds the Deepgram API key in their dashboard ("Providers
→ Deepgram"). We don't need DEEPGRAM_API_KEY in our .env — Recall
authenticates on our behalf.
"""
from __future__ import annotations

from typing import Optional

from app.config.settings import settings


class DeepgramProvider:
    name = "deepgram"
    recall_provider_key = "deepgram_streaming"

    def build_recording_config(self, language: str = "auto") -> dict:
        """Deepgram streaming config. The `language` param is OUR
        normalized code; we translate it here.

        Mapping:
          'auto' / 'multi' -> Deepgram `language=multi` (multilingual
                              auto-detect; the right choice for Hindi/
                              English code-switching)
          'hi' / 'hi-IN'   -> Deepgram `language=hi` (explicit Hindi —
                              slightly more accurate on pure Hindi
                              audio but worse on Hinglish)
          'en' / 'en-US'   -> Deepgram `language=en`
          (other BCP-47)   -> stripped to base tag and passed through
        """
        dg_lang = self._normalize_language(language)

        # Deepgram-via-Recall options. Defaults are tuned for natural
        # meeting audio:
        # - model: nova-3 is the only Hindi-capable model
        # - smart_format: punctuation + casing + number formatting
        # - punctuate: explicit punctuation (redundant with smart_format
        #   on Nova-3 but harmless)
        # - diarize: speaker labels — Recall already handles speaker
        #   attribution via its participant tracking, so we can skip
        #   this. Set False to save Deepgram cost.
        return {
            "model": settings.DEEPGRAM_MODEL,
            "language": dg_lang,
            "smart_format": True,
            "punctuate": True,
            "diarize": False,
        }

    @staticmethod
    def _normalize_language(language: str) -> str:
        if not language:
            return "multi"
        lang = language.strip().lower()
        if lang in ("auto", "multi", ""):
            return "multi"
        # Strip BCP-47 region (hi-IN -> hi, en-US -> en).
        # Deepgram accepts both forms but the base tag is more permissive.
        base = lang.split("-")[0]
        # Sanity check — Deepgram-supported short codes are 2-3 chars.
        return base if 1 < len(base) <= 3 else "multi"

    def extract_language_code(self, webhook_payload: dict) -> Optional[str]:
        data_block = webhook_payload.get("data") or {}
        provider_data = data_block.get("provider_data") or {}
        # Deepgram surfaces detected language as `language` in its
        # provider_data block. When `language=multi` is requested,
        # Deepgram populates this per-utterance with the detected one.
        code = provider_data.get("language") or provider_data.get("detected_language")
        if isinstance(code, str) and code.strip():
            return code.strip().lower()
        # Fall back to data_block.language if provider_data is empty
        # (older payload shape).
        fallback = data_block.get("language")
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip().lower()
        return None
