"""Phase 12D — Audio delivery to Recall.ai.

Takes synthesized audio bytes (from `TTSService`), uploads them to
S3/MinIO using the existing `storage_service` (Recall needs a public
URL to fetch the audio), kicks off playback on the bot, polls until
playback completes, and ALWAYS leaves the call afterwards — even on
playback failure — so the bot doesn't camp in the meeting.

The "always leave" guarantee is the contract. If TTS works but playback
fails halfway, the bot must still leave. If the upload fails before
playback even starts, the bot must still leave. If Recall's API is
flaky and we never get a confirmed playback status, we time out and
leave anyway.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.config.settings import settings
from app.services.briefing.tts_service import TTSResult
from app.services.recall_ai_service import RecallService
from app.services.storage_service import storage, StorageNotConfigured
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class PlaybackResult:
    """Audit-friendly outcome of one play_audio_for_bot() call."""
    bot_id: str
    audio_storage_key: str
    audio_url: str               # presigned URL Recall fetched
    playback_id: Optional[str]   # Recall-side id; None on early failure
    status: str                  # 'spoken' | 'playback_failed' | 'upload_failed'
                                 # | 'timeout' | 'storage_not_configured'
    duration_s: float            # wall time from upload to playback complete
    error_message: Optional[str] = None
    left_call: bool = False      # did we successfully call leave_call?


class AudioPlayer:
    """Coordinates upload -> play -> poll -> leave. Stateless across calls."""

    def __init__(self, recall_service: Optional[RecallService] = None) -> None:
        # Inject for testability — the test suite passes a mocked
        # RecallService; production uses the default-constructed one.
        self._recall = recall_service or RecallService()
        self._timeout_s = settings.RECALL_PLAYBACK_TIMEOUT_S
        # Presigned URL TTL. Recall typically fetches within seconds,
        # but give a generous window in case of internal queueing.
        self._presigned_ttl_s = max(self._timeout_s * 2, 600)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deliver(
        self,
        bot_id: str,
        meeting_id: int,
        tts_result: TTSResult,
        *,
        leave_after: bool = True,
    ) -> PlaybackResult:
        """Upload -> play -> wait -> leave.

        Returns a PlaybackResult describing what happened. The caller
        (Phase 12E orchestrator) decides how to map the status field to
        `closing_briefing_status` and what to persist to the audit table.

        `leave_after=False` is provided for tests + diagnostic scripts
        that want to test playback without dropping the bot.
        """
        t_start = time.monotonic()
        storage_key = self._build_storage_key(meeting_id, tts_result)

        # 1. Upload the audio so Recall can fetch it.
        try:
            audio_url = self._upload(tts_result, storage_key)
        except StorageNotConfigured as exc:
            logger.error(f"[PLAYBACK] storage not configured: {exc}")
            # Can't deliver audio at all. Still leave the call.
            self._safe_leave(bot_id, leave_after)
            return PlaybackResult(
                bot_id=bot_id,
                audio_storage_key=storage_key,
                audio_url="",
                playback_id=None,
                status="storage_not_configured",
                duration_s=time.monotonic() - t_start,
                error_message=str(exc),
                left_call=leave_after,
            )
        except Exception as exc:
            logger.error(f"[PLAYBACK] upload failed: {exc}", exc_info=True)
            self._safe_leave(bot_id, leave_after)
            return PlaybackResult(
                bot_id=bot_id,
                audio_storage_key=storage_key,
                audio_url="",
                playback_id=None,
                status="upload_failed",
                duration_s=time.monotonic() - t_start,
                error_message=str(exc),
                left_call=leave_after,
            )

        # 2. Tell Recall to play it.
        #
        # Recall's output_audio endpoint takes base64 bytes INLINE — it
        # doesn't fetch from a URL. We still uploaded to S3 above so the
        # frontend's audio-replay endpoint has somewhere to serve from.
        try:
            play_response = self._recall.play_audio(
                bot_id,
                tts_result.audio_bytes,
                kind=tts_result.format,
            )
            playback_id = play_response.get("id") or play_response.get("playback_id")
        except Exception as exc:
            logger.error(f"[PLAYBACK] play_audio failed: {exc}", exc_info=True)
            self._safe_leave(bot_id, leave_after)
            return PlaybackResult(
                bot_id=bot_id,
                audio_storage_key=storage_key,
                audio_url=audio_url,
                playback_id=None,
                status="playback_failed",
                duration_s=time.monotonic() - t_start,
                error_message=str(exc),
                left_call=leave_after,
            )

        # 3. Wait for playback to complete.
        try:
            completed = self._recall.wait_for_playback_complete(
                bot_id=bot_id,
                playback_id=playback_id,
                timeout=self._timeout_s,
            )
        except Exception as exc:
            logger.error(f"[PLAYBACK] wait_for_playback failed: {exc}", exc_info=True)
            self._safe_leave(bot_id, leave_after)
            return PlaybackResult(
                bot_id=bot_id,
                audio_storage_key=storage_key,
                audio_url=audio_url,
                playback_id=playback_id,
                status="timeout",
                duration_s=time.monotonic() - t_start,
                error_message=str(exc),
                left_call=leave_after,
            )

        if not completed:
            # Timed out gracefully (no exception). Still leave.
            self._safe_leave(bot_id, leave_after)
            return PlaybackResult(
                bot_id=bot_id,
                audio_storage_key=storage_key,
                audio_url=audio_url,
                playback_id=playback_id,
                status="timeout",
                duration_s=time.monotonic() - t_start,
                error_message=f"playback did not complete within {self._timeout_s}s",
                left_call=leave_after,
            )

        # 4. Happy path — leave cleanly.
        left = self._safe_leave(bot_id, leave_after)
        return PlaybackResult(
            bot_id=bot_id,
            audio_storage_key=storage_key,
            audio_url=audio_url,
            playback_id=playback_id,
            status="spoken",
            duration_s=time.monotonic() - t_start,
            error_message=None,
            left_call=left,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_storage_key(self, meeting_id: int, tts_result: TTSResult) -> str:
        """Predictable but unique key. The UUID suffix prevents collisions
        when the same script is delivered twice (e.g. a re-test)."""
        return (
            f"closing_briefings/{meeting_id}/"
            f"{tts_result.cache_key[:12]}-{uuid.uuid4().hex[:8]}."
            f"{tts_result.format}"
        )

    def _upload(self, tts_result: TTSResult, key: str) -> str:
        storage.upload_bytes(
            data=tts_result.audio_bytes,
            key=key,
            content_type=tts_result.content_type,
        )
        url = storage.presigned_get_url(key, expires_in=self._presigned_ttl_s)
        logger.info(
            f"[PLAYBACK] uploaded audio key={key} size={len(tts_result.audio_bytes)}b "
            f"presigned_ttl={self._presigned_ttl_s}s"
        )
        return url

    def _safe_leave(self, bot_id: str, should_leave: bool) -> bool:
        """leave_call must NEVER raise to the caller — the orchestrator
        relies on this being terminal."""
        if not should_leave:
            return False
        try:
            self._recall.leave_call(bot_id)
            logger.info(f"[PLAYBACK] bot {bot_id} left call cleanly")
            return True
        except Exception as exc:
            logger.error(
                f"[PLAYBACK] leave_call failed for bot {bot_id}: {exc}",
                exc_info=True,
            )
            return False
