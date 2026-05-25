from app.db.database import SessionLocal
from app.db.models import Meeting
import json

db = SessionLocal()
try:
    meeting = db.query(Meeting).filter(Meeting.id == 4422).first()
    if meeting:
        print(f"Meeting ID: {meeting.id}")
        print(f"Status: {meeting.status}")
        print(f"Title: {meeting.title}")
        print(f"Summary exists: {bool(meeting.summary)}")
        print(f"Transcript Raw exists: {bool(meeting.transcript_raw)}")
        print(f"Transcript Text exists: {bool(meeting.transcript_text)}")
        print(f"Bot ID: {meeting.bot_id}")
    else:
        print("Meeting not found.")
finally:
    db.close()
