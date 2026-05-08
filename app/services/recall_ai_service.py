import requests
from app.config.settings import settings
import time
import json
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


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
                        "recallai_streaming": {
                            "mode": "prioritize_low_latency",
                            "language_code": "en"
                        }
                    }
                },
                "participant_events": {},
                "meeting_metadata": {}
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
                    "events": ["transcript.data", "transcript.partial_data"]
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
    
    def wait_for_transcript(self, bot_id: str, timeout: int = 1200):
        start_time = time.time()
        logger.info(f"Waiting for transcript for bot {bot_id}...")

        while True:
            bot_data = self.get_bot(bot_id)
            recordings = bot_data.get("recordings", [])

            if recordings:
                rec = next(
                    (r for r in recordings if r.get("status", {}).get("code") in ["done", "completed"]),
                    None
                )

                if not rec:
                    logger.info("⏳ No completed recording yet...")
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
                logger.info("⏳ No recordings yet...")

            if time.time() - start_time > timeout:
                logger.error(f"Timeout waiting for transcript for bot {bot_id}")
                raise TimeoutError("Transcript not ready in time")

            sleep_time = min(10 + int((time.time() - start_time) / 60), 30)
            logger.debug(f"Sleeping for {sleep_time} seconds...")
            time.sleep(sleep_time)
