"""
Verification Script for Phase 11G: Live UI Readiness.
Tests the full bridge: Raw WS -> StreamManager -> LiveTaskDetector -> Stabilizer -> LiveEventBus -> UI Broadcast & DB Persistence.
"""
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone
import uuid

from app.api.ws_router import recall_websocket_receiver
from app.services.meeting_memory.meeting_state_store import state_store
from app.db.database import SessionLocal
from app.db.models import Meeting, Task

async def test_live_ui_flow():
    print("\n🚀 Starting Phase 11G: Live UI Readiness & Persistence Validation...")
    
    # 0. Setup: Use an existing meeting from the DB to satisfy FK constraints
    db = SessionLocal()
    meeting = db.query(Meeting).order_by(Meeting.id.desc()).first()
    if not meeting:
        print("❌ Error: No meetings found in database. Run a meeting first.")
        db.close()
        return
        
    meeting_id = meeting.id
    organization_id = meeting.organization_id
    print(f"✅ Setup: Using existing meeting {meeting_id} (Org: {organization_id}) for test.")

    try:
        # 1. Mock WebSocket for Recall.ai
        mock_ws = AsyncMock()
        
        # Simulate a "Final" transcript event from Recall.ai with a keyword to trigger cognition
        raw_payload = {
            "event": "transcript.data",
            "data": {
                "transcript": {
                    "participant": {"name": "John"},
                    "text": "I will deploy the fix by tomorrow.",
                    "is_final": True
                }
            }
        }
        
        # We want to exit the loop after one message
        mock_ws.receive_text.side_effect = [json.dumps(raw_payload), Exception("Stop Loop")]

        # 2. Mock OpenAI for Task Detection
        with patch("app.services.live_tasks.task_extractor._get_client") as mock_openai_client:
            mock_openai = MagicMock()
            mock_openai_client.return_value = mock_openai
            mock_openai.chat.completions.create.return_value.choices[0].message.content = json.dumps({
                "tasks": [{
                    "task": "DUMMY TEST TASK - DEPLOY FIX",
                    "owner": "John",
                    "type": "self_assigned_task",
                    "deadline": "tomorrow",
                    "confidence": 0.99
                }]
            })

            # 3. Mock ConnectionManager.broadcast (The final UI destination)
            with patch("app.api.ws_router.manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
                
                print(f"🏃 Step 1: Simulating incoming Recall.ai WebSocket message for meeting {meeting_id}...")
                try:
                    await recall_websocket_receiver(mock_ws, meeting_id)
                except Exception as e:
                    if str(e) != "Stop Loop":
                        raise

                # Give a moment for background task to run
                await asyncio.sleep(1.5)

                # 4. Verify UI Broadcasts
                print(f"📊 Total UI Broadcasts: {mock_broadcast.call_count}")
                
                cognitive_calls = [call for call in mock_broadcast.call_args_list if call.args[1]["type"] == "cognitive_event"]
                assert len(cognitive_calls) > 0
                print("✅ Cognitive event broadcasted to UI.")

                # 5. Verify Database Persistence
                db_task = db.query(Task).filter(
                    Task.meeting_id == meeting_id, 
                    Task.task == "DUMMY TEST TASK - DEPLOY FIX"
                ).first()
                
                assert db_task is not None
                assert db_task.owner_name == "John"
                print(f"✅ Task successfully persisted to database in real-time: {db_task.task}")

    finally:
        # Cleanup ONLY our test task
        db.query(Task).filter(
            Task.meeting_id == meeting_id, 
            Task.task == "DUMMY TEST TASK - DEPLOY FIX"
        ).delete()
        db.commit()
        db.close()
        print("🧹 Cleanup: Test task removed from DB.")

    print("\n⭐ Live UI Readiness & Persistence: ALL SYSTEMS GO (MOCKED)")

if __name__ == "__main__":
    asyncio.run(test_live_ui_flow())
