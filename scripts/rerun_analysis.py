import logging
import sys
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.services.behavior.resolver import resolve_behavior_profile
from app.services.agents.graph_orchestrator import AgentGraphOrchestrator

# Setup logging to see the modular skills in action
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("rerun_analysis")

def rerun_meeting_analysis(meeting_id: int):
    db: Session = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            print(f"Error: Meeting {meeting_id} not found.")
            return

        print(f"🚀 Rerunning analysis for meeting {meeting_id}: {meeting.title}")
        
        # 1. Resolve Behavior Profile
        profile = resolve_behavior_profile(
            db, 
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id
        )
        
        # 2. Run Orchestrated Analysis
        transcript = meeting.transcript or ""
        if not transcript:
            print("Error: No transcript found for this meeting.")
            return

        result = AgentGraphOrchestrator.run_meeting_analysis(
            db, 
            transcript, 
            profile, 
            meeting_id=meeting.id
        )

        # 3. Update Meeting Record
        meeting.summary = result.summary
        meeting.title = result.title # Synthesis might have updated the title
        
        # In a real pipeline we'd update tasks/decisions too, but for this verification
        # let's just see if the modular execution completes.
        
        db.commit()
        print(f"\n✅ Analysis complete for meeting {meeting_id}!")
        print(f"Title: {meeting.title}")
        print(f"Summary (First 100 chars): {meeting.summary[:100]}...")

    except Exception as e:
        db.rollback()
        print(f"❌ Error during rerun: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        rerun_meeting_analysis(int(sys.argv[1]))
    else:
        # Get last meeting
        db = SessionLocal()
        last = db.query(Meeting).order_by(Meeting.id.desc()).first()
        db.close()
        if last:
            rerun_meeting_analysis(last.id)
