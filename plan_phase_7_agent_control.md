# Phase 7 — Agent Control Dashboard

> **Status:** PLANNED. Awaiting "go".
> **Renumbering note:** the previously-drafted "Phase 7 — Live in-meeting copilot" is being **deferred to Phase 8**. This document supersedes it. The live copilot still slots in cleanly *after* this layer ships — the runtime resolver designed here is exactly what the live copilot will consume.
> **Position in the roadmap:** the system has shipped Phases 1–6 (288/288 tests, head migration `b6e2d4a8c517`). This phase adds the **central runtime configuration layer** that sits *on top of* the existing RAG runtime; it does not duplicate it.

---

## 0. Framing — what this is and what it is not

**This is** the runtime configuration layer for every agent the platform runs. The four existing LLM-driven services — `query_planner.py`, `synthesizer.py`, `graph_extractor_llm.py`, `transcript_analyzer.py` (and Phase 6 importance scoring + future Phase 8 live copilot) — currently read their prompts from filesystem text files (`app/ai_agents/prompts/...`) and read their knobs from `settings.py` env vars. After Phase 7, those same services consume a **`ResolvedAgentConfig`** built by a hierarchical resolver at runtime, with the filesystem prompts and env vars as the floor (system-default tier).

**This is NOT** a parallel orchestration system. There is no new "agent framework". We do not add LangChain / LangGraph / autogen / any agent meta-runtime. The existing functions keep their signatures; we add a single resolver call at the top of each and inject a config object.

The architectural payoff: an org admin can change how their Sales team's Customer-Demo synthesizer behaves — different prompt, different `top_k`, different rerank strategy, different citation strictness — **without touching code, without redeploying**, while every existing observability surface continues to work.

---

## 1. Current state we are integrating with (read this first)

### 1.1 Existing prompt resolution

`app/ai_agents/prompts/rag/__init__.py` already does versioned filesystem prompt loading with an in-process cache. Each prompt is a single `v1.txt` blob today. The version string is already plumbed all the way through to `rag_query_runs.planner_prompt_version` / `rag_query_runs.synth_prompt_version`. Phase 7 keeps this loader as the **system-default tier** and adds DB-backed overrides above it.

### 1.2 Existing RAG entry point

`app/services/rag/ask_pipeline.py:ask_stream(...)` already accepts:
- `requested_scope_type`, `requested_scope_id` — `team` | `category` | `global`
- `sources: SourcesFilter` — `all` | `meetings_only` | `documents_only`
- `top_k_final: Optional[int]` — overrides settings
- `rerank_strategy: Optional[str]` — overrides settings (Phase 6C strategy router: `legacy_weighted` | `importance_aware` | `auto`)

These are the knobs Phase 7 makes per-agent.

### 1.3 Existing models (no rename, no churn)

- `Organization` (UUID PK)
- `Category` (Integer PK) — the project's "meeting type" surface. The HTTP layer exposes this as `/meeting-types`. We'll surface "meeting type" in the dashboard UI; internally we keep `category_id`.
- `Team` (Integer PK, FK to `Category`)
- `User` (UUID PK, has `organization_id`, has a `role` column today)
- `RagQueryRun` — already has `planner_model`, `planner_prompt_version`, `synth_model`, `synth_prompt_version`, `rerank_strategy`. We add three nullable columns: `agent_profile_id`, `prompt_version_id`, `resolution_path_hash`.

### 1.4 Existing audit patterns we mirror

- **Six-column knowledge-metadata mandate** (importance/confidence/version/source-meeting/last-accessed/access-count) — agent_profiles get a slim equivalent.
- **Audit-log shape** (`algorithm_version`, `weights_json`, `score_distribution_json`, `status`, `error_message`) — `prompt_test_runs` and `agent_runtime_logs` follow it.
- **Soft-active dedup** via partial unique index `WHERE status = 'active'` — used on all four new "live" tables.
- **Sticky-rejection** pattern (LEAST/GREATEST canonicalized pair) — not used here; pairs aren't the shape.
- **Strategy router** (Phase 6C: `legacy_weighted` vs `importance_aware`) — extended; `rerank_strategy` becomes a per-agent setting, not a request-time argument.
- **Fire-and-forget for non-critical** — playground writes, cache invalidation propagation.
- **Eval-gated changes** — Phase 7H makes the Phase 5F eval harness optionally required for publish.

### 1.5 Existing routers (no replacement)

`auth`, `category`, `meeting_types`, `team`, `document`, `team_document`, `transcription`, `google_auth`, `search`, `graph`, `rag`, `consolidation`, `observability`, `ws`, `recall_webhook`.

We add: `agents`, `prompt_configs`, `playground`. We **extend** `observability` (do not fork it).

---

## 2. Architectural commitments

These follow Phase 1–6 conventions exactly:

1. **Multi-tenant by `organization_id` on every new row**, with `ON DELETE CASCADE` from `organizations`.
2. **One global-default tier exists**, identified by a sentinel `organization_id` (the existing `Organization` row created for the platform owner — there is no NULL org). Resolver special-cases that org.
3. **Non-destructive defaults**: every config knob has a baseline that matches today's behavior. A brand-new org with no agent configs runs identically to today.
4. **Filesystem prompts stay**, as the final fallback. They also seed the first published `prompt_version` for every default agent on org creation.
5. **No new agent framework**. Existing functions (`plan_query`, `synthesize_stream`, `extract_graph`, etc.) gain one new keyword argument: `resolved_config: ResolvedAgentConfig | None = None`. When `None`, behavior is bit-for-bit the current behavior.
6. **Append-only deployment audit** (`prompt_deployments`, `agent_runtime_logs`) — BIGSERIAL PK, no FK on volatile pointers, partition-ready.
7. **Resolver-pure**: the resolver is a pure function of the DB + inputs. No globals other than the LRU cache. Cache invalidation is a monotonic epoch counter in a tiny shared table.
8. **Versioning is immutable**. `prompt_versions` rows are append-only. Draft is a state; published is a state; archived is a state. Never UPDATE the prompt body of a published version.
9. **Strict tenant isolation**: every API filters by `current_user.organization_id`. Cross-org access by superusers requires an explicit `X-Acting-Org` header + an `agent_audit_events` row.
10. **Eval-gated publish is opt-in per agent profile**. When required, publish is blocked unless a Phase 5F-style eval scored against a fixture set returns ≥ threshold. Mirrors Phase 5F harness.

---

## 3. Database architecture

Six new tables + three new columns on `rag_query_runs`. Four Alembic migrations.

### 3.1 `agent_profiles`

Reusable agent identities. The "what kind of assistant is this".

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | gen_random_uuid() |
| `organization_id` | UUID FK orgs CASCADE NOT NULL | tenant scope |
| `slug` | text NOT NULL | e.g. `sales_copilot`, `sprint_assistant`, `interviewer`, `exec_summarizer` |
| `display_name` | text NOT NULL | UI label |
| `description` | text | optional admin notes |
| `agent_type` | text NOT NULL | enum: `rag_synth` \| `rag_planner` \| `graph_extractor` \| `transcript_analyzer` \| `importance_scorer` \| `summarizer` \| `live_copilot` (reserved for Phase 8) |
| `status` | text NOT NULL DEFAULT 'active' | `active` \| `archived` |
| `default_modular_prompt_json` | JSONB | optional starter template surfaced in the editor on profile creation |
| `eval_gate_required` | boolean NOT NULL DEFAULT false | Phase 7H — block publish unless eval threshold met |
| `eval_fixture_set_id` | UUID nullable | references a Phase 5F fixture set |
| `eval_min_score` | float nullable | threshold |
| `created_by` | UUID FK users SET NULL | nullable |
| `created_at` / `updated_at` | timestamptz | |

**Indexes:**
- `UNIQUE (organization_id, slug) WHERE status = 'active'` — soft-active dedup, lets you archive a `sales_copilot` and create a new one with the same slug.
- `INDEX (organization_id, agent_type, status)`

**`agent_type` ↔ existing service mapping** (locked):

| `agent_type` | Existing service | Modular sections consumed |
|---|---|---|
| `rag_planner` | `app/services/rag/query_planner.py` | `system`, `behavior`, `guardrails`, `output` (the JSON contract section) |
| `rag_synth` | `app/services/rag/synthesizer.py` | all 8 sections |
| `graph_extractor` | `app/ai_agents/graph_extractor_llm.py` | `system`, `behavior`, `output` (JSON contract), `guardrails` |
| `transcript_analyzer` | `app/ai_agents/openAI_transcript_analyzer.py` | `system`, `behavior`, `output`, `meeting_type` |
| `importance_scorer` | `app/services/importance/scorer.py` | none today (deterministic Python). Profile exists for future LLM-assisted scoring + carries `retrieval_config_json.importance_weight_overrides` to adjust the scorer's six signal weights. |
| `summarizer` | reserved | post-meeting summary agent (already partially exists in transcript_analyzer; broken out for per-team override) |
| `live_copilot` | reserved for Phase 8 | all 8 sections + tool permissions |

### 3.2 `agent_prompt_configs`

The binding table — "which agent profile is active at which scope, pointing to which active version".

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL | denormalized for tenant safety |
| `agent_profile_id` | UUID FK agent_profiles CASCADE NOT NULL | |
| `scope_type` | text NOT NULL | enum: `organization` \| `category` \| `team` \| `meeting_specific` (Phase 8+) |
| `scope_id` | bigint nullable | NULL when `scope_type='organization'`; integer for `category`/`team`; UUID-as-bigint not used — meetings have UUID PKs, so for `meeting_specific` we add a sibling `scope_uuid` column in Phase 8 |
| `active_version_id` | UUID FK prompt_versions SET NULL nullable | NULL until first publish |
| `status` | text NOT NULL DEFAULT 'active' | |
| `created_by` | UUID FK users SET NULL | |
| `created_at` / `updated_at` | timestamptz | |

**Constraints:**
- `CHECK (scope_type IN ('organization','category','team') )` — Phase 7. Migration 8 adds `meeting_specific`.
- `CHECK ((scope_type = 'organization' AND scope_id IS NULL) OR (scope_type IN ('category','team') AND scope_id IS NOT NULL))`
- `UNIQUE (organization_id, agent_profile_id, scope_type, scope_id) WHERE status = 'active'`
  → one active binding per (org, profile, scope) tuple, soft-active.

**The "global default" tier** lives in this table too, in the **platform-owner org** (the sentinel org). Resolver reads it as the lowest-priority real DB layer. Beneath it sits the filesystem fallback (Phase 0).

### 3.3 `prompt_versions`

Immutable snapshot of a full configuration: modular prompts + retrieval config + model config + tool permissions.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL | |
| `agent_prompt_config_id` | UUID FK agent_prompt_configs CASCADE NOT NULL | |
| `version_number` | integer NOT NULL | autoincrement per config — application-managed (see §6.1) |
| `label` | text | optional human label, e.g. `"q2-demo-test"` |
| `modular_prompt_json` | JSONB NOT NULL | the 8 sections (see §4) |
| `variables_schema_json` | JSONB NOT NULL DEFAULT '[]' | declared list of `{name, required, description, sample}` for validation |
| `retrieval_config_json` | JSONB NOT NULL | see §5 |
| `model_config_json` | JSONB NOT NULL | `{model, temperature, max_tokens, response_format}` |
| `tool_permissions_json` | JSONB NOT NULL DEFAULT '{"allowed":[],"denied":[]}' | §7 |
| `meta_json` | JSONB | free-form tags, notes, eval markers |
| `state` | text NOT NULL DEFAULT 'draft' | `draft` \| `published` \| `archived` |
| `published_at` | timestamptz nullable | |
| `published_by` | UUID FK users SET NULL nullable | |
| `eval_score` | float nullable | most recent eval-gate score, if run |
| `eval_run_id` | UUID nullable | references a Phase 5F eval-run row |
| `created_by` | UUID FK users SET NULL | |
| `created_at` / `updated_at` | timestamptz | |

**Constraints:**
- `UNIQUE (agent_prompt_config_id, version_number)`
- `CHECK ((state = 'published') = (published_at IS NOT NULL))`
- `INDEX (agent_prompt_config_id, state, version_number DESC)` — drives "latest published" lookups.

**Immutability:** application code never UPDATEs `modular_prompt_json`, `retrieval_config_json`, `model_config_json`, `tool_permissions_json`, `variables_schema_json` for a row in state `published` or `archived`. Enforced in the service layer; doubled by a Postgres trigger in 7B that raises on UPDATE if state ≠ 'draft' for those columns.

### 3.4 `prompt_deployments`

Append-only deployment audit. Mirrors `rag_chunk_access_events` (Phase 6B) — BIGSERIAL, append-only, no destructive ops.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `organization_id` | UUID NOT NULL | |
| `agent_prompt_config_id` | UUID NOT NULL | not FK — we never want a cleanup to wipe deployment history |
| `action` | text NOT NULL | `publish` \| `rollback` \| `unpublish` \| `eval_gate_failed` |
| `from_version_id` | UUID nullable | |
| `to_version_id` | UUID nullable | nullable for `unpublish` |
| `actor_user_id` | UUID FK users SET NULL nullable | |
| `reason` | text | |
| `metadata_json` | JSONB | e.g. eval score, request_id |
| `created_at` | timestamptz | |

**Indexes:**
- `INDEX (organization_id, agent_prompt_config_id, created_at DESC)`
- `INDEX (organization_id, action, created_at DESC)` — for analytics ("deploys this week")

### 3.5 `prompt_test_runs`

Playground/sandbox executions. Pure observability — never participates in retrieval reranking, never logs `rag_chunk_access_events`, never writes to `rag_query_runs`, never touches a conversation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID NOT NULL | |
| `agent_prompt_config_id` | UUID nullable | NULL if testing freeform |
| `prompt_version_id` | UUID nullable | NULL if testing inline-edited draft |
| `inline_overrides_json` | JSONB nullable | deltas vs `prompt_version_id` |
| `simulated_scope_type` | text | what scope was resolved against |
| `simulated_scope_id` | bigint nullable | |
| `simulated_user_id` | UUID nullable | "as user X" |
| `query_text` | text NOT NULL | |
| `assembled_prompt_text` | text NOT NULL | full composed prompt — what was actually sent to the LLM |
| `retrieval_bundle_json` | JSONB | same shape as `rag_query_runs.retrieval_bundle` |
| `answer_text` | text | |
| `citations_json` | JSONB | |
| `input_tokens` / `output_tokens` | integer | |
| `planner_duration_ms` / `retrieval_duration_ms` / `synth_duration_ms` / `total_duration_ms` | integer | |
| `status` | text | `completed` \| `no_context` \| `failed` |
| `error_message` | text | |
| `created_by` | UUID FK users SET NULL | |
| `created_at` | timestamptz | |

**Indexes:** `(organization_id, created_at DESC)`, `(prompt_version_id, created_at DESC)`.

### 3.6 `agent_runtime_logs`

One row per **resolution call** (which is at most one per `/rag/ask`, plus one per planner-only call if planner is split). Captures the resolution chain, separate from the per-query observability that already lives on `rag_query_runs`.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `organization_id` | UUID NOT NULL | |
| `rag_query_run_id` | UUID nullable | back-reference for joining; nullable because resolver fires before the run row exists |
| `agent_profile_id` | UUID nullable | nullable when the resolver falls all the way back to filesystem |
| `prompt_version_id` | UUID nullable | likewise |
| `agent_type` | text NOT NULL | denormalized |
| `requested_scope_type` / `requested_scope_id` | text / bigint | what the caller asked for |
| `resolution_path_json` | JSONB NOT NULL | ordered list: `[{layer:'team', config_id, version_id, fields_contributed:[...]}, ...]` |
| `resolved_config_hash` | text NOT NULL | sha256 over the canonicalized resolved config — drives "how many distinct configs ran today" |
| `cache_hit` | boolean NOT NULL | |
| `resolve_duration_ms` | integer NOT NULL | |
| `warnings_json` | JSONB | missing-variable warnings, etc. |
| `created_at` | timestamptz | |

**Indexes:** `(organization_id, agent_profile_id, created_at DESC)`, `(rag_query_run_id)`.

### 3.7 `agent_config_epochs`

Tiny shared counter table for cache invalidation across workers. One row per (org, agent_profile) pair, monotonic counter.

| Column | Type | Notes |
|---|---|---|
| `organization_id` | UUID NOT NULL | composite PK |
| `agent_profile_id` | UUID NOT NULL | composite PK |
| `epoch` | bigint NOT NULL DEFAULT 0 | bumped on every publish/rollback |
| `updated_at` | timestamptz | |

**PK:** `(organization_id, agent_profile_id)`.

Bumps are advisory-locked per (org, profile) to serialize concurrent publishes. The application bumps inside the same transaction as the publish, so a successful publish *always* produces a visible epoch change.

### 3.8 Changes to existing tables

`rag_query_runs` (Phase 7C migration):

| Column | Type | Notes |
|---|---|---|
| `agent_profile_id` | UUID FK agent_profiles SET NULL nullable | backfill NULL for pre-existing rows |
| `prompt_version_id` | UUID FK prompt_versions SET NULL nullable | |
| `resolution_path_hash` | text nullable | denormalized for cardinality counting |

Backward compat: every pre-Phase-7 row has these three columns NULL. Observability tolerates NULL by grouping under a synthetic "filesystem-default" bucket.

### 3.9 Migration sequence (Alembic)

Four migrations land across slices:

| Slice | Migration | Tables / changes |
|---|---|---|
| 7A | `g8a1..._phase7a_agent_profiles_and_configs.py` | `agent_profiles`, `agent_prompt_configs`, `agent_config_epochs` |
| 7B | `h9b2..._phase7b_prompt_versions.py` | `prompt_versions`, `prompt_deployments`, immutability trigger |
| 7C | `i0c3..._phase7c_runtime_logs.py` | `agent_runtime_logs`, three new columns on `rag_query_runs` |
| 7E | `j1d4..._phase7e_playground.py` | `prompt_test_runs` |

All migrations are reversible. All FKs are CASCADE-from-org or SET-NULL-from-user — matches Phase 1–6 convention.

---

## 4. Modular prompt design

**No monolithic prompt is ever stored.** Every `prompt_versions.modular_prompt_json` is an object with eight string keys. Missing keys = empty string. Required vs optional is enforced per-agent-type by a validator.

### 4.1 The eight modular sections

| Section | Purpose | Example contents |
|---|---|---|
| `system` | Agent identity — who it is, what it answers for | "You are the Sales Copilot for {{org_name}}. You answer questions about deals, customers, and pipeline." |
| `behavior` | Style, tone, response shape | "Be terse. Lead with the answer. No filler." |
| `team_rules` | Org-/team-specific business rules | "We never discuss competitor pricing. Refer to legal for contract questions." |
| `meeting_type` | Meeting-type bias | "Customer-demo questions: lean toward exec-summary length. Surface objections explicitly." |
| `retrieval` | How to use retrieved context | "Use ONLY the numbered blocks. ENTITY/RELATIONSHIP blocks are for reasoning, not citation." |
| `citation` | Citation format and strictness | "Every factual claim ends in `[N]`. If two blocks support, cite both." |
| `output` | Output format / JSON contract | "Plain prose. No headings. 1–4 sentences for factual; 5–10 for summary." |
| `guardrails` | Refusals, safety, hallucination fallback | "If context doesn't support an answer, reply exactly: 'I don't have enough information to answer that.'" |

The current `app/ai_agents/prompts/rag/synth/v1.txt` decomposes cleanly into these (it's already a `system` + `citation` + `behavior` + `guardrails` + `retrieval` mash; we split it in the 7D migration script).

### 4.2 Composition order (locked)

The composer produces a **two-message chat completion** with this layout:

**System message** = concatenation, separated by double-newlines:
```
{{system}}

{{behavior}}

{{team_rules}}

{{meeting_type}}

{{guardrails}}

{{retrieval}}

{{citation}}

{{output}}
```

Empty sections are skipped (no leading/trailing blank lines, no empty section markers — keeps token count clean).

**User message** = the existing per-call payload (context blocks + question) verbatim. Today this is the trailing `=== CONTEXT === / === QUESTION === / === ANSWER ===` block in `v1.txt`. In 7D this gets extracted into a small, agent-type-specific *user-message template* (separate from the modular sections, owned by the service file). Agent admins **cannot edit the user-message template** in Phase 7 — only the system-message modular sections. This is a deliberate guardrail: it keeps the retrieval-context contract stable.

### 4.3 Variable interpolation

Syntax: `{{var_name}}` — Jinja-lite, no expressions, no filters, no loops.

| Variable | Source | Always available? |
|---|---|---|
| `{{org_name}}` | `Organization.name` | yes |
| `{{org_id}}` | `Organization.id` | yes |
| `{{team_name}}` | `Team.name` resolved from scope | only when scope is `team` |
| `{{category_name}}` / `{{meeting_type}}` | `Category.name` | only when scope is `category` (alias) |
| `{{current_user_name}}` | `User.full_name` | yes (when called from API) |
| `{{current_user_role}}` | `User.role` | yes |
| `{{today}}` | ISO date | yes |
| `{{now}}` | ISO datetime | yes |
| `{{scope_type}}` / `{{scope_id}}` | resolved scope | yes |
| `{{query_text}}` | the user's question | yes, in user-message template (not system message) |
| `{{context_blocks}}` | retrieved chunks | yes, in user-message template (not system message) |
| `{{participants}}` | meeting participants list (string) | only in `transcript_analyzer` / `summarizer` / `live_copilot` agent types |
| `{{meeting_title}}` | meeting title | only when scope is `meeting_specific` (Phase 8) |
| `{{entity_graph}}` | retrieved entities + relationships, formatted | only in `rag_synth` |

**Validation:** when a `prompt_versions` row is moved to `published`, the composer dry-renders against the agent_type's available variable set. Any `{{var}}` not in the set → publish fails with `unknown_variable: var_name`. Each `prompt_versions.variables_schema_json` row may declare *additional* expected runtime variables (for forward compat with new agent types) — publish-time validation only allows the declared set.

**Missing-variable handling at runtime:** a variable that is available *in principle* for the agent type but unresolvable for this specific call (e.g. `{{team_name}}` when the call's scope is `category`) renders as `[team_name unavailable]`. This is logged to `agent_runtime_logs.warnings_json` but the call proceeds. Never crashes — same defensive posture as `query_planner`'s fallback plan.

**Safe rendering:** values are HTML-escaped before substitution. The composer uses plain `str.replace` in a fixed order, not template evaluation. No `eval`, no `exec`, no Jinja, no Mustache.

### 4.4 Per-agent-type required sections

| agent_type | Required sections | Optional |
|---|---|---|
| `rag_synth` | `system`, `retrieval`, `citation`, `guardrails` | all others |
| `rag_planner` | `system`, `output` (the JSON contract) | `behavior`, `guardrails` |
| `graph_extractor` | `system`, `output` | `behavior`, `guardrails` |
| `transcript_analyzer` | `system`, `output` | `behavior`, `meeting_type` |
| `importance_scorer` | none (no LLM call today) | all |
| `summarizer` | `system`, `output` | all |
| `live_copilot` | `system`, `behavior`, `guardrails` | all |

Validator runs at publish time. Drafts can be incomplete (you can iterate without satisfying the contract).

---

## 5. Retrieval-control integration

Each `prompt_versions.retrieval_config_json` carries the full set of retrieval knobs. Default values match `settings.py` exactly (zero behavior change on a fresh org).

### 5.1 Schema (`retrieval_config_json`)

```text
{
  "top_k_vector":            int,           # default 20  (== RAG_TOP_K_VECTOR)
  "top_k_final":             int,           # default 10  (== RAG_TOP_K_FINAL)
  "max_graph_depth":         int,           # default 1   (== RAG_MAX_GRAPH_DEPTH); 0 means "vector-only", a valid graph-RAG-off mode
  "tier_widen_threshold":    int,           # default 5; widen tier when primary stage returns fewer than this many chunks
  "rerank_strategy":         enum,          # auto | legacy_weighted | importance_aware
  "sources_filter":          enum,          # all | meetings_only | documents_only
  "include_archived":        bool,          # default false; Phase 6D archived chunks excluded today
  "citation_strictness":     enum,          # strict (current) | relaxed | off; controls post-stream citation validation
  "importance_weight_overrides": {          # Phase 6C scorer weight overrides for importance_aware rerank
    "access": float | null,
    "citation": float | null,
    "recency": float | null,
    "anchor_density": float | null,
    "confidence": float | null,
    "centrality": float | null
  },
  "entity_expansion_enabled": bool,         # default true; when false, step 5 of retrieval (mention_chunks for related entities) is skipped — i.e. graph-RAG off
  "embedding_model":         text | null    # default null = settings.EMBEDDING_MODEL; lets future versions A/B embedding models without code changes
}
```

### 5.2 Runtime injection

`ask_stream` gains a `resolved_config: ResolvedAgentConfig | None = None` kwarg. Inside:

1. If `resolved_config` is `None`, call the resolver. (HTTP layer normally passes one; tests can skip.)
2. Use `resolved_config.retrieval_config` to override every previously-settings-backed knob.
3. Pass through to `retrieve()` and `synthesize_stream()`.

`retrieve()` gets new kwargs (all `Optional[…]`, all defaulting to current `settings` reads). The internals stay identical — just read from kwargs first, fall back to settings.

### 5.3 Strategy-router extension

Phase 6C's `legacy_weighted` vs `importance_aware` router stays. `auto` means "use the org's default" — today this is `settings.RAG_RERANK_STRATEGY`, after Phase 7D it becomes "the value from the resolved config, falling back to settings".

### 5.4 Validation

`retrieval_config_json` is validated by a Pydantic model on every write to `prompt_versions`. Bounds:
- `top_k_vector ∈ [1, 200]`
- `top_k_final ∈ [1, 50]` and `≤ top_k_vector + 30` (allowing room for entity-expansion chunks)
- `max_graph_depth ∈ [0, 3]` (Phase 5 ships 1; Phase 6+ extensible; we cap at 3 to prevent runaway)
- `tier_widen_threshold ∈ [0, 50]`
- importance_weight_overrides values ∈ [0, 1]

Invalid → publish fails. Drafts may be invalid (UI shows lint).

---

## 6. Runtime resolution engine — the heart of this phase

### 6.1 Public API (locked)

Lives at `app/services/agents/resolver.py`:

```text
def resolve_agent_runtime_config(
    db: Session,
    *,
    organization_id: UUID,
    agent_type: str,                          # "rag_synth", "rag_planner", ...
    agent_profile_id: UUID | None = None,     # if caller knows the exact profile
    agent_profile_slug: str | None = None,    # otherwise resolve by slug
    team_id: int | None = None,
    category_id: int | None = None,
    meeting_id: UUID | None = None,           # Phase 8
    current_user_id: UUID | None = None,
) -> ResolvedAgentConfig
```

Never raises. Always returns a `ResolvedAgentConfig`. On total failure: returns the filesystem-default bundle with `is_default_fallback=True` and a `warnings` list explaining why.

### 6.2 `ResolvedAgentConfig` shape

```text
ResolvedAgentConfig:
    agent_profile_id:    UUID | None
    agent_type:          str
    prompt_version_id:   UUID | None
    version_number:      int  | None
    label:               str  | None

    modular_prompts:     dict[str, str]      # 8 keys, "" for missing
    variables_used:      list[str]           # for warnings_json
    retrieval_config:    RetrievalConfig     # Pydantic
    model_config:        ModelConfig         # Pydantic
    tool_permissions:    ToolPermissions     # Pydantic

    resolution_path:     list[ResolutionStep]
    config_hash:         str
    is_default_fallback: bool
    warnings:            list[str]
```

`config_hash` = sha256 over canonicalized JSON of (modular_prompts, retrieval_config, model_config, tool_permissions). Drives `agent_runtime_logs.resolved_config_hash` for cardinality counting.

### 6.3 Resolution order (precedence, highest wins)

```
1. meeting_specific override            (Phase 8 — scope_type='meeting_specific', scope_uuid=meeting_id)
2. team override                        (scope_type='team',     scope_id=team_id)
3. category/meeting-type override       (scope_type='category', scope_id=category_id)
4. organization override                (scope_type='organization', scope_id=NULL)
5. global default                       (scope_type='organization' in the platform-owner org)
6. filesystem fallback                  (load_planner_prompt / load_synth_prompt from app/ai_agents/prompts/...)
```

Phase 7 implements layers 2, 3, 4, 5, 6. Layer 1 is a one-column migration in Phase 8.

### 6.4 Merge semantics

Each layer contributes:
- A **set of modular sections** it overrides (it's allowed to override fewer than 8).
- A **partial retrieval_config**: only keys the admin set in the UI are present.
- A **partial model_config**.
- A **tool_permissions delta**: `{allowed:[...], denied:[...]}`.

Merge algorithm:

```
result = filesystem_floor  # all 8 sections from filesystem, retrieval_config = settings values

for layer in [global_default, org, category, team, meeting]:  # ascending priority
    if layer present and has version published:
        for k in modular_sections:
            if layer.modular_prompts[k] is not None and layer.modular_prompts[k] != "":
                result.modular_prompts[k] = layer.modular_prompts[k]
                result.resolution_path.append({k: layer.scope})
        for k in retrieval_config_keys:
            if layer.retrieval_config[k] is not None:
                result.retrieval_config[k] = layer.retrieval_config[k]
        for k in model_config_keys:
            if layer.model_config[k] is not None:
                result.model_config[k] = layer.model_config[k]
        result.tool_permissions.allowed |= layer.tool_permissions.allowed
        result.tool_permissions.denied  |= layer.tool_permissions.denied  # deny is monotonic
```

Key rules:

- **Higher layer wins** — last writer in iteration order. Path is recorded so admins can see *why* a section came from a given layer.
- **Empty string = "clear this section"**, opt-in. Admins must explicitly set `""` (UI: a "clear" toggle); omitting the field leaves the lower-priority value in place. This avoids accidental wipeouts.
- **`allowed`** is union (any layer granting a tool grants it).
- **`denied`** is also union but evaluated last: a tool denied at *any* layer is denied. Deny is sticky. (Matches the org-admin intuition: "if my org admin says no Slack posting, the team admin can't override that".)
- **`retrieval_config` numeric keys**: higher layer's explicit value overrides. No averaging.
- **Importance weight overrides**: dict-merge by key, higher layer wins per-key.

### 6.5 Caching

In-process LRU per worker, keyed by:

```
(organization_id, agent_type, agent_profile_id or slug, team_id, category_id, meeting_id)
```

Cache value: `(epoch_seen, ResolvedAgentConfig)`.

Cache invalidation:
- **Epoch check on every cache hit.** Read `agent_config_epochs.epoch` for `(org_id, agent_profile_id)`. If `epoch > epoch_seen`, evict and recompute. The epoch read is a single small indexed SELECT (~0.2ms); we accept it as the price of correctness across workers.
- **TTL**: 60 seconds absolute, so even with no publishes the cache eventually re-evaluates (handles things like new teams getting added).
- **Capacity**: 2048 entries per worker. LFU-ish (use `functools.lru_cache` with maxsize, or `cachetools.TTLCache` — we'll pick `cachetools` for the explicit TTL behavior).

**Stampede protection**: per-key `threading.Lock` (or `asyncio.Lock` in async path). On miss, one thread computes; others wait on the lock and pick up the new entry. Bounded.

**Settings:**
- `AGENT_RESOLVER_CACHE_TTL_S` — default 60
- `AGENT_RESOLVER_CACHE_SIZE` — default 2048
- `AGENT_RESOLVER_EPOCH_CHECK_EVERY_HIT` — default true (turn off in load tests if needed)

### 6.6 Database query strategy

The naive read is 5 separate queries (one per layer). Replaced with a single query:

```sql
SELECT
    apc.scope_type,
    apc.scope_id,
    pv.id              AS version_id,
    pv.version_number,
    pv.modular_prompt_json,
    pv.retrieval_config_json,
    pv.model_config_json,
    pv.tool_permissions_json,
    pv.label
FROM agent_prompt_configs apc
JOIN prompt_versions pv ON pv.id = apc.active_version_id
WHERE apc.status = 'active'
  AND pv.state  = 'published'
  AND apc.agent_profile_id = :agent_profile_id
  AND (
       (apc.organization_id = :org_id)
    OR (apc.organization_id = :global_org_id AND apc.scope_type = 'organization')
  )
  AND (
       (apc.scope_type = 'organization')
    OR (apc.scope_type = 'category' AND apc.scope_id = :category_id)
    OR (apc.scope_type = 'team'     AND apc.scope_id = :team_id)
  )
ORDER BY
  CASE apc.scope_type
    WHEN 'team'         THEN 1
    WHEN 'category'     THEN 2
    WHEN 'organization' THEN
      CASE WHEN apc.organization_id = :global_org_id THEN 4 ELSE 3 END
  END
```

One indexed query. The composite index on `(organization_id, agent_profile_id, scope_type, scope_id) WHERE status='active'` makes this O(layers) seek — ≤ 5 rows back. Then the merge runs in Python in microseconds.

Resolver target latency:
- Cache hit: < 1ms (epoch SELECT + dict lookup)
- Cache miss: < 10ms p95 (one SQL + composition)
- Total resolver overhead per `/rag/ask` is invisible next to retrieval (~hundreds of ms) and synthesis (seconds).

### 6.7 Service boundaries

```
app/services/agents/
    __init__.py
    resolver.py         # resolve_agent_runtime_config + ResolvedAgentConfig + cache
    composition.py      # compose_system_message + interpolate_variables
    cache.py            # thin wrapper over cachetools.TTLCache + per-key locks
    publish.py          # draft → published, rollback, validation, advisory lock
    diff.py             # version-vs-version diff for UI
    playground.py       # sandbox runner (calls into retrieval+synth with is_test=True)
    seed_defaults.py    # 7D one-shot script: split filesystem v1.txt → modular sections → seed global-default prompt_versions
    eval_gate.py        # 7H: integrate Phase 5F harness
```

The resolver is pure-Python and pure-DB; it never calls an LLM, never calls retrieval, never touches the embedder. That stays the responsibility of `ask_stream` / `plan_query` / `synthesize_stream`, which receive the resolved config.

---

## 7. Tool permission system

Today no agent has tool access (the RAG runtime is read-only knowledge retrieval). This is forward-looking but the scaffolding ships now so future tool-using agents (live copilot, autonomous workflows) have a clean enforcement path.

### 7.1 Tool registry

`app/services/tools/registry.py` — a module-level dict mapping `tool_id → ToolDescriptor`:

```text
ToolDescriptor:
    tool_id: str         # e.g. "web_search", "crm_lookup", "calendar_write", "slack_post", "task_create", "doc_upload"
    display_name: str
    description: str
    handler: Callable    # the actual implementation
    schema: pydantic     # arg schema
    cost_class: str      # free | low | high — for cost analytics
    side_effecting: bool # true if it mutates external state
```

Phase 7 ships the registry **empty** plus three stub descriptors (`web_search`, `crm_lookup`, `slack_post`) with `handler` set to a "not implemented" raise. Subsequent phases register real handlers.

### 7.2 Enforcement helper

`app/services/tools/permissions.py:enforce_tool_permission(resolved_config, tool_id)`:

- raises `PermissionDeniedError` if `tool_id ∈ resolved_config.tool_permissions.denied`
- raises `PermissionDeniedError` if `tool_id ∉ resolved_config.tool_permissions.allowed`
- otherwise returns the `ToolDescriptor`

Every call site that invokes a tool MUST go through this helper. We add a `# enforce_tool_permission required` lint comment to the registry and a `tests/test_phase7g_tool_enforcement.py` that grep-asserts.

### 7.3 Extensibility

New tools register themselves at import time (`registry.register(...)`). The dashboard surfaces them in the prompt editor's "Tool Permissions" tab automatically — no UI code changes needed.

---

## 8. Versioning system

### 8.1 Lifecycle

```
       create
draft  ───────►  draft
  │
  │ edit (allowed)
  │
  ▼ publish
published
  │
  │ rollback (selects a different published version as active)
  │
  ▼ archive (manual)
archived
```

Transitions:
- `draft → published` — via `POST /prompt-configs/{id}/publish/{version_id}`. Validates: required sections present, all variables in declared schema, retrieval_config bounds, model_config sanity. If `eval_gate_required` on the profile, runs eval first; if score < threshold, transition refused, `prompt_deployments.action='eval_gate_failed'` row written.
- `published → archived` — via `POST /prompt-configs/{id}/versions/{version_id}/archive`. Refused if version is currently active. (Must rollback first.)
- `archived → published` — not allowed. Re-publishing means cloning to a new draft.
- `draft → archived` — allowed, frees the slot.

### 8.2 Publish semantics

Inside one transaction:

1. Acquire advisory lock `pg_advisory_xact_lock(hash(org_id, agent_prompt_config_id))`.
2. Re-read the `prompt_versions` row; assert `state='draft'`.
3. Run validators (required sections, variables, bounds).
4. If `eval_gate_required`: run eval; on fail, write `prompt_deployments(action='eval_gate_failed')` and abort.
5. UPDATE `prompt_versions` SET state='published', published_at=now(), published_by=actor, eval_score=...
6. UPDATE `agent_prompt_configs` SET active_version_id=version.id
7. INSERT `prompt_deployments(action='publish', from_version_id=<prev active>, to_version_id=version.id, ...)`
8. UPDATE `agent_config_epochs` SET epoch=epoch+1 (or INSERT if not exists)
9. COMMIT.

After commit: fire-and-forget Celery task `propagate_agent_config_invalidation(org_id)` which publishes a Redis message that workers can subscribe to for immediate cache eviction (optional optimization; epoch check already correct).

### 8.3 Rollback semantics

Identical to publish, but `from_version_id` is the current active and `to_version_id` is an older `published` version (selectable in UI from the version history). The "from" version stays `published` (it's just no longer active). Rolling back is reversible — there's no destructive op.

### 8.4 Safety constraints

- Cannot rollback to a `draft` or `archived` version.
- Cannot delete a `published` version (HTTP layer rejects `DELETE`).
- Cannot edit a `published` version (DB trigger + service-layer check).
- Cannot publish a draft whose `agent_prompt_config.status='archived'`.
- Cannot publish into a config whose `agent_profile.status='archived'`.

### 8.5 Diff

`app/services/agents/diff.py:diff_versions(version_a_id, version_b_id) → VersionDiff`:

```text
VersionDiff:
    modular_prompt_diff: dict[section_name, {a: str, b: str, unified_diff: str}]
    retrieval_config_diff: dict[key, {a, b}]
    model_config_diff: dict[key, {a, b}]
    tool_permissions_diff: {added: [...], removed: [...]}
    variables_schema_diff: ...
```

Renders unified-diff text per modular section so the UI can show line-level highlights.

---

## 9. Playground / Sandbox

The most subtle part of the design. Real retrieval, fake everything else.

### 9.1 Goals

- Admin types a query, picks (or builds inline) a config, and gets back: assembled prompt preview, retrieved chunks, citations, answer, token counts, latencies.
- Comparisons between configs side-by-side.
- Zero pollution of production observability: no `rag_query_runs` row, no `rag_chunk_access_events`, no `rag_citation_click_events`, no conversation touch, no importance signal.

### 9.2 Architecture

`POST /agent-playground/run` accepts:

```text
{
  "query_text": str,
  "scope_type": "organization" | "category" | "team",
  "scope_id":   int | null,
  "configs": [                    # 1 or 2 entries — second enables side-by-side
    {
      "mode": "saved_version" | "inline_draft" | "freeform",
      "prompt_version_id": UUID | null,      # for saved_version
      "agent_prompt_config_id": UUID | null, # for inline_draft
      "inline_overrides": {                  # for inline_draft / freeform
        "modular_prompt": { ... 8 sections ... },
        "retrieval_config": { ... },
        "model_config": { ... },
        "tool_permissions": { ... }
      }
    }
  ],
  "simulated_user_id": UUID | null
}
```

Internally:

1. For each config, construct a `ResolvedAgentConfig` directly (bypassing DB resolution for inline modes).
2. Call a *new* function `run_playground(...)` in `app/services/agents/playground.py` which is structurally identical to `ask_stream` but:
   - Pulls real retrieval from the real DB.
   - Calls the real LLM.
   - Writes ONE row to `prompt_test_runs`.
   - Does NOT write to `rag_query_runs`.
   - Does NOT call `log_chunk_events_batch`.
   - Does NOT touch any conversation.
3. Stream events back over SSE (same shape as `/rag/ask`).
4. If `configs` has 2 entries: run both via `asyncio.gather`; emit interleaved events with a `config_index` field.

### 9.3 What admins see

- **Assembled prompt preview** — the exact system+user messages that will go to the LLM, with all variables interpolated.
- **Retrieval inspector** — every chunk, with its `retrieval_reasons` (vector, anchor, expansion, etc.), `retrieval_stage_scores`, and `final_score`. Mirrors the existing `retrieval_bundle` debug shape.
- **Citation inspector** — which citations the LLM emitted, which were missing, which were bogus.
- **Latency breakdown** — planner / retrieval / synth ms.
- **Token / cost** — input + output tokens; cost computed from the model's price table (see §11).

### 9.4 Isolation guarantees

Three tests in `tests/test_phase7e.py`:

- `test_playground_does_not_write_query_run` — count before/after.
- `test_playground_does_not_log_access_events` — count before/after.
- `test_playground_does_not_touch_conversation` — `RagConversation.updated_at` unchanged.

---

## 10. Observability integration

Extend, don't fork.

### 10.1 New endpoints on `observability_router`

(All filter by `organization_id`. All accept `?since=ISO` / `?until=ISO`.)

| Endpoint | Returns |
|---|---|
| `GET /rag/observability/agents` | List agent_profiles with last-30d usage rollup |
| `GET /rag/observability/agents/{profile_id}` | One profile's metrics: calls, latency p50/p95, no_context rate, citation density, token spend |
| `GET /rag/observability/agents/{profile_id}/versions` | Per-version metrics — usage + performance + cost since publish |
| `GET /rag/observability/agents/{profile_id}/versions/{v_id}/runs` | Recent `rag_query_runs` for this version (paginated) |
| `GET /rag/observability/deployments` | `prompt_deployments` feed (paginated) |
| `GET /rag/observability/resolution-distribution` | Distinct `resolved_config_hash` counts last 24h — how many distinct configs ran |

### 10.2 Metric definitions

- **Success rate** = `count(status='completed') / count(*)`
- **No-context rate** = `count(status='no_context') / count(*)` (higher = retrieval not finding answers; tune retrieval_config or write better content)
- **Citation density** = `avg(jsonb_array_length(citations))` (proxy for grounding strength)
- **Hallucination indicator** = `avg(retrieved_chunks - jsonb_array_length(citations))` — chunks retrieved but not cited. Not a hard signal but a screening one.
- **Latency** = p50/p95 of `total_duration_ms`
- **Token spend** = sum(input_tokens) and sum(output_tokens) × per-model price
- **Cost analysis** = token spend grouped by `agent_profile_id` and `prompt_version_id`
- **Retrieval quality** = avg `len(citations) / top_k_final` — how well the rerank pulls cite-worthy chunks
- **Per-version performance** = same metrics scoped to `prompt_version_id`

### 10.3 Aggregation

Daily Celery beat task `aggregate_agent_performance_daily` (Phase 7F) materializes a small `agent_performance_daily` table:

| Column | Type |
|---|---|
| `organization_id` | UUID |
| `agent_profile_id` | UUID |
| `prompt_version_id` | UUID nullable |
| `bucket_date` | date |
| `runs_total` / `runs_completed` / `runs_no_context` / `runs_failed` | int |
| `avg_total_duration_ms` / `p95_total_duration_ms` | int |
| `sum_input_tokens` / `sum_output_tokens` | bigint |
| `avg_citation_count` / `avg_chunks_retrieved` | float |
| `distinct_users` | int |

PK = (org_id, agent_profile_id, prompt_version_id, bucket_date). Built from `rag_query_runs`. Idempotent rebuild for yesterday's data.

This is the data layer behind the UI's Analytics panel — same pattern as the existing Phase 6E rollups.

### 10.4 Price table

Stored in `app/services/agents/pricing.py` as a small dict keyed by model name. Falls back to a default of zero (so cost charts show "unknown" instead of crashing). Admin-overridable via a future settings row.

---

## 11. API design

All endpoints are org-scoped (read `current_user.organization_id`). All write endpoints require `prompt_editor` or `org_admin` role.

### 11.1 Agent management

| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/agents` | — | viewer |
| GET | `/agents/{id}` | — | viewer |
| POST | `/agents` | `{slug, display_name, description, agent_type, default_modular_prompt_json?, eval_gate_required?, eval_fixture_set_id?, eval_min_score?}` | prompt_editor |
| PATCH | `/agents/{id}` | partial | prompt_editor |
| POST | `/agents/{id}/archive` | — | org_admin |
| POST | `/agents/{id}/duplicate` | `{new_slug, new_display_name}` | prompt_editor |
| GET | `/agents/types` | — | viewer | (returns enum of supported agent_types — drives UI dropdown) |

### 11.2 Prompt configs and versions

| Method | Path | Body |
|---|---|---|
| GET | `/prompt-configs?agent_profile_id=...` | — |
| POST | `/prompt-configs` | `{agent_profile_id, scope_type, scope_id?}` — creates an empty config binding |
| GET | `/prompt-configs/{id}` | — | returns config + version list summary |
| DELETE | `/prompt-configs/{id}` | — | soft-archive; refused if any published version |
| GET | `/prompt-configs/{id}/versions` | — | paginated |
| POST | `/prompt-configs/{id}/versions` | `{label?, modular_prompt, variables_schema, retrieval_config, model_config, tool_permissions}` — creates a draft |
| PATCH | `/prompt-configs/{id}/versions/{v_id}` | partial — only allowed when `state='draft'` |
| POST | `/prompt-configs/{id}/versions/{v_id}/publish` | `{reason?}` |
| POST | `/prompt-configs/{id}/rollback` | `{to_version_id, reason?}` |
| POST | `/prompt-configs/{id}/versions/{v_id}/archive` | — |
| GET | `/prompt-configs/{id}/versions/{v_id}/diff?against={other_v_id}` | — |

### 11.3 Playground

| Method | Path | Body |
|---|---|---|
| POST | `/agent-playground/run` | (see §9.2) — streams SSE |
| GET | `/agent-playground/history` | recent `prompt_test_runs` (paginated) |
| GET | `/agent-playground/history/{run_id}` | full detail incl. assembled_prompt_text |

### 11.4 Runtime resolution (debug/admin)

| Method | Path | Body |
|---|---|---|
| GET | `/agent-runtime-config` | query params: `agent_type`, `agent_profile_slug?`, `team_id?`, `category_id?` — returns the `ResolvedAgentConfig` JSON. Useful for "why is my prompt acting weird" debugging. Org_admin only. |

### 11.5 Validation rules

- All bodies validated by Pydantic models in `app/schemas/agent_api_schema.py`.
- Strict envelope, lenient row validation — same convention as Phase 5's `rag_api_schema.py`.
- All write endpoints rate-limited via the existing `app/middleware/rate_limit.py` (if present; otherwise add per-org sliding window).

### 11.6 Pagination / filtering

- Cursor pagination on list endpoints (created_at + id), max 100/page.
- Filters: `?agent_type=`, `?status=`, `?scope_type=`, `?since=`, `?until=`.

### 11.7 Audit requirements

Every write produces a `prompt_deployments` or `agent_audit_events` (Phase 7E adds the latter for non-publish events: profile create/update/archive, config create/delete). Audit is queryable via `GET /rag/observability/deployments`.

---

## 12. UI / dashboard plan

A single new top-level route `/agents`, with subroutes per detail surface.

### 12.1 Routes

```
/agents                              — agents list page
/agents/new                          — create agent profile wizard
/agents/{profile_id}                 — agent detail (overview tab)
    /scopes                          — list of agent_prompt_configs (per-scope bindings)
    /editor                          — prompt editor (drafts + version history)
    /playground                      — sandbox
    /analytics                       — performance metrics
    /settings                        — eval gate, archive, danger zone
```

### 12.2 Agents list page

- Table: `display_name`, `slug`, `agent_type`, `# active scopes`, `last 7d calls`, `last 7d no_context %`.
- Filters: agent_type, status (active/archived).
- Actions: create, duplicate, archive.

### 12.3 Prompt editor

Eight collapsible sections (one per modular slot) with:

- Monaco-based text editor with syntax highlighting for `{{variable}}` tokens.
- Variable autocomplete pulled from the agent_type's allowed-variable list (§4.3).
- Live validation: missing required section → red badge; unknown variable → yellow badge.
- Token estimation: `tiktoken` `cl100k_base` count per section + total estimate of the assembled system message.
- "Inherits from: [layer]" badge — if this scope-level config doesn't override a section, show the value from the next layer up (read-only).
- "Clear at this scope" toggle — sets the section to `""` (explicit override-to-empty).

A side panel shows the **assembled preview** — the full system message as it will be sent, with all variables resolved against a chosen sample scope (default: a random recent meeting in this org).

### 12.4 Retrieval-config editor

A form with all keys from §5.1, each with:
- The value at this scope (or "inherited from {layer}")
- A "reset to inherited" button
- Inline help describing what the knob does
- Live validation against bounds

### 12.5 Tool permissions

A two-column allow/deny picker. Each tool shows: `display_name`, `description`, `cost_class`, `side_effecting?` (a 🔥 icon for side-effecting tools).

### 12.6 Version history

- Vertical timeline of versions, newest first.
- Per row: `version_number`, `label`, `state`, `published_at`, `published_by`, `eval_score`, `runs since publish`.
- Click two versions → opens diff viewer (unified diff per modular section + retrieval_config/model_config/tool_permissions key-level diffs).
- Rollback action surfaces on every `published` version that is not the current active.
- Deployment markers (chevrons in the timeline) show publish/rollback events.

### 12.7 Playground

- Query input (multi-line).
- Config picker — either a saved version or "Edit current draft inline".
- "Run" button.
- Streaming output panel — same SSE event types as `/rag/ask`: `plan`, `retrieved`, `token`, `citations`, `done`.
- Retrieval inspector (collapsible) — full chunk list with reasons + scores.
- Assembled prompt preview (collapsible) — exact text sent to LLM.
- Latency / token / cost summary card.
- "Compare with" button → opens a second column with a different config; both run on the same query.

### 12.8 Analytics

- Per-agent / per-version performance charts (built on `agent_performance_daily`):
  - Runs over time, stacked by status
  - p50/p95 latency
  - No-context rate
  - Token spend / cost
  - Citation density
- Version comparison: pick two versions, see the metrics side-by-side over an overlapping window.

### 12.9 Implementation stack

Same as existing frontend:
- React 18, Vite, TypeScript, React Router
- Monaco editor for prompt sections
- Recharts (already used elsewhere) for analytics
- Manual SSE parser (already in place — `useChatStream` pattern from Phase 5E)
- Shared `apiClient.ts` with 401 redirect behavior

Module path: `meeting_ai_frontend/src/features/agents/...` mirroring `features/ask/`.

---

## 13. Celery + background tasks

Add `app/celery_tasks/agent_tasks.py` and register it in `app/celery_app.py`'s `include` list (same convention as Phase 6 tasks).

### 13.1 Tasks

| Task | Trigger | Purpose |
|---|---|---|
| `propagate_agent_config_invalidation(org_id, agent_profile_id)` | fired on publish/rollback | publishes a Redis pub/sub message; workers subscribe and proactively evict their LRU. Optional optimization on top of epoch correctness. |
| `aggregate_agent_performance_daily()` | beat-scheduled (e.g. 03:00 UTC daily) | rebuilds `agent_performance_daily` for yesterday |
| `run_eval_for_prompt_version(version_id, fixture_set_id, requested_by)` | manual from UI, or auto on publish if `eval_gate_required` | runs the Phase 5F harness; updates `prompt_versions.eval_score` and `eval_run_id` |
| `seed_default_agents_for_org(org_id)` | fired on org creation (hook into existing org-create flow) | creates the four default profiles (`rag_synth`, `rag_planner`, `graph_extractor`, `transcript_analyzer`), each bound to one `organization`-scoped config with a published v1 sourced from the filesystem |
| `cleanup_orphan_drafts(days=30)` | beat-scheduled weekly | archives draft versions older than 30 days with no edits |

### 13.2 Beat schedule additions

Append to `app/celery_app.py:beat_schedule`:

```text
'aggregate_agent_performance_daily': {'task': '...', 'schedule': crontab(hour=3, minute=0)},
'cleanup_orphan_drafts':             {'task': '...', 'schedule': crontab(day_of_week=0, hour=4)},
```

### 13.3 Dependencies on existing infra

- Redis (broker + pub/sub) — already deployed.
- Celery beat — already running (Phase 6 schedule established).
- The eval harness (`tests/eval_phase5/`) — already exists; `run_eval_for_prompt_version` is a thin wrapper that targets a fixture set + a config rather than the filesystem default.

---

## 14. Security + governance

### 14.1 Roles

Today `User.role` is a single text column. Phase 7E formalizes three values:

- `viewer` — can view agents, configs, versions, analytics; cannot edit.
- `prompt_editor` — viewer + can create/edit drafts, publish, rollback.
- `org_admin` — prompt_editor + can archive profiles, manage eval gates, view audit log.

If the existing role system is more granular, we **layer on top** instead of replacing: add a `prompt_role` column or a join table `user_org_prompt_roles`. Decision deferred to 7E based on what's already wired in `app/services/auth_service.py`.

### 14.2 Tenant isolation

- Every endpoint reads `current_user.organization_id` from JWT and uses it as the filter.
- A 404 (not 403) is returned for cross-org access — same convention as existing routers.
- The platform-owner org (global defaults) is read-only via API for non-platform users — they see resolved values via `/agent-runtime-config`, not the underlying configs.

### 14.3 Audit log

Two audit surfaces:

- `prompt_deployments` — all publish/rollback events (already-required by §3.4).
- `agent_audit_events` (new in 7E) — non-publish mutations (profile create/update/archive, config create/delete, eval-gate config changes). Schema mirrors `prompt_deployments`. Append-only, BIGSERIAL.

### 14.4 Rollback protections

- Cannot delete published versions.
- Cannot rollback to draft/archived.
- Cannot rollback if the target version's `model_config.model` is no longer a supported model (e.g. a model was retired). Block with explicit error.
- Rate-limit publish to 10/hour/org-admin (prevent oscillation).

### 14.5 Secret / tool safety

- Tool registry entries marked `side_effecting: true` (e.g. `slack_post`, `task_create`) require a *second confirmation* in the UI to add to allowed list.
- `tool_permissions.allowed` cannot contain a `side_effecting` tool unless the agent_profile has `tools_allow_side_effects: true` (a flag on the profile). This is a defense in depth.
- Secret values (API keys for tools) are stored in the existing secrets infra (settings + env vars, plus `secrets_table` if it exists). They are NEVER on `tool_permissions_json` — that table only carries the *permission* to use a tool, never the key to use it.

### 14.6 Cross-org leak prevention in cache

The resolver cache key includes `organization_id`. Cache poisoning across orgs is structurally impossible. A test asserts this (`test_resolver_cache_isolation_across_orgs`).

---

## 15. Performance considerations

### 15.1 Latency budget

The resolver adds at most ~10ms to the start of an `/rag/ask` call (cache miss path); cache-hit path is well under a millisecond. Compared to retrieval (~100–500ms) and synth (~1–3s), this is invisible.

### 15.2 Cache sizing

A typical org will have ≤ 50 distinct `(agent_profile, scope)` combinations. The 2048-entry LRU comfortably covers ~40 orgs per worker, which matches realistic worker→tenant ratios.

### 15.3 Query optimization

The single composed SQL in §6.6 plus the supporting partial index keeps resolution at one indexed seek + ≤5 rows back. The index:

```sql
CREATE INDEX ix_agent_prompt_configs_resolution
ON agent_prompt_configs (organization_id, agent_profile_id, scope_type, scope_id)
WHERE status = 'active';
```

### 15.4 Prompt assembly

`composition.compose_system_message` does `n` string `.replace()` calls and one `\n\n`.join. Sub-millisecond. We avoid Jinja, which would parse-then-render every call.

### 15.5 Memoization

Within a single Celery task or HTTP request, the same `(org, profile, scope)` resolution can be called multiple times (e.g. once for the planner, once for the synth, both for the same conversation turn). We memoize on the Python-thread / asyncio task using `contextvars`, so a single `/rag/ask` does *one* DB read max.

### 15.6 Scale concerns

- **Many small orgs** — fine. Cache is small per-org.
- **Few huge orgs with many teams** — the cache key includes `team_id`; a single org with 500 teams hitting all profiles fills the cache. We bump cache size to 8192 in those deployments via settings.
- **High publish frequency** — the advisory-lock in publish serializes per-config. Epoch bumps are cheap. No global contention.
- **Hot agent profile** (e.g. one used by 100k req/hour) — cache hits dominate; resolver is invisible. Worker count scales with HTTP load, not resolver load.

### 15.7 Drift in cache vs DB

The epoch-on-every-hit policy means stale-read window = 0 (a publish that commits before a request starts will be seen by that request, *if the resolver re-runs after publish commit*). For request-mid-flight: not affected because resolver runs once at the start of `/rag/ask`. There is no resolver-mid-flight invalidation path; we accept that a single in-flight request can use a soon-to-be-stale config. That's fine for prompts.

---

## 16. Phased implementation plan

Same shape as Phase 5 / Phase 6: each slice = migration (if any) + models + service + HTTP/CLI surface + ship test + regression sweep. Each slice independently mergeable. Order is engineered so the runtime never breaks: shadow-mode lands before live consumption.

### Phase 7A — Profiles, scoped bindings, epoch table

- **Schema:** `agent_profiles`, `agent_prompt_configs`, `agent_config_epochs`. Indexes incl. soft-active uniques.
- **Models:** `AgentProfile`, `AgentPromptConfig`, `AgentConfigEpoch` in `app/db/models.py`.
- **Schemas:** `app/schemas/agent_schema.py` (internal), `app/schemas/agent_api_schema.py` (HTTP).
- **Services:** None yet beyond CRUD repositories.
- **APIs:** `/agents` full CRUD (list, get, create, patch, archive, duplicate, types). `/prompt-configs` (create, list, delete-soft).
- **Tests:** `tests/test_phase7a.py` — CRUD round-trips, scope-uniqueness, archive→re-create, cross-org isolation.
- **Observability:** none yet.
- **Risks:** unique-index migration on existing tables — N/A (new tables).
- **Dependencies:** none beyond Phase 1.

### Phase 7B — Versions, publish flow, deployment audit

- **Schema:** `prompt_versions`, `prompt_deployments`. Trigger blocking UPDATE on published rows.
- **Models:** `PromptVersion`, `PromptDeployment`.
- **Services:** `app/services/agents/publish.py` (draft→published, rollback, validation). `app/services/agents/diff.py`.
- **APIs:** version CRUD, publish, rollback, archive, diff endpoints.
- **Tests:** `tests/test_phase7b.py` — create draft, publish, can't edit published, rollback, diff. Includes `test_publish_validates_required_sections`, `test_rollback_refuses_draft_target`, `test_concurrent_publish_serialized`.
- **Observability:** the existing `prompt_deployments` table acts as the source of truth; no new endpoints yet.
- **Risks:** the immutability trigger needs careful CHECK syntax; we test by hand on a scratch DB before migrating.
- **Dependencies:** 7A.

### Phase 7C — Runtime resolver in shadow mode

- **Schema:** `agent_runtime_logs`; add `agent_profile_id`, `prompt_version_id`, `resolution_path_hash` to `rag_query_runs`.
- **Models:** `AgentRuntimeLog`.
- **Services:** `app/services/agents/resolver.py`, `app/services/agents/cache.py`, `app/services/agents/composition.py`.
- **Wiring:** `ask_stream` calls the resolver but **does not yet consume** the resolved config — it logs the resolution to `agent_runtime_logs` and proceeds with the existing filesystem prompts / settings. This is shadow mode: we generate observability data for a release cycle before flipping the switch.
- **APIs:** `GET /agent-runtime-config` (debug).
- **Tests:** `tests/test_phase7c.py` — resolver precedence (6 layers), cache hit/miss, epoch invalidation, isolation, fallback to filesystem when nothing in DB.
- **Observability:** new endpoints `GET /rag/observability/resolution-distribution`.
- **Risks:** the SQL query in §6.6 needs the EXPLAIN ANALYZE check on realistic data; verify the partial index is used.
- **Dependencies:** 7B.

### Phase 7D — Live consumption + filesystem→DB migration

- **Schema:** none.
- **Services:** `app/services/agents/seed_defaults.py` — one-shot script that:
  1. Reads `app/ai_agents/prompts/rag/synth/v1.txt` and `planner/v1.txt`.
  2. Splits each into the 8 modular sections by recognizing section markers (we add comment markers to the existing files first: `# === SECTION:system ===`, etc., as a non-breaking edit).
  3. Creates `rag_synth` and `rag_planner` agent profiles in the platform-owner org.
  4. Creates one `organization`-scoped `agent_prompt_config` per profile.
  5. Creates a `prompt_versions` row v1, published, sourced from the filesystem.
  6. Idempotent — running twice is a no-op.
- **Wiring:** `ask_stream`, `plan_query`, `synthesize_stream` now consume `resolved_config.modular_prompts` to build their LLM payloads. The composition function (§6.2) replaces the current `.replace()`-on-template approach. Filesystem load remains the final fallback (Layer 6) for the case where seed hasn't run.
- **Backward compat:** a brand-new install with no `prompt_versions` rows runs identically to today, by falling through all DB layers to the filesystem floor. Verified by `test_phase7d_unseeded_org_matches_filesystem_baseline`.
- **APIs:** none new.
- **Tests:** `tests/test_phase7d.py` — full end-to-end through `/rag/ask` proving:
  - Pre-seed: behavior matches Phase 6 baseline.
  - Post-seed: behavior bit-equal to pre-seed for the default config.
  - With an org-level override: behavior changes as expected.
  - With a team-level override stacking on org: team value wins, org fills missing sections.
- **Risks:** the migration script is one-shot and must be perfectly idempotent. We add a guard column `seeded_from_filesystem: bool` on `prompt_versions` to detect prior seeds.
- **Dependencies:** 7C.

### Phase 7E — Playground + RBAC + audit-events

- **Schema:** `prompt_test_runs`, `agent_audit_events`.
- **Models:** corresponding.
- **Services:** `app/services/agents/playground.py`.
- **APIs:** `POST /agent-playground/run` (SSE), `GET /agent-playground/history`, `GET /agent-playground/history/{id}`. RBAC enforcement on all write endpoints across 7A–7D (lift the centralized check helper).
- **Tests:** `tests/test_phase7e.py` — playground does not pollute `rag_query_runs` / access events / conversations; RBAC viewer can't publish; side-by-side comparison runs both configs.
- **Observability:** none.
- **Risks:** SSE response generator must be carefully tested under disconnect (manual SSE pattern from Phase 5E).
- **Dependencies:** 7D.

### Phase 7F — Observability + analytics aggregation

- **Schema:** `agent_performance_daily`.
- **Services:** `app/services/agents/analytics.py` (read-only rollup queries). Celery task `aggregate_agent_performance_daily`.
- **APIs:** all `/rag/observability/agents/*` endpoints. `GET /rag/observability/deployments`.
- **Tests:** `tests/test_phase7f.py` — daily rollup correctness, query-time aggregation correctness, per-version metrics, deployments feed pagination.
- **Observability:** this IS the observability slice.
- **Risks:** large `rag_query_runs` tables (post-Phase-5 production) require the rollup to be incremental, not full-scan.
- **Dependencies:** 7E.

### Phase 7G — Frontend dashboard

- **Schema:** none.
- **APIs:** none new.
- **UI:** All routes from §12. Built feature-by-feature: list → editor → versions → playground → analytics.
- **Tests:** ship tests are visual / manual + a small set of frontend integration tests on the editor's validation behavior. Backend regression sweep unchanged.
- **Risks:** Monaco bundle size — we lazy-load the editor.
- **Dependencies:** 7F.

### Phase 7H — Tool registry stub + eval-gated publish

- **Schema:** none.
- **Services:** `app/services/tools/registry.py`, `app/services/tools/permissions.py`, `app/services/agents/eval_gate.py`.
- **APIs:** `POST /agents/{id}/eval/run` (manual trigger), `GET /agents/{id}/eval/runs`.
- **Wiring:** `publish_version` calls into `eval_gate.run_if_required(profile, version)`. Failure produces `prompt_deployments.action='eval_gate_failed'` and refuses publish.
- **Tests:** `tests/test_phase7h.py` — eval gate blocks publish; eval pass allows publish; tool enforcement raises PermissionDeniedError when not allowed.
- **Risks:** the Phase 5F eval harness must be callable as a library, not just a CLI. May require a small refactor of `tests/eval_phase5/` into `app/services/agents/eval_runner.py`.
- **Dependencies:** 7G optional (UI surface is nice-to-have, the gate works without it).

### Sequencing rationale

Shadow-mode (7C) before consumption (7D) is the most important order rule: it gives us a release cycle where we can see *what* the resolver would have done in production without any production behavior change. If 7C reveals bugs (wrong precedence, slow cache, schema gaps), we fix them with zero user impact.

Playground (7E) before observability (7F) because the playground is what makes analytics useful — admins won't trust prompt changes until they can preview them.

UI (7G) last among the "build" slices so backend APIs are stable before the frontend wraps them.

---

## 17. Testing strategy

### 17.1 Unit tests

| Module | Tests |
|---|---|
| `resolver.py` | precedence (6 layers in every permutation); empty-string-clears-vs-omitted; tool deny-overrides-allow; cache hit returns same object; cache miss after epoch bump; warnings on unresolved variables |
| `composition.py` | each variable interpolation; HTML-escape on user inputs; missing variable yields placeholder; empty section omits cleanly |
| `publish.py` | required-section validation; variable-schema validation; retrieval-bound validation; advisory lock serializes concurrent publishes; rollback refuses non-published targets |
| `diff.py` | per-section unified diff; tool permission diff add/remove; key-level retrieval diff |
| `cache.py` | TTL expiry; per-key lock prevents stampede; epoch bump evicts |
| `playground.py` | inline-override resolver; isolation guarantees |

### 17.2 Integration tests

- Full `/rag/ask` flow with a team-level prompt override → verify `agent_runtime_logs` row, verify `rag_query_runs.prompt_version_id` populated, verify answer reflects the override.
- Publish → next request uses new version. Time the gap (should be < 100ms epoch-detection).
- Rollback → next request reverts.
- Two concurrent publishes serialize.
- Cross-org request never sees other org's configs.

### 17.3 End-to-end tests

- Onboard a new org → defaults seeded → ask works identically to today.
- Customize an agent at org → category → team → ask in scope=team → all three layers contribute as expected.
- Playground run → no `rag_query_runs` row, no access event.
- RBAC viewer attempts publish → 403.
- Eval-gated publish below threshold → blocked.

### 17.4 Performance tests

- 1000 cache-hit resolves: target < 100ms total.
- 1000 cache-miss resolves (cold cache): target < 5s total.
- 100 concurrent publishes against the same config: all serialize without deadlock; total time < 2s.
- One `/rag/ask` p95 latency overhead vs Phase 6 baseline: < 15ms.

### 17.5 Eval gating (Phase 5F integration)

- Run the existing canonical-org fixture set against the seeded default config — expect identical Phase 5F scores to today (the seed is bit-equal to filesystem).
- Run against a deliberately-bad override (empty `retrieval` section, no citation rules) — expect a measurable score drop; this validates the eval surface for the dashboard.

### 17.6 Regression sweep

After every slice, run the full 288-test suite. Phase 7A–7C must not change any pre-existing test's outcome. Phase 7D may shift specific Phase 5/6 tests by zero or one assertion if and only if those tests asserted against `settings.RAG_*` env vars directly — those tests get updated to assert against the resolved-config layer instead. Net test count grows monotonically.

---

## 18. Risks and edge cases

| Risk | Mitigation |
|---|---|
| Resolver precedence subtly wrong | Exhaustive precedence test in 7C with all 64 combinations of which layers are present |
| Cache stale across workers | Epoch table + per-hit epoch check; tested |
| Publish race condition | Postgres advisory lock per (org, config); tested |
| Filesystem→DB migration drift | Seed script writes a bit-equal version; eval harness verifies identical score; manual diff on first run |
| Missing variable in published prompt | Publish-time validator catches; runtime falls back to `[var unavailable]` placeholder |
| HTML-injection via interpolated variable | HTML-escape at composition time; tested |
| Prompt-injection via variable contents | Variables are HTML-escaped and inserted into the *system* message only (or the *user* message in the contract template); we follow the same defensive prompt structure as today (the synthesizer already trusts retrieved chunks as context). No new injection surface. |
| Large `rag_query_runs` joins for analytics | Daily rollup table `agent_performance_daily` is the query target; raw table only read for paginated detail pages |
| Eval gate timeout | `run_eval_for_prompt_version` runs in Celery, not in the API thread; publish UI shows "evaluating…" and polls; settings.AGENT_EVAL_TIMEOUT_S |
| Org admin disables retrieval entirely (`top_k_final=0` or `include_archived=true` only) | Validators enforce `top_k_final ≥ 1`; admins can set `entity_expansion_enabled=false` but cannot turn off the vector recall stage |
| Tool permission allow-list bypassed | Single helper `enforce_tool_permission`; lint comment plus `test_tools_always_enforce` that fails if any new tool handler lacks the call |
| Side-effecting tool added via UI typo | Double confirmation in UI; profile-level `tools_allow_side_effects: false` default |
| User loses work by clicking publish on wrong draft | Publish always shows a diff-vs-current-active modal before commit |
| Eval flakiness blocks legitimate publishes | Eval gate has a "force publish" admin override that writes a `forced=true` flag onto `prompt_deployments` |

---

## 19. Folder / module structure (full)

```
alembic/versions/
    g8a1b2c3d4e5_phase7a_agent_profiles_and_configs.py
    h9b2c3d4e5f6_phase7b_prompt_versions.py
    i0c3d4e5f6a7_phase7c_runtime_logs.py
    j1d4e5f6a7b8_phase7e_playground.py

app/
    db/
        models.py                                  # MODIFIED: + 6 new models, + 3 cols on RagQueryRun
    schemas/
        agent_schema.py                            # NEW: internal (ResolvedAgentConfig, RetrievalConfig, ModelConfig, ToolPermissions, ResolutionStep, etc.)
        agent_api_schema.py                        # NEW: HTTP request/response shapes
    services/
        agents/
            __init__.py                            # NEW
            resolver.py                            # NEW
            composition.py                         # NEW
            cache.py                               # NEW
            publish.py                             # NEW
            diff.py                                # NEW
            playground.py                          # NEW
            seed_defaults.py                       # NEW
            analytics.py                           # NEW (7F)
            eval_gate.py                           # NEW (7H)
            pricing.py                             # NEW (7F)
        tools/
            __init__.py                            # NEW
            registry.py                            # NEW
            permissions.py                         # NEW
        rag/
            ask_pipeline.py                        # MODIFIED: accept ResolvedAgentConfig kwarg
            query_planner.py                       # MODIFIED: accept modular prompt sections
            synthesizer.py                         # MODIFIED: accept modular prompt sections + retrieval_config
            retrieval.py                           # MODIFIED: accept retrieval_config kwarg overrides
    api/
        agents_router.py                           # NEW: /agents CRUD
        prompt_configs_router.py                   # NEW: /prompt-configs + versions
        playground_router.py                       # NEW: /agent-playground
        observability_router.py                    # MODIFIED: + agent-aware endpoints
    celery_tasks/
        agent_tasks.py                             # NEW
    celery_app.py                                  # MODIFIED: include + beat additions
    config/
        settings.py                                # MODIFIED: + AGENT_RESOLVER_CACHE_*, AGENT_EVAL_TIMEOUT_S
    scripts/
        seed_default_agents.py                     # NEW: CLI wrapper around seed_defaults.py
        backfill_agent_runtime_logs.py             # NEW: optional, populates resolution-path for old rag_query_runs

meeting_ai_frontend/src/features/agents/          # NEW
    AgentsListPage.tsx
    AgentNewPage.tsx
    AgentDetailLayout.tsx
    tabs/
        OverviewTab.tsx
        ScopesTab.tsx
        EditorTab.tsx
        PlaygroundTab.tsx
        AnalyticsTab.tsx
        SettingsTab.tsx
    editor/
        ModularSectionEditor.tsx
        RetrievalConfigForm.tsx
        ToolPermissionsPicker.tsx
        AssembledPromptPreview.tsx
        VariableAutocomplete.ts
    versions/
        VersionTimeline.tsx
        DiffViewer.tsx
    playground/
        PlaygroundPanel.tsx
        SideBySideCompare.tsx
        RetrievalInspector.tsx
    analytics/
        AnalyticsPanel.tsx
        VersionComparisonChart.tsx
    hooks/
        useAgentList.ts
        useAgentDetail.ts
        usePromptConfig.ts
        useVersionDiff.ts
        usePlaygroundStream.ts
        useAgentAnalytics.ts
    types.ts

tests/
    test_phase7a.py                                # NEW
    test_phase7b.py                                # NEW
    test_phase7c.py                                # NEW
    test_phase7d.py                                # NEW
    test_phase7e.py                                # NEW
    test_phase7f.py                                # NEW
    test_phase7h.py                                # NEW (no 7g — UI-only slice)
    fixtures/
        agent_profiles.py                          # NEW: canonical agent fixtures for the 4 default types

app/ai_agents/prompts/                             # KEPT as the filesystem floor
    rag/
        planner/v1.txt                             # MODIFIED: + section markers for the seed script to split
        synth/v1.txt                               # MODIFIED: + section markers
```

---

## 20. Integration points with existing code (line-level expectations)

These are the touch points where Phase 7 modifies existing files. All edits are additive — existing callers continue to work unchanged.

| File | Change |
|---|---|
| `app/db/models.py` | + 6 new models. + 3 nullable cols on `RagQueryRun`. + `agent_profile_id` Index. |
| `app/services/rag/ask_pipeline.py:ask_stream` | + `resolved_config: ResolvedAgentConfig \| None = None` kwarg. + a single `resolve_agent_runtime_config(...)` call at function top if not supplied. Pass through to `retrieve()` and `synthesize_stream()`. |
| `app/services/rag/retrieval.py:retrieve` | + `retrieval_config: RetrievalConfig \| None = None` kwarg. Replace every `settings.RAG_*` read with `(retrieval_config.* if supplied else settings.*)`. |
| `app/services/rag/query_planner.py:plan_query` | + `modular_prompts: dict \| None = None` kwarg. Pass to `_render_prompt` which now uses modular composition if supplied; else current behavior. |
| `app/services/rag/synthesizer.py:synthesize_stream` | + `modular_prompts: dict \| None = None`, `model_config: ModelConfig \| None = None`. Compose the system message accordingly. |
| `app/api/rag_router.py:/rag/ask` | + optional `agent_profile_slug` query param; passes to `ask_stream` via the resolver. |
| `app/config/settings.py` | + `AGENT_RESOLVER_CACHE_TTL_S=60`, `AGENT_RESOLVER_CACHE_SIZE=2048`, `AGENT_EVAL_TIMEOUT_S=120`, `AGENT_DEFAULT_FALLBACK_ENABLED=true`. |
| `app/celery_app.py` | + include `app.celery_tasks.agent_tasks`; + 2 beat entries. |
| `main.py` | + 3 new router includes: `agents_router`, `prompt_configs_router`, `playground_router`. |
| `meeting_ai_frontend/src/app/router.tsx` | + agents route tree. |
| `meeting_ai_frontend/src/shared/components/Sidebar.tsx` | + "Agents" nav item, role-gated. |
| `app/ai_agents/prompts/rag/synth/v1.txt`, `planner/v1.txt` | + non-breaking `# === SECTION:<name> ===` markers so `seed_defaults.py` can split them. Tests verify the post-split composition is bit-equal to the original text. |

---

## 21. Future extensibility (designed for, not built)

| Future capability | Already supported because… |
|---|---|
| Multi-agent orchestration (DAG of agents) | `agent_profiles.agent_type` is open enum; resolver works per agent_type. Add `agent_workflows` table later linking profiles. |
| Autonomous workflows (tools that call tools) | `tool_permissions` + `enforce_tool_permission` already enforce policy at every call site. |
| Workflow builders (UI) | Pure additive UI layer over the same backend. |
| Prompt marketplaces | `prompt_versions` rows are self-contained JSONB; add `is_public`, `forked_from_version_id` columns. Export = pull the row + zip. |
| Enterprise fine-tuning | `model_config_json` is already an opaque dict; supporting a fine-tuned `model_id` is config-only. |
| Evaluation pipelines | `eval_gate` slice (7H) already integrates the Phase 5F harness. Adding new eval dimensions = adding new fixture sets. |
| Human approval flows | `prompt_versions.state` can grow `pending_approval`; add `approvals` table referencing version_id + reviewer. Resolver continues to read state='published'. |
| Cross-org template sharing | `prompt_versions.forked_from_version_id` + an `is_template` flag + a copy operation. |
| Per-meeting overrides | Already accounted for: `scope_type='meeting_specific'` slot. Layer 1 in the resolver order. Just adds a column + a CHECK relaxation. |
| Per-user overrides | Add `scope_type='user'` with `scope_uuid=user_id`. Same merge logic. Resolver call adds `user_id` to the cache key. |
| Live in-meeting copilot (former Phase 7) | This becomes Phase 8 and is a thin layer that reads `resolve_agent_runtime_config(agent_type='live_copilot', meeting_id=...)` and runs against a WS transport. The runtime config layer is already done. |

---

## 22. Acceptance criteria for the phase

Phase 7 is "done" when:

1. All 288 existing tests pass. All new Phase 7 tests pass. Net suite: 288 + (~80 expected new tests).
2. Migration head advances to `j1d4e5f6a7b8` after 7E.
3. An org admin can change the synth prompt for a single team without code changes, and the next `/rag/ask` to that team's scope reflects the change within 1 second.
4. The Phase 5F eval harness produces an identical score on the seeded default config as it did against the filesystem `v1.txt` before the migration.
5. `agent_runtime_logs` accumulates at least one row per `/rag/ask` call after 7C ships.
6. The playground demonstrably does not pollute production observability (three isolation tests pass).
7. Rollback is reversible and the deployment audit reconstructs the full history of a config from `prompt_deployments`.
8. The frontend dashboard surfaces all 8 modular sections in the editor with live validation.
9. RBAC: a `viewer` cannot publish, archive, or modify; tested.
10. Resolver p95 overhead measured at < 15ms on a representative `/rag/ask`.

When all 10 are green, Phase 7 ships and Phase 8 (Live in-meeting copilot) begins by consuming `resolve_agent_runtime_config(agent_type='live_copilot', ...)`.

---

## 23. Open questions (for sign-off)

These are the decisions to lock before "go":

1. **RBAC source-of-truth** — does the existing `User.role` column suffice for the three Phase 7 roles, or do we need a `user_org_prompt_roles` join in 7E? (Recommendation: extend `User.role` first; promote to a join table only if a user needs multiple roles in different orgs.)
2. **Platform-owner sentinel org** — confirm the existing setup creates exactly one platform-owner `Organization` row that we can use for global defaults. If not, 7A's migration creates it.
3. **Eval-gate fixture set** — do we reuse `tests/eval_phase5/`'s canonical fixture as the default `eval_fixture_set_id` for `rag_synth`, or do we make a separate, smaller "fast eval" set for the publish path? (Recommendation: separate smaller set, ~10 queries, for fast publish; keep the full set for periodic regression runs.)
4. **Cache invalidation transport** — epoch-only (always correct, ~0.2ms per hit) or epoch + Redis pub/sub (faster on hot path but added moving part)? (Recommendation: epoch-only for Phase 7. Add pub/sub in a later perf slice only if measured needed.)
5. **Importance-scorer profile** — does `agent_type='importance_scorer'` truly need a profile in 7A, or does it land in a later slice when we have an LLM-assisted scorer? (Recommendation: profile lands in 7A as a scaffolding row so `retrieval_config.importance_weight_overrides` has a home; the scorer keeps its deterministic Python implementation but reads weight overrides from the resolver.)
6. **Frontend Monaco vs simpler textarea** — Monaco is heavy. Alternative: a simple `<textarea>` with regex-based `{{var}}` highlighting via CSS. (Recommendation: Monaco for the editor pages, lazy-loaded; plain textarea for the playground inline-overrides.)
7. **Per-meeting overrides timing** — wait until Phase 8 (where they're more useful with live copilot), or land the scope slot in 7A as a CHECK relaxation? (Recommendation: relax the CHECK in 7A so the column space is reserved; populate in Phase 8.)
8. **Default agent_profiles to seed on new org** — exactly which ones? (Recommendation: `rag_synth`, `rag_planner`, `graph_extractor`, `transcript_analyzer`, `summarizer`. Skip `importance_scorer` for now; skip `live_copilot` until Phase 8.)
9. **Tool registry stubs** — do we ship empty in 7H, or pre-populate with three "coming soon" entries (`web_search`, `crm_lookup`, `slack_post`)? (Recommendation: pre-populate three stubs so the UI's tool-permission picker has something to show; flag handler as `raise NotImplementedError`.)

On "go", I'll confirm each of these and proceed with 7A: migration + models + CRUD + ship test, same shape as every prior slice.
