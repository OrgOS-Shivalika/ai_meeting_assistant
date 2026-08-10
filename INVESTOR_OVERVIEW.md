# Agentic Meeting Assistant — Product & Technology Overview

**Document purpose:** a complete technical and product description of the platform for investor diligence.
**Date:** 2026-08-07
**Status of this document:** every capability described below was verified against the source code and the running system. Sections marked `[TO BE SUPPLIED]` require commercial data the engineering record does not contain (traction, revenue, market sizing, team, funding history) and must be completed by the founders before circulation.

---

## 1. Executive summary

The Agentic Meeting Assistant is an **organizational memory and execution layer for meetings**. It joins a company's video calls as a participant, transcribes and understands them in real time, speaks a closing summary aloud before the call ends, and then converts the conversation into durable, queryable organizational knowledge — decisions, commitments, owners, risks and tasks — that persists and compounds across every future meeting.

It is not a note-taker. Three things distinguish it:

1. **It participates.** The assistant can be addressed by voice mid-meeting (*"iris, summarize this"*) and will speak a spoken recap into the call, then leave. Most competitors deliver a document after the fact.
2. **It remembers across meetings.** A distilled long-term memory, a knowledge graph, and a vector index mean the 40th meeting with a client is informed by the previous 39 — automatically, without anyone writing anything down.
3. **It is configurable per team, not per product.** An 11-dimension behaviour system lets each department run a differently-behaved AI (HR runs learning-and-development analysis; engineering runs code and architecture review; compliance runs PII and policy checks) from one codebase, governed centrally.

The platform is **multi-tenant, role-based-access-controlled, fully audited, and self-hostable end to end** — including the two AI infrastructure dependencies (memory and LLM observability), which were both migrated in-house in August 2026 so that no customer prompt or transcript need leave the deployment's own infrastructure.

**Scale of the built asset (measured, not estimated):**

| | |
|---|---|
| Python (backend, tests, tooling) | **91,657 lines** across 326 modules |
| TypeScript / React (frontend) | **34,331 lines** across 163 files |
| REST + WebSocket endpoints | **205** across 27 router modules |
| Database tables | **53**, under **44** versioned migrations |
| AI skills (specialised analysis units) | **38** (33 general + 5 agent-scoped) |
| Background job types | **15** |
| Frontend application routes | **30** across 16 feature modules |
| Test / verification files | **54** |

---

## 2. The problem

Meetings are where companies actually make decisions, and they are the least durable artefact a company produces. Concretely:

- **Decisions evaporate.** What was agreed in a call exists only in the memories of whoever attended, and disagreement surfaces weeks later.
- **Commitments go untracked.** Action items are captured inconsistently, assigned ambiguously ("Priya will look at it"), and never reconciled against what was actually delivered.
- **Context does not transfer.** A new account manager inheriting a client has no access to the eleven prior conversations that explain why the relationship is where it is.
- **Recordings do not solve this.** A 60-minute recording is not knowledge. Nobody re-watches meetings. Search over a transcript returns keyword matches, not answers.
- **Existing note-takers stop at the summary.** They produce a document per meeting. They do not build a model of the organisation, they do not enforce who may see what, and they do not act.

The gap is between **capture** (solved) and **organisational memory that can be queried and acted upon** (not solved).

---

## 3. What the product does — the user's experience

**Before the meeting.** The assistant syncs with Google Calendar every two minutes and automatically joins scheduled calls. No one has to remember to invite it. Meetings can also be started manually by pasting a link.

**During the meeting.** Live transcription streams into the interface as people speak, speaker-attributed. Behind it, a cognitive engine continuously extracts tasks and decisions from the conversation as it happens, stabilising them across mentions so a commitment restated three times becomes one task with rising confidence rather than three duplicates. A rolling summary is maintained throughout. Participants can ask the assistant questions about the live meeting *and* about the organisation's entire history, mid-call.

**At the end of the meeting.** When someone says *"iris, summarize this"* — or when the assistant detects the meeting winding down from wrap-up language or participants leaving — it composes a spoken recap, converts it to speech, waits for a natural pause so it does not talk over anyone, plays it into the call, and leaves.

**After the meeting.** The full transcript is analysed by whichever AI configuration governs that team. Tasks land on a Kanban board. Entities and relationships are extracted into a knowledge graph. The transcript is chunked and embedded for semantic search. Durable facts are distilled into long-term memory. Every one of those steps is independently retryable and independently audited.

**Forever after.** Anyone with permission can ask the system a question in natural language — *"what did we decide about the pricing model?"* — and receive a synthesised, **cited** answer drawn from meetings, uploaded documents and the knowledge graph, filtered to exactly what that person is allowed to see.

---

## 4. Feature catalogue

Maturity is labelled per subsystem:
**`PRODUCTION`** — live, exercised by real data.
**`PILOT`** — built and functioning, deployed to a single scope.
**`BUILT / NOT ENABLED`** — complete and tested, behind a disabled flag.
**`SCAFFOLD`** — schema and management surface exist; runtime is stubbed.

### 4.1 Meeting capture and live intelligence — `PRODUCTION`

**Automatic attendance.** A Celery Beat job polls connected Google Calendars every two minutes and dispatches a bot to qualifying meetings. Google Meet, Zoom, Teams and Webex are detected and recorded via a meeting-bot provider (Recall.ai).

**Duplicate-bot protection.** Two independent guards prevent the "two bots joined the same call" failure: a per-meeting check on an existing bot ID, and a cross-meeting check for any other active meeting on the same URL within a 15-minute window. The second meeting is marked failed rather than left hanging.

**Live transcription** with pluggable providers. Two are implemented: AssemblyAI (default) and **Deepgram Nova-3**, which supports Hindi and 35 other languages with code-switching — a deliberate choice for the Indian market, since AssemblyAI's streaming mode has no Hindi. Language can be set per workspace (`auto`, `multi`, or an explicit code); the adapter layer normalises provider differences so a third provider is an adapter, not a refactor.

**Real-time delivery.** Transcript lines are broadcast over WebSocket to every connected viewer, and persisted using a Postgres string-concatenation update so the accumulated transcript never round-trips through the application — a deliberate optimisation for long meetings. Persistence runs off-thread so a slow database write cannot stall the live stream. Instrumentation measures every handler invocation and warns above 50ms, distinguishing "the provider stopped sending" from "we stopped processing".

**Live cognitive engine.** Final utterances are buffered and flushed for analysis on any of three triggers: 180 accumulated words, 8 conversational turns, or an importance keyword ("deadline", "action", "owner", "Friday"…). The 180-word threshold was tuned upward from 60 because commitments routinely span utterances and a short window cut the *what* away from the *who*. On each flush, three analyses run:

- **Task detection** with cross-mention stabilisation — a task mentioned repeatedly accumulates confidence rather than duplicating. New tasks below 0.4 confidence are suppressed.
- **Decision detection** with its own stabiliser and a stricter 0.55 floor, to keep low-confidence decisions out of the live interface.
- **Rolling summary** maintained continuously for the closing briefing.

Each branch is independently error-contained: a failure in decisions cannot break tasks or the summary.

**Live participant events.** Joins and leaves surface inline in the transcript view.

### 4.2 Spoken closing briefing — `PRODUCTION`

The differentiating capability: the assistant **speaks** before it leaves.

**Three independent triggers**, deliberately not one:
- **Status** (authoritative) — the provider's `call_ended` signal. Correct, but arrives 0–5s after the host clicks End, too late for heavy work.
- **Participant linger** (advisory) — active participants drop to one or fewer for 30+ seconds.
- **Linguistic** (advisory) — a regex bank over final utterances. Includes the explicit command `"iris summarize this"`, built to tolerate transcription errors (`irish`, `eris`, `aris`, `isis` are all accepted mishearings), optional filler words, and both British and American spellings. Also covers natural wrap-up phrases in English **and Hindi/Hinglish** (`फिर मिलेंगे`, `chaliye band karte hain`, `bas itna hi`).

**Composition and delivery.** A composer builds a spoken script from the live meeting state under a word budget derived from a speaking-rate estimate (150 wpm) and a hard ceiling (60s default, 8s floor below which the briefing is skipped as not worth speaking). Text-to-speech runs through a provider abstraction (OpenAI implemented; the interface is designed so ElevenLabs or Azure is a new adapter, not a call-site change), with an on-disk cache keyed by script hash. Audio is uploaded to object storage and injected into the call. The system waits for a configurable quiet window (default 2 seconds) so the assistant does not speak over a human.

**Robustness.** Idempotency is enforced twice: in-memory flags for fast rejection of duplicate signals, and a `SELECT … FOR UPDATE` on a database status column as the cross-process source of truth, so a process restart mid-briefing cannot produce two spoken recaps. A pre-flight check queries the bot's state and fails fast with a human-readable reason when the bot is no longer in the call, rather than surfacing an opaque provider error seconds later. Every attempt writes a full audit row — script, sections, word count, model, TTS provider and voice, character count, cache hit, audio key and size, playback ID, per-stage timestamps, and the terminal outcome across twelve defined states.

**Manual trigger.** An endpoint allows an operator to force a briefing at any time, with control over whether the bot leaves afterwards.

### 4.3 Post-meeting analysis pipeline — `PRODUCTION`

A blocking pipeline dispatched at bot creation:

1. Waits for the compiled transcript, self-delivering a lost `call_ended` webhook if the provider fails to send one.
2. **Falls back to the live transcript** if the compiled transcript fails entirely — the meeting is still analysed, losing only speaker-perfect attribution rather than the whole meeting.
3. Resolves participants (see §4.9).
4. Routes to the appropriate AI configuration and runs analysis.
5. Saves title, summary and tasks; tasks are deduplicated against anything the live engine already captured, and harmonised rather than duplicated.
6. Fans out to: memory distillation (synchronous), embedding → graph extraction → importance scoring (chained background jobs), and the vertical product pipeline (concurrent).

Every stage tracks its own lifecycle status independently, so an embedding failure does not roll back a successfully analysed meeting, and each stage is individually retryable from the interface.

### 4.4 The agent platform — configurable AI per team

This is the most architecturally significant part of the system and the basis for the "one codebase, many verticals" claim.

**Behaviour profiles — `PRODUCTION`.** An organisation's AI behaviour is defined across **11 dimensions**: master prompt, enabled agents, retrieval config, memory config, output config, extraction rules, automation rules, evaluation rules, tone and personality, compliance and guardrails, and tools/integrations. A resolver merges **five layers** at runtime — platform global default → category template → team template → workspace category overrides → workspace team overrides — with defined semantics (dictionaries shallow-merge with later winning; the agent list unions). Every resolution returns an audit trail of which layer contributed what, surfaced in the interface as "where did this value come from".

**Intent layer — `PRODUCTION`.** Rather than requiring administrators to understand 11 technical dimensions, a higher-level *intent* can be expressed and is expanded into technical dimensions automatically, with explicit settings still winning over intent-derived ones.

**Skills — `PRODUCTION`.** 38 discrete analysis units, each a prompt plus a typed input/output contract, self-registering into a capability registry:

| Domain | Count | Skills |
|---|---|---|
| Meetings | 6 | action items, agenda tracking, decisions, context research, sentiment, summaries |
| Executive | 6 | blocker escalation, closing briefing, investment areas, key takeaways, risk rollup, strategic alignment |
| Engineering | 6 | API review, architecture review, code review, dependency mapping, performance profiling, security audit |
| Compliance | 5 | access control, data retention, PII detection, policy violation, regulatory audit |
| Incidents | 5 | impact assessment, incident detection, mitigation planning, postmortem generation, root cause analysis |
| Product | 5 | competitor analysis, feature extraction, roadmap alignment, success metrics, user pain points |
| Agent-scoped | 5 | blocker detector, commitment watcher, follow-up drafter, key-moments extractor, participant sentiment |

**Tool-calling harness — `PRODUCTION` (runtime), tool catalogue partly `SCAFFOLD`.** Skills that declare required tools can execute inside an agentic loop where the model calls tools and iterates. **Six safety rails** bound the blast radius: maximum 8 iterations; a 30,000-token budget per loop; a 10-second wall-clock cap per tool; JSON-schema validation of every tool argument; a per-skill allow-list so a hallucinated tool name cannot dispatch; and organisation scoping such that a tool can only ever see one tenant. A seventh guard — a retry-storm detector — aborts when the same tool fails with the same error three times consecutively, added after a real incident in which a model burned an entire budget re-calling a broken tool. Every tool invocation writes an audit row (arguments, result, success, duration, tokens), grouped by run.

Of 11 catalogued tools, **4 are fully implemented** (create task, update task, look up meeting, search knowledge base) and 7 are deliberate scaffolds with working schemas and permission wiring but stubbed execution (Slack, email, Jira, GitHub, Notion, CRM, calendar). The integration surface is designed and governed; the connectors are not yet built.

**Unified cognition merger — `PRODUCTION`.** Outputs from the master analyzer and every skill are synthesised into one coherent result rather than concatenated, with normalisation, deduplication and conflict resolution stages.

**Agent lineage note (important for diligence).** Three generations of the agent system coexist in the codebase:
- **The legacy runtime** is the production path and handles every meeting without a dedicated agent record.
- **A management plane** (versioned prompts, publish/rollback, evaluation gates, playground, analytics) is fully built; its independent configuration-resolution engine has been superseded and its public entry point now delegates to the behaviour resolver above. It is retained for rollback.
- **A next-generation per-scope agent architecture** is `PILOT` — one first-class agent package per team, with its own prompts, skills and tracing. One pilot agent (HR learning & development) is deployed and running against live meetings.

This is normal for a system of this age, but it means the codebase contains more agent infrastructure than is simultaneously active. Consolidation is a known, scoped item (§10).

### 4.5 Knowledge layer — `PRODUCTION`

Four distinct stores, deliberately separated:

**Vector memory.** Completed meetings are chunked (≈800 tokens, 100-token overlap, speaker-turn aware) and embedded at 1536 dimensions. Uploaded documents are chunked separately with block-aware parsing and page/section provenance. Both live in HNSW-indexed pgvector tables and are unioned in a single ranked query at retrieval time.

**Knowledge graph.** An LLM extractor identifies entities and relationships from meeting chunks and documents, with strict pipeline ordering (entities → resolve → upsert → map → relationships → mentions). Entities carry canonical names, aliases and typed attributes; scope is encoded so the same name in two teams is two entities. Every graph row carries provenance — the exact chunk and text span it came from. Extraction is versioned by prompt so a prompt improvement can target only the rows that need re-extraction.

**Long-term organisational memory.** After each meeting, a distiller emits a small number of durable facts typed as ownership, decision, open question, risk, preference, pattern or event, each with a subject, an importance and confidence score, and a source excerpt. Facts supersede rather than overwrite, preserving history. This is what gives the assistant continuity between meetings.

**Full historical record.** A read-only access layer over the complete meeting and task history, used when the AI needs everything rather than a distilled subset.

**Importance scoring — `PRODUCTION`.** An hourly, deterministic, non-LLM scorer assigns every knowledge row a score in [0,1] from six signals: access count, citation count, recency (exponential decay, 30-day half-life), confidence, entity density, and graph centrality (degree-based, log-saturated). Every scoring pass writes an audit row containing the algorithm version, the exact weights used, and the resulting score distribution — a deliberate drift sentinel, since importance systems degrade silently.

**Consolidation — `PRODUCTION`.** A weekly pass archives content that is simultaneously old, never accessed and low-importance (all three conditions required), and proposes entity merges by name similarity. Archival is reversible — a "rehydrate" action restores a row. Merge proposals queue for human approval and rejections are sticky, so a re-run does not re-propose a pair a human already declined.

### 4.6 Retrieval and question answering — `PRODUCTION`

A hybrid graph-RAG pipeline, not simple vector search:

1. **Planning** — one cheap LLM call classifies the question (factual / summarisation / list / comparison), chooses a scope tier, and extracts entity names. It deliberately does *not* decide whether context exists; that is retrieval's job.
2. **Vector retrieval** with **scope tier widening** — search the tightest scope (team) first, then expand outward (category, then global) only if results are thin.
3. **Anchor entity discovery** from both the question and the retrieved chunks.
4. **Graph expansion** one hop from those anchors.
5. **The step that makes it graph-RAG rather than vector-search-plus-graph-data:** for every related entity not already anchored, retrieve the chunks where that entity is mentioned. This surfaces material the question's wording would never have matched.
6. **Reranking** combining similarity, entity-anchor overlap and recency, with an importance-aware strategy available.
7. **Synthesis with enforced citation.** Only chunks are citable; entities and relationships inform reasoning but cannot be cited. Every `[N]` marker in the model's answer is validated against the retrieval bundle, and hallucinated citations are stripped from the answer rather than shown to the user.

Answers stream token-by-token over server-sent events. Every query writes an audit row containing the full retrieval bundle, per-stage timings, token counts, the prompt versions used and the final citations — so any answer can be replayed and evaluated without re-running the model.

Two variants exist: standard retrieval, and a **live variant** that additionally injects the in-progress meeting's state and the long-term record, for asking questions mid-call.

**Conversational memory — `BUILT / NOT ENABLED`.** Session-scoped chat memory so follow-up questions resolve against earlier turns is implemented, verified end-to-end, and gated behind a disabled flag pending a decision on the per-turn cost.

### 4.7 Task management and Kanban — `PRODUCTION`

Tasks originate three ways: extracted live during the meeting, extracted by post-meeting analysis, or created by hand.

Boards are scoped to the organisation, a category or a team. Columns carry an optional bound status, so renaming a column's label does not lose the underlying state semantics; they also support work-in-progress limits and a designated done column. Card ordering uses fractional positioning (midpoint insertion with rebalancing when the gap collapses), which makes drag-and-drop a single-row update rather than a reorder of the column.

Each card carries a markdown description, priority, due date, a display owner name **and** a resolvable assignee link — the two are separate because the analyzer writes free text ("Priya", "TBD", "the design team") that cannot answer "what is assigned to me". Cards support threaded comments with author-name snapshotting so attribution survives account deletion, and an **append-only activity log** across eleven event types, never updated in place.

A database constraint keeps the legacy completion boolean and the authoritative status column in permanent lockstep, so the two can never disagree.

### 4.8 Continuum Core — vertical product — `PILOT`

A consulting-deal tracker built on the platform, demonstrating vertical extensibility.

Each client is a persistent JSON "board" — the accumulated state of the relationship. After every recorded meeting with that client, an LLM rewrites the board with the new information, versioning it. A six-stage pipeline (discovery → strategy pitch → strategy document → financials → handoff → delivery) is displayed as a Kanban.

**A deliberate product rule enforced in code, not in the prompt:** the AI never advances a deal stage. It only *recommends*, with a rationale; a human confirms by dragging the card. If the model ignores the instruction and edits the stage inside the board JSON, the code pins it back and logs the attempt. Every run — input envelope, output package, resulting board, stage recommendation — is retained, so the board's history is never lost despite being rewritten each time. A database constraint guarantees a meeting can be processed into a board only once.

Runtime is configurable per organisation (model, token budget, temperature, and a full master-prompt override). If an operator's prompt override accidentally removes the response contract the parser depends on, the system re-appends it — a bad edit degrades output quality but cannot break the system.

### 4.9 Identity, access control and multi-tenancy — `PRODUCTION`

**Tenancy.** Every user, meeting, category, document, chunk, entity and task is scoped to an organisation. Every query filters on it. Cross-tenant requests return *not found* rather than *forbidden*, so the existence of another tenant's record is never confirmed.

**Two independent role systems**, deliberately not merged because they govern unrelated surfaces: a meeting-access role (member / admin / org admin) and a prompt-management role (viewer / prompt editor / org admin).

**The central access design: a grant says *where*, a role says *what*.** Assigning someone a category or team defines their scope; it is not a promotion. The same grant means "may read this category" for a member and "may read and manage it" for an admin. This is what allows an organisation admin to scope a plain member without granting them any editing rights.

**Membership is attendance.** A user sees a meeting because they attended it — evidenced by a participant row linking them to it. Critically, **not every link is trusted**: participant identity is resolved by matching provider-reported speaker names against calendar attendees, and only exact matches (email or full display name) or explicit administrator action confer access. Partial name-token matches are retained for display but grant nothing, because two colleagues named "Chris" would otherwise inherit each other's meetings. Ambiguous name tokens are discarded entirely rather than resolved arbitrarily.

**Retrieval is access-controlled at the SQL level.** This is the subtlest and most important security property in the system. Every other endpoint returns a record the user requested by ID; retrieval returns verbatim sentences from whatever the embedding space considers relevant. Filtering meetings but not retrieval would mean a member could ask "what was decided about the restructure?" and receive the executive meeting read back to them, correctly cited. The access filter therefore lives *inside* the query that selects chunks, applied before ranking and limiting — a chunk that reached the reranker has already been read.

**Delegated administration.** Category administrators can manage members within their own scope, including promoting to administrator, but can never create an organisation administrator, and any grant they issue is confined to what they themselves hold. Their edits to another user's grants are additive within scope, so one administrator cannot silently strip another's unrelated grants by saving a form they could not see all of.

**Manual attendance override.** An administrator can link or unlink a participant to an account by hand, with the action recorded as a trusted source. This exists because there was previously no recovery from a failed automatic match. The interface surfaces a one-click confirmation driven by exact email suggestion.

**Session security.** Authentication uses an HttpOnly cookie, so a cross-site scripting payload cannot exfiltrate the session. Tokens carry an issued-at claim and are refused if minted before the account's last password change — real session revocation on a stateless token. A 30-second clock tolerance prevents a fresh login from invalidating itself, and the check fails open on legacy tokens so a deployment does not sign everyone out.

**Account deletion safety.** Deleting a user is guarded rather than cascading. Of roughly 28 foreign keys into the user table, the dangerous ones are handled explicitly — most notably, deleting a category's creator would otherwise cascade-delete the category, its teams, its documents, its access grants, and unfile every meeting under it. Ownership is reassigned instead. A test fails the build if a new cascading foreign key into users is introduced without review.

### 4.10 Documents and knowledge ingestion — `PRODUCTION`

Documents upload to object storage at category or team scope. PDF, DOCX and XLSX parsers extract text with structural awareness. Ingestion chunks, embeds and feeds the same knowledge graph as meetings, with independent lifecycle status so a parser failure does not corrupt storage state. Chunk counts and token totals are cached on the record so the interface does not need a join. Retry actions exist for both embedding and graph extraction.

### 4.11 Templates and workspace provisioning — `PRODUCTION`

A platform-owned registry of starter bundles — pre-built categories, teams and agent configurations — that a workspace installs. New organisations can auto-provision a configured workspace at signup, so the product is useful on day one rather than after a configuration project.

Every provisioned entity records its lineage: which template, which version, which bundle, and a divergence state (pristine / modified / heavily modified / forked) with a stored diff. This enables template upgrades: when the platform publishes a new template version, the system can identify which workspaces are still close enough to the original to accept the upgrade, and propose it rather than force it.

### 4.12 Observability, evaluation and cost tracking — `PRODUCTION`

The system is instrumented as an AI product, not just as a web application:

- **Per-query observability** — every retrieval run's full bundle, timings, token counts and citations.
- **Nightly performance rollups** per agent and prompt version: run counts by outcome, p50/p95 latency, token totals, average citation count, distinct users.
- **Prompt version analytics** — because prompts are versioned and every run records which version produced it, the effect of a prompt change is measurable rather than anecdotal.
- **Tool invocation audit** and harness metrics.
- **Evaluation gates** — a prompt version can be blocked from publication unless it scores above a threshold on a fixture set, with the full report retained.
- **A playground** for testing prompt changes against real retrieval in a sandbox that never writes to production observability.
- **LLM tracing** — every AI call in the new agent architecture and the vertical product emits a trace with model, token counts, computed cost and latency, assembled into a per-meeting tree.
- **Citation click tracking**, which feeds the importance scorer: content users actually open is scored as more important.

### 4.13 Administration and organisational management — `PRODUCTION`

Member provisioning with generated one-time passwords and forced password change on first use; role and grant management with a scoped picker; password reset with session revocation; and transactional email over standard SMTP with no vendor SDK, so any provider works by configuration. Email is optional by design — with no mail server configured, member creation still succeeds and returns the credential for manual delivery. Sends occur only after the database commit, so a credential is never mailed for a write that failed.

### 4.14 Interface — `PRODUCTION`

A React 19 single-page application, 30 routes across 16 feature modules: dashboard, meetings list and detail, live transcript view, calendar, categories and teams, action items, Kanban boards with drag-and-drop, board summaries and charts, knowledge hub, knowledge graph explorer, natural-language Ask with streaming answers and citation chips, agent control panel, prompt studio with version history and diffing, templates browser, members administration, reports, integrations, settings, and the Continuum board.

Notably, the frontend carries **no state-management or data-fetching dependency** — no Redux, no React Query, no Zustand, no axios. Data access is a thin fetch wrapper plus purpose-built hooks. This is a deliberate dependency-minimisation choice that keeps the bundle small and the upgrade surface narrow.

---

## 5. Technical architecture

**Backend.** Python 3.13 / FastAPI, serving both the API and the compiled frontend from one process — a single deployable unit. Two route prefixes separate authenticated application endpoints from the two public ones (register, login); machine-to-machine endpoints sit at the root because the provider posts to fixed URLs.

**Data.** PostgreSQL 16 with the pgvector extension. 53 tables under 44 sequential migrations. HNSW indexes on every vector column.

**Background processing.** Celery over Redis, 15 job types, with a scheduler for recurring work (calendar sync every 2 minutes, importance scoring hourly, analytics nightly, consolidation weekly). Long-running jobs are configured with an extended visibility timeout and late acknowledgement so a worker crash does not lose work.

**Storage.** S3-compatible object storage (MinIO locally, any S3 provider in production) for documents and generated audio.

**Frontend.** React 19 + Vite, TypeScript, Tailwind, compiled to static assets served by the backend.

**Deployment.** A multi-stage Docker image containing both the built frontend and the backend; the same image runs the web, worker and scheduler roles with only the start command differing. A development stack composes Postgres, Redis, MinIO, the worker and the observability service.

### 5.1 Engineering posture

Several patterns recur deliberately and are worth noting in diligence, because they represent accumulated operational learning rather than initial design:

- **Independent lifecycle status per stage.** Meetings, documents, embeddings, graph extraction and briefings each track their own state, so one subsystem's failure never rolls back another's success.
- **Append-only audit tables** for every consequential operation — graph extraction runs, retrieval runs, importance runs, tool invocations, deployments, template provisioning, task activity, briefings. Audit rows intentionally have no foreign key to the entities they describe, so history outlives deletion.
- **Fail-safe degradation.** Optional subsystems (memory, tracing, email, storage) degrade to no-ops rather than failing the request. The application boots and processes meetings with none of them configured.
- **Idempotency at every external boundary** — duplicate webhooks, duplicate bot dispatch, re-run analysis, repeated provisioning, repeated processing of the same meeting.
- **Versioned prompts and algorithms.** Prompt versions, graph extraction versions and importance algorithm versions are recorded on every output row, so any result is attributable and replayable.

---

## 6. Data model

53 tables in seven groups: core meeting entities; organisation and access control; vector memory; knowledge graph; retrieval audit; agent configuration and prompt versioning; and vertical product state. The schema encodes correctness in the database rather than only in application code — check constraints for enumerations, partial unique indexes that handle PostgreSQL's "NULL is distinct" behaviour correctly, cross-column consistency constraints, and triggers enforcing immutability of published prompt versions.

---

## 7. Security and compliance posture

| Property | Status |
|---|---|
| Multi-tenant isolation | Enforced on every query; cross-tenant returns *not found* |
| Access control | Role + grant model, enforced in SQL including retrieval |
| Session security | HttpOnly cookie; issued-at revocation on password change |
| Webhook authentication | Signature verification with replay window |
| Credentials at rest | Encrypted in the observability service; secrets in environment only, never committed |
| Audit trail | Append-only across all consequential operations |
| PII detection | Skill implemented; runtime redaction gated by behaviour profile |
| Data residency | **Fully self-hostable** — see §8 |

**Known coverage gaps, stated plainly:** document download endpoints and two graph endpoints are currently scoped to the organisation but not to the finer access model, meaning a member could retrieve a knowledge document from a category they cannot otherwise see — while the same content is correctly hidden from AI retrieval. These are identified, bounded, and scheduled.

---

## 8. Data residency and vendor independence

A material differentiator for enterprise and regulated buyers, completed in August 2026.

The platform previously depended on two hosted AI services: a memory platform and an LLM observability platform. Both have been **migrated in-house**:

- **LLM observability** now runs as a self-hosted service (open-source, MIT-licensed core) inside the deployment, backed by the same database. No prompt or completion leaves the customer's infrastructure for tracing.
- **Organisational memory** now runs in the deployment's own PostgreSQL, using the same embedding model as the rest of the platform. 112 existing memories were migrated with full metadata preservation.

Both migrations retain a one-line rollback to the hosted equivalents. Telemetry is disabled on both.

**What still requires an external call:** the language and embedding models themselves (OpenAI, with Google Gemini as a configured fallback), the meeting-bot provider, and the transcription providers. The model layer is abstracted per call site, so a customer-specific or on-premise model is a configuration and adapter change rather than a rewrite.

The practical claim to enterprise buyers: **everything except the model inference itself can run inside the customer's own boundary.**

---

## 9. Maturity matrix

| Subsystem | Maturity | Note |
|---|---|---|
| Meeting capture, transcription, live stream | `PRODUCTION` | 208 meetings processed in the reference deployment |
| Live cognitive engine (tasks, decisions, summary) | `PRODUCTION` | |
| Spoken closing briefing | `PRODUCTION` | Voice-triggered, full audit |
| Post-meeting analysis pipeline | `PRODUCTION` | |
| Behaviour profiles, 5-layer resolver, intent layer | `PRODUCTION` | |
| Skill library (38) | `PRODUCTION` | |
| Tool-calling harness + safety rails | `PRODUCTION` | 4 of 11 tools implemented; 7 scaffolded |
| Vector memory, knowledge graph, importance, consolidation | `PRODUCTION` | 1,054 entities, 386 chunks in reference deployment |
| Graph-RAG question answering with citation validation | `PRODUCTION` | |
| Long-term organisational memory | `PRODUCTION` | Self-hosted since Aug 2026 |
| Kanban and task management | `PRODUCTION` | 1,246 tasks in reference deployment |
| RBAC, multi-tenancy, delegated administration | `PRODUCTION` | 28 automated access-control assertions |
| Documents and ingestion | `PRODUCTION` | |
| Templates and provisioning | `PRODUCTION` | |
| Observability, analytics, evaluation gates | `PRODUCTION` | |
| LLM tracing | `PRODUCTION` | Self-hosted since Aug 2026 |
| Next-generation per-scope agents | `PILOT` | One agent live |
| Continuum Core vertical | `PILOT` | One client live |
| Conversational (session) memory | `BUILT / NOT ENABLED` | Flag-gated |
| Third-party action connectors (Slack, Jira, GitHub, Notion, CRM, email, calendar) | `SCAFFOLD` | Schemas and permissions built; execution stubbed |

---

## 10. Known limitations and near-term engineering roadmap

Stated deliberately, because diligence will surface them:

1. **Agent architecture consolidation.** Three generations coexist. The oldest is production; the newest is a pilot. Merging them is scoped work, not research.
2. **Action connectors.** Seven integrations are governed scaffolds. Building them is bounded, well-understood work and the highest-leverage near-term product investment — it converts the system from *understanding* meetings to *acting* on them.
3. **Analysis tracing coverage.** LLM tracing covers the newest agent architecture and the vertical product; the legacy production path is not yet instrumented.
4. **Access-control coverage gaps** in document download and two graph endpoints (§7).
5. **Production schema currency.** The production database trails the current branch by four migrations; these must be applied before the next deployment.
6. **Historical attendance backfill.** Meetings recorded before participant-provenance tracking do not confer access and require a one-time re-linking pass.
7. **Deployment URL stability.** The reference deployment uses a tunnelled public URL, meaning emailed sign-in links expire; a stable domain is required for production email.
8. **Prompt context budgeting.** The knowledge block injected into agent prompts is capped, and the cap is currently saturated — memory competes with open tasks for space. Raising it is a one-line configuration change pending a cost decision.

None of these are architectural. They are scope, coverage and operational items.

---

## 11. Commercial section — to be completed by founders

The engineering record does not contain this information, and it has deliberately not been estimated:

- `[TO BE SUPPLIED]` Market size and segmentation
- `[TO BE SUPPLIED]` Target customer profile and go-to-market motion
- `[TO BE SUPPLIED]` Competitive positioning and named comparisons
- `[TO BE SUPPLIED]` Pricing model and unit economics
- `[TO BE SUPPLIED]` Traction: customers, users, revenue, retention, pipeline
- `[TO BE SUPPLIED]` Team composition and hiring plan
- `[TO BE SUPPLIED]` Funding history, current raise, use of funds
- `[TO BE SUPPLIED]` Financial projections

**One input this document can supply for unit economics:** per-meeting AI cost is measurable and low. A representative fully-analysed meeting in the pilot agent configuration consumed approximately 11,300 tokens across 7 model calls, at a measured cost of roughly **$0.0027**. Memory distillation adds approximately $0.001. Embedding costs are negligible. The dominant cost driver is the meeting-bot provider, not inference.

---

## 12. Appendix — verified metrics

All figures measured from the codebase and reference deployment on 2026-08-07.

| Metric | Value |
|---|---|
| Backend code | 91,657 lines / 326 modules |
| Frontend code | 34,331 lines / 163 files |
| API endpoints | 205 |
| Router modules | 27 |
| Database tables | 53 |
| Schema migrations | 44 |
| AI skills | 38 |
| Harness tools | 11 catalogued (4 implemented) |
| Background job types | 15 |
| Scheduled jobs | 4 |
| Frontend routes | 30 |
| Frontend feature modules | 16 |
| Test and verification files | 54 |
| Transcription providers supported | 2 |
| Meeting platforms supported | 4 |
| Behaviour dimensions | 11 |
| Resolution layers | 5 |
| Reference deployment | 208 meetings, 1,246 tasks, 1,054 entities, 386 meeting chunks, 112 memories, 61 users, 58 organisations |
