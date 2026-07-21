"""Re-export the existing ExtractionSummary contract.

The agents_v2 orchestrator returns the same shape as the legacy
`AgentGraphOrchestrator.run_meeting_analysis()` so no downstream
consumer needs to change (meeting_pipeline saves title/summary/tasks
identically for both paths).
"""
from app.services.cognition.contracts import ExtractionSummary  # noqa: F401
