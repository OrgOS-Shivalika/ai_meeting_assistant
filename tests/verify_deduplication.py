"""
Verification Script for Smart Deduplication.
Tests: Fuzzy fingerprinting of similar tasks.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.live_stream.stream_manager import stream_manager
from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
from app.services.meeting_memory.meeting_state_store import state_store

def test_smart_deduplication():
    print("\n🚀 Starting Smart Deduplication Validation...")
    
    meeting_id = "dedup_test_456"
    stream_manager.start_session(meeting_id)
    
    # 1. Mention 1: "Fix the auth bug"
    chunk1 = LiveTranscriptChunk(
        speaker_id="u1", speaker_name="Alice",
        text="Someone should fix the auth bug task.",
        sequence_number=1
    )
    
    with patch("app.services.live_tasks.task_extractor._get_client") as mock_client:
        mock_openai = MagicMock()
        mock_client.return_value = mock_openai
        
        # Result 1
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "Fix the auth bug",
              "type": "unassigned_task",
              "confidence": 0.5
            }
          ]
        }
        """
        
        print("🏃 Step 1: Ingesting 'Fix THE auth bug'...")
        stream_manager.ingest_chunk(meeting_id, chunk1)
        
        state = state_store.get_state(meeting_id)
        assert len(state.active_tasks) == 1
        original_fp = list(state.active_tasks.keys())[0]
        print(f"✅ Initial task created with fingerprint: {original_fp}")

        # 2. Mention 2: "Fix auth bug" (Slightly different text)
        chunk2 = LiveTranscriptChunk(
            speaker_id="u2", speaker_name="Bob",
            text="I'll fix auth bug task.",
            sequence_number=2
        )
        
        # Result 2: Different text, but same meaning
        mock_openai.chat.completions.create.return_value.choices[0].message.content = """
        {
          "tasks": [
            {
              "task": "Fix auth bug",
              "owner": "Bob",
              "type": "self_assigned_task",
              "confidence": 0.8
            }
          ]
        }
        """
        
        print("🏃 Step 2: Ingesting 'Fix auth bug' (Checking fuzzy dedup)...")
        stream_manager.ingest_chunk(meeting_id, chunk2)
        
        # VERIFY: Still only 1 task because of fuzzy fingerprinting
        assert len(state.active_tasks) == 1
        task = state.active_tasks[original_fp]
        assert task.mention_count == 2
        assert task.owner == "Bob"
        print(f"✅ Fuzzy Deduplication Successful! Task count remains 1. Confidence: {task.confidence}")

    print("\n⭐ Smart Deduplication: ALL SYSTEMS GO (MOCKED)")

if __name__ == "__main__":
    test_smart_deduplication()
