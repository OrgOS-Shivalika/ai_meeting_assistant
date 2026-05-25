import requests
import json
import asyncio
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.services.recall_ai_service import RecallService
from app.processors.transcript_processor import TranscriptProcessor
from app.services.agents.graph_orchestrator import AgentGraphOrchestrator
from app.services.behavior.resolver import resolve_behavior_profile
from app.services.compliance.runtime import ComplianceRuntime
from app.services.automation.bus import AutomationBus, AutomationEvent
from app.pipelines.meeting_pipeline import MeetingPipeline

def recover_meeting(meeting_id):
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            print(f"Meeting {meeting_id} not found.")
            return

        bot_id = meeting.bot_id
        if not bot_id:
            print(f"Meeting {meeting_id} has no bot_id.")
            return

        recall = RecallService()
        pipeline = MeetingPipeline()

        print(f"🚀 Recovering meeting {meeting_id} (Bot: {bot_id})")

        # 1. Fetch transcript URL
        print("⏳ Fetching transcript URL...")
        transcript_url = recall.wait_for_transcript(bot_id, timeout=60) # Should be fast now
        
        # 2. Download transcript
        print("📥 Downloading transcript...")
        transcript_json = requests.get(transcript_url).json()
        meeting.transcript_raw = transcript_json
        db.commit()

        # 3. Format transcript
        print("🧾 Formatting transcript...")
        formatted = TranscriptProcessor.format(transcript_json)
        meeting.transcript_text = formatted
        db.commit()

        # 4. Save Participants
        print("👥 Saving participants...")
        try:
            bot_data = recall.get_bot(bot_id)
        except Exception:
            bot_data = None
        pipeline.save_participants(db, meeting, transcript_json, bot_data=bot_data)

        # 5. Execute Agent Graph (Phase 9.6)
        print("🕸️  Running Orchestrated AI analysis...")
        prof = resolve_behavior_profile(
            db,
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id
        )

        result_obj = AgentGraphOrchestrator.run_meeting_analysis(
            db, 
            formatted, 
            prof
        )
        result_json = result_obj.model_dump()

        # 6. Save results
        meeting.title = result_obj.title or f"Meeting {meeting.id}"
        meeting.summary = result_obj.summary
        meeting.status = "completed"
        db.commit()

        pipeline.save_tasks(db, meeting.id, result_json.get("action_items", []))
        print("✅ Analysis saved.")

        # 7. Compliance & Automation (Phase 9.3 & 9.5)
        print("🛡️ Applying compliance & emitting automations...")
        ComplianceRuntime.apply_to_meeting(db, meeting, prof)
        db.commit()

        AutomationBus.emit(
            db, 
            AutomationEvent(
                "meeting.summary.completed", 
                meeting.organization_id, 
                meeting.id, 
                {"title": meeting.title, "summary": meeting.summary}
            ),
            prof
        )
        if result_json.get("action_items"):
            AutomationBus.emit(
                db,
                AutomationEvent(
                    "meeting.tasks.extracted",
                    meeting.organization_id,
                    meeting.id,
                    result_json["action_items"]
                ),
                prof
            )

        # 8. Trigger embedding
        print("🧠 Dispatching embedding task...")
        try:
            from app.celery_tasks.embedding_tasks import dispatch_embed_meeting
            dispatch_embed_meeting(meeting.id)
        except Exception as e:
            print(f"Embedding dispatch failed: {e}")

        print(f"✨ Meeting {meeting_id} successfully processed!")

    except Exception as e:
        print(f"❌ Recovery failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    recover_meeting(4422)
