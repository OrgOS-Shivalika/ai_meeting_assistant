# Skill-Based Runtime System: Architectural Specification

This document details the transition of the **Agentic Meeting Assistant** from a monolithic, prompt-oriented agent architecture to a modular, capability-driven **Skill-Based Runtime System**.

---

## 🏗️ 1. Core Architecture
The system is now organized around **Capabilities**, not Agents. Agents have been demoted to "Orchestrators" that manage a collection of discrete, specialized "Skills."

### The Multi-Layer Execution Stack
1.  **User Intent Layer**: High-level toggles in the Frontend (e.g., "Architecture Review").
2.  **Policy Resolver**: Translates Intents into a `BehaviorProfile` containing technical `enabled_agents` and `allowed_tools`.
3.  **Agent Orchestrator**: Resolves the list of active agents into a graph of specialized **Skills**.
4.  **Skill Runtime**: The `SkillExecutor` handles the atomic execution of each skill unit.
5.  **Event Bus**: Skills emit runtime events (e.g., `risk.detected`) to trigger async automations.

---

## 🔄 2. The Skill Runtime Flow
Every skill execution follows a standardized, six-step deterministic pipeline managed by `app/runtime/skill_executor.py`:

| Step | Phase | Action |
| :--- | :--- | :--- |
| **0** | **Governance** | Validates `required_tools` against the `BehaviorProfile` authorized tools. Blocks execution if unauthorized. |
| **1** | **Assembly** | Stacks prompts: `Global Foundation` + `Org Intent` + `Skill Mission` + `Output Schema`. |
| **2** | **Retrieval** | Performs skill-specific RAG (vector/graph search) based on `search_bias` and `sources`. |
| **3** | **Execution** | Dispatches the assembled context to the LLM (GPT-4o-mini) with `json_object` enforcement. |
| **4** | **Validation** | Parses and validates the LLM response against the skill's defined `output_schema`. |
| **5** | **Events** | Fires `emits_events` into the `AutomationBus` for Slack, Jira, or webhook processing. |

---

## 📂 3. File System & Key Components

### 🧠 Backend: The Cognition Engine
*   `app/skills/base.py`: The **Skill Contract**. Defines `SkillDefinition`, `RetrievalConfig`, and `MemoryConfig`.
*   `app/skills/registry.py`: The **Central Catalog**. Maps capabilities to skills and handles runtime registration.
*   `app/skills/[domain]/*.py`: **31+ Reusable Skills** across Engineering, Incidents, Meetings, Product, Executive, and Compliance.
*   `app/runtime/skill_executor.py`: The **Runtime Engine**. Manages the full cognition lifecycle (Assembly to Events).
*   `app/services/agents/base.py`: Refactored **Agent Orchestrators**. Agents no longer contain prompts; they list skill IDs.
*   `app/services/agents/graph_orchestrator.py`: The **Graph Resolver**. Orchestrates the loop between multiple agents and the `SkillExecutor`.
*   `app/services/behavior/policy_resolver.py`: The **Intent Bridge**. Maps UI capability toggles to technical skill sets.

### 🖥️ Frontend: The Control Surface
*   `meeting_ai_frontend/src/features/agent-control/components/dimensions/SkillsDimension.tsx`: New **Modular Skills Panel**. Replaces the low-level agent chip list with a clean, capability-oriented UI.
*   `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`: Integrated the new Skills layer into Advanced Mode.

---

## 📚 4. Multi-Domain Skill Catalog
We have expanded the system to support **31 specialized enterprise cognition modules**:

*   **Engineering**: `architecture_review`, `code_review`, `api_review`, `performance_profiling`, `security_audit`.
*   **Incident Management**: `incident_detection`, `root_cause_analysis`, `postmortem_generator`, `impact_assessment`.
*   **Meetings**: `summaries`, `action_items`, `decisions`, `sentiment_analysis`, `agenda_tracking`.
*   **Product**: `feature_extraction`, `user_pain_points`, `roadmap_alignment`, `competitor_analysis`.
*   **Executive**: `strategic_alignment`, `risk_rollup`, `investment_areas`, `executive_briefing`.
*   **Compliance**: `pii_detection`, `policy_violation`, `regulatory_audit`, `access_control`.

---

## 🛡️ 5. Governance & Safety
Skills are now "Governance-Aware." If a skill declares a requirement for `jira`, the `SkillExecutor` will check the `BehaviorProfile` of the specific organization. If the user has not authorized the Jira tool connection, the skill is **automatically skipped**, ensuring the assistant never attempts unauthorized data access or integration calls.

---

## 🧪 6. Testing & Validation
The system includes an end-to-end verification script to validate the entire lifecycle.

**Run the verification suite:**
```powershell
$env:PYTHONPATH="."; python tests/verify_skill_runtime.py
```

**Key Verification Benchmarks:**
- **Intent Resolution**: UI toggles correctly map to backend skills.
- **Dynamic Assembly**: Prompts are correctly layered based on workspace context.
- **Error Containment**: A failure in one skill does not crash the entire orchestration graph.
- **Event Provenance**: All events emitted by skills carry the correct `meeting_id` and `organization_id`.

---
*Created on 2026-05-26 | Skill Runtime Migration Phase 1-9 Completed.*
