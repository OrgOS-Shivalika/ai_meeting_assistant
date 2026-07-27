# Agentic Meeting Assistant: Technical Documentation

## Overview
The **Agentic Meeting Assistant** is a sophisticated "AI Operating System" for organizations. It transforms raw meeting transcripts into structured intelligence by utilizing a hierarchical cognition runtime, contract-governed extractions, and event-driven automations. 

The system is designed for multi-tenant isolation, enterprise-grade compliance (PII redaction), and extensible multi-agent orchestration.

---

## 1. High-Level Architecture
The application follows a layered N-tier architecture:

- **Frontend:** React + TypeScript (Vite) feature-based modular design.
- **API Layer:** FastAPI (Python) handles request routing, auth, and pipeline orchestration.
- **Cognition Runtime (The "Kernel"):** Governs AI behavior through `BehaviorProfiles`, enforces `ExtractionContracts`, and executes specialized agents in a deterministic graph.
- **Task Queue:** Celery + Redis for asynchronous heavy lifting (AI analysis, embedding, graph extraction).
- **Data Layer:** 
    - **PostgreSQL + pgvector:** Relational data + semantic vector memory.
    - **Knowledge Graph:** Entities and relationships extracted from meetings.
    - **Object Storage:** S3/MinIO for raw documents and transcripts.

---

## 2. Core Folder Structure & File Responsibilities

### `app/` (Backend Source)
*   **`main.py`**: Entry point. Configures FastAPI, CORS, and mounts all routers.
*   **`api/`**: REST API layer.
    *   `auth_router.py`: JWT-based authentication and user management.
    *   `agents_router.py`: CRUD for Agent Profiles and Prompt Versions.
    *   `behavior_router.py`: Handles sparse overrides and organizational behavior settings.
    *   `rag_router.py`: The "Ask AI" endpoint with hybrid vector/graph retrieval.
    *   `ws_router.py`: WebSocket manager for real-time status updates.
*   **`ai_agents/`**: LLM provider implementations.
    *   `transcript_analyzer.py`: Provider-agnostic facade (OpenAI with Gemini fallback).
    *   `prompts/`: Versioned prompt templates for analysis and RAG.
*   **`services/`**: Business logic and Cognition Runtime.
    *   **`behavior/`**:
        *   `resolver.py`: The hierarchical config merger (Global -> Category -> Team -> Workspace).
        *   `meeting_context.py`: Builds the preamble "pre-prompt" for AI agents.
    *   **`cognition/`**:
        *   `contracts.py`: **Phase 9 foundation.** Defines Pydantic schemas (ExtractionSummary) and validation logic.
    *   **`compliance/`**:
        *   `runtime.py`: Enforcement gate for PII redaction and restricted data.
    *   **`automation/`**:
        *   `bus.py`: Event-driven dispatcher for Slack, Jira, and Webhooks.
    *   **`agents/`**:
        *   `graph_orchestrator.py`: Deterministic multi-agent execution manager.
*   **`pipelines/`**: High-level workflow orchestration.
    *   `meeting_pipeline.py`: Coordinates the full lifecycle from Recall.ai ingestion to finalized intelligence.
*   **`db/`**: SQLAlchemy models (`models.py`) and session management (`database.py`).
*   **`celery_tasks/`**: Background worker logic for embedding, summarization, and graph extraction.

### `tests/` (Verification Suite)
*   **`phase9/layers/`**: Granular tests for the Cognition Runtime (Contracts, Compliance, Automation, Orchestration).
*   **`test_phase1-8.py`**: Legacy regression tests for previous development milestones.

---

## 3. Key Feature Deep-Dive

### 3.1 Hierarchical Behavior Resolution
The system doesn't use static prompts. Instead, it **resolves** behavior at runtime:
1.  **Global Default:** Baseline AI behavior.
2.  **Template Layer:** Installed from the Template Store (e.g., "Engineering", "HR").
3.  **Workspace Overrides:** Org-wide customizations.
4.  **Category/Team Overrides:** Specific tweaks for "Backend Team" or "Sales Category".
The `resolver.py` merges these into a `ResolvedBehaviorProfile` using a **Sparse Override** pattern (storing only what changed).

### 3.2 Extraction Contract Runtime (Phase 9.4)
Ensures the AI never returns "garbage." 
- All AI output is validated against a **Pydantic Model**.
- If the AI fails to follow the schema, the runtime logs the failure and prepares for a "Repair Cycle" (re-prompting).
- This ensures downstream consumers (like the Jira integrator) always receive valid, typed objects.

### 3.3 Compliance & PII Redaction (Phase 9.3)
A hard security gate. Before a summary is saved to the DB or sent to Slack:
- The `ComplianceRuntime` scans the text for emails, phone numbers, and restricted entities.
- Data is masked (e.g., `[EMAIL REDACTED]`) based on the `BehaviorProfile` flags.
- **Critical:** This happens *before* data hits persistence, ensuring sensitive data never touches the disk in unmasked form.

### 3.4 Event-Driven Automation (Phase 9.5)
Decouples the meeting pipeline from external noise.
- The pipeline simply says: `meeting.tasks.extracted`.
- The `AutomationBus` checks if the workspace has Slack or Jira enabled.
- If authorized, it dispatches the side-effect asynchronously.
- Failures in Slack don't cause the meeting analysis to fail.

### 3.5 Agent Graph Orchestration (Phase 9.6)
Moves beyond "one prompt for everything."
- Specialized agents (e.g., Risk Agent, CRM Agent) are executed based on the `enabled_agents` list.
- Agents can depend on each other (e.g., the CRM Agent needs the output of the Action Item Agent).
- The `GraphOrchestrator` manages this execution flow deterministically.

---

## 4. The Meeting Lifecycle (End-to-End)
1.  **Join:** A bot joins a Google Meet via Recall.ai.
2.  **Ingest:** Pipeline fetches the raw transcript.
3.  **Resolve:** System identifies the organization/team and resolves the `BehaviorProfile`.
4.  **Orchestrate:** `AgentGraphOrchestrator` runs AI analysis using the resolved preamble.
5.  **Validate:** `ExtractionContractRuntime` ensures the summary and tasks are valid.
6.  **Gated Compliance:** `ComplianceRuntime` redacts PII.
7.  **Persist:** Sanitized results are saved to PostgreSQL.
8.  **Automate:** `AutomationBus` triggers Slack/Webhook notifications.
9.  **Memory:** Background tasks chunk the transcript and embed it into the vector store for future RAG queries.
