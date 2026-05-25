from app.db.database import SessionLocal
from app.db.models import Meeting
import json

db = SessionLocal()
try:
    meeting = db.query(Meeting).order_by(Meeting.created_at.desc()).first()
    if meeting:
        print(f"Meeting ID: {meeting.id}")
        print(f"Status: {meeting.status}")
        print(f"Created At: {meeting.created_at}")
        print(f"URL: {meeting.meeting_url}")
        # Check for error info if it was stored somewhere, or just status
    else:
        print("No meetings found.")
finally:
    db.close()
