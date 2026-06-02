"""
Verification Script for Phase 11.5: Cognitive Stabilization Layer.
Tests: Event Deduplication, Confidence Scaling, Owner Resolution, and State Evolution.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.live_stream.stream_manager import stream_manager
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.meeting_memory.meeting_state_store import state_store

def test_cognitive_stabilization_lifecycle():
    print("\n🚀 Starting Phase 11.5 Stabilization Validation...")
    
    meeting_id = "stabilize_test_123"
    stream_manager.start_session(meeting_id)
    
    # 1. First mention (Initial detection)
    # Added "task" keyword to bypass word-count buffer in StreamManager
    chunk1 = LiveTranscriptChunk(
        speaker_id="u1", speaker_name="Alice",
        text="Someone should fix the auth bug as a task.",
        sequence_number=1
    )
    
    with patch("app.services.live_tasks.task_extractor._get_client") as mock_client:
        mock_openai = MagicMock()
        mock_client.return_value = mock_openai
        
        # Detection 1: Low confidence, no owner
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "Fix auth bug",
              "type": "unassigned_task",
              "confidence": 0.5
            }
          ]
        }
        """
        
        print("🏃 Step 1: Ingesting first mention...")
        stream_manager.ingest_chunk(meeting_id, chunk1)
        
        state = state_store.get_state(meeting_id)
        # Verify initial state
        task_fp = list(state.active_tasks.keys())[0]
        task = state.active_tasks[task_fp]
        assert task.status == "detected"
        assert task.confidence == 0.5
        assert task.mention_count == 1
        print(f"✅ Initial detection: {task.task} (Conf: {task.confidence})")

        # 2. Second mention (Confidence boost + Inferred ownership)
        chunk2 = LiveTranscriptChunk(
            speaker_id="u2", speaker_name="Bob",
            text="I think John can handle the auth bug task.",
            sequence_number=2
        )
        
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "Fix auth bug",
              "owner": "John",
              "type": "assigned_task",
              "confidence": 0.8
            }
          ]
        }
        """
        
        print("🏃 Step 2: Ingesting second mention (deduplication check)...")
        stream_manager.ingest_chunk(meeting_id, chunk2)
        
        # Verify deduplication & boost
        assert len(state.active_tasks) == 1
        assert task.mention_count == 2
        assert task.confidence > 0.5 # Boosted
        assert task.owner == "John"
        assert task.status == "inferred"
        print(f"✅ Confidence boosted: {task.confidence}, State: {task.status}, Owner: {task.owner}")

        # 3. Third mention (Confirmed state)
        chunk3 = LiveTranscriptChunk(
            speaker_id="u1", speaker_name="Alice",
            text="Yes, John will definitely fix the auth bug task by Friday.",
            sequence_number=3
        )
        
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "Fix auth bug",
              "owner": "John",
              "type": "assigned_task",
              "deadline": "Friday",
              "confidence": 0.95
            }
          ]
        }
        """
        
        print("🏃 Step 3: Ingesting third mention (state machine progression)...")
        stream_manager.ingest_chunk(meeting_id, chunk3)
        
        assert task.status == "confirmed"
        assert len(task.evolution) >= 3
        print(f"✅ Final stable state: {task.status}, Evolution steps: {len(task.evolution)}")

    print("\n⭐ Cognitive Stabilization Layer: ALL SYSTEMS GO (MOCKED)")

if __name__ == "__main__":
    test_cognitive_stabilization_lifecycle()
