from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.services import transcription_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/transcriptions", tags=["Transcriptions"])


# ✅ Get formatted transcript
@router.get("/{meeting_id}")
def get_transcript(meeting_id: int, db: Session = Depends(get_db), user = Depends(get_current_user)):
    meeting = transcription_service.get_owned_meeting(db, user, meeting_id)

    return {
        "meeting_id": meeting.id,
        "transcript_text": meeting.transcript_text
    }


# ✅ Get raw transcript JSON
@router.get("/{meeting_id}/raw")
def get_raw_transcript(meeting_id: int, db: Session = Depends(get_db), user = Depends(get_current_user)):
    meeting = transcription_service.get_owned_meeting(db, user, meeting_id)

    return {
        "meeting_id": meeting.id,
        "transcript_raw": meeting.transcript_raw
    }
