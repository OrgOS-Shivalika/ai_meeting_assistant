from app.services.recall_ai_service import RecallService
from app.config.settings import settings
import json

bot_id = "649ab4ff-a7ad-494f-9192-da6b259ddf1b"
recall = RecallService()
try:
    bot_data = recall.get_bot(bot_id)
    print(json.dumps(bot_data, indent=2))
except Exception as e:
    print(f"Error fetching bot: {e}")
