# Phase 8 — Prebuilt Enterprise Template System

> **Status:** PLANNED. Awaiting "go" on the slice sequencing.
> **Renumbering:** the previously-drafted "live in-meeting copilot" (originally Phase 7, then deferred to Phase 8) is being deferred **again** to Phase 9. This phase shipsthe Template System as the next major platform layer per the user's brief.
> **Position in the roadmap:** Phases 1–7 are SHIPPED (454/454 tests, head migration `l3f6a7b8c9d0`). Phase 8 sits **above** the Phase 7 runtime — it does not change runtime semantics; it only populates the workspace-owned rows that Phase 7's resolver already reads.

---

## 0. Framing — what this is and what it is not

**This is** a registry of **immutable global blueprints** plus a **provisioning machine** that materializes them into **workspace-owned editable copies**. The deliverable is: every new workspace starts with a production-grade set of teams, meeting categories, agent profiles, prompt versions, and runtime policies — all of which the workspace owner can edit, fork, reset, or upgrade without affecting any other workspace or the global template.

**This is NOT** a redesign of the Phase 7 runtime. The resolver, synthesizer, planner, retrieval, observability — all stay exactly as they are. Templates produce **rows in the existing workspace tables** (`teams`, `categories`, `agent_profiles`, `agent_prompt_configs`, `prompt_versions`). The runtime keeps reading those tables, ignorant of whether they came from a template or were hand-authored.

**Critical invariant** (from the user's brief):
> *The runtime system must NEVER execute directly from global templates. Runtime execution must ALWAYS use workspace-owned copies.*

This is enforced by **construction**: the runtime resolver (`app/services/agents/resolver.py`) only queries workspace-scoped tables. The template tables are read by the **provisioning service** during write paths — never by the runtime.

---

## 1. Current state we are integrating with

### 1.1 Existing workspace-owned tables (Phase 1–7) the templates write to

| Table | Owner | Purpose |
|---|---|---|
| `organizations` | platform | tenant boundary |
| `teams` (under `categories`) | workspace | per-org collaboration scope |
| `categories` (a.k.a. meeting types) | workspace | per-org meeting type bucket |
| `agent_profiles` | workspace | agent identity (Phase 7A) |
| `agent_prompt_configs` | workspace | scope→profile binding (Phase 7A) |
| `prompt_versions` | workspace | immutable prompt + retrieval + model config snapshot (Phase 7B) |

### 1.2 Existing org-create entry point

`app/api/auth_router.py:register` creates a fresh `Organization` row on user signup. **This is the auto-provisioning hook**. Phase 8 adds one line: after `db.commit()`, call `provision_starter_pack_for_org(db, org_id, user_id)` fire-and-forget (errors logged, never block signup).

### 1.3 Existing Phase 7 conventions Phase 8 mirrors

- **Multi-tenant by `organization_id` on every workspace row**, CASCADE-from-organizations
- **Audit-log shape**: `algorithm_version` / `weights_json` / `score_distribution_json` (Phase 6A) — Phase 8's provisioning jobs follow this
- **Soft-active dedup via partial unique indexes** — Phase 8 lineage links use the same pattern
- **Strategy router / version_tag** — Phase 8 carries `template_version` strings the same way
- **Append-only audit** (Phase 6B `rag_chunk_access_events`, Phase 7B `prompt_deployments`) — Phase 8's provisioning jobs + upgrade proposals are append-only too
- **Fire-and-forget for non-critical paths** — auto-provisioning on signup
- **Eval-gated changes** — upgrade proposals get the same eval option (per-profile via Phase 7H)
- **Idempotent seed pattern** (Phase 7D `seed_defaults.py`'s `did_anything_new` flag) — Phase 8 provisioning reuses the exact same shape

### 1.4 Existing test pattern

Each ship test creates an org, exercises the slice, and asserts invariants — never against a shared global org, always isolated. Phase 8 tests follow this verbatim.

---

## 2. Architectural commitments

These follow the locked Phase 1–7 conventions:

1. **Templates are immutable platform assets**. A "version" of a template is a new row, not an UPDATE. Same shape as `prompt_versions` in Phase 7B.
2. **Workspaces own editable copies**. Editing a workspace row never reaches back to a template; deleting a template never breaks a workspace.
3. **Lineage is a side-table, not a column on existing tables**. Existing `teams` / `categories` / `agent_profiles` schemas don't change. Lineage lives in `workspace_template_links`. This keeps Phase 8 migrations additive — production-critical tables are untouched.
4. **Provisioning is idempotent**. Calling it twice on the same workspace produces no duplicates. Same pattern as Phase 7D's `seed_default_agents_for_org`.
5. **Runtime is unaware**. The resolver, synth, planner, retrieval all stay byte-identical. Templates are a **write-path concept**.
6. **Tenant isolation is structural**. Every workspace_template_link row carries `organization_id`. Every API endpoint filters by `current_user.organization_id`. Global template reads are open to all authenticated users (the catalog is public-within-the-platform).
7. **Append-only provisioning + upgrade audit**. BIGSERIAL PKs, no FK on volatile pointers, partition-ready — Phase 6B convention.
8. **Three-way merge for upgrades, never auto-apply**. Admin sign-off required for every upgrade adoption. Mirrors Phase 7B's publish/rollback explicit-action requirement.
9. **Code-defined catalog → DB seed**. The 9 teams + 11 categories + 9 agents are written as Python dataclasses in `app/services/templates/catalog.py`; a one-shot seed migration writes them to `template_*` tables. Same pattern as Phase 7D's filesystem→DB seed.
10. **Marketplace-ready, not marketplace-built**. We reserve a `signature` column on `template_bundles` and design the API around a stable manifest shape, but don't build the publishing/discovery surface in this phase.

---

## 3. Database architecture

Five new global tables + four new workspace tables. Four Alembic migrations.

### 3.1 Global registry tables (immutable, platform-owned)

These hold the catalog. Read by provisioning + upgrade; never read by the runtime.

#### `template_bundles`

A *bundle* is the unit a workspace installs. Bundles group teams, categories, and agents into a coherent starter pack ("Engineering Starter", "Sales Starter", "All-In Starter").

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | gen_random_uuid() |
| `slug` | text NOT NULL | e.g. `engineering-starter` |
| `display_name` | text NOT NULL | |
| `description` | text | |
| `category` | text | `engineering` \| `sales` \| `hr` \| `cs` \| `executive` \| `marketing` \| `product` \| `recruiting` \| `support` \| `full` (the "all-in" bundle) |
| `version` | text NOT NULL | semver; e.g. `1.0.0` |
| `state` | text NOT NULL DEFAULT 'draft' | `draft` \| `published` \| `deprecated` |
| `published_at` | timestamptz nullable | |
| `published_by` | UUID nullable | platform-staff user id |
| `signature` | text nullable | **reserved for marketplace** — base64 signed manifest |
| `manifest_hash` | text nullable | sha256 of (sorted item-defs + retrieval/model/tool defaults). Detects bundle drift. |
| `is_recommended_on_signup` | boolean NOT NULL DEFAULT false | one or more bundles flagged `true` auto-provision on org create |
| `created_at` / `updated_at` | timestamptz | |

**Constraints:**
- `UNIQUE (slug, version)` — same slug across versions is fine; same (slug, version) is not
- `CHECK (state IN ('draft','published','deprecated'))`
- `CHECK (version ~ '^\d+\.\d+\.\d+$')` — semver shape

**Indexes:**
- `INDEX (state, is_recommended_on_signup) WHERE state = 'published'`
- `INDEX (category, state)`

#### `template_team_definitions`

Reusable team templates. Slug is the natural key.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | text NOT NULL UNIQUE | `engineering`, `sales`, … |
| `display_name` | text NOT NULL | |
| `description` | text | |
| `suggested_category_slugs` | text[] | e.g. `['sprint-planning', 'incident-review']` — provisioning creates these categories under this team if not yet present |
| `meta_json` | JSONB | reserved |
| `created_at` / `updated_at` | timestamptz | |

#### `template_category_definitions`

Reusable meeting-category templates.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | text NOT NULL UNIQUE | `sprint-planning`, `discovery-call`, … |
| `display_name` | text NOT NULL | |
| `description` | text | |
| `default_agent_slugs` | text[] | the agents recommended for this meeting type |
| `default_color` / `default_icon` | text | UX defaults for the workspace `categories` row |
| `meta_json` | JSONB | retrieval / behavior hints |
| `created_at` / `updated_at` | timestamptz | |

#### `template_agent_definitions`

Reusable agent recipes. This is the headline table — carries the full Phase 7 configuration shape.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `slug` | text NOT NULL UNIQUE | `incident-investigator`, `sales-coach`, … |
| `display_name` | text NOT NULL | |
| `description` | text | |
| `agent_type` | text NOT NULL | one of Phase 7A's locked enum |
| `default_modular_prompt_json` | JSONB NOT NULL | the 8-section prompt (Phase 7's shape) |
| `default_variables_schema_json` | JSONB NOT NULL DEFAULT '[]' | |
| `default_retrieval_config_json` | JSONB NOT NULL DEFAULT '{}' | |
| `default_model_config_json` | JSONB NOT NULL DEFAULT '{}' | |
| `default_tool_permissions_json` | JSONB NOT NULL | `{"allowed":[],"denied":[]}` |
| `eval_gate_required` | boolean NOT NULL DEFAULT false | |
| `eval_min_score` | float nullable | |
| `meta_json` | JSONB | reserved |
| `version` | text NOT NULL DEFAULT '1.0.0' | per-definition semver — bundles can pin a specific version of an agent |
| `created_at` / `updated_at` | timestamptz | |

**Constraints:**
- `UNIQUE (slug, version)`
- Same `agent_type` CHECK as Phase 7A's enum

#### `template_bundle_items`

Join table — what's in each bundle.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `bundle_id` | UUID FK template_bundles CASCADE NOT NULL | |
| `item_type` | text NOT NULL | `team` \| `category` \| `agent` |
| `item_slug` | text NOT NULL | references the relevant definition table by slug |
| `item_version` | text nullable | when null, "latest" of that definition |
| `provisioning_hints_json` | JSONB | e.g. `{"create_org_scoped_config": true, "publish_v1": true}` |
| `ordering` | int NOT NULL DEFAULT 0 | render order for the bundle detail page |

**Constraints:**
- `UNIQUE (bundle_id, item_type, item_slug)`
- `CHECK (item_type IN ('team','category','agent'))`

### 3.2 Workspace-side tables (per-org, mutable, lineage-aware)

#### `workspace_template_links`

The link table mapping workspace-owned rows back to the template they were provisioned from. **One row per provisioned workspace entity.**

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `organization_id` | UUID FK organizations CASCADE NOT NULL | tenant scope |
| `entity_type` | text NOT NULL | `team` \| `category` \| `agent_profile` \| `prompt_config` \| `prompt_version` |
| `entity_id_uuid` | UUID nullable | for UUID-PK entities (agent_profile, prompt_config, prompt_version) |
| `entity_id_int` | bigint nullable | for Integer-PK entities (team, category) |
| `source_template_kind` | text NOT NULL | `team` \| `category` \| `agent` (mirrors the definition table family) |
| `source_template_slug` | text NOT NULL | |
| `source_template_version` | text NOT NULL | the version of the definition that was provisioned |
| `source_bundle_id` | UUID FK template_bundles SET NULL nullable | nullable: ad-hoc provisioning may not target a bundle |
| `source_bundle_version` | text nullable | |
| `provisioning_job_id` | UUID FK template_provisioning_jobs SET NULL nullable | |
| `provisioned_at` | timestamptz NOT NULL | |
| `lineage_state` | text NOT NULL DEFAULT 'pristine' | `pristine` \| `modified` \| `heavily_modified` \| `forked` |
| `diff_summary_json` | JSONB NOT NULL DEFAULT '{}' | cached output of `DivergenceAnalysisService` — keys: `prompt_sections_changed`, `retrieval_changed`, `model_changed`, `tool_perms_changed`, `removed`, `last_computed_at` |
| `last_diverged_at` | timestamptz nullable | populated when lineage_state first leaves 'pristine' |
| `created_at` / `updated_at` | timestamptz | |

**Constraints:**
- `CHECK ((entity_id_uuid IS NOT NULL) <> (entity_id_int IS NOT NULL))` — exactly one set
- `CHECK (entity_type IN ('team','category','agent_profile','prompt_config','prompt_version'))`
- `CHECK (source_template_kind IN ('team','category','agent'))`
- `CHECK (lineage_state IN ('pristine','modified','heavily_modified','forked'))`
- One workspace entity can only have ONE link row:
  `UNIQUE (entity_type, COALESCE(entity_id_uuid::text, ''), COALESCE(entity_id_int::text, ''))`

**Indexes:**
- `(organization_id, source_template_kind, source_template_slug)` — common "find the workspace's instance of `incident-investigator`"
- `(organization_id, lineage_state) WHERE lineage_state <> 'pristine'` — "what has the workspace customized?"
- `(source_bundle_id, source_template_version)` — upgrade-detection query

#### `template_provisioning_jobs`

Append-only audit. One row per provisioning invocation.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID FK organizations CASCADE NOT NULL | |
| `bundle_id` | UUID FK template_bundles SET NULL nullable | nullable for ad-hoc item-level provisioning |
| `bundle_version` | text nullable | |
| `mode` | text NOT NULL | `bundle` \| `item_list` \| `auto_signup` |
| `requested_items_json` | JSONB | for `item_list` mode: `[{type, slug, version?}, ...]` |
| `status` | text NOT NULL | `pending` \| `in_progress` \| `completed` \| `partial` \| `failed` |
| `items_created` | int NOT NULL DEFAULT 0 | |
| `items_skipped` | int NOT NULL DEFAULT 0 | already provisioned |
| `items_failed` | int NOT NULL DEFAULT 0 | |
| `failure_details_json` | JSONB NOT NULL DEFAULT '[]' | per-item error messages |
| `duration_ms` | int nullable | |
| `error_message` | text nullable | top-level error if status='failed' |
| `triggered_by` | text NOT NULL | `auto_signup` \| `manual` \| `admin_api` \| `celery` |
| `triggered_by_user_id` | UUID FK users SET NULL nullable | |
| `started_at` | timestamptz NOT NULL | |
| `completed_at` | timestamptz nullable | |
| `created_at` | timestamptz NOT NULL | |

**Indexes:** `(organization_id, created_at DESC)`, `(status, created_at DESC)` for admin observability.

#### `template_upgrade_proposals`

When a template gets a new published version, a proposal is created per workspace link affected. Admin reviews and accepts/rejects.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `organization_id` | UUID FK organizations CASCADE NOT NULL | |
| `workspace_template_link_id` | bigint NOT NULL | no FK — see audit-survives-cascade pattern (Phase 6B) |
| `entity_type` | text NOT NULL | denormalized for filter ergonomics |
| `from_template_version` | text NOT NULL | current version on the link |
| `to_template_version` | text NOT NULL | the new published version |
| `diff_json` | JSONB NOT NULL | three-way diff payload: `{workspace_current, template_old, template_new, conflict_sections}` |
| `selectable_changes_json` | JSONB NOT NULL | each upgradable section as a togglable item |
| `resolution_state` | text NOT NULL DEFAULT 'open' | `open` \| `accepted` \| `partial_accepted` \| `rejected` \| `superseded` |
| `accepted_changes_json` | JSONB nullable | which selectable changes the admin opted in |
| `decided_by_user_id` | UUID FK users SET NULL nullable | |
| `decided_at` | timestamptz nullable | |
| `applied_at` | timestamptz nullable | when the accepted changes actually landed in the workspace |
| `applied_prompt_version_id` | UUID FK prompt_versions SET NULL nullable | the new Phase 7B version created by acceptance |
| `created_at` | timestamptz NOT NULL | |

**Constraints:**
- `CHECK (resolution_state IN ('open','accepted','partial_accepted','rejected','superseded'))`

**Indexes:**
- `(organization_id, resolution_state, created_at DESC)` — admin inbox query
- `UNIQUE (workspace_template_link_id, from_template_version, to_template_version)` — one proposal per (link, version-transition)

#### `template_publish_events`

Append-only platform-side audit when a global template's version is published. Used by `template_upgrade_detector` Celery task to scan for affected workspaces.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `template_kind` | text NOT NULL | `bundle` \| `team` \| `category` \| `agent` |
| `template_slug` | text NOT NULL | |
| `from_version` | text nullable | first publish: null |
| `to_version` | text NOT NULL | |
| `published_by` | UUID nullable | platform-staff user |
| `manifest_hash_before` | text nullable | |
| `manifest_hash_after` | text NOT NULL | |
| `created_at` | timestamptz NOT NULL | |

**Indexes:** `(template_kind, template_slug, created_at DESC)`.

### 3.3 Migration sequence (Alembic)

Four migrations across slices:

| Slice | Migration | Tables / changes |
|---|---|---|
| 8A | `m4..._phase8a_global_registry.py` | `template_bundles`, `template_team_definitions`, `template_category_definitions`, `template_agent_definitions`, `template_bundle_items`. Code-defined catalog seeded via `seed_global_templates.py` (one-shot, idempotent). |
| 8B | `n5..._phase8b_provisioning.py` | `workspace_template_links`, `template_provisioning_jobs` |
| 8C | (lineage state lives on `workspace_template_links` from 8B; 8C is service + API only — no migration) | — |
| 8D | `o6..._phase8d_upgrades.py` | `template_upgrade_proposals`, `template_publish_events` |

All migrations are additive. Existing tables (teams, categories, agent_profiles, agent_prompt_configs, prompt_versions, users, organizations) get **zero schema changes** in Phase 8. The lineage info lives entirely in the new join table.

---

## 4. Service architecture

Five services, all under `app/services/templates/`.

### 4.1 `TemplateRegistryService` (registry.py)

Read + write on the global template tables. Used by:
- The seed script
- Platform admin UI (deferred to Phase 8.5+; the API surface exists but is gated to platform-staff users)
- The provisioning service (reads only)

Key methods:
```
list_bundles(state='published') -> list[TemplateBundle]
get_bundle(slug, version='latest') -> TemplateBundle
get_team_definition(slug, version='latest') -> TemplateTeamDefinition
get_category_definition(slug, version='latest') -> TemplateCategoryDefinition
get_agent_definition(slug, version='latest') -> TemplateAgentDefinition
publish_bundle(bundle_id) -> emits a template_publish_events row + triggers upgrade detector
publish_agent_definition(slug, new_version, ...) -> same
```

### 4.2 `TemplateProvisioningService` (provisioning.py)

The core write engine. Materializes templates into workspace rows. The function `provision_bundle_for_org` is the single public entry point used by:
- `/templates/provision` (admin API)
- The auto-signup hook in `auth_router.py:register`
- A Celery task for bulk-provisioning (e.g. "install this new bundle for all existing orgs in cohort X")

Public surface:
```
provision_bundle_for_org(
    db, *, organization_id, bundle_slug, bundle_version='latest',
    triggered_by, triggered_by_user_id, dry_run=False,
) -> TemplateProvisioningJob

provision_items_for_org(
    db, *, organization_id, items: list[ProvisionItemSpec],
    triggered_by, triggered_by_user_id,
) -> TemplateProvisioningJob
```

**Algorithm (locked):**

```
1. Acquire pg_advisory_xact_lock(hash(organization_id, 'templates')) so two
   concurrent provisionings for the same org serialize.
2. Insert template_provisioning_jobs row with status='in_progress'.
3. Resolve the bundle's items (teams, categories, agents).
4. For each item, in dependency order (teams → categories → agents → configs → versions):
     a. Check workspace_template_links for an existing row keyed by
        (organization_id, source_template_kind, source_template_slug).
        If found AND lineage_state IN ('pristine','modified'): skip (idempotent).
     b. Otherwise materialize:
          - team   → create teams row (under a "Default Workspace" category if no category provisioned yet)
          - category → create categories row
          - agent  → create:
              agent_profiles (Phase 7A)
              agent_prompt_configs (org-scoped, Phase 7A)
              prompt_versions (state=draft, with the template's body) — Phase 7B
              publish that version via Phase 7B's publish_version()
                (BYPASSES eval gate even if eval_gate_required is true on the
                 template, by setting seeded_from_filesystem=true on the
                 prompt_versions row — matches the Phase 7D seed precedent.)
     c. Insert workspace_template_links row pointing at the new entity.
        Set lineage_state='pristine' + diff_summary_json={}.
5. Set template_provisioning_jobs.status = 'completed' (or 'partial' if any
   items failed); fill items_created / items_skipped / items_failed.
6. COMMIT.
```

Failure isolation: each item's creation is wrapped in `try / except`; on error the item is recorded in `failure_details_json` and the loop continues. A bundle with 9 items succeeds with 8 + records 1 failure, rather than rolling back the 8.

Dry-run mode: returns the would-be `requested_items_json` + skip flags but writes nothing. Job row is still appended (`status='completed'`, all counts zero) so the admin sees the planned action.

### 4.3 `DivergenceAnalysisService` (divergence.py)

Computes `lineage_state` for a workspace link by comparing the live workspace row against the source template definition at the row's `source_template_version`.

```
compute_lineage_for_link(db, link_id) -> DivergenceReport
recompute_all_for_org(db, organization_id) -> int  # rows updated
```

**Classification rules:**

- **`pristine`** — every modular section matches; every retrieval/model/tool config key matches; no extra prompt_versions on top.
- **`modified`** — 1–3 modular sections differ OR retrieval config has 1–3 key changes; same agent_type; no removed sections; no new published prompt_versions beyond the seeded one.
- **`heavily_modified`** — 4+ sections differ OR 4+ retrieval keys diverge OR a section was explicitly cleared OR tool_permissions added new entries.
- **`forked`** — workspace authored ≥ 1 new published `prompt_versions` beyond the seeded one OR the workspace's `agent_profile.display_name` / `slug` was changed (renamed).

The classification is **monotonic in severity**: once a link enters `forked`, it can only return to `pristine` via an explicit "reset to defaults" action.

Cached on `workspace_template_links.diff_summary_json`. Refresh triggers:
- on-demand via API
- nightly Celery beat (`recompute_template_divergence_all_orgs`)
- post-edit hook (fired by the prompt-config router after a publish)

### 4.4 `TemplateUpgradeService` (upgrade.py)

Detects new template versions, generates proposals, applies accepted changes.

```
detect_upgradable_links(db, template_kind, template_slug, new_version) -> list[link_ids]
  # called by the Celery task when a template version is published

generate_proposal(db, link_id, to_template_version) -> TemplateUpgradeProposal
  # 3-way diff: (workspace_current, template_old, template_new)
  # produces selectable_changes_json with toggles per section

accept_proposal(db, proposal_id, accepted_changes, actor_user_id) -> PromptVersion
  # creates a new prompt_versions draft in the workspace, applies the
  # accepted_changes on top of workspace_current, publishes via Phase 7B
  # publish_version (so the change is rollback-able via existing tooling).
  # Updates proposal.resolution_state to 'accepted' or 'partial_accepted'.

reject_proposal(db, proposal_id, actor_user_id) -> None

supersede_open_proposals(db, link_id) -> int
  # when a NEW upgrade arrives, open proposals on older versions become
  # 'superseded' so the inbox doesn't show stale items.
```

**Conflict detection:** a section is "in conflict" when:
- `workspace_current[section] != template_old[section]` (workspace customized it), AND
- `template_old[section] != template_new[section]` (template also changed it)

The proposal's `selectable_changes_json` marks conflict sections separately so the UI can warn before adoption.

**Atomicity:** acceptance is wrapped in one DB transaction + Phase 7B's advisory lock per agent_prompt_config. No partial-apply state is possible.

### 4.5 `WorkspaceTemplateResolver` (resolver.py)

Not a runtime resolver — a **helper** for the API layer + frontend. Given a workspace entity, returns:
- the source template metadata (kind, slug, version)
- the current lineage state
- a diff snippet for the badge ("3 prompt sections customized")
- "is upgradable?" boolean

Used by:
- `GET /agents/{id}` — augments the response with `lineage` metadata
- `GET /templates/links/{id}` — full detail

Pure read; no side effects.

### 4.6 Catalog (catalog.py)

The 9 teams + 11 categories + 9 agents from the brief, defined in pure Python as frozen dataclasses. Single source of truth. The seed script reads this and writes to the `template_*` tables.

```python
TEAMS = [
    TeamDef(slug="engineering", display_name="Engineering", ...),
    TeamDef(slug="sales", ...),
    ...
]
CATEGORIES = [...]
AGENTS = [
    AgentDef(
        slug="incident-investigator",
        agent_type="rag_synth",
        default_modular_prompt={
            "system": "...",
            "retrieval": "...",
            "citation": "...",
            "guardrails": "...",
        },
        default_retrieval_config={
            "top_k_final": 15,           # higher than default for incident review
            "max_graph_depth": 2,        # graph-depth boosting
            "rerank_strategy": "importance_aware",
        },
        ...
    ),
    ...
]
BUNDLES = [
    BundleDef(
        slug="engineering-starter",
        items=[
            BundleItem("team", "engineering"),
            BundleItem("category", "sprint-planning"),
            BundleItem("category", "incident-review"),
            BundleItem("category", "architecture-review"),
            BundleItem("agent", "incident-investigator"),
            BundleItem("agent", "technical-analyst"),
            BundleItem("agent", "executive-summarizer"),
        ],
    ),
    BundleDef(slug="sales-starter", ...),
    BundleDef(slug="all-in-starter", is_recommended_on_signup=True, ...),
]
```

CI check: a "catalog matches DB" test runs `seed_global_templates.py` in dry-run mode and asserts zero diff against `template_*` tables. Catches drift between code + DB.

---

## 5. Provisioning flow (sequence)

**Auto-signup path:**
```
POST /auth/register
  └─ Organization row inserted
  └─ User row inserted
  └─ db.commit()
  └─ (fire-and-forget) provision_bundle_for_org(
       organization_id=org.id,
       bundle_slug=settings.TEMPLATE_AUTO_PROVISION_BUNDLE,  # default 'all-in-starter'
       triggered_by='auto_signup',
       triggered_by_user_id=user.id,
     )
       ├─ acquire advisory lock
       ├─ resolve bundle items
       ├─ for each item: materialize → create workspace_template_links row
       └─ insert template_provisioning_jobs(status='completed')
```

Failures here log + write a `template_provisioning_jobs(status='failed')` row but **do not** roll back signup. Admin can re-run via `POST /templates/provision`.

**Manual provisioning path:**
```
POST /templates/provision
  body: {bundle_slug: 'sales-starter', dry_run: false}
  └─ TemplateProvisioningService.provision_bundle_for_org(...)
  └─ returns the job row with items_created / items_skipped counts
```

**Item-level provisioning (advanced):**
```
POST /templates/provision
  body: {items: [{type:'agent', slug:'sales-coach'}, {type:'category', slug:'discovery-call'}]}
```

---

## 6. Runtime integration (locked: zero changes)

The Phase 7 resolver reads from `agent_profiles` / `agent_prompt_configs` / `prompt_versions`. Phase 8 only adds rows to those tables (and a sibling `workspace_template_links` row pointing at them). The resolver never queries the template tables.

**Verification:** `tests/test_phase8b.py` runs the canonical fixture's `/rag/ask` flow against an org that's been auto-provisioned, and confirms the resolver's `prompt_version_id` points at a workspace-owned row — not a template row.

---

## 7. Lineage + divergence

### 7.1 The state machine

```
pristine ──┬──► modified ──┬──► heavily_modified ──► forked
           │               │
           └───────── reset_to_template ─────────────►(back to pristine)
```

Allowed transitions:
- `pristine → modified` / `→ heavily_modified` / `→ forked` based on `DivergenceAnalysisService` classification
- `modified → heavily_modified → forked` as edits accumulate
- `forked` is sticky — only an explicit "reset to defaults" returns to pristine

### 7.2 Reset to defaults

`POST /templates/links/{id}/reset` does:
1. Look up the source template's current version
2. Create a new prompt_versions draft with the template's body (drops workspace customizations)
3. Publish via Phase 7B publish_version
4. The new version becomes active; the workspace's previous active stays `state='published'` (rollback-able via Phase 7B)
5. Recompute lineage_state → `pristine`

The previous edits are **never destroyed** — they live in the prior published prompt_versions row. Admins can roll back to them via the standard Phase 7B rollback UI.

### 7.3 Diff summary shape

`diff_summary_json`:
```
{
  "prompt_sections_changed": ["system", "guardrails"],
  "retrieval_keys_changed": ["top_k_final"],
  "model_keys_changed": [],
  "tool_perms_added_allowed": ["web_search"],
  "tool_perms_removed_allowed": [],
  "tool_perms_added_denied": [],
  "tool_perms_removed_denied": [],
  "extra_published_versions_above_seed": 2,
  "renamed": false,
  "last_computed_at": "2026-05-18T12:34:56Z"
}
```

Drives the "Customized: prompt + retrieval" badge in the UI.

---

## 8. Upgrade system

### 8.1 Detection

When a platform admin publishes a new version of a template (bundle or definition):
1. `TemplateRegistryService.publish_*` writes the new row + inserts a `template_publish_events` row.
2. Celery task `template_upgrade_detector` (eager-triggered + nightly beat) scans `workspace_template_links` for rows whose `(source_template_kind, source_template_slug, source_template_version)` matches the OLD version.
3. For each affected link: generate a `template_upgrade_proposals` row with the 3-way diff.

### 8.2 Three-way diff

The proposal contains:
- `template_old` — the body at the link's current `source_template_version`
- `template_new` — the body at the new version
- `workspace_current` — the body live in the workspace row

For each modular section:
- If `template_old == template_new` → no change; skip.
- Else if `workspace_current == template_old` → "fast-forward" — workspace can adopt cleanly (no conflict).
- Else if `workspace_current == template_new` → workspace already happens to match the new template (admin made the same change).
- Else → **conflict**. The selectable change is flagged; the UI warns before acceptance.

Retrieval/model/tool configs go through the same logic per-key.

### 8.3 Acceptance flow

```
POST /templates/upgrade-proposals/{id}/accept
  body: { accepted_changes: ["section:system", "retrieval:top_k_final"] }
```

The service:
1. Loads the proposal + the current workspace version
2. Constructs the merged body: starts from `workspace_current`, overrides the accepted change keys with `template_new[key]`
3. Creates a new draft `prompt_versions` row with the merged body
4. Publishes via Phase 7B `publish_version` (which honors the eval gate if `eval_gate_required` is true on the agent profile)
5. Updates the proposal: `resolution_state='accepted'` or `'partial_accepted'`, `applied_prompt_version_id=<new version>`
6. Recomputes lineage_state on the link

If the eval gate fails, the proposal acceptance is rolled back; the `prompt_deployments(action='eval_gate_failed')` row records the failure; the proposal stays `open` so the admin can retry or reject.

### 8.4 Rejection

`POST /templates/upgrade-proposals/{id}/reject` sets `resolution_state='rejected'`. The next published version of the template will produce a fresh proposal — admins can re-evaluate at the next upgrade cycle.

### 8.5 Supersession

When a NEW version is published and a workspace's link is still on the original (pre-old) version, any open proposals targeting the intermediate version get `resolution_state='superseded'`. A fresh proposal targeting the latest is generated.

---

## 9. API design

Twelve new endpoints. All org-scoped (filter by `current_user.organization_id`). Mutation endpoints require `prompt_editor` or `org_admin` (Phase 7E RBAC dependencies).

### 9.1 Template registry (read-mostly, open to all authenticated users in org)

| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/templates/bundles` | filters: `category`, `state`, `recommended_only` | any user |
| GET | `/templates/bundles/{slug}` | returns full bundle + items | any user |
| GET | `/templates/teams` | list team definitions | any user |
| GET | `/templates/categories` | list category definitions | any user |
| GET | `/templates/agents` | list agent definitions, with retrieval + model defaults | any user |
| GET | `/templates/agents/{slug}` | full definition incl. modular_prompt | any user |

### 9.2 Provisioning

| Method | Path | Body | Auth |
|---|---|---|---|
| POST | `/templates/provision` | `{bundle_slug?, items?, dry_run?, mode}` | org_admin |
| GET | `/templates/provisioning-jobs` | paginated history | org_admin |
| GET | `/templates/provisioning-jobs/{id}` | full detail incl. failure_details_json | org_admin |

### 9.3 Lineage + workspace links

| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/templates/links` | filters: `entity_type`, `lineage_state`, `source_template_slug` | any user (filtered to org) |
| GET | `/templates/links/{id}` | full link + cached diff summary | any user |
| GET | `/templates/links/{id}/diff` | recomputes + returns fresh diff vs source template | any user |
| POST | `/templates/links/{id}/reset` | resets the linked entity to its template defaults | prompt_editor |

### 9.4 Upgrades

| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/templates/upgrade-proposals` | filters: `resolution_state`, `entity_type` | org_admin |
| GET | `/templates/upgrade-proposals/{id}` | full proposal incl. selectable_changes_json | org_admin |
| POST | `/templates/upgrade-proposals/{id}/accept` | `{accepted_changes: [...]}` | org_admin |
| POST | `/templates/upgrade-proposals/{id}/reject` | `{reason?}` | org_admin |

### 9.5 Observability (extends Phase 7F's `observability_router`)

| Method | Path | Body | Auth |
|---|---|---|---|
| GET | `/rag/observability/templates/adoption` | per-bundle: provisioned-orgs count, total items | any |
| GET | `/rag/observability/templates/divergence` | distribution of lineage_state across this org's links | any |
| GET | `/rag/observability/templates/upgrade-adoption` | per-bundle: open / accepted / rejected counts | any |

### 9.6 Validation rules

- Bundle slug + agent slug: `^[a-z][a-z0-9-]{2,63}$`
- Version: semver `^\d+\.\d+\.\d+$`
- `accepted_changes[]` items must match keys in `selectable_changes_json`
- Provisioning dry-run mode always returns a 200 with a planned-action payload even if items_created would be 0

---

## 10. Frontend architecture

Six new pages/components + small additions to existing Phase 7G surfaces.

### 10.1 Routes

```
/templates                           — template browser (gallery of bundles)
/templates/bundles/{slug}            — bundle detail page (what's inside, install button)
/templates/upgrades                  — open upgrade proposals inbox
/templates/upgrades/{id}             — upgrade detail + 3-way diff + accept toggles
/onboarding/starter-setup            — first-login modal (also accessible standalone)
```

The existing `/agents` + `/agents/{id}` pages from Phase 7G get a small **lineage badge** showing source template + lineage_state.

### 10.2 Components

| Component | Purpose |
|---|---|
| `templates/StarterSetupWizard.tsx` | Onboarding modal — list of recommended bundles, "Install all" / "Customize selection" / "Skip" |
| `templates/TemplateBrowserPage.tsx` | Gallery of all bundles, filterable by category, with install action |
| `templates/BundleDetailPage.tsx` | Bundle's items list, dependency graph (teams → categories → agents), install / dry-run buttons |
| `templates/UpgradeInboxPage.tsx` | List of open proposals across the workspace |
| `templates/UpgradeDetailPage.tsx` | 3-way diff per section + checkbox toggles for selective acceptance + conflict warnings |
| `templates/LineageBadge.tsx` | Inline component showing "From Engineering Starter v1.2 · Modified" — reusable on agent pages, version history, etc. |
| `templates/DivergenceSummary.tsx` | Section-by-section breakdown of customizations on one link |
| `templates/ResetToDefaultsButton.tsx` | Confirm-modal-wrapped action, calls `POST /templates/links/{id}/reset` |

### 10.3 Wizard flow

```
[ start ]
   │
   ▼
Show recommended bundles (default: all-in-starter)
   │
   ├──► [Install all]
   │       │
   │       ▼
   │     POST /templates/provision { bundle_slug: 'all-in-starter' }
   │       │
   │       ▼
   │     Poll /templates/provisioning-jobs/{id} until completed
   │       │
   │       ▼
   │     Show success + sample "Try /agents" CTA
   │
   ├──► [Customize selection]
   │       │
   │       ▼
   │     Multi-select grid of bundle cards → POST with `items`
   │
   └──► [Skip]
           │
           ▼
         Persist `org.template_setup_skipped = true` so wizard
         doesn't re-appear next login (deferred to 8E — for 8B
         we just close the modal)
```

### 10.4 Stack

Same as Phase 7G: React 18, Vite, TypeScript, React Router, Tailwind, Lucide icons, manual SSE where needed (provisioning is non-streaming for 8B; can stream progress events in a later slice).

---

## 11. Celery + background tasks

`app/celery_tasks/template_tasks.py` adds three tasks:

| Task | Schedule | Purpose |
|---|---|---|
| `template_upgrade_detector(template_kind, template_slug, new_version)` | eager-fired on publish | Generate `template_upgrade_proposals` rows for affected workspace links |
| `recompute_template_divergence_all_orgs` | beat: 02:30 UTC daily | Refresh `diff_summary_json` + `lineage_state` for every link |
| `bulk_provision_for_orgs(bundle_slug, org_ids)` | manual admin trigger | Backfill: install a new bundle for a cohort |

Registered in `app/celery_app.py` include list + beat schedule.

---

## 12. Phased implementation plan

Same pattern as Phase 7 — each slice is independently mergeable. Migration + models + service + API + tests + regression sweep.

### Phase 8A — Global registry + catalog seed

- **Schema:** `template_bundles`, `template_team_definitions`, `template_category_definitions`, `template_agent_definitions`, `template_bundle_items`. Indexes + CHECKs.
- **Models:** corresponding ORM classes.
- **Services:** `catalog.py` (Python definitions), `registry.py` (read-only CRUD), `seed_global_templates.py` (one-shot idempotent populator).
- **APIs:** `GET /templates/bundles`, `GET /templates/teams`, `GET /templates/categories`, `GET /templates/agents`, `GET /templates/agents/{slug}`, etc.
- **Tests:** schema + seed presence + catalog↔DB invariant.
- **Observability:** none yet.
- **Risks:** the catalog content is the biggest risk — 9 production-quality prompts × 8 modular sections each ≈ 72 prompt-section authoring tasks. We start with a "good enough" baseline cribbed from the existing filesystem prompts + the user's brief; refinement is a forever-task.

### Phase 8B — Provisioning service + auto-signup hook

- **Schema:** `workspace_template_links`, `template_provisioning_jobs`.
- **Models:** corresponding ORM.
- **Services:** `provisioning.py` with `provision_bundle_for_org` + `provision_items_for_org`. Advisory-lock-guarded.
- **Wiring:** `auth_router.py:register` calls `provision_bundle_for_org` fire-and-forget after `db.commit()`.
- **APIs:** `POST /templates/provision`, `GET /templates/provisioning-jobs`, `GET .../{id}`.
- **Tests:** `tests/test_phase8b.py`:
  - provision a fresh org → N workspace rows created
  - provision twice → no duplicates (skip count > 0 on second pass)
  - failure-isolated: one bad item doesn't roll back the others
  - cross-org isolation: org A's provisioning doesn't touch org B
  - concurrent provisioning serializes via advisory lock
  - the existing canonical fixture's `/rag/ask` flow works against the auto-provisioned org (runtime integration)
- **Observability:** none yet.
- **Risks:** the auto-signup hook is hot. Failures here must NEVER block signup. Guard with try/except + log; the job row records the failure for admin re-run.

### Phase 8C — Lineage + divergence

- **Schema:** none (uses `workspace_template_links.lineage_state` + `diff_summary_json` columns from 8B).
- **Services:** `divergence.py` with `compute_lineage_for_link` + `recompute_all_for_org`. Post-edit hooks in `prompt_configs_router` after `patch_version` + `publish_version`.
- **APIs:** `GET /templates/links`, `GET /templates/links/{id}`, `GET .../diff`, `POST .../reset`.
- **Tests:** classification correctness on every transition (pristine → modified → heavily_modified → forked); reset returns to pristine; diff payload shape; post-edit hook fires.
- **Observability:** none yet.
- **Risks:** classification thresholds are subjective. Document them clearly in the divergence service docstring; expose them as `settings` env vars so admins can tune (per-org overrides deferred to a later phase).

### Phase 8D — Upgrade system

- **Schema:** `template_upgrade_proposals`, `template_publish_events`.
- **Services:** `upgrade.py` with detect/generate/accept/reject/supersede + the eager Celery task.
- **APIs:** `GET /templates/upgrade-proposals`, `GET .../{id}`, `POST .../accept`, `POST .../reject`.
- **Tests:** 3-way diff correctness; conflict detection; partial acceptance; eval-gate interaction (acceptance failing eval rolls back proposal); supersession when newer version publishes; rollback via Phase 7B works on accepted upgrades.
- **Observability:** none yet (in 8E).
- **Risks:** the 3-way merge is the trickiest piece. We narrow scope: modular_prompt is per-section (string equality at the section level — no inline merge); retrieval/model are per-key (value-equality); tool_permissions are set-based (add/remove deltas). No fancy text merge; conflicts are surfaced for human resolution.

### Phase 8E — Observability + frontend (UI is split into 8F if scope demands)

- **Schema:** none.
- **Services:** read-only aggregations on top of `template_provisioning_jobs` + `workspace_template_links` + `template_upgrade_proposals`.
- **APIs:** `GET /rag/observability/templates/adoption`, `.../divergence`, `.../upgrade-adoption`.
- **Frontend:** `StarterSetupWizard`, `TemplateBrowserPage`, `BundleDetailPage`, `UpgradeInboxPage`, `UpgradeDetailPage`, `LineageBadge`. Sidebar gets a "Templates" entry.
- **Tests:** rollup correctness; UI builds clean (`tsc -b`).
- **Risks:** UI risk same as Phase 7G — can't visually verify without browser. Backend tests cover the data plane fully.

### Phase 8F — Marketplace foundation (architecture only)

- **Schema:** none beyond the `signature` + `manifest_hash` columns already on `template_bundles` in 8A.
- **Services:** `export_bundle(bundle_slug, version) -> SignedManifest` — deterministic JSON serialization + reserved signing slot.
- **APIs:** `POST /templates/export`, `POST /templates/import` (both admin-gated, deferred verification).
- **Tests:** export → import round-trip preserves all definitions.
- **Risks:** signature verification is intentionally a no-op in 8F. Real signing infrastructure is a future slice.

### Sequencing rationale

- 8A first → seed the catalog so 8B has something to provision.
- 8B second → provisioning is the headline feature. Auto-signup hook lands here.
- 8C third → lineage tracking is needed before upgrades make sense.
- 8D fourth → upgrades depend on lineage + provisioning.
- 8E fifth → observability + UI bundle.
- 8F sixth → architecture-only marketplace prep.

---

## 13. Migration strategy

| Migration | Touches existing tables? | Backward compat |
|---|---|---|
| 8A | No | New tables only. Existing orgs unaffected. |
| 8B | No | New tables only. Existing rows on `agent_profiles` / `agent_prompt_configs` / `prompt_versions` work unchanged (they just have no `workspace_template_links` row). |
| 8C | No | Service-only; uses 8B columns. |
| 8D | No | New tables only. |

**No backfill required.** Pre-existing orgs simply don't have lineage links — that's the `manual` state (not in the enum; represented by "no link row exists"). Admins can opt-in by calling `POST /templates/provision`. The UI surfaces a "You haven't installed any templates yet" prompt on the agents page.

---

## 14. Caching strategy

| What | Where | TTL / Invalidation |
|---|---|---|
| Template definitions (read-mostly) | In-process LRU keyed by `(kind, slug, version)` | 1 hour TTL. Invalidated on `template_publish_events` via Redis pub/sub (the existing Phase 7C pattern). |
| Bundle definitions (with item resolution) | In-process LRU keyed by `(bundle_slug, version)` | Same. |
| Divergence diff summaries | Materialized on `workspace_template_links.diff_summary_json` | Refreshed on demand + nightly Celery beat. |
| Upgrade proposals | None (rare reads, fresh queries) | — |

The catalog is small (~30 definitions × ~10 versions = 300 entries cap). Cache size 1024 is plenty.

**No caching on workspace rows.** The runtime resolver already has its own cache (Phase 7C) — Phase 8 doesn't second-guess it.

---

## 15. Scalability analysis

| Surface | Cost | Bound |
|---|---|---|
| Provisioning one org | O(items in bundle) | ≤ 50 items × a few ms each = ~250ms worst case |
| Divergence recompute one link | O(modular sections + retrieval keys) | ~20 comparisons; sub-ms |
| Divergence recompute all orgs (nightly) | O(orgs × links/org) | At 10k orgs × 30 links = 300k rows × <1ms = ~5min total |
| Upgrade detection | One SQL UPDATE per publish event | indexed; fast |
| Storage — template tables | tiny (~30 definitions × ~10 versions = 300 rows) | bounded |
| Storage — `workspace_template_links` | O(orgs × items) | at 10k orgs × 30 items = 300k rows; one row ~500B = 150MB |
| Storage — `template_provisioning_jobs` | O(provisioning events) | typically 1–2 per org/year |

This is small data even at large scale. No partitioning needed for the foreseeable future.

---

## 16. Operational risk analysis

| Risk | Mitigation |
|---|---|
| Auto-signup hook fails → user sees confusing empty state | try/except wrap; on failure, the org has zero templates but the wizard re-appears next login offering install. |
| Concurrent provisioning races on same org | Postgres advisory xact lock per `(org_id, 'templates')` — same pattern as Phase 7B publishes. |
| Catalog drift from DB | CI test re-runs `seed_global_templates.py` in dry-run + asserts zero changes against fixtures. |
| Bad template prompts ship to all new orgs | Every template publish creates a `template_publish_events` row; we add a 24-hour "soak" period before `recommended_on_signup=true` is honored for a new version (configurable via setting). |
| Upgrade applies to a customized workspace and breaks it | 3-way diff surfaces conflicts; admin sign-off required; the new version is published via Phase 7B so rollback is one click. |
| Eval gate blocks an upgrade acceptance | Proposal stays open; admin can lower the threshold, fix the prompt, or reject. The rollback-safety is built-in via Phase 7B. |
| Workspace deletes a category that's wired to provisioned agents | Cascade rules are already org-level; per-category deletes set `meeting_chunks.category_id=NULL` (Phase 1). The lineage link points at the workspace row's id, which is now gone; nightly recompute marks the link as `forked` (entity-deleted) — the dashboard surfaces this. |
| Template publish floods the upgrade inbox | Detection is per-org, lazy-generated; the Celery task batches into 100-org chunks. Workspaces with `lineage_state='forked'` are skipped (the proposal would be useless). |
| Cross-org leak via shared template id | Templates are read-only globals; workspace_template_links carry `organization_id`; every query filters. Dedicated test: `test_cross_org_link_leak` confirms a different org's link IDs return 404. |
| Marketplace signature spoofing (future) | Out of scope for 8F. The `signature` column is reserved; verification deferred until import/export ship. |
| Performance regression on nightly divergence recompute | Beat task batches per org + has a per-batch timeout. If a workspace has thousands of links (shouldn't happen but defensive), it's processed in chunks. |

---

## 17. Testing strategy

Mirrors Phase 7's per-slice ship-test + regression-sweep pattern.

### 17.1 Per-slice ship tests

| Slice | File | Headline assertions |
|---|---|---|
| 8A | `tests/test_phase8a.py` | Catalog seeded; CHECK constraints reject bogus values; bundle UNIQUE on (slug, version); read API returns expected definitions. |
| 8B | `tests/test_phase8b.py` | Single provision creates N workspace rows; double provision = no duplicates; cross-org isolation; auto-signup hook fires; failure-isolated; concurrent locks serialize; canonical-org `/rag/ask` works against an auto-provisioned org. |
| 8C | `tests/test_phase8c.py` | Pristine after provision; modified after 1 section edit; heavily_modified after 4+ edits; forked after authoring a new version; reset → pristine; post-edit hook fires; diff summary shape. |
| 8D | `tests/test_phase8d.py` | New version publish triggers proposal creation; 3-way diff finds conflicts correctly; accept creates a new prompt_version; reject closes proposal; supersession on intermediate version; eval-gate interaction; rollback via Phase 7B works post-acceptance. |
| 8E | `tests/test_phase8e.py` | Observability rollups correct; frontend build passes `tsc -b`. |
| 8F | `tests/test_phase8f.py` | Export → import round-trip preserves all definitions. |

### 17.2 Cross-cutting tests

- **Tenant isolation** — covered per slice (mandatory pattern).
- **Concurrent provisioning** — 8B includes a threaded smoke test (same as Phase 7B's concurrent publish).
- **Eval-gate interaction** — 8D includes the case where an upgrade acceptance fails its eval gate; proposal stays open; no workspace-state corruption.
- **Rollback via Phase 7B** — 8D includes a test that confirms `POST /prompt-configs/{id}/rollback` works on an upgrade-applied version.

### 17.3 Performance tests

- `test_provisioning_p95` — provisioning the `all-in-starter` bundle for 100 fresh orgs in <30s.
- `test_divergence_recompute_p95` — recomputing 10k links in <60s.

### 17.4 Regression sweep

After every slice, run the full ~454-test suite + every prior Phase 8 slice. Net test count grows monotonically.

---

## 18. Future extensibility — marketplace foundation

This phase establishes the **building blocks** for a marketplace without shipping the marketplace itself.

| Marketplace need | What 8A–8F gives | What's deferred |
|---|---|---|
| Stable manifest shape | `template_bundles.manifest_hash` deterministic over bundle items | — |
| Signing | `template_bundles.signature` column reserved | Actual signing key + verification logic |
| Versioning | `version` column + UNIQUE (slug, version) | — |
| Discovery | `GET /templates/bundles` API | Cross-platform discovery server |
| Import/export | `POST /templates/export`, `POST /templates/import` (8F) | Cross-platform transport (HTTPS pull from registry server) |
| Custom packs | Bundles can be authored as new code-defined `BundleDef` entries OR via admin UI in a later slice | UI for non-staff authoring |
| Industry-specific packs | Bundle's `category` field already supports filtering | Domain-specific bundle bundles (e.g. "healthcare-starter") |
| Forking + republishing | Workspace can `fork` a link; export the forked artifact via 8F | Cross-workspace forking + publish-back |

The design choice that makes this all work: **bundles are content, not code**. A new bundle is an INSERT into `template_bundles` + a few rows in `template_bundle_items`. The platform doesn't need a redeploy to ship a new bundle.

---

## 19. Folder / module structure (full)

```
alembic/versions/
    m4..._phase8a_global_registry.py
    n5..._phase8b_provisioning.py
    o6..._phase8d_upgrades.py

app/
    db/
        models.py                                  # MODIFIED: + 9 new model classes
    schemas/
        template_schema.py                         # NEW: internal types (TeamDef, CategoryDef, AgentDef, BundleDef, ProvisionItemSpec, DivergenceReport, ...)
        template_api_schema.py                     # NEW: HTTP request/response shapes (strict-envelope Pydantic)
    services/
        templates/
            __init__.py                            # NEW
            catalog.py                             # NEW: code-defined definitions (9+11+9 items)
            registry.py                            # NEW: TemplateRegistryService
            provisioning.py                        # NEW: TemplateProvisioningService
            divergence.py                          # NEW: DivergenceAnalysisService
            upgrade.py                             # NEW: TemplateUpgradeService
            resolver.py                            # NEW: WorkspaceTemplateResolver (read helper for API/UX)
            seed_catalog.py                        # NEW: one-shot DB populator
    api/
        templates_router.py                        # NEW: all /templates endpoints
        observability_router.py                    # MODIFIED: + 3 template aggregations
        auth_router.py                             # MODIFIED: + auto-provision hook on register
        prompt_configs_router.py                   # MODIFIED: + post-edit divergence-refresh hook
    celery_tasks/
        template_tasks.py                          # NEW: detector + nightly recompute + bulk provision
    celery_app.py                                  # MODIFIED: + include + beat schedule
    config/
        settings.py                                # MODIFIED: + TEMPLATE_AUTO_PROVISION_BUNDLE, TEMPLATE_DIVERGENCE_THRESHOLDS, TEMPLATE_PUBLISH_SOAK_HOURS
    scripts/
        seed_global_templates.py                   # NEW: CLI wrapper around services/templates/seed_catalog.py
        backfill_template_lineage.py               # NEW: optional — links existing workspace rows to templates retroactively where slugs match

meeting_ai_frontend/src/features/templates/        # NEW
    api.ts                                         # typed wrappers over /templates/*
    types.ts                                       # TS mirrors of backend response shapes
    pages/
        StarterSetupWizard.tsx                     # onboarding modal (also standalone route)
        TemplateBrowserPage.tsx
        BundleDetailPage.tsx
        UpgradeInboxPage.tsx
        UpgradeDetailPage.tsx
    components/
        BundleCard.tsx
        LineageBadge.tsx
        DivergenceSummary.tsx
        ThreeWayDiff.tsx                           # rendering the upgrade diff
        ResetToDefaultsButton.tsx
    hooks/
        useTemplateRegistry.ts
        useWorkspaceLinks.ts
        useUpgradeProposals.ts

tests/
    test_phase8a.py                                # NEW
    test_phase8b.py                                # NEW
    test_phase8c.py                                # NEW
    test_phase8d.py                                # NEW
    test_phase8e.py                                # NEW
    test_phase8f.py                                # NEW
    fixtures/
        catalog_fixtures.py                        # NEW: minimal test catalog (3 teams + 3 cats + 3 agents + 1 bundle) for fast tests
```

---

## 20. Integration points with existing code (line-level expectations)

| File | Change |
|---|---|
| `app/api/auth_router.py:register` | + 6 lines: after `db.commit()`, fire-and-forget call to `provision_bundle_for_org(... triggered_by='auto_signup')`. Wrapped in try/except; failures log + record `template_provisioning_jobs(status='failed')` but never block signup. |
| `app/api/prompt_configs_router.py:patch_version` / `publish_prompt_version` | + post-edit hook: enqueue `recompute_lineage_for_link(link_id)` if the version's `agent_prompt_config_id` has a workspace_template_link row. |
| `app/api/agents_router.py:get_agent_profile` | + augment response with `lineage` block via `WorkspaceTemplateResolver.lineage_for_agent_profile(profile_id)`. |
| `app/db/models.py` | + 9 new ORM classes; **no changes to existing models**. |
| `app/services/agents/publish.py` | No changes. Upgrade acceptance goes through the existing `publish_version` and inherits its eval gate + rollback semantics. |
| `app/services/agents/resolver.py` | **No changes.** The runtime is template-agnostic. |
| `app/celery_app.py` | + 1 include + 1 beat entry + 1 eager task wiring. |
| `app/config/settings.py` | + 3 env-var-backed settings (auto-bundle, divergence thresholds, publish soak hours). |
| `main.py` | + 1 router include: `templates_router`. |
| `meeting_ai_frontend/src/app/router.tsx` | + 5 routes. |
| `meeting_ai_frontend/src/shared/components/Sidebar.tsx` | + 1 nav entry: "Templates" (icon: `Package` from lucide). |

---

## 21. Acceptance criteria

Phase 8 is "done" when:

1. All ~454 prior tests pass. New Phase 8 tests pass. Net suite: ~454 + ~100 expected new tests.
2. Migration head advances to the final 8D revision.
3. A fresh user signup creates an org that has a usable set of teams + categories + agents + prompts within 1 second of registration.
4. The Phase 7 runtime serves `/rag/ask` against an auto-provisioned org with no behavioral difference vs a hand-configured org.
5. An admin can edit a provisioned agent's system prompt; the link's `lineage_state` flips to `modified` on next divergence recompute (or immediately via post-edit hook).
6. Resetting a link to defaults creates a new prompt_version with the template's body, publishes it, and lineage_state returns to `pristine`.
7. Publishing a new template version creates upgrade proposals for affected workspaces.
8. An admin can accept selected sections of an upgrade; the workspace gets a new published prompt_version reflecting the merge; the change is rollback-able via the standard Phase 7B UI.
9. The frontend dashboard surfaces all six new pages + lineage badges on existing agent pages. `tsc -b` clean; Vite build succeeds.
10. Cross-org isolation tested: no scenario allows org A's actions to affect org B's templates, links, jobs, or proposals.

When all 10 are green, Phase 8 ships and Phase 9 (live in-meeting copilot) begins by consuming the resolved configs of the provisioned `live_copilot` agent.

---

## 22. Backend interfaces (locked signatures)

These are the headline service surfaces. Other internal helpers omitted for brevity.

```python
# app/services/templates/registry.py

def list_bundles(
    db: Session, *, state: BundleState = 'published',
    category: Optional[str] = None,
    recommended_only: bool = False,
) -> list[TemplateBundle]: ...

def get_bundle(
    db: Session, *, slug: str, version: str = 'latest',
) -> Optional[TemplateBundle]: ...

def get_agent_definition(
    db: Session, *, slug: str, version: str = 'latest',
) -> Optional[TemplateAgentDefinition]: ...


# app/services/templates/provisioning.py

@dataclass
class ProvisionItemSpec:
    item_type: Literal['team', 'category', 'agent']
    slug: str
    version: Optional[str] = None  # None = 'latest'

@dataclass
class ProvisioningResult:
    job_id: UUID
    status: Literal['completed', 'partial', 'failed']
    items_created: int
    items_skipped: int
    items_failed: int
    failure_details: list[dict]
    workspace_link_ids: list[int]  # the rows now linked

def provision_bundle_for_org(
    db: Session, *,
    organization_id: UUID,
    bundle_slug: str,
    bundle_version: str = 'latest',
    triggered_by: Literal['auto_signup','manual','admin_api','celery'],
    triggered_by_user_id: Optional[UUID],
    dry_run: bool = False,
) -> ProvisioningResult: ...

def provision_items_for_org(
    db: Session, *,
    organization_id: UUID,
    items: list[ProvisionItemSpec],
    triggered_by: str,
    triggered_by_user_id: Optional[UUID],
    dry_run: bool = False,
) -> ProvisioningResult: ...


# app/services/templates/divergence.py

@dataclass(frozen=True)
class DivergenceReport:
    link_id: int
    lineage_state: Literal['pristine','modified','heavily_modified','forked']
    diff_summary: dict
    computed_at: datetime

def compute_lineage_for_link(
    db: Session, *, link_id: int,
) -> DivergenceReport: ...

def recompute_all_for_org(
    db: Session, *, organization_id: UUID,
) -> int: ...  # rows updated


# app/services/templates/upgrade.py

@dataclass
class UpgradeProposalDetail:
    proposal_id: UUID
    workspace_template_link_id: int
    entity_type: str
    from_template_version: str
    to_template_version: str
    selectable_changes: list[SelectableChange]
    conflict_sections: list[str]

def detect_upgradable_links(
    db: Session, *,
    template_kind: str, template_slug: str, new_version: str,
) -> list[int]: ...

def generate_proposal(
    db: Session, *, link_id: int, to_version: str,
) -> Optional[UUID]: ...

def accept_proposal(
    db: Session, *,
    proposal_id: UUID,
    accepted_changes: list[str],
    actor_user_id: Optional[UUID],
) -> UUID: ...  # new prompt_version_id


# app/services/templates/resolver.py

@dataclass(frozen=True)
class LineageInfo:
    source_template_kind: str
    source_template_slug: str
    source_template_version: str
    source_bundle_id: Optional[UUID]
    source_bundle_version: Optional[str]
    lineage_state: str
    diff_summary: dict

def lineage_for_agent_profile(
    db: Session, *, agent_profile_id: UUID, organization_id: UUID,
) -> Optional[LineageInfo]: ...
```

TypeScript shapes (`meeting_ai_frontend/src/features/templates/types.ts`):

```typescript
export interface TemplateBundle {
  id: string;
  slug: string;
  display_name: string;
  description: string | null;
  category: string;
  version: string;
  state: 'draft' | 'published' | 'deprecated';
  is_recommended_on_signup: boolean;
  items: TemplateBundleItem[];
}

export interface WorkspaceTemplateLink {
  id: number;
  entity_type: 'team' | 'category' | 'agent_profile' | 'prompt_config' | 'prompt_version';
  entity_id: string | number;
  source_template_kind: string;
  source_template_slug: string;
  source_template_version: string;
  source_bundle_id: string | null;
  lineage_state: 'pristine' | 'modified' | 'heavily_modified' | 'forked';
  diff_summary: DiffSummary;
  provisioned_at: string;
}

export interface UpgradeProposal {
  id: string;
  workspace_template_link_id: number;
  entity_type: string;
  from_template_version: string;
  to_template_version: string;
  resolution_state: 'open' | 'accepted' | 'partial_accepted' | 'rejected' | 'superseded';
  selectable_changes: SelectableChange[];
  conflict_sections: string[];
}
```

---

## 23. Open questions (for sign-off)

These are the decisions to lock before "go" on 8A:

1. **Auto-provision on signup default** — install `all-in-starter` (every default team + category + agent) or `minimal-starter` (one general-purpose agent + one team + one meeting type)? (Recommendation: `all-in-starter` — the user's brief is explicit about "instantly receive a production-ready AI operating environment". Override via env var.)
2. **Provisioning hook synchronous vs async** — call inline in `register` (adds ~250ms) or fire-and-forget via Celery (async, but adds a Celery dependency in the signup hot path)? (Recommendation: **inline in `register`** for 8B. Latency is acceptable; the visual UX is "signup succeeded and your workspace already has agents". Celery is an optional optimization later.)
3. **Catalog freshness** — should template definitions be versioned with the platform release, or live-editable via the admin UI? (Recommendation: versioned-with-release for Phase 8. The admin UI for editing global templates is a Phase 8.7 deferred slice.)
4. **Eval gate on auto-provisioned versions** — every seeded version has `seeded_from_filesystem=true` (Phase 7D bypasses the validator). Should provisioning skip eval too? (Recommendation: yes — seeded prompts are already validated at the catalog level. The eval gate kicks in when admins author NEW versions, same as today.)
5. **Backfill existing orgs** — should we retroactively link existing workspace rows to templates where slugs match? (Recommendation: no for Phase 8. Pre-existing rows stay "manual" — no link row. Admins can opt-in via a one-shot `backfill_template_lineage.py` CLI that does conservative slug+content matching.)
6. **Lineage classification thresholds** — exact section-count cutoffs for `modified` vs `heavily_modified`? (Recommendation: 1–3 sections changed = modified; 4+ = heavily_modified. Exposed as `TEMPLATE_HEAVY_MOD_THRESHOLD` setting.)
7. **Upgrade detection cadence** — eager (on every publish event) + nightly safety net, or nightly only? (Recommendation: both — eager for fast feedback, nightly to catch missed events.)
8. **Publish soak period** — should a new template version wait 24h before being eligible for upgrade proposals? (Recommendation: yes for the auto-recommendation flag; no for upgrades. Admin can manually trigger upgrade detection if they want immediate.)
9. **Marketplace signature today** — should `manifest_hash` be computed at publish time, or deferred? (Recommendation: compute now — it's cheap, and gives us drift detection even pre-marketplace.)
10. **Frontend wizard skip persistence** — where to store "user dismissed the starter wizard"? On `users.metadata_json` or a new `user_preferences` table? (Recommendation: defer to Phase 8E; for 8B the wizard is one-time per login session.)

On "go", I'll confirm each of these and proceed with 8A: migration + models + catalog + seed + read API + ship test.

---

## 24. Summary diagram

```
                       ┌─────────────────────────────────────────┐
                       │       GLOBAL TEMPLATE REGISTRY          │
                       │       (immutable, versioned)            │
                       │                                         │
                       │  template_bundles                       │
                       │  template_team_definitions              │
                       │  template_category_definitions          │
                       │  template_agent_definitions             │
                       │  template_bundle_items                  │
                       └────────────────┬────────────────────────┘
                                        │
                          (read-only)   │   (admin publishes new version)
                                        │              │
                                        ▼              ▼
                       ┌────────────────────────────────────────┐
                       │     PROVISIONING + UPGRADE SERVICES    │
                       │                                        │
                       │  TemplateRegistryService               │
                       │  TemplateProvisioningService           │
                       │  TemplateUpgradeService                │
                       │  DivergenceAnalysisService             │
                       │  WorkspaceTemplateResolver (read help) │
                       └────────────────┬───────────────────────┘
                                        │ (writes workspace rows
                                        │  + lineage links)
                                        ▼
                       ┌────────────────────────────────────────┐
                       │    WORKSPACE-OWNED ROWS (Phase 1-7)    │
                       │                                        │
                       │  teams                                 │
                       │  categories                            │
                       │  agent_profiles                        │
                       │  agent_prompt_configs                  │
                       │  prompt_versions                       │
                       │  workspace_template_links (NEW)        │
                       │  template_provisioning_jobs (NEW)      │
                       │  template_upgrade_proposals (NEW)      │
                       └────────────────┬───────────────────────┘
                                        │ (Phase 7 runtime reads
                                        │  workspace rows ONLY)
                                        ▼
                       ┌────────────────────────────────────────┐
                       │        PHASE 7 RUNTIME (unchanged)     │
                       │                                        │
                       │  resolve_agent_runtime_config()        │
                       │  ask_stream() → planner → retrieval    │
                       │  → synthesizer → audit                 │
                       └────────────────────────────────────────┘
```

The arrow from "global registry" to "runtime" is **dotted (never direct)**. Every workspace gets its own materialized copies. Editing one workspace can never reach another.
