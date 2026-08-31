"""Phase 13A — AssemblyAI provider adapter.

Preserves the existing behavior from before the provider abstraction:
universal-streaming-multilingual with language_detection enabled.

Limitations vs Deepgram:
- Streaming model supports ~7 European languages (en/es/fr/de/it/pt/nl)
- NO Hindi or other Indic language support in streaming mode
- Code-switching support is mediocre

Kept available so deployments that don't need Hindi can avoid switching.
"""
from __future__ import annotations

from typing import Optional


class AssemblyAIProvider:
    name = "assemblyai"
    recall_provider_key = "assembly_ai_v3_streaming"
    # v3 streaming exposes no diarization option through Recall.
    supports_diarization = False

    def build_recording_config(
        self, language: str = "auto", *, diarize: bool = False,
    ) -> dict:
        """AssemblyAI streaming config. language_detection is enabled
        when caller asks for 'auto' (the default); explicit non-auto
        language codes are ignored because AssemblyAI streaming doesn't
        actually let you pin to a specific language — the multilingual
        model always detects.

        `diarize` is accepted and IGNORED. AssemblyAI's v3 streaming model
        exposes no speaker-diarization option through Recall, so there is
        nothing to forward. Swallowing it rather than raising is deliberate:
        the caller cannot know which provider is active, and a rejected
        create_bot payload loses the meeting entirely. In-room capture
        therefore requires TRANSCRIPTION_PROVIDER=deepgram — a fact
        `RecallService.create_bot` logs loudly when the two disagree, since
        the alternative is a silently mono-speaker in-room transcript.
        """
        # AssemblyAI v3 streaming options:
        # - speech_model: 'universal-streaming-multilingual' is the only
        #   multilingual variant. There's no Hindi-specific model in
        #   streaming mode.
        # - language_detection: when True, the provider auto-detects
        #   which of its supported languages is being spoken.
        # - format_turns: emits finalized turns when speakers pause,
        #   instead of streaming words continuously. Better for our
        #   turn-aware UI but introduces some latency.
        return {
            "speech_model": "universal-streaming-multilingual",
            "language_detection": True,
            "format_turns": True,
        }

    def extract_language_code(self, webhook_payload: dict) -> Optional[str]:
        data_block = webhook_payload.get("data") or {}
        # Provider-specific metadata lives under provider_data.
        provider_data = data_block.get("provider_data") or {}
        # AssemblyAI exposes the detected language as `language_code`.
        # Older payload variants put it under `data.language`.
        code = provider_data.get("language_code") or data_block.get("language")
        if isinstance(code, str) and code.strip():
            return code.strip().lower()
        return None
