import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,  # bound at import time, survives mock.patch
    ReadTimeout,
    Timeout,
)
from typing import Callable, Optional
from app.config.settings import settings
import base64
import time
import json
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Per-call timeout on every HTTP request to Recall. None was the default —
# meant a slow Recall API could hang the worker indefinitely. 15s is well
# above their typical p99; anything longer is broken.
_HTTP_TIMEOUT_S = 15

# Retry config for the polling path. Transient network blips against
# ap-northeast-1 from out-of-region workers are normal — without retries,
# one dropped poll = whole meeting marked failed.
_RETRYABLE_EXCEPTIONS = (RequestsConnectionError, ReadTimeout, Timeout)
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_S = (1, 2, 4)  # waits between attempt 1→2, 2→3, 3→4


# Phase 12A — bot status codes that matter for closing-briefing trigger.
# `call_ended` is authoritative for MEETING_ENDED; `done` arrives AFTER
# the bot has left and is too late to inject audio, so we only use it
# for cleanup. `recording_permission_denied` and `fatal` short-circuit
# the briefing to a 'failed' terminal state.
RECALL_TERMINAL_STATUSES = {
    "call_ended",
    "done",
    "recording_permission_denied",
    "fatal",
}


def _request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """HTTP request with retry on transient network errors only.

    Retries ConnectionError + ReadTimeout — these are the failure modes
    that took down meeting 4708 and 4712. HTTP errors (4xx, 5xx) are
    NOT retried here; the caller's `raise_for_status()` handles those.

    Default timeout applied if caller didn't pass one.
    """
    kwargs.setdefault("timeout", _HTTP_TIMEOUT_S)
    last_exc: Optional[Exception] = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return requests.request(method, url, **kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt + 1 >= _RETRY_MAX_ATTEMPTS:
                logger.error(
                    f"[RECALL] {method} {url} failed after {_RETRY_MAX_ATTEMPTS} "
                    f"attempts: {type(exc).__name__}: {exc}"
                )
                raise
            backoff = _RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)]
            logger.warning(
                f"[RECALL] {method} {url} attempt {attempt + 1}/{_RETRY_MAX_ATTEMPTS} "
                f"failed ({type(exc).__name__}); retrying in {backoff}s"
            )
            time.sleep(backoff)
    # Unreachable — loop either returns or raises. Belt-and-suspenders.
    if last_exc:
        raise last_exc
    raise RuntimeError("retry loop fell through without raising")


class RecallService:
    def __init__(self):
        self.base_url = settings.BASE_URL
        self.headers = {
            "Authorization": f"Bearer {settings.RECALL_API_KEY}",
            "Content-Type": "application/json"
        }

    # 1. Create bot (join meeting)
    def create_bot(
        self,
        meeting_url: str,
        meeting_id: int,
        bot_name: str = "AI Note Taker",
        *,
        language: Optional[str] = None,
    ):
        url = f"{self.base_url}/bot/"

        # Phase 13A — provider-aware transcript config. The active
        # provider is chosen by settings.TRANSCRIPTION_PROVIDER and the
        # adapter builds the right shape for Recall's payload.
        # `language` is the per-meeting override; falls back to the
        # workspace default when not provided.
        from app.services.transcription import get_active_provider

        provider = get_active_provider()
        effective_language = language or settings.TRANSCRIPTION_LANGUAGE
        transcript_provider_config = provider.build_recording_config(effective_language)
        logger.info(
            f"Bot {meeting_id}: using transcription provider={provider.name!r} "
            f"recall_key={provider.recall_provider_key!r} language={effective_language!r}"
        )

        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {
                "transcript": {
                    "provider": {
                        provider.recall_provider_key: transcript_provider_config,
                    }
                },
                "participant_events": {},
                "meeting_metadata": {
                    "capture_participant_list": True
                }
            }
        }
        
        # Only add webhook_url if it's a valid public URL (not localhost)
        if settings.APP_PUBLIC_URL and "localhost" not in settings.APP_PUBLIC_URL and "127.0.0.1" not in settings.APP_PUBLIC_URL:
            webhook_url = f"{settings.APP_PUBLIC_URL}/webhook/recall/{meeting_id}"
            payload["webhook_url"] = webhook_url
            payload["recording_config"]["realtime_endpoints"] = [
                {
                    "type": "webhook",
                    "url": webhook_url,
                    # Phase 12A — only RECORDING-level events go in
                    # `realtime_endpoints.events`. Recall.ai's API rejects
                    # `bot.status_change` here ("not a valid choice") —
                    # bot lifecycle events come through the separate
                    # `webhook_url` field below, which posts to the same
                    # `/webhook/recall/{id}` URL. Our dispatcher already
                    # routes both event families.
                    "events": [
                        "transcript.data",
                        "transcript.partial_data",
                        "participant_events.join",
                        "participant_events.leave",
                    ]
                }
            ]
        else:
            logger.warning("APP_PUBLIC_URL is localhost or not set. Realtime streaming will be disabled to avoid API errors.")
        
        # DEBUG: Print the actual payload being sent
        print(f"\n>>> RECALL BOT PAYLOAD: {json.dumps(payload, indent=2)}")
        
        logger.info(f"Sending request to create bot: {url}")
        response = _request_with_retry("POST", url, json=payload, headers=self.headers)

        logger.info(f"Create bot STATUS: {response.status_code}")
        
        if response.status_code != 201:
            logger.error(f"Failed to create bot: {response.text}")

        response.raise_for_status()
        return response.json()

    # 2. Get bot status. Retries transient network errors — without
    # this, a single ReadTimeout against ap-northeast-1 would take
    # down the meeting pipeline (meeting 4708, 4712).
    def get_bot(self, bot_id: str):
        url = f"{self.base_url}/bot/{bot_id}/"
        response = _request_with_retry("GET", url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # 3. List all bots (optional but useful)
    def list_bots(self):
        url = f"{self.base_url}/bot/"
        response = _request_with_retry("GET", url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # Phase 12A — belt-and-suspenders status poll.
    #
    # The closing-briefing trigger is primarily driven by Recall's
    # `bot.status_change` webhook. Webhooks can be lost (network blips,
    # tunnel drops, server restart during a meeting). This method is the
    # backup: an existing background job (`wait_for_transcript`, the
    # post-meeting Celery task) can call this in parallel to detect
    # `call_ended` even when the webhook never fires.
    #
    # `on_terminal_status` receives the raw status dict from Recall:
    #   {"code": "call_ended", "sub_code": "scheduled_end", "created_at": "..."}
    # The caller is expected to be idempotent (i.e. check
    # `Meeting.closing_briefing_status` before acting) — this poll WILL
    # fire on every poll cycle once the bot reaches a terminal state.
    def poll_bot_status(
        self,
        bot_id: str,
        on_terminal_status: Callable[[dict], None],
        poll_interval_s: int = 15,
        max_duration_s: int = 7200,  # 2 hours — longest plausible meeting
    ) -> Optional[dict]:
        """Poll the bot until it reaches a terminal status; invoke callback once.

        Returns the terminal status dict, or None if max_duration_s elapsed
        first (the callback is NOT invoked in that case)."""
        deadline = time.time() + max_duration_s
        fired = False
        while time.time() < deadline:
            try:
                bot_data = self.get_bot(bot_id)
            except Exception as exc:
                logger.warning(f"[POLL] get_bot({bot_id}) failed: {exc}")
                time.sleep(poll_interval_s)
                continue

            status_changes = bot_data.get("status_changes") or []
            if status_changes:
                latest = status_changes[-1] or {}
                code = latest.get("code")
                if not fired and code in RECALL_TERMINAL_STATUSES:
                    logger.info(
                        f"[POLL] Bot {bot_id} reached terminal status '{code}' "
                        f"via fallback poll — invoking callback"
                    )
                    fired = True
                    try:
                        on_terminal_status(latest)
                    except Exception as exc:
                        logger.error(f"[POLL] on_terminal_status callback raised: {exc}", exc_info=True)
                    return latest

            time.sleep(poll_interval_s)

        logger.info(f"[POLL] Bot {bot_id} did not reach terminal status within {max_duration_s}s")
        return None
    
    def wait_for_transcript(
        self,
        bot_id: str,
        timeout: Optional[int] = None,
        *,
        meeting_id: Optional[int] = None,
    ):
        """Wait for the transcript to be ready.
        If timeout is None, it will wait indefinitely until the bot call ends and the transcript is processed.

        Phase 12E: when `meeting_id` is provided, each poll cycle also
        checks whether `call_ended` has appeared in status_changes and
        whether our DB still shows the meeting as pending. If both,
        self-delivers the bot.status_change webhook locally (fallback
        for Recall's unreliable per-bot webhook_url delivery).
        """
        start_time = time.time()
        logger.info(f"Waiting for transcript for bot {bot_id} (Timeout: {timeout or 'None'})...")

        while True:
            try:
                bot_data = self.get_bot(bot_id)
            except _RETRYABLE_EXCEPTIONS as exc:
                # get_bot() already retried 4x with backoff. If it still
                # raised, that's a sustained outage — wait one more poll
                # interval and try again instead of killing the meeting.
                # Meeting 4712 died from a single ReadTimeout here.
                logger.warning(
                    f"[RECALL] wait_for_transcript poll failed transiently "
                    f"({type(exc).__name__}); waiting then retrying"
                )
                time.sleep(15)
                continue
            recordings = bot_data.get("recordings", [])
            status_changes_list = bot_data.get("status_changes", []) or []
            bot_status = status_changes_list[-1].get("code") if status_changes_list else "unknown"

            # Phase 12E — self-deliver the call_ended webhook if it never
            # arrived through Recall's webhook channel. Idempotent.
            if meeting_id is not None:
                try:
                    self.self_deliver_call_ended_if_pending(meeting_id, status_changes_list)
                except Exception as exc:
                    # Never let the fallback path crash transcript waiting.
                    logger.error(f"[POLL] self_deliver raised (ignoring): {exc}")

            if recordings:
                rec = next(
                    (r for r in recordings if r.get("status", {}).get("code") in ["done", "completed"]),
                    None
                )

                if not rec:
                    logger.info(f"⏳ No completed recording yet (Bot Status: {bot_status})...")
                else:
                    transcript = rec.get("media_shortcuts", {}).get("transcript", {})
                    status = transcript.get("status", {}).get("code")
                    download_url = transcript.get("data", {}).get("download_url")

                    logger.info(f"📝 Transcript Status: {status}")

                    if status in ["failed", "canceled"]:
                        logger.error(f"Transcript failed with status: {status}")
                        raise Exception(f"Transcript failed: {status}")

                    if status in ["done", "completed"] and download_url:
                        logger.info("✅ Transcript ready!")
                        return download_url

            else:
                logger.info(f"⏳ No recordings yet (Bot Status: {bot_status})...")

            # Check for timeout if one is provided
            if timeout and (time.time() - start_time > timeout):
                logger.error(f"Timeout waiting for transcript for bot {bot_id}")
                raise TimeoutError("Transcript not ready in time")
            
            # If the bot has left the call and still no recordings after a grace period, we should probably stop.
            if bot_status in ["done", "call_ended"] and not recordings and (time.time() - start_time > 300):
                 logger.error(f"Bot {bot_id} ended call but no recording appeared after 5 minutes.")
                 raise Exception("Bot ended call without recording.")

            sleep_time = min(10 + int((time.time() - start_time) / 60), 30)
            logger.debug(f"Sleeping for {sleep_time} seconds...")
            time.sleep(sleep_time)

    # ---------------------------------------------------------------------
    # Phase 12D — In-meeting audio output + bot leave.
    #
    # These three methods exist so the Phase 12E orchestrator (and 12D's
    # `AudioPlayer`) can drive the bot's mouth + exit cleanly. None of
    # them touch live state; they're thin HTTP wrappers over Recall's
    # bot-control endpoints.
    # ---------------------------------------------------------------------

    def play_audio(
        self,
        bot_id: str,
        audio_bytes: bytes,
        *,
        kind: str = "mp3",
    ) -> dict:
        """Push audio into the meeting via Recall's output_audio endpoint.

        Recall.ai's contract is "send me the bytes" — the audio MUST be
        base64-encoded and sent inline as `b64_data`. There is no fetch-from-URL
        variant. A previous version of this method sent `url=...` which
        Recall silently 400s.

        `kind` matches the audio container (currently always 'mp3' since
        TTSService produces mp3). If a future provider returns wav, the
        TTSResult.format flows through here too.

        Returns the Recall response dict; the caller grabs the playback id
        from `id` or `playback_id`. Raises on HTTP error — AudioPlayer
        catches and degrades.
        """
        if not audio_bytes:
            raise ValueError("play_audio requires non-empty audio_bytes")

        b64 = base64.b64encode(audio_bytes).decode("ascii")
        url = f"{self.base_url}/bot/{bot_id}/output_audio/"
        payload = {"kind": kind, "b64_data": b64}

        logger.info(
            f"[RECALL] play_audio bot={bot_id} kind={kind} "
            f"audio_bytes={len(audio_bytes)} b64_len={len(b64)}"
        )
        response = _request_with_retry("POST", url, json=payload, headers=self.headers)
        if response.status_code not in (200, 201, 202):
            # Don't print the entire base64 blob in error logs.
            body = response.text[:500] if response.text else "(no body)"
            logger.error(
                f"[RECALL] play_audio failed: {response.status_code} body={body}"
            )
            # Raise an exception WITH the body included so the orchestrator
            # captures it in the audit row's error_message column. Plain
            # response.raise_for_status() only includes the URL, not the
            # response body — which is exactly the diagnostic info we need.
            raise HTTPError(
                f"play_audio {response.status_code}: {body}",
                response=response,
            )
        return response.json() if response.content else {"id": None}

    def wait_for_playback_complete(
        self,
        bot_id: str,
        playback_id: Optional[str],
        timeout: int,
        poll_interval_s: float = 1.0,
    ) -> bool:
        """Poll the bot until output playback is reported complete.

        Returns True on confirmed completion; False on timeout (caller
        decides whether to still leave the call — `AudioPlayer` always
        leaves regardless of this return value).

        Recall's output-audio status surfaces under
        `bot_data["output_media"]` or `bot_data["recording_status"]`
        depending on API version. We look for the playback id in either
        location and check its status code.
        """
        if not playback_id:
            # Some Recall plans return no id — we fall back to a fixed
            # delay matched to a conservative upper bound for a 60s clip.
            logger.warning(
                "[RECALL] wait_for_playback called with no playback_id; "
                "falling back to fixed timeout"
            )
            time.sleep(min(timeout, 90))
            return True

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                bot_data = self.get_bot(bot_id)
            except Exception as exc:
                logger.warning(f"[RECALL] wait_for_playback poll failed: {exc}")
                time.sleep(poll_interval_s)
                continue

            # Look in both common shapes — Recall's response schema for
            # output_media has shifted between API versions.
            candidates = []
            if isinstance(bot_data.get("output_media"), list):
                candidates.extend(bot_data["output_media"])
            elif isinstance(bot_data.get("output_media"), dict):
                candidates.append(bot_data["output_media"])
            if isinstance(bot_data.get("output_audio"), list):
                candidates.extend(bot_data["output_audio"])

            for entry in candidates:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("id") or entry.get("playback_id")
                if entry_id != playback_id:
                    continue
                status = entry.get("status") or {}
                if isinstance(status, dict):
                    code = status.get("code")
                else:
                    code = status
                if code in ("done", "completed", "played"):
                    return True
                if code in ("failed", "error"):
                    logger.error(f"[RECALL] playback {playback_id} entered failure state: {code}")
                    return False

            time.sleep(poll_interval_s)

        logger.warning(
            f"[RECALL] wait_for_playback timed out after {timeout}s for "
            f"playback_id={playback_id}"
        )
        return False

    def leave_call(self, bot_id: str) -> None:
        """Tell the bot to disconnect from the meeting.

        Idempotent: Recall returns 200/204 even if the bot has already
        left. We swallow connection errors here too — by the time we
        ask the bot to leave, we want zero remaining work; any failure
        is logged and forgotten.
        """
        url = f"{self.base_url}/bot/{bot_id}/leave_call/"
        try:
            response = _request_with_retry("POST", url, headers=self.headers)
            if response.status_code not in (200, 202, 204):
                logger.warning(
                    f"[RECALL] leave_call returned {response.status_code}: {response.text}"
                )
        except Exception as exc:
            logger.error(f"[RECALL] leave_call request error: {exc}")

    # ---------------------------------------------------------------------
    # Phase 12E — Webhook delivery fallback.
    #
    # Recall.ai's per-bot `webhook_url` field is unreliable for
    # `bot.status_change` events (transcripts + participant events arrive
    # fine via realtime_endpoints, but bot lifecycle events don't). When
    # the polling loop sees `call_ended` in status_changes but our DB
    # still says 'pending', the webhook was lost — we self-deliver by
    # POSTing to our OWN /webhook/recall/{id} endpoint over localhost.
    #
    # Idempotency: the webhook handler refuses to re-emit when
    # closing_briefing_status is already past 'pending', so this can
    # be called repeatedly without side effects.
    # ---------------------------------------------------------------------

    def self_deliver_call_ended_if_pending(
        self, meeting_id: int, status_changes: list,
    ) -> bool:
        """If `call_ended` appears in status_changes but our DB still
        shows the meeting as pending, self-deliver the webhook locally.

        Returns True if a self-delivery was attempted, False otherwise.
        Safe to call on every poll cycle — handler is idempotent.
        """
        # Find the FIRST call_ended entry — Recall sometimes repeats
        # status transitions; we only want the original timestamp.
        ended_status = next(
            (s for s in (status_changes or [])
             if isinstance(s, dict) and s.get("code") == "call_ended"),
            None,
        )
        if ended_status is None:
            return False

        # Cheap DB check first to avoid pointless HTTP roundtrips.
        from app.db.database import SessionLocal
        from app.db.models import Meeting

        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting is None:
                logger.warning(
                    f"[POLL] meeting {meeting_id} not found for self-deliver"
                )
                return False
            if meeting.closing_briefing_status != "pending":
                # Already processed (or in flight). Don't re-fire.
                return False
        finally:
            db.close()

        # Self-deliver. Use the internal URL (localhost) — bypasses ngrok,
        # avoids re-entering our own public endpoint via the tunnel.
        local_url = f"{settings.INTERNAL_WEBHOOK_BASE_URL}/webhook/recall/{meeting_id}"
        payload = {
            "event": "bot.status_change",
            "data": {"status": ended_status},
        }
        logger.info(
            f"[POLL] self-delivering call_ended webhook for meeting {meeting_id} "
            f"(ended_at={ended_status.get('created_at')})"
        )
        try:
            response = requests.post(local_url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.warning(
                    f"[POLL] self-deliver got {response.status_code}: {response.text[:200]}"
                )
                return True  # we tried
            logger.info(f"[POLL] self-deliver succeeded for meeting {meeting_id}")
            return True
        except Exception as exc:
            logger.error(f"[POLL] self-deliver request failed: {exc}")
            return True  # we tried; orchestrator may still pick up next cycle
