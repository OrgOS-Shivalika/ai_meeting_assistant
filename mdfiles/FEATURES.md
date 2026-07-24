# Agentic Meeting Assistant: The Full Feature Encyclopedia

This document provides a comprehensive technical breakdown of every feature in the project, mapping functional capabilities to their respective code modules, database models, and internal data flows.

---

## Pillar 1: Identity, Access & Tenancy
**Purpose:** Manage users, organizations, and multi-tenant isolation.

### 1.1 Multi-Tenant Organizations
*   **Feature:** Complete isolation of data (Meetings, Documents, AI behavior) between organizations.
*   **Files:** `app/db/models.py` (`Organization`), `app/api/auth_router.py`.
*   **Database:** `organizations` table.
*   **Flow:** Every record in the system (except global templates) is pinned to an `organization_id`.

### 1.2 Authentication (Local & Google OAuth)
*   **Feature:** Standard JWT login + Google SSO integration.
*   **Files:** 
    *   `app/api/auth_router.py`: Local registration/login.
    *   `app/api/google_auth_router.py`: OAuth2 flow and token management.
    *   `app/services/auth_service.py`: Password hashing and JWT generation.
*   **Database:** `users` table (stores `hashed_password`, `google_access_token`, `google_refresh_token`).
*   **Flow:** User authenticates -> System issues JWT -> Frontend stores JWT in localStorage -> Subsequent API calls use `Authorization: Bearer <token>`.

### 1.3 Hierarchy: Categories & Teams
*   **Feature:** Logical grouping of meetings and documents within an organization.
*   **Files:** `app/api/category_router.py`, `app/api/team_document_router.py`.
*   **Database:** `categories`, `teams` tables.
*   **Flow:** Organizations have Categories -> Categories have Teams. Behavior profiles can be overridden at any of these levels.

---

## Pillar 2: Meeting Intelligence Engine
**Purpose:** Transform raw audio/video into structured, searchable data.

### 2.1 Bot Ingestion (Recall.ai)
*   **Feature:** Autonomous bots that join meetings to record and transcribe.
*   **Files:** `app/services/recall_ai_service.py`, `app/api/transcription_router.py`.
*   **Flow:** User sends URL -> `RecallService` spawns bot -> Bot records -> Bot sends webhook or pipeline polls for transcript -> Pipeline downloads raw JSON.

### 2.2 Transcript Processing
*   **Feature:** Cleaning and formatting raw diarized JSON into readable text.
*   **Files:** `app/processors/transcript_processor.py`.
*   **Process:** Normalizes speaker names, timestamps, and segments into a unified `transcript_text` field.

### 2.3 Participant & Calendar Mapping
*   **Feature:** Cross-referencing transcript participants with Google Calendar attendees to resolve real names and emails.
*   **Files:** `app/pipelines/meeting_pipeline.py` (`save_participants`), `app/services/google_calendar_service.py`.
*   **Database:** `participants` table.

---

## Pillar 3: Knowledge Base & Memory
**Purpose:** Long-term storage and semantic retrieval of organizational knowledge.

### 3.1 Document Ingestion & Parsing
*   **Feature:** Support for PDF, Docx, and XLSX file uploads with automatic text extraction.
*   **Files:** 
    *   `app/api/document_router.py`.
    *   `app/parsers/`: `pdf_parser.py`, `docx_parser.py`, `xlsx_parser.py`.
    *   `app/services/storage_service.py`: S3/MinIO management.
*   **Database:** `category_documents`, `team_documents`.

### 3.2 Semantic Vector Memory
*   **Feature:** Chunking and embedding text for similarity search.
*   **Files:** 
    *   `app/services/document_chunker.py`: Recursive character splitting.
    *   `app/services/embedder.py`: Interaction with OpenAI/Gemini embedding models.
    *   `app/celery_tasks/embedding_tasks.py`: Background processing.
*   **Database:** `meeting_chunks`, `document_chunks` (using `pgvector`).

### 3.3 Knowledge Graph Extraction
*   **Feature:** Extracting entities (People, Projects, Dates) and relationships from text.
*   **Files:** `app/services/graph_extractor.py`, `app/ai_agents/graph_extractor_llm.py`.
*   **Database:** `entities`, `relationships`, `entity_mentions`.
*   **Process:** LLM scans text -> Identifies "Divyansh" (Person) "Works On" (Relationship) "Phase 9" (Entity) -> Stores in graph.

---

## Pillar 4: AI Orchestration & Agent Control
**Purpose:** Manage AI behaviors, prompts, and specialized execution.

### 4.1 Agent Profiles & Prompt Versioning
*   **Feature:** Create specialized AI personalities with versioned prompt templates.
*   **Files:** `app/api/agents_router.py`, `app/api/prompt_configs_router.py`.
*   **Database:** `agent_profiles`, `agent_prompt_configs`, `prompt_versions`.
*   **Flow:** Developer creates profile -> Adds prompt -> Publishes version -> Runtime uses the "active" version.

### 4.2 Template Store
*   **Feature:** A catalog of pre-configured AI behaviors that can be "installed" into a workspace.
*   **Files:** `app/services/templates/behavior_catalog.py`, `app/api/templates_router.py`.
*   **Process:** Workspace installs "Engineering Template" -> System creates links -> Engineering-specific tone and extraction rules are now available.

### 4.3 Sparse Overrides (Agent Control UI)
*   **Feature:** Deep customization of AI behavior at any level of the hierarchy without duplicating data.
*   **Files:** `app/services/behavior/resolver.py`, `app/services/behavior/overrides.py`.
*   **Database:** `workspace_behavior_overrides`.
*   **Mechanism:** Stores only the diff (e.g., `tone.formality = "formal"`). The resolver merges this into the global default at runtime.

---

## Pillar 5: Cognition Runtime (The "AI OS")
**Purpose:** Governed, deterministic execution of AI logic.

### 5.1 Extraction Contracts
*   **Feature:** Schema-validated AI outputs using Pydantic models.
*   **Files:** `app/services/cognition/contracts.py`.
*   **Guarantee:** The system will never persist malformed AI output; all summaries and tasks must adhere to the contract.

### 5.2 Gated Compliance (PII Redaction)
*   **Feature:** Hard redaction of sensitive data (emails, phones) before storage.
*   **Files:** `app/services/compliance/runtime.py`.
*   **Timing:** Executes *after* AI analysis but *before* DB commit and vector indexing.

### 5.3 Event-Driven Automation Bus
*   **Feature:** Triggering external side-effects (Slack, Webhooks) via normalized events.
*   **Files:** `app/services/automation/bus.py`.
*   **Events:** `meeting.summary.completed`, `meeting.tasks.extracted`, etc.

### 5.4 Agent Graph Orchestrator
*   **Feature:** Capability-based execution of multiple specialized agents with dependency management.
*   **Files:** `app/services/agents/graph_orchestrator.py`.
*   **Process:** Master Agent (Summary) -> Dependent Agent (Risk Analysis) -> Dependent Agent (CRM Sync).

---

## Pillar 6: Retrieval Augmented Generation (RAG)
**Purpose:** Conversational interface for organization-wide knowledge.

### 6.1 Hybrid Retrieval (/rag/ask)
*   **Feature:** Combining Vector Search (Similarity) and Graph Traversal (Relationships).
*   **Files:** `app/api/rag_router.py`, `app/services/rag/ask_pipeline.py`.
*   **Flow:** Query -> Vector Search (top chunks) -> Graph Search (related entities) -> Synthesis LLM -> Final Answer.

### 6.2 Importance Scoring
*   **Feature:** Ranking chunks by their relative importance to ensure the best context is used.
*   **Files:** `app/services/importance/importance_service.py`.

---

## Pillar 7: Observability & Communication
**Purpose:** Monitor system health and provide real-time feedback.

### 7.1 Runtime Tracing
*   **Feature:** Detailed logs of every AI execution, resolution path, and contract validation.
*   **Files:** `app/api/observability_router.py`, `app/db/models.py` (`AgentRuntimeLog`).

### 7.2 Performance Monitoring
*   **Feature:** Daily performance stats (latency, token usage, success rates).
*   **Database:** `performance_daily_stats`.

### 7.3 Real-time Status (WebSockets)
*   **Feature:** Live updates in the frontend for meeting processing progress.
*   **Files:** `app/api/ws_router.py`.

---

## Pillar 8: Frontend Architecture
**Purpose:** User interface for managing and interacting with meeting intelligence.

- **Files:** `meeting_ai_frontend/src/features/`.
- **Modules:**
    - `agent-control`: The complex UI for managing sparse overrides and behavior hierarchies.
    - `ask`: The conversational RAG interface.
    - `meetings`: Meeting list and detailed intelligence view.
    - `knowledge`: Document management and knowledge graph visualization.
    - `templates`: The Template Store browser.
