import logging
import sys
import json
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.services.live_stream.stream_manager import stream_manager
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.meeting_memory.meeting_state_store import state_store

# Force high-detail logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("debug_live_pipeline")

def debug_replay(meeting_id: int):
    db: Session = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            print(f"Error: Meeting {meeting_id} not found.")
            return

        transcript = meeting.transcript or ""
        if not transcript:
            print("Error: Meeting has no transcript.")
            return

        # Split transcript into lines (simulating chunks)
        lines = [l.strip() for l in transcript.split("\n") if l.strip()]
        print(f"🕵️ Debugging Live Pipeline for Meeting {meeting_id}")
        print(f"📖 Replaying {len(lines)} conversational turns...")

        # 1. Start Session
        stream_manager.start_session(str(meeting_id))
        
        # 2. Ingest Chunks
        for i, line in enumerate(lines):
            speaker = "Unknown"
            text = line
            if ": " in line:
                speaker, text = line.split(": ", 1)
            
            chunk = LiveTranscriptChunk(
                speaker_id="debug_user",
                speaker_name=speaker,
                text=text,
                sequence_number=i + 1,
                is_final=True
            )
            
            print(f"\n--- Turn {i+1}: {speaker} ---")
            print(f"Text: {text}")
            
            # This triggers: Ingestion -> Detection -> Stabilization -> Events
            stream_manager.ingest_chunk(str(meeting_id), chunk)
            
        # 3. Final State Report
        state = state_store.get_state(str(meeting_id))
        print("\n" + "="*50)
        print("🧠 FINAL COGNITIVE STATE REPORT")
        print("="*50)
        print(f"Total Active Tasks: {len(state.active_tasks)}")
        
        for fp, task in state.active_tasks.items():
            print(f"\n📍 Task: {task.task}")
            print(f"   Status: {task.status}")
            print(f"   Confidence: {task.confidence:.2f}")
            print(f"   Mentions: {task.mention_count}")
            print(f"   Owner: {task.owner} ({task.ownership_type})")
            print(f"   Evolution: {' -> '.join([e.to_state for e in task.evolution])}")

    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        debug_replay(int(sys.argv[1]))
    else:
        print("Usage: python scripts/debug_live_pipeline.py [meeting_id]")
