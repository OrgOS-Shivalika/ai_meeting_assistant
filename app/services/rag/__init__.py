"""Phase 5 RAG services — planner, retrieval, synthesizer.

Each service is a plain Python module with a sync API. The Celery /
HTTP / WebSocket layers wrap these; they never wrap each other. Phase 7
will reuse `RetrievalEngine` + `Synthesizer` for the live copilot —
that's why the layer boundaries are strict.
"""
