"""
Verification Script for Phase 11G: Live UI Readiness.
Tests the full bridge: Raw WS -> StreamManager -> LiveTaskDetector -> Stabilizer -> LiveEventBus -> UI Broadcast.
"""
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from app.api.ws_router import recall_websocket_receiver
from app.services.meeting_memory.meeting_state_store import state_store

async def test_live_ui_flow():
    print("\n🚀 Starting Phase 11G: Live UI Readiness Validation...")
    
    meeting_id = 9999
    
    # 1. Mock WebSocket for Recall.ai
    mock_ws = AsyncMock()
    
    # Simulate a "Final" transcript event from Recall.ai
    raw_payload = {
        "event": "transcript.data",
        "data": {
            "transcript": {
                "participant": {"name": "John"},
                "text": "I will deploy the fix by EOD.",
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
                "task": "Deploy fix",
                "owner": "John",
                "type": "self_assigned_task",
                "deadline": "EOD",
                "confidence": 0.99
            }]
        })

        # 3. Mock ConnectionManager.broadcast (The final UI destination)
        with patch("app.api.ws_router.manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
            
            print("🏃 Step 1: Simulating incoming Recall.ai WebSocket message...")
            try:
                await recall_websocket_receiver(mock_ws, meeting_id)
            except Exception as e:
                if str(e) != "Stop Loop":
                    raise

            # Give a small moment for the background task to run
            await asyncio.sleep(0.5)

            # 4. Verify UI Broadcasts
            # We expect AT LEAST 2 broadcasts: 
            # 1. transcript_update (immediate)
            # 2. cognitive_event (after stabilization)
            
            print(f"📊 Total UI Broadcasts: {mock_broadcast.call_count}")
            
            # Check for transcript update
            transcript_calls = [call for call in mock_broadcast.call_args_list if call.args[1]["type"] == "transcript_update"]
            assert len(transcript_calls) > 0
            print("✅ Transcript update broadcasted to UI.")

            # Check for cognitive event
            cognitive_calls = [call for call in mock_broadcast.call_args_list if call.args[1]["type"] == "cognitive_event"]
            assert len(cognitive_calls) > 0
            
            event_payload = cognitive_calls[0].args[1]
            assert event_payload["event_type"] == "task.created"
            assert event_payload["payload"]["task"] == "Deploy fix"
            print(f"✅ Cognitive event '{event_payload['event_type']}' broadcasted to UI with payload: {event_payload['payload']['task']}")

    print("\n⭐ Live UI Readiness: ALL SYSTEMS GO (MOCKED)")

if __name__ == "__main__":
    asyncio.run(test_live_ui_flow())
