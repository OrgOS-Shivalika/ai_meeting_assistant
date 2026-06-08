import requests
from typing import Callable, Optional
from app.config.settings import settings
import time
import json
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


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


class RecallService:
    def __init__(self):
        self.base_url = settings.BASE_URL
        self.headers = {
            "Authorization": f"Bearer {settings.RECALL_API_KEY}",
            "Content-Type": "application/json"
        }

    # 1. Create bot (join meeting)
    def create_bot(self, meeting_url: str, meeting_id: int, bot_name: str = "AI Note Taker"):
        url = f"{self.base_url}/bot/"

        payload = {
            "meeting_url": meeting_url,
            "bot_name": bot_name,
            "recording_config": {
                "transcript": {
                    "provider": {
                        "assembly_ai_v3_streaming": {
                            "speech_model": "universal-streaming-multilingual",
                            "language_detection": True,
                            "format_turns": True
                        }
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
        response = requests.post(url, json=payload, headers=self.headers)

        logger.info(f"Create bot STATUS: {response.status_code}")
        
        if response.status_code != 201:
            logger.error(f"Failed to create bot: {response.text}")

        response.raise_for_status()
        return response.json()

    # 2. Get bot status
    def get_bot(self, bot_id: str):
        url = f"{self.base_url}/bot/{bot_id}/"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        return response.json()

    # 3. List all bots (optional but useful)
    def list_bots(self):
        url = f"{self.base_url}/bot/"
        response = requests.get(url, headers=self.headers)
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
    
    def wait_for_transcript(self, bot_id: str, timeout: Optional[int] = None):
        """Wait for the transcript to be ready. 
        If timeout is None, it will wait indefinitely until the bot call ends and the transcript is processed.
        """
        start_time = time.time()
        logger.info(f"Waiting for transcript for bot {bot_id} (Timeout: {timeout or 'None'})...")

        while True:
            bot_data = self.get_bot(bot_id)
            recordings = bot_data.get("recordings", [])
            bot_status = bot_data.get("status_changes", [])[-1].get("code") if bot_data.get("status_changes") else "unknown"

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
