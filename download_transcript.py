import requests
from app.services.recall_ai_service import RecallService
import json

bot_id = "649ab4ff-a7ad-494f-9192-da6b259ddf1b"
recall = RecallService()
try:
    bot_data = recall.get_bot(bot_id)
    recordings = bot_data.get("recordings", [])
    if recordings:
        rec = recordings[0]
        transcript_data = rec.get("media_shortcuts", {}).get("transcript", {}).get("data", {})
        download_url = transcript_data.get("download_url")
        if download_url:
            print(f"Downloading from: {download_url}")
            resp = requests.get(download_url)
            print("Transcript JSON Content:")
            print(json.dumps(resp.json(), indent=2)[:2000])
        else:
            print("No download URL found.")
    else:
        print("No recordings found.")
except Exception as e:
    print(f"Error: {e}")
