"""Phase 9 Layer 7 — Load + Stability Tests.

Simulates concurrent meeting processing to ensure the deterministic 
cognition runtime is thread-safe and stable under load.
"""
import pytest
import concurrent.futures
from uuid import uuid4
from unittest.mock import MagicMock, patch
from app.pipelines.meeting_pipeline import MeetingPipeline
from app.db.models import Meeting, Organization, User
from app.services.cognition.contracts import ExtractionSummary
from app.services.behavior.resolver import ResolvedBehaviorProfile

@pytest.fixture
def load_fixtures():
    org_id = uuid4()
    user_id = uuid4()
    org = Organization(id=org_id, name="Load Org")
    user = User(id=user_id, organization_id=org_id, email="load@test.com")
    return {"org_id": org_id, "user_id": user_id, "user": user}

def run_simulated_meeting(meeting_id, fixtures):
    """Simulates one full pipeline run."""
    db = MagicMock()
    meeting = Meeting(
        id=meeting_id,
        organization_id=fixtures["org_id"],
        user_id=fixtures["user_id"],
        meeting_url=f"http://test.com/{meeting_id}",
        status="pending"
    )
    meeting.user = fixtures["user"]
    
    pipeline = MeetingPipeline()
    
    # Deeply mock external dependencies to avoid actual network/LLM calls
    with patch("app.services.recall_ai_service.RecallService.create_bot", return_value={"id": f"bot_{meeting_id}"}), \
         patch("app.services.recall_ai_service.RecallService.wait_for_transcript", return_value="http://t.com"), \
         patch("requests.get", return_value=MagicMock(json=lambda: [])), \
         patch("app.services.agents.graph_orchestrator.AgentGraphOrchestrator.run_meeting_analysis") as mock_run:
        
        mock_run.return_value = ExtractionSummary(
            title=f"Meeting {meeting_id}",
            summary="Load test summary.",
            action_items=[]
        )
        
        with patch.object(pipeline, "save_participants"), \
             patch.object(pipeline, "save_tasks"), \
             patch("app.services.behavior.resolver.resolve_behavior_profile", 
                   return_value=ResolvedBehaviorProfile(organization_id=fixtures["org_id"])), \
             patch("app.api.ws_router.manager.broadcast"), \
             patch("app.celery_tasks.embedding_tasks.dispatch_embed_meeting"):
            
            pipeline.run(db, meeting)
            return meeting.status

def test_concurrent_meeting_processing(load_fixtures):
    """Layer 7.1: Process 10 meetings concurrently."""
    num_meetings = 10
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(run_simulated_meeting, i, load_fixtures) 
            for i in range(num_meetings)
        ]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    assert len(results) == num_meetings
    assert all(r == "completed" for r in results)

def test_large_transcript_stress(load_fixtures):
    """Layer 7.2: Verify handling of large transcripts (contract scaling)."""
    # Create a dummy large transcript
    large_transcript = "Speaker A: " + ("Talk " * 1000)
    
    db = MagicMock()
    meeting = Meeting(id=1, organization_id=load_fixtures["org_id"], user_id=load_fixtures["user_id"])
    meeting.user = load_fixtures["user"]
    
    pipeline = MeetingPipeline()
    
    with patch("app.services.recall_ai_service.RecallService.create_bot", return_value={"id": "b"}), \
         patch("app.services.recall_ai_service.RecallService.wait_for_transcript", return_value="t"), \
         patch("requests.get", return_value=MagicMock(json=lambda: [])), \
         patch("app.processors.transcript_processor.TranscriptProcessor.format", return_value=large_transcript), \
         patch("app.ai_agents.transcript_analyzer.TranscriptAnalyzer.analyze") as mock_analyze:
        
        mock_analyze.return_value = ExtractionSummary(title="Large", summary="Long")
        
        with patch.object(pipeline, "save_participants"), \
             patch.object(pipeline, "save_tasks"), \
             patch("app.services.behavior.resolver.resolve_behavior_profile", 
                   return_value=ResolvedBehaviorProfile(organization_id=load_fixtures["org_id"])):
            
            pipeline.run(db, meeting)
            assert meeting.status == "completed"
