# Agentic Meeting Assistant: Comprehensive Project Structure

This document provides a **detailed, file-level map** of the entire repository structure, explaining the architectural purpose and contents of each directory and key files.

---

## 📂 ROOT-LEVEL FILES & CONFIGURATION

### **Core Application**
- **main.py** — FastAPI application entry point; initializes routes, middleware, static file serving, CORS
- **requirements.txt** — Python dependencies (FastAPI, Celery, SQLAlchemy, OpenAI, Anthropic, Google Generative AI, boto3, etc.)

### **Containerization**
- **Dockerfile** — Container image definition for production deployment
- **docker-compose.yml** — Multi-service orchestration (API server, PostgreSQL, Redis, Celery worker, beat scheduler)
- **.dockerignore** — Files excluded from Docker build context

### **Development & Configuration**
- **Makefile** — Development commands (docker, backend, frontend, test, lint, clean)
- **alembic.ini** — Alembic database migration configuration
- **.env.example** — Environment variable template for configuration
- **.gitignore** — Git ignore rules

### **Documentation**
- **README.md** — Project overview, setup instructions, and quick start guide
- **ARCHITECTURE.md** — System design, architectural principles, data flow
- **FEATURES.md** — Feature list and functional capabilities
- **DOCS.md** — Comprehensive technical documentation
- **STRUCTURE.md** — This file

---

## 📂 `app/` — CORE BACKEND APPLICATION

### **Root-Level Application Files**
- **\_\_init\_\_.py** — Package initialization
- **celery_app.py** — Celery task queue configuration, Redis broker setup, result backend

---

### 📁 `app/ai_agents/` — LLM & AI INTEGRATIONS

**Core Analyzer Implementations:**
- **transcript_analyzer.py** — Base facade for transcript analysis with provider fallback strategy
- **openAI_transcript_analyzer.py** — OpenAI GPT model adapter for meeting transcript analysis
- **gemini_transcript_analyzer.py** — Google Gemini model adapter for analysis
- **graph_extractor_llm.py** — Knowledge graph extraction using LLM capabilities
- **test_transcript.py** — Utilities for testing and validating transcript processing

**Prompt Management:**
- **prompts/** — Directory containing versioned prompt templates
  - System prompts for different extraction contexts (XML/Text format)
  - Prompt engineering files for various LLM capabilities

---

### 📁 `app/api/` — HTTP REST API ROUTES

**Authentication & User Management:**
- **auth_router.py** — User registration, login, password reset, JWT token management
- **google_auth_router.py** — Google OAuth flow, callback handling, token refresh

**Agent & Behavior Management:**
- **agents_router.py** — Agent list, get, publish, version management endpoints
- **behavior_router.py** — Agent behavior configuration, override endpoints, resolution queries

**Meeting Management:**
- **category_router.py** — Meeting category CRUD, hierarchy management
- **team_document_router.py** — Team-scoped document operations, access control
- **document_router.py** — Document upload, processing status, retrieval, deletion
- **transcription_router.py** — Transcription status polling, live transcript data

**Search & Knowledge:**
- **search_router.py** — Full-text search, keyword-based retrieval
- **graph_router.py** — Knowledge graph query, entity relationships, traversal
- **rag_router.py** — RAG (Retrieval-Augmented Generation) query endpoints, answer synthesis

**Real-time Communication:**
- **ws_router.py** — WebSocket connections for live transcript streaming, real-time updates

**Intelligence & Analytics:**
- **consolidation_router.py** — Meeting consolidation, summary generation, archive endpoints
- **observability_router.py** — Metrics, telemetry, observability endpoints

**Development & Testing:**
- **playground_router.py** — Agent playground for testing, prompt iteration, behavior validation
- **prompt_configs_router.py** — Prompt configuration management, testing

**Template & Configuration:**
- **templates_router.py** — Template management, catalog, provisioning, installation
- **routes.py** — Main router aggregation, endpoint mounting

**Infrastructure:**
- **db_dependency.py** — Database session dependency injection for FastAPI routes

**Webhooks:**
- **webhooks/** — External event handlers
  - **recall_webhook.py** — Recall.ai meeting event webhooks, event parsing, job triggering

---

### 📁 `app/celery_tasks/` — ASYNCHRONOUS BACKGROUND JOBS

**Meeting Processing:**
- **meeting_tasks.py** — Create meeting, process recording, handle completion, retry logic
- **consolidation_tasks.py** — Meeting consolidation workflows, archival, rollup

**Document Processing:**
- **document_tasks.py** — Document upload handling, format detection, processing orchestration
- **document_ingest.py** — Document ingestion pipeline, chunking, storage
- **document_graph_tasks.py** — Graph building from document content, entity extraction

**Vector & Embedding Generation:**
- **embedding_tasks.py** — Vector embedding generation for documents, semantic search preparation

**Knowledge Graph:**
- **graph_tasks.py** — Knowledge graph operations, entity extraction, relationship discovery

**Agent Execution:**
- **agent_tasks.py** — Agent execution tasks, capability invocation, result persistence

**Team & Document Management:**
- **team_document_tasks.py** — Team-scoped document operations, permissions, access logs

**Scoring & Analytics:**
- **importance_tasks.py** — Importance scoring for entities, access frequency calculation

---

### 📁 `app/config/` — CONFIGURATION MANAGEMENT

- **settings.py** — Environment-based configuration using Pydantic settings
  - Database URL, API keys, model providers, feature flags
  - FastAPI settings, logging configuration, CORS policies

---

### 📁 `app/db/` — DATABASE & ORM LAYER

- **database.py** — SQLAlchemy engine setup, session factory, Base model definition
  - Database connection pooling, engine configuration
  - Session scoped_session setup for FastAPI dependency injection
- **models.py** — All SQLAlchemy ORM models (comprehensive schema):
  - **User models:** User accounts, authentication records
  - **Meeting models:** Meeting records, transcripts, metadata
  - **Document models:** Documents, document chunks, document storage
  - **Graph models:** Entities, relationships, entity types
  - **AI models:** Agent definitions, prompt versions, behavior profiles
  - **Behavior models:** Behavior overrides, templates, configurations
  - **Supporting models:** Categories, teams, tags, access logs, audit trails
- **init_db.py** — Database initialization utilities, schema creation, seeding

---

### 📁 `app/dependencies/` — DEPENDENCY INJECTION

- **auth.py** — Authentication middleware, current user extraction from JWT, permission verification

---

### 📁 `app/parsers/` — DOCUMENT PARSING

- **base.py** — Abstract parser base class with common interface
- **pdf_parser.py** — PDF text extraction using PyPDF2 or pdfplumber
- **docx_parser.py** — Microsoft Word document parsing
- **xlsx_parser.py** — Excel spreadsheet parsing and tabular data extraction

---

### 📁 `app/pipelines/` — ORCHESTRATION PIPELINES

- **meeting_pipeline.py** — End-to-end meeting processing workflow:
  - Ingestion → Transcription → Analysis → Graph Building → Indexing → Archive

---

### 📁 `app/processors/` — DATA PROCESSING

- **transcript_processor.py** — Transcript cleaning, normalization, speaker attribution

---

### 📁 `app/schemas/` — REQUEST/RESPONSE VALIDATION (Pydantic)

**Core Data Models:**
- **auth_schema.py** — Authentication DTOs (LoginRequest, RegisterRequest, TokenResponse)
- **meeting_schema.py** — Meeting data schemas, create/update requests, responses
- **document_schema.py** — Document upload, storage, retrieval schemas

**Knowledge Representation:**
- **graph_schema.py** — Graph structure schemas, entity definitions
- **graph_extraction.py** — Graph extraction data models, entity types

**Search & Retrieval:**
- **search_schema.py** — Full-text search request/response schemas
- **rag_schema.py** — RAG query and response schemas
- **rag_api_schema.py** — RAG API-specific request/response shapes

**System & Observability:**
- **observability_schema.py** — Metrics and telemetry schemas
- **agent_schema.py** — Agent definition schemas, profile schemas
- **agent_api_schema.py** — Agent API schemas, request/response DTOs

**Organization & Configuration:**
- **category_schema.py** — Meeting category schemas

---

### 📁 `app/services/` — BUSINESS LOGIC LAYER

#### **Core Services (Root-Level):**

- **auth_service.py** — User authentication, JWT token generation, validation, refresh
- **google_service.py** — Google API client setup and management
- **google_calendar_service.py** — Calendar event querying, meeting extraction
- **google_calendar_worker.py** — Background worker for calendar synchronization
- **graph_extractor.py** — Knowledge graph extraction from meeting content
- **graph_normalizer.py** — Graph entity normalization, deduplication, type resolution
- **embedder.py** — Vector embedding generation using various embedding models
- **document_chunker.py** — Document chunking strategies, semantic chunking
- **chunker.py** — Generic chunking utilities, overlap handling
- **recall_ai_service.py** — Recall.ai API client, meeting ingestion, webhook handling
- **storage_service.py** — Document storage abstraction (S3 / local filesystem)
- **scheduler.py** — APScheduler task scheduling, periodic job management

#### **app/services/agents/ — AGENT SYSTEM SERVICES:**

- **analytics.py** — Agent usage analytics, performance metrics collection
- **audit.py** — Agent behavior audit, change tracking
- **cache.py** — Agent caching strategy, invalidation
- **composition.py** — Agent prompt composition, template merging
- **diff.py** — Agent version diffing, change visualization
- **eval_gate.py** — Evaluation quality gating, performance validation
- **graph_orchestrator.py** — Graph-based agent orchestration, capability execution
- **playground.py** — Agent playground API, testing interface
- **pricing.py** — Token pricing calculations, cost estimation
- **publish.py** — Agent publishing workflow, version control
- **resolver.py** — Agent resolution and inheritance, fallback logic
- **seed_defaults.py** — Default agent seeding during initialization

#### **app/services/behavior/ — BEHAVIOR MANAGEMENT SERVICES:**

- **meeting_context.py** — Meeting-specific behavior context, scoped resolution
- **overrides.py** — Behavior override resolution, hierarchical merging
- **provisioning.py** — Behavior provisioning pipeline, template application
- **resolver.py** — Behavior inheritance resolver, layer-based resolution

#### **app/services/cognition/ — AI COGNITION SERVICES:**

- **contracts.py** — Cognition interface contracts, extraction schema validation

#### **app/services/rag/ — RETRIEVAL-AUGMENTED GENERATION SERVICES:**

- **ask_pipeline.py** — RAG query pipeline orchestration
- **query_planner.py** — Query planning and decomposition, query optimization
- **retrieval.py** — Document retrieval strategy, relevance ranking
- **synthesizer.py** — Answer synthesis from retrieved documents, response generation

#### **app/services/templates/ — TEMPLATE SYSTEM SERVICES:**

- **behavior_bundle_seed.py** — Template bundle seeding, bulk template initialization
- **behavior_catalog.py** — Template catalog management, discovery
- **behavior_registry.py** — Template registry, version tracking
- **behavior_seed.py** — Individual template seeding, default template setup
- **resolver.py** — Template resolution, template inheritance

#### **app/services/automation/ — AUTOMATION SERVICES:**

- **bus.py** — Event bus for automation, event-driven architecture

#### **app/services/compliance/ — COMPLIANCE SERVICES:**

- **runtime.py** — Compliance runtime enforcement, policy validation

#### **app/services/consolidation/ — CONSOLIDATION SERVICES:**

- **archive.py** — Archive management, historical consolidation
- **merges.py** — Meeting consolidation merges, rollup operations

#### **app/services/importance/ — IMPORTANCE SCORING SERVICES:**

- **scorer.py** — Entity importance calculation, scoring algorithms
- **access_log.py** — Access event logging, usage tracking

#### **app/services/tools/ — TOOL MANAGEMENT SERVICES:**

- **registry.py** — Tool registry, capability management
- **permissions.py** — Tool permissions, access control

---

### 📁 `app/store/` — STATE MANAGEMENT

- **job_store.py** — Background job storage, state persistence

---

### 📁 `app/scripts/` — UTILITY SCRIPTS

- **seed_default_agents.py** — Initialize default agents at startup
- **seed_global_templates.py** — Initialize global behavior templates
- **backfill_documents.py** — Backfill document processing for existing records
- **backfill_embeddings.py** — Backfill vector embeddings for documents
- **backfill_graph.py** — Backfill knowledge graph for existing meetings
- **backfill_importance.py** — Backfill importance scores for entities

---

### 📁 `app/utils/` — UTILITY FUNCTIONS

- **logger.py** — Centralized logging setup, log formatting, handlers

---

## 📂 `meeting_ai_frontend/` — REACT VITE FRONTEND APPLICATION

### **Build & Configuration Files**

- **package.json** — NPM dependencies, build scripts, metadata
- **vite.config.ts** — Vite build configuration, dev server settings
- **tsconfig.json** — TypeScript base configuration
- **tsconfig.app.json** — App-specific TypeScript settings
- **tsconfig.node.json** — Node-specific TypeScript settings
- **eslint.config.js** — ESLint rules and code quality configuration
- **index.html** — HTML entry point with Vite placeholder
- **README.md** — Frontend documentation and setup instructions

### **Application Root**

- **src/App.tsx** — Root React component, top-level layout
- **src/main.tsx** — React DOM mount point, application entry
- **src/App.css** — Global application styles
- **src/index.css** — Global CSS variables, base styling

---

### 📁 `src/app/` — APPLICATION ROUTING

- **router.tsx** — React Router configuration, route definitions

---

### 📁 `src/services/` — SERVICE LAYER

- **apiClient.ts** — Axios HTTP client setup, request interceptors, base configuration
- **authService.ts** — Authentication helpers, token management, user context

---

### 📁 `src/shared/` — SHARED COMPONENTS & UTILITIES

**Components:**
- **components/Layout.tsx** — Main layout wrapper, navigation structure
- **components/Sidebar.tsx** — Navigation sidebar with feature links

**Assets:**
- **assets/react.svg** — React logo
- **assets/vite.svg** — Vite logo
- **assets/hero.png** — Hero image for branding

---

### 📁 `src/features/` — FEATURE MODULES (Feature-Based Architecture)

#### **auth/** — AUTHENTICATION & USER MANAGEMENT

**Pages:**
- **pages/LoginPage.tsx** — User login form with email/password
- **pages/RegisterPage.tsx** — User registration form
- **pages/GoogleCallbackPage.tsx** — Google OAuth callback handler

**Components:**
- **components/ProtectedRoute.tsx** — Route guard component, authorization wrapper

**Hooks:**
- **hooks/useCurrentUser.ts** — Current user state hook, session management

**Types & API:**
- **types.ts** — Authentication type definitions
- **auth-specific services** — Auth-related API calls

---

#### **dashboard/** — MAIN DASHBOARD

**Pages:**
- **pages/DashboardPage.tsx** — Main dashboard view, summary widgets

---

#### **meetings/** — MEETING MANAGEMENT & INTELLIGENCE

**Pages:**
- **pages/MeetingPage.tsx** — Meeting list with filtering, sorting
- **pages/MeetingTypesPage.tsx** — Meeting type configuration and management
- **pages/MeetingDetailPage.tsx** — Individual meeting details and analysis
- **pages/ActionItemsPage.tsx** — Action item tracking and management

**Components:**
- **components/MeetingCard.tsx** — Meeting display card widget
- **components/MeetingList.tsx** — Meeting list container with state
- **components/MeetingRow.tsx** — Table row component for meeting lists
- **components/MeetingSourceIcon.tsx** — Platform icon display (Teams, Zoom, etc.)
- **components/MeetingAIMemorySection.tsx** — AI analysis insights section
- **components/AIMemoryStatusDot.tsx** — Status indicator for AI processing
- **components/ScheduleMeetingForm.tsx** — Form for scheduling new meetings
- **components/JoinMeetingModal.tsx** — Modal for joining live meetings
- **components/CategoryModal.tsx** — Modal for category assignment
- **components/CategoryAssignControl.tsx** — Category selector control
- **components/TeamModal.tsx** — Modal for team selection
- **components/DocumentsPanel.tsx** — Panel displaying meeting-specific documents
- **components/OrgDocumentsPanel.tsx** — Panel for organizational documents

**Hooks:**
- **hooks/useMeetings.ts** — Meeting list state management, pagination
- **hooks/useLiveTranscript.ts** — WebSocket hook for live transcript streaming
- **hooks/useCategories.ts** — Category data fetching and caching

**Types & API:**
- **types.ts** — Meeting-related type definitions
- **api.ts** — Meeting API calls (CRUD, status, filtering)

---

#### **ask/** — CONVERSATIONAL Q&A / RAG INTERFACE

**Pages:**
- **pages/AskPage.tsx** — Main chat interface for Q&A

**Components:**
- **components/MessageBubble.tsx** — Chat message display component
- **components/ConversationSidebar.tsx** — Conversation history sidebar
- **components/CitationChip.tsx** — Citation reference display chip

**Hooks:**
- **hooks/useChatStream.ts** — Streaming chat responses from backend

**Types & API:**
- **types.ts** — Chat-related type definitions
- **api.ts** — Chat and RAG API calls

---

#### **knowledge/** — KNOWLEDGE HUB & KNOWLEDGE GRAPH VISUALIZATION

**Pages:**
- **pages/KnowledgeHubPage.tsx** — Knowledge search and discovery interface
- **pages/KnowledgeGraphPage.tsx** — Knowledge graph visualization

**Components:**
- **components/SearchHitCard.tsx** — Search result card display
- **components/EntityCard.tsx** — Entity display card
- **components/EntityDetailDrawer.tsx** — Detailed entity information panel
- **components/ScopePicker.tsx** — Search scope selector (workspace/team/meeting)

**Hooks:**
- **hooks/useSearch.ts** — Search query state management
- **hooks/useEntities.ts** — Entity list state and fetching
- **hooks/useEntityDetail.ts** — Entity detail state
- **hooks/useMeetingGraph.ts** — Knowledge graph data fetching
- **hooks/useMeetingChunks.ts** — Document chunks fetching
- **hooks/useDebouncedValue.ts** — Debounce utility hook

**Types & API:**
- **types.ts** — Knowledge-related type definitions
- **api.ts** — Knowledge API calls (search, entity detail, graph queries)

---

#### **templates/** — TEMPLATE MANAGEMENT & BROWSING

**Pages:**
- **pages/TemplatesLandingPage.tsx** — Template overview and introduction
- **pages/TemplatesBrowsePage.tsx** — Browse available templates
- **pages/TemplatesInstalledPage.tsx** — View installed templates
- **pages/BundlePreviewPage.tsx** — Template bundle preview

**Services:**
- **services/templatesApi.ts** — Template API client

---

#### **agents/** — AGENT MANAGEMENT & CONFIGURATION

**Pages:**
- **pages/AgentsListPage.tsx** — Agent list view
- **pages/AgentDetailPage.tsx** — Agent detail and configuration

**Components:**
- **components/PromptEditor.tsx** — Prompt editing interface
- **components/VersionHistory.tsx** — Agent version timeline
- **components/PlaygroundPanel.tsx** — Agent testing playground
- **components/EvalPanel.tsx** — Evaluation results display
- **components/AnalyticsPanel.tsx** — Usage analytics dashboard

**Types & API:**
- **types.ts** — Agent type definitions
- **api.ts** — Agent API calls

---

#### **agent-control/** — AGENT BEHAVIOR OVERRIDE SYSTEM

**Pages:**
- **pages/AgentControlPage.tsx** — Main behavior override control panel

**Components:**
- **components/BehaviorControlsModal.tsx** — Behavior settings modal
- **components/BehaviorEditor.tsx** — Override value editor
- **components/ScopeSidebar.tsx** — Scope selector (workspace/category/team)
- **components/DimensionAccordion.tsx** — Behavior dimension accordion UI
- **components/InheritanceBadge.tsx** — Inheritance indicator badge
- **components/FieldRow.tsx** — Individual setting row with save/reset

**Dimension Components:**
- **components/dimensions/MasterPromptDimension.tsx** — Prompt override UI
- **components/dimensions/StringListDimension.tsx** — List-type override UI
- **components/dimensions/KeyValueDimension.tsx** — Key-value override UI
- **components/dimensions/useDimensionEditor.ts** — Shared dimension editing hook

**Services:**
- **services/behaviorApi.ts** — Behavior API client

**Types:**
- **types.ts** — Behavior type definitions

---

#### **calendar/** — CALENDAR INTEGRATION

**Pages:**
- **pages/CalendarPage.tsx** — Calendar view and sync management

---

#### **integrations/** — THIRD-PARTY INTEGRATIONS

**Pages:**
- **pages/IntegrationsPage.tsx** — Integration management and configuration

**Components:**
- **components/IntegrationCard.tsx** — Integration tile/card component

---

#### **tasks/** — TASK MANAGEMENT

- Task-specific pages, components, and hooks for task management features

---

## 📂 `alembic/` — DATABASE MIGRATIONS

- **env.py** — Alembic environment configuration, migration engine setup
- **script.py.mako** — Alembic migration script template
- **README** — Migration documentation

### **versions/** — Granular Migration Files

#### **Phase 1-2 (Core Infrastructure & Vector Memory):**
- **02e7a18dd266_initial_schema.py** — Initial database schema (users, meetings, documents, etc.)
- **c8a3f1e9d27a_phase2a_vector_memory.py** — Vector embedding storage table

#### **Phase 3 (Knowledge Graph Foundation):**
- **d4f7c2a8e3b1_phase3a_graph_foundation.py** — Graph entities and relationships tables
- **e9b2d1f6c834_phase3b_prompt_version_string.py** — Prompt versioning support
- **f3a7d8c1b569_phase3c_meeting_graph_status.py** — Graph status tracking table

#### **Phase 4 (Document Processing & Chunking):**
- **a8b3e7d9f4c1_phase4a_document_chunks.py** — Document chunks table with vector refs
- **c2b0e7f4a915_phase4d_doc_extraction_runs.py** — Document extraction run tracking

#### **Phase 5 (RAG Audit & Logging):**
- **d3f4a2c8b619_phase5a_rag_audit.py** — RAG query audit logging table

#### **Phase 6 (Consolidation & Importance):**
- **e7b3c9d8a142_phase6a_importance.py** — Entity importance scores table
- **f4d8c2b6e913_phase6b_access_events.py** — Access event tracking for analytics
- **a9c5e1f2d731_phase6c_rerank_strategy.py** — Ranking strategies and configurations
- **b6e2d4a8c517_phase6d_consolidation.py** — Meeting consolidation records

#### **Phase 7 (Agent System, Playground, Evaluation):**
- **g8a1b2c3d4e5_phase7a_agent_profiles.py** — Agent profile definitions
- **h9b2c3d4e5f6_phase7b_prompt_versions.py** — Detailed prompt versioning
- **i0c3d4e5f6a7_phase7c_runtime_logs.py** — Runtime execution logging
- **j1d4e5f6a7b8_phase7e_playground.py** — Playground state persistence
- **k2e5f6a7b8c9_phase7f_performance_daily.py** — Daily performance metrics aggregation
- **l3f6a7b8c9d0_phase7h_eval_runs.py** — Evaluation run tracking

#### **Phase 8 (Behavior Management & Templates):**
- **m4a1b2c3d4e5_phase8a_global_template_registry.py** — Global template registry
- **n5b2c3d4e5f6_phase8b_workspace_provisioning.py** — Workspace-level provisioning
- **o6c3d4e5f6a7_phase8d_upgrade_proposals.py** — Upgrade proposal tracking
- **p7d4e5f6a7b8_phase8c_behavior_overrides.py** — Behavior override storage
- **q8e5f6a7b8c9_phase8a_behavior_profiles.py** — Behavior profile definitions
- **r9f7a8b9c0d1_phase8f_cleanup.py** — Cleanup and optimization operations
- **s0a8b9c0d1e2_phase8g_team_parent.py** — Team hierarchy and parent relationships
- **t1b9c0d1e2f3_phase8g_team_entity_type.py** — Team entity type definitions

---

## 📂 `tests/` — COMPREHENSIVE TEST SUITE

### **Phase 1-2 Tests (Core Infrastructure):**
- **test_phase1.py** — Core infrastructure tests (database, auth, basic models)
- **test_phase2b.py** — Vector memory and embedding tests
- **test_phase2c.py** — Document handling and storage tests
- **test_phase2d.py** — Transcription API and webhook tests
- **test_phase2e.py** — Utility and helper function tests

### **Phase 3 Tests (Knowledge Graph):**
- **test_phase3a.py** — Graph foundation tests (entity/relationship creation)
- **test_phase3b.py** — Prompt versioning tests
- **test_phase3c.py** — Meeting graph status tracking tests
- **test_phase3d.py** — Graph extraction from meetings tests
- **test_phase3e.py** — Entity normalization and deduplication tests

### **Phase 4 Tests (Document Processing):**
- **test_phase4a.py** — Document chunking strategy tests
- **test_phase4b.py** — Chunking algorithm validation tests
- **test_phase4c.py** — Document extraction tests
- **test_phase4d.py** — Extraction run tracking tests
- **test_phase4e.py** — Parser (PDF, DOCX, XLSX) tests
- **test_phase4f.py** — End-to-end document processing tests

### **Phase 5 Tests (RAG):**
- **test_phase5a.py** — RAG pipeline orchestration tests
- **test_phase5b.py** — Document retrieval and ranking tests
- **test_phase5c.py** — Answer synthesis and response generation tests
- **test_phase5d.py** — Query planning and decomposition tests
- **test_phase5f.py** — End-to-end RAG integration tests

### **Phase 6 Tests (Consolidation):**
- **test_phase6a.py** — Importance scoring algorithm tests
- **test_phase6b.py** — Access event logging and analytics tests
- **test_phase6c.py** — Ranking and reranking tests
- **test_phase6d.py** — Consolidation merge logic tests
- **test_phase6e.py** — Archive management tests
- **test_phase6f.py** — Meeting merge and rollup tests

### **Phase 7 Tests (Agent System):**
- **test_phase7a.py** — Agent profile definition tests
- **test_phase7b.py** — Prompt versioning tests
- **test_phase7e.py** — Playground functionality tests
- **test_phase7f.py** — Performance metrics tests
- **test_phase7h.py** — Evaluation framework tests

### **Phase 8 Tests (Behavior Management):**
- **test_phase8a_behavior_profiles.py** — Behavior profile tests
- **test_phase8b_provisioning.py** — Provisioning workflow tests
- **test_phase8c_overrides.py** — Override storage and retrieval tests
- **test_phase8d_resolver.py** — Behavior resolution and inheritance tests
- **test_phase8e_behavior_api.py** — Behavior API endpoint tests

### **Phase 9 Tests (Runtime Behavior):**
- **test_phase9_runtime.py** — Runtime behavior validation tests

### **Test Support:**
- **fixtures/** — Test fixtures and mock data
  - **canonical_org.py** — Standard test organization fixture
- **eval_phase5/** — RAG evaluation datasets and benchmarks
- **phase9/** — Runtime behavior evaluation suite
  - **layers/** — Comprehensive 7-layer runtime testing

---

## 📂 `.planning/` — PROJECT PLANNING & ARCHITECTURE

Strategic architecture mapping, development notes, and design decisions used during the project's evolution.

Contains:
- Phase-specific planning documents
- Architecture decision records
- Design prototypes and spike notes
- Milestone planning artifacts
- Development progress tracking

---

## Architecture Overview

This project follows a **microservice-oriented architecture** with clear separation of concerns:

1. **API Layer** (`app/api/`) — HTTP endpoints, request validation, response serialization
2. **Business Logic Layer** (`app/services/`) — Core business rules, orchestration, integrations
3. **Data Access Layer** (`app/db/`) — ORM models, database operations, schema
4. **Asynchronous Layer** (`app/celery_tasks/`) — Background jobs, async processing, task scheduling
5. **Frontend Layer** (`meeting_ai_frontend/`) — React UI, feature modules, user interactions

**Key Design Patterns:**
- **Feature-based organization** in both backend (services) and frontend (feature modules)
- **Service-oriented** with clear responsibility boundaries
- **Dependency injection** for database sessions and authentication
- **Template-based** agent behavior configuration with hierarchical override system
- **Event-driven** automation and webhook processing
- **Comprehensive test coverage** aligned with development phases
