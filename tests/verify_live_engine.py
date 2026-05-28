"""
Verification Script for Phase 11: Live Task Detection & Real-Time Engine.
Tests the full lifecycle: Ingestion -> Detection -> Memory Reconciliation -> Event Emission.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.live_stream.stream_manager import stream_manager
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.meeting_memory.meeting_state_store import state_store

def test_live_task_detection_lifecycle():
    print("\n🚀 Starting Live Task Engine Verification...")
    
    meeting_id = "test_live_4427"
    
    # 1. Start Session
    stream_manager.start_session(meeting_id)
    print("✅ Step 1: Live Session Started")

    # 2. Ingest Chunk 1 (New Task)
    chunk1 = LiveTranscriptChunk(
        speaker_id="user_1",
        speaker_name="John",
        text="I will handle the API migration by tomorrow.",
        sequence_number=1
    )
    
    # Mock LLM response for Chunk 1
    with patch("app.services.live_tasks.task_extractor._get_client") as mock_client:
        mock_openai = MagicMock()
        mock_client.return_value = mock_openai
        
        # Simulate LLM detecting a self-assigned task
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "API migration",
              "owner": "John",
              "type": "self_assigned_task",
              "deadline": "tomorrow",
              "confidence": 0.98
            }
          ]
        }
        """
        
        print("🏃 Step 2: Ingesting Chunk 1 (New Task)...")
        stream_manager.ingest_chunk(meeting_id, chunk1)
        
        # Verify state store
        state = state_store.get_state(meeting_id)
        assert len(state.active_tasks) == 1
        assert "api migration" in state.active_tasks
        assert state.active_tasks["api migration"].owner == "John"
        print("✅ Task Created & Persisted in Temporal Memory")

        # 3. Ingest Chunk 2 (Ownership Transfer)
        chunk2 = LiveTranscriptChunk(
            speaker_id="user_2",
            speaker_name="Sarah",
            text="Actually, I think Priya should handle the API migration instead.",
            sequence_number=2
        )
        
        # Simulate LLM detecting an ownership change
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "API migration",
              "owner": "Priya",
              "type": "assigned_task",
              "deadline": "tomorrow",
              "confidence": 0.92
            }
          ]
        }
        """
        
        print("🏃 Step 3: Ingesting Chunk 2 (Ownership Transfer)...")
        stream_manager.ingest_chunk(meeting_id, chunk2)
        
        # Verify state mutation
        assert state.active_tasks["api migration"].owner == "Priya"
        assert "John" in state.active_tasks["api migration"].previous_owners
        print("✅ Task Ownership Transferred Dynamically")

    print("\n⭐ Live Task Engine: ALL SYSTEMS GO (MOCKED)")

if __name__ == "__main__":
    test_live_task_detection_lifecycle()
