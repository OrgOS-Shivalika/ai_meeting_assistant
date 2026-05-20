# Phase 8 — Prebuilt Enterprise Template System

A two-layer template system that lets the platform ship curated AI
agents, meeting categories, and team archetypes — and lets each
workspace install, customize, and upgrade them without losing edits.

**Total scope:** 5 slices (8A–8E) · 9 new tables · 105 passing tests ·
backend services + REST API + React admin UI.

---

## Table of contents

1. [Goals + locked architectural commitments](#1-goals--locked-architectural-commitments)
2. [The two-layer architecture](#2-the-two-layer-architecture)
3. [Data model](#3-data-model)
4. [Slice 8A — Global template registry](#4-slice-8a--global-template-registry)
5. [Slice 8B — Workspace provisioning](#5-slice-8b--workspace-provisioning)
6. [Slice 8C — Divergence + lineage](#6-slice-8c--divergence--lineage)
7. [Slice 8D — Upgrade proposals + 3-way diff](#7-slice-8d--upgrade-proposals--3-way-diff)
8. [Slice 8E — Observability + frontend](#8-slice-8e--observability--frontend)
9. [End-to-end flows](#9-end-to-end-flows)
10. [Integration points](#10-integration-points)
11. [Key invariants](#11-key-invariants)
12. [Out of scope (deferred)](#12-out-of-scope-deferred)

---

## 1. Goals + locked architectural commitments

### Goals

- Ship the platform with **9 teams, 11 meeting categories, 9 agents, 6
  bundles** out of the box.
- Let new workspaces install a curated bundle in one click + start
  using it immediately.
- Let workspaces freely edit their copies without the platform stomping
  changes on the next release.
- When the platform ships a new template version, the affected
  workspace admin gets an **inbox of upgrade proposals** with a 3-way
  diff — they decide which changes to adopt.

### Locked architectural commitments

| # | Rule | Why |
|---|------|-----|
| 1 | Runtime NEVER executes from global templates | Templates are immutable platform property; runtime must be workspace-owned so users can edit safely. |
| 2 | Platform upgrades NEVER overwrite workspace edits automatically | Eliminates the "platform pushed an update and broke my prompt" failure mode. |
| 3 | Schema additions are non-destructive | No changes to existing tables in Phase 8. New tables only. |
| 4 | Multi-tenant by `organization_id` with CASCADE | Cross-org isolation must be structural, not enforced by application code. |
| 5 | Append-only audit for event tables | `template_publish_events` survives org/link deletion (BIGSERIAL, no FK on volatile pointers). |
| 6 | Cross-org access returns 404, not 403 | Don't leak existence. |
| 7 | Eval-gated changes (Phase 7B/7H) gate upgrade acceptance too | Adopting an upgrade goes through `publish_version` → runs validator + eval gate. |

---

## 2. The two-layer architecture

```
   ┌──────────────────────────────────────────────────────────────────┐
   │                     LAYER 1: PLATFORM CATALOG                    │
   │                       (immutable, global)                        │
   │                                                                  │
   │   template_bundles ──┐                                           │
   │                      ├─→ template_bundle_items ──┐               │
   │                      │                            │              │
   │   template_team_definitions                       │              │
   │   template_category_definitions   ←───────────────┘ (by slug)    │
   │   template_agent_definitions                                     │
   │                                                                  │
   │   Identity:  (slug, version)                                     │
   │   Owned by:  platform admins                                     │
   │   Read by:   provisioning service + admin browse UI              │
   │   Written:   seed script + future admin tooling                  │
   └──────────────────────────────────────────────────────────────────┘
                              │
                              │  provision_bundle_for_org
                              │  (one-time materialization)
                              ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                     LAYER 2: WORKSPACE COPIES                    │
   │                  (mutable, scoped to one org)                    │
   │                                                                  │
   │   categories                  ←──┐                               │
   │   agent_profiles              ←──┤  workspace_template_links     │
   │   agent_prompt_configs        ←──┘  (lineage pointers)           │
   │   prompt_versions             ←──── (versioned bodies)           │
   │                                                                  │
   │   Identity:  uuid / int                                          │
   │   Owned by:  organization_id                                     │
   │   Read by:   the runtime (Phase 7 resolver)                      │
   │   Written:   workspace admins via /prompt-configs/* APIs         │
   └──────────────────────────────────────────────────────────────────┘
                              │
                              │  publish_agent_definition (v1.1)
                              │  → emit_publish_event
                              │  → template_upgrade_detector
                              ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                  LAYER 3: UPGRADE PROPOSAL FLOW                  │
   │                                                                  │
   │   template_publish_events  (append-only audit)                   │
   │           │                                                      │
   │           ▼                                                      │
   │   detect_upgradable_links  →  generate_proposal  per link        │
   │           │                                                      │
   │           ▼                                                      │
   │   template_upgrade_proposals (open)                              │
   │     · diff_json (3-way)                                          │
   │     · selectable_changes_json (per-key checkboxes)               │
   │     · conflict_keys_json                                         │
   │           │                                                      │
   │     admin reviews → accept / partial_accept / reject             │
   │           │                                                      │
   │           ▼                                                      │
   │   on accept: create new prompt_version via Phase 7B publish      │
   │              → eval gate fires → workspace bumps to new version  │
   └──────────────────────────────────────────────────────────────────┘
```

**Key isolation property:** Layer 1 has zero workspace-specific data.
Layer 2 has zero platform-specific data (only a lineage pointer in
`workspace_template_links` pointing back at a `(slug, version)` in
Layer 1). They evolve independently.

---

## 3. Data model

### New tables introduced in Phase 8

| Table | Slice | Purpose |
|-------|-------|---------|
| `template_bundles` | 8A | Named groups of items (e.g. "all-in-starter") |
| `template_bundle_items` | 8A | Items in a bundle (FK to bundle, item_slug + item_type) |
| `template_team_definitions` | 8A | Team archetypes (e.g. "engineering") |
| `template_category_definitions` | 8A | Meeting type templates (e.g. "incident-postmortem") |
| `template_agent_definitions` | 8A | Agent prompt + retrieval config templates |
| `workspace_template_links` | 8B | Per-org lineage pointer: workspace_entity_id → (template_slug, version) + lineage_state |
| `template_provisioning_jobs` | 8B | Audit log of bundle installs (status, items_created/skipped/failed) |
| `template_upgrade_proposals` | 8D | Per-link "v1.1 is out; here's the 3-way diff" record |
| `template_publish_events` | 8D | Append-only audit of every `publish_agent_definition` call |

### What does NOT change

- `meetings`, `users`, `agent_profiles`, `agent_prompt_configs`,
  `prompt_versions`, `prompt_deployments`, `categories` — all
  pre-existing tables get **zero schema changes** in Phase 8.
- Existing FastAPI routes get **zero behavioral changes**, except:
  - `/auth/register` adds an after-commit hook calling
    `auto_provision_for_new_org` (8B)
  - `/prompt-configs/{id}` PATCH + POST publish add an after-commit
    hook calling `compute_lineage_for_link` (8C)

---

## 4. Slice 8A — Global template registry

**Goal:** Define + populate the platform catalog. Read-only at runtime.

### What ships

- **Schema:** 5 tables (see [Data model](#3-data-model))
- **Catalog:** [app/services/templates/catalog.py](app/services/templates/catalog.py) — code-defined, **not** filesystem JSON. Compiled into the seed script + asserted against the DB on startup (drift detection).
  - 9 teams (engineering, sales, hr, product, customer-success, security, finance, executive, marketing)
  - 11 categories (daily-standup, sprint-planning, incident-postmortem, board-meeting, all-hands, discovery-call, demo-call, customer-escalation, interview, performance-review, strategy-session)
  - 9 agents (full modular prompts including system / behavior / team_rules / meeting_type / guardrails / retrieval / citation / output sections)
  - 6 bundles (engineering-starter, sales-starter, hr-starter, customer-success-starter, executive-starter, **all-in-starter** with `is_recommended_on_signup=True`)
- **Service:** [app/services/templates/registry.py](app/services/templates/registry.py) — read-only with `version='latest'` semver resolution
- **Seed script:** [app/scripts/seed_global_templates.py](app/scripts/seed_global_templates.py) — idempotent populator; detects catalog drift via manifest hash
- **HTTP:** 8 read endpoints under `/templates/*` (open to any authenticated user)

### Why "code-defined catalog" instead of JSON files

Catalog content is **part of the codebase**:
- Type-checked + caught by import-time validation
- Reviewed via PR — no "I dropped a JSON file in prod" surprises
- Compiled into the manifest hash so we can detect "DB drifted from
  shipped code" at startup

### Version semantics

Every catalog row has a semver `version`. `get_*(slug, version='latest')`
resolves to highest published version. Drafts and deprecated rows are
excluded. The provisioning service always materializes a **specific
version** so workspaces have a stable lineage pointer.

---

## 5. Slice 8B — Workspace provisioning

**Goal:** Install a catalog bundle into one workspace, creating
runtime-executable workspace rows.

### What ships

- **Schema:** `workspace_template_links` + `template_provisioning_jobs`
- **Service:** [app/services/templates/provisioning.py](app/services/templates/provisioning.py)
  - `provision_bundle_for_org(org_id, bundle_slug)` — install one bundle
  - `provision_items_for_org(org_id, items=[...])` — freeform item list
  - `auto_provision_for_new_org(org_id, user_id, bundle_slug)` — signup hook
- **Phase 7B bypass:** seed-time prompt versions skip the validator + eval gate via `seeded_from_filesystem=True` (extended this session in [app/services/agents/publish.py](app/services/agents/publish.py))
- **Auto-signup hook** in [app/api/auth_router.py:44-54](app/api/auth_router.py#L44-L54)
- **Setting:** `TEMPLATE_AUTO_PROVISION_BUNDLE` (default `all-in-starter`; empty disables)

### Concurrency

Provisioning takes a Postgres advisory transactional lock keyed by
`organization_id`. Two concurrent install requests for the same org
serialize; cross-org installs run in parallel. Soft-active dedup via
partial unique index on `workspace_template_links` means re-running
the same install is a no-op (`items_skipped=N`).

### Schema-mismatch resolution

The platform catalog has `team` + `category` items. The existing
workspace schema only has a `categories` table (which carries
`category_id` as parent / "team" pointer). Resolution:

| Catalog item type | Workspace materialization |
|-------------------|---------------------------|
| `team` | `categories` row (parent — no category_id set) + `workspace_template_links` row |
| `category` | `categories` row (child — points at team's category_id) + link |
| `agent` | `agent_profiles` + `agent_prompt_configs` + initial `prompt_versions` (published as seeded) + link |

This lets us ship 9 teams + 11 categories without adding a `teams`
table to existing schema (rule #3 — non-destructive).

### What lives in `workspace_template_links`

Each row says: "**this workspace entity** (`entity_type`,
`entity_id_uuid` OR `entity_id_int`) was provisioned from
**this catalog item** (`source_template_kind`,
`source_template_slug`, `source_template_version`) on this date."

XOR check ensures exactly one of `entity_id_uuid` / `entity_id_int`
is set (uuid for agent_profile, int for category).

---

## 6. Slice 8C — Divergence + lineage

**Goal:** Track how far each workspace copy has drifted from its
source template. Surface this in the UI so admins know what's
customized.

### What ships

- **Service:** [app/services/templates/divergence.py](app/services/templates/divergence.py) — section-by-section diff
- **Lineage state machine:** `pristine → modified → heavily_modified → forked` (forked is sticky via version count)
- **Reset:** [app/services/templates/reset.py](app/services/templates/reset.py) — `reset_link_to_template` creates a new `prompt_version` with template body + publishes via Phase 7B (so prior versions stay rollback-able)
- **Post-edit hooks:** PATCH + POST publish on `/prompt-configs/*` recompute lineage after commit
- **HTTP:** `GET /templates/links`, `GET /templates/links/{id}`, `GET /templates/links/{id}/diff`, `POST /templates/links/{id}/reset`

### Lineage state rules

```
  Compare every modular section + retrieval key + model key
  + tool permission set against the source template's defaults:

    0 differences        → pristine
    1–2 differences      → modified
    3+ differences       → heavily_modified
    workspace has 3+ distinct prompt_version rows since provisioning
                         → forked   (STICKY — never reverts)
```

`forked` is sticky because: once a workspace has actively iterated
3+ times, they've taken ownership. Treating their work as
"recoverable to pristine" misrepresents what's happening.

### Reset semantics

Resetting an agent link doesn't **delete** workspace versions — it
publishes a **new version** with the template's content. The old
versions stay reachable via Phase 7B's `/rollback`. This means
"reset" is fully undoable.

Resetting a category link **overwrites** the category row's fields
(name/description/color/icon) — no version history table.

---

## 7. Slice 8D — Upgrade proposals + 3-way diff

**Goal:** When platform ships v1.1 of a template, every workspace
on v1.0 gets an inbox proposal showing what changed + a per-key
checkbox for which changes to adopt.

### What ships

- **Schema:** `template_upgrade_proposals` + `template_publish_events`
- **Service:** [app/services/templates/upgrade.py](app/services/templates/upgrade.py)
- **Publish helpers** in [app/services/templates/registry.py](app/services/templates/registry.py):
  - `publish_agent_definition(slug, version, ...)` — INSERT + emit publish event + dispatch detector
  - `publish_category_definition(...)` — same for categories
- **Celery task:** [app/celery_tasks/template_tasks.py](app/celery_tasks/template_tasks.py) — `template_upgrade_detector`
  - **Note:** dispatch is now **synchronous** (the Celery `.delay()` path was a footgun — fixed this session). Publishing is a rare admin action; running inline keeps the publish→proposal contract deterministic. The Celery beat schedule is the safety net.
- **HTTP:** 4 endpoints — list, detail, accept, reject

### 3-way diff classification

For each section / retrieval key / model key / tool permission set:

```
                    template_old  ==  template_new
                    ────────────  ──  ────────────
                                 ↓
                          no change           → omit from proposal entirely

  workspace_current == template_old           → "fast_forward"
                                                  (workspace hasn't customized;
                                                   safe to adopt cleanly)

  workspace_current == template_new           → "already_matches_new"
                                                  (workspace happens to have
                                                   the same value)

  workspace differs from BOTH old and new     → "conflict"
                                                  (real merge decision)
```

The UI defaults `fast_forward` + `already_matches_new` as **checked**.
Conflicts default **unchecked** — admin must explicitly opt in.

### Acceptance

```
1. Validate accepted_changes keys exist in proposal.selectable_changes_json
2. Load workspace's currently-active prompt_version body
3. Build merged body:
     - start from workspace_current
     - for each accepted key, overlay template_new's value
4. Create new prompt_version via Phase 7B create_draft
     - seeded_from_filesystem = FALSE
       → validator runs
       → if profile.eval_gate_required: eval gate runs
5. publish_version()
     - on success: mark proposal accepted, bump link version,
                   stamp applied_prompt_version_id
     - on eval gate failure: delete orphan draft, leave proposal open
                             (admin can edit + retry)
```

This means accepting an upgrade is just **a normal Phase 7B publish**
with the merged body as input. All Phase 7B properties hold:
rollback-able, eval-gated, audit-logged, atomic.

### Supersession

When v1.2 is published while v1.1 proposal is still open:

```
detect_upgradable_links finds the link (still on v1.0, < v1.2)
  → supersede_open_proposals marks v1.1 proposal as 'superseded'
  → generate_proposal for v1.2 (workspace's body vs v1.0 vs v1.2)
  → inbox now shows ONE open proposal (v1.2), one superseded (v1.1)
```

The admin sees the most-current upgrade target.

### Rejection

`reject_proposal(reason)` closes the proposal. Future detector runs
on the same template+version produce a fresh proposal — the workspace
can re-evaluate next cycle. This is intentional: rejecting v1.1 doesn't
permanently lock you out of v1.1; it just clears the inbox.

---

## 8. Slice 8E — Observability + frontend

**Goal:** Expose 8A–D through admin UI. Backend stays read-mostly
(all writes already exist in 8B/8C/8D).

### What ships — backend

- `GET /templates/bundles/{slug}/preview` — expanded items with full definitions + counts dict
- `GET /templates/links/summary` — counts grouped by lineage_state + entity_type
- `GET /templates/upgrade-proposals/summary` — counts + `open_count` for nav bell
- `GET /templates/metrics` — KPI dashboard (bundles_installed, drift_pct, upgrade counts, recent_activity feed)
- New service: [app/services/templates/metrics.py](app/services/templates/metrics.py) — single-query aggregations

### What ships — frontend

[meeting_ai_frontend/src/features/templates/](meeting_ai_frontend/src/features/templates/) feature directory:

| Route | Page | Function |
|-------|------|----------|
| `/templates` | TemplatesLandingPage | KPI tiles + lineage breakdown + recent activity |
| `/templates/browse` | TemplatesBrowsePage | Catalog grid with "recommended" badges |
| `/templates/browse/:slug` | BundlePreviewPage | Expanded items + install action |
| `/templates/installed` | TemplatesInstalledPage | Links table with lineage badges + state filter |
| `/templates/installed/:linkId` | TemplateLinkDetailPage | Diff summary + reset-to-template |
| `/templates/upgrades` | TemplatesUpgradesPage | Proposal inbox with state filter |
| `/templates/upgrades/:proposalId` | UpgradeProposalDetailPage | **3-way diff UI** with per-change checkboxes |

Plus `LineageBadge` component (used in installed table + detail page)
and an indigo bell badge in the **Sidebar** showing `open_count` of
upgrade proposals.

---

## 9. End-to-end flows

### Flow A — New user signup + auto-provision

```
POST /auth/register {name, email, password}
  │
  ├─→ create Organization
  ├─→ create User (role=org_admin)
  ├─→ db.commit()
  │
  └─→ if TEMPLATE_AUTO_PROVISION_BUNDLE is set:
        │
        ├─→ provision_bundle_for_org(
        │     organization_id=org.id,
        │     bundle_slug="all-in-starter",
        │     triggered_by="signup",
        │   )
        │
        ├─→ for each bundle item:
        │     · resolve catalog row (team / category / agent definition)
        │     · materialize workspace row (Category / AgentProfile / etc.)
        │     · create initial prompt_version with seeded_from_filesystem=True
        │       (skips validator + eval gate)
        │     · INSERT workspace_template_links row pointing back
        │       to (slug, version)
        │
        └─→ INSERT template_provisioning_jobs row
              (status='completed', items_created=N, items_skipped=0)
```

Failure semantics: provisioning failures **don't block signup**. The
job row records what failed; admin can re-run via `POST /templates/provision`.

### Flow B — Admin browses catalog + installs

```
GET /templates/bundles                       → list of available bundles
GET /templates/bundles/all-in-starter/preview → expanded items + counts
       (admin reviews — "this installs 9 teams, 11 categories, 9 agents")
POST /templates/provision {bundle_slug}      → idempotent install
       (re-running is safe: items_created=0, items_skipped=N)
```

### Flow C — Workspace admin edits a prompt → lineage recomputed

```
PATCH /prompt-configs/{cfg_id}/versions/{ver_id} {modular_prompt_json: {...}}
  │
  ├─→ Phase 7B updates the prompt_version body
  ├─→ db.commit()
  │
  └─→ _recompute_lineage_for_config(cfg_id):
        │
        ├─→ find workspace_template_links pointing at this config's
        │   agent_profile
        │
        └─→ for each link:
              · load template defaults (from registry)
              · diff vs workspace body
              · count differences:
                  0   → pristine
                  1-2 → modified
                  3+  → heavily_modified
                  + override: if 3+ prompt_versions exist → forked
              · UPDATE workspace_template_links SET lineage_state, diff_summary
```

### Flow D — Platform publishes v1.1 → workspace gets proposal

```
publish_agent_definition(
  slug="executive-summarizer",
  version="1.1.0",
  modular_prompt={"system": "v1.1 NEW SYSTEM", ...},
)
  │
  ├─→ INSERT template_agent_definitions(slug="executive-summarizer", version="1.1.0")
  ├─→ emit_publish_event(from_version="1.0.0", to_version="1.1.0")
  ├─→ INSERT template_publish_events (append-only audit)
  │
  └─→ _dispatch_upgrade_detector(synchronous):
        │
        ├─→ detect_upgradable_links:
        │     SELECT * FROM workspace_template_links
        │     WHERE source_template_slug='executive-summarizer'
        │       AND source_template_version < '1.1.0'
        │
        └─→ for each link:
              │
              ├─→ supersede_open_proposals (mark older proposals 'superseded')
              │
              ├─→ load workspace's currently-active prompt_version
              ├─→ load template v1.0.0 + v1.1.0 from registry
              │
              ├─→ for each section/retrieval/model/tool key:
              │     · _classify_change(workspace, template_old, template_new):
              │         · template_old == template_new           → skip (no_change)
              │         · workspace == template_old              → fast_forward
              │         · workspace == template_new              → already_matches_new
              │         · workspace differs from both            → conflict
              │
              └─→ INSERT template_upgrade_proposals(
                    workspace_template_link_id=link.id,
                    from_template_version='1.0.0',
                    to_template_version='1.1.0',
                    diff_json={...},                  # full 3-way bodies
                    selectable_changes_json=[         # per-key entries
                      {key: 'section:system', status: 'fast_forward',
                       default_selected: true, workspace: '...',
                       template_old: '...', template_new: '...'},
                      ...
                    ],
                    conflict_keys_json=['section:guardrails'],
                    resolution_state='open',
                  )
```

### Flow E — Admin accepts an upgrade

```
GET /templates/upgrade-proposals/{id}        → load proposal
       (UI renders 3-way diff with per-key checkboxes;
        fast_forward + already_matches_new pre-checked,
        conflicts unchecked)

User unchecks 1 conflict key, leaves 4 fast_forward keys checked.
Clicks "Accept 4 changes".

POST /templates/upgrade-proposals/{id}/accept
  body: {accepted_changes: ["section:system", "section:retrieval", ...]}
  │
  ├─→ validate keys exist in proposal.selectable_changes_json
  ├─→ load workspace's currently-active prompt_version body
  │
  ├─→ _apply_changes_to_body:
  │     merged_modular = dict(workspace_body.modular)
  │     for each accepted key:
  │       merged_modular[key.field] = template_new.modular[key.field]
  │     # similarly for retrieval / model / tools
  │
  ├─→ create_draft(merged_body, seeded_from_filesystem=False)
  │     (validator runs)
  │
  ├─→ publish_version(new_draft_id)
  │     (eval gate runs if profile.eval_gate_required)
  │     ├─→ on success: workspace now active on new_version
  │     └─→ on PublishGateFailed: delete draft, raise UpgradeAcceptanceFailed
  │
  └─→ if publish succeeded:
        · proposal.resolution_state = 'accepted' (or 'partial_accepted'
          if fewer keys than selectable_changes)
        · proposal.applied_prompt_version_id = new_version.id
        · proposal.applied_at = now
        · link.source_template_version = '1.1.0'    (bumped)
        · compute_lineage_for_link (recompute drift)
```

### Flow F — Admin resets a forked workspace back to template

```
POST /templates/links/{link_id}/reset
  │
  ├─→ load link + source template definition
  │
  ├─→ create_draft(template.modular_prompt, seeded_from_filesystem=True)
  │     (skips validator + eval gate — reset to known-good defaults)
  │
  ├─→ publish_version(new_draft_id)
  │
  └─→ compute_lineage_for_link → lineage_state goes back to 'pristine'
```

Prior versions stay rollback-able via Phase 7B's standard `/rollback`.
"Reset" is fully undoable.

---

## 10. Integration points

### Phase 7B (prompt versioning)

- Provisioning creates initial `prompt_versions` with
  `seeded_from_filesystem=True` → bypasses validator + eval gate
  (extended this session: bypass now covers both validator AND eval
  gate, not just one)
- Upgrade acceptance creates `prompt_versions` with
  `seeded_from_filesystem=False` → full Phase 7B gauntlet runs
- Reset creates `prompt_versions` with `seeded_from_filesystem=True`
- All accepted upgrades + resets are **rollback-able** via Phase 7B
  `/rollback` because they're regular published versions

### Phase 7H (eval gate)

- Acceptance routes through `publish_version`, which runs the eval
  gate when `agent_profile.eval_gate_required=True`
- Failure raises `UpgradeAcceptanceFailed` → orphan draft cleaned up,
  proposal stays open for retry
- The Phase 5F canonical-org fixture is used as the eval reference
  dataset

### `/auth/register` (signup)

- After successful commit, calls `auto_provision_for_new_org` (fire-and-forget)
- Setting `TEMPLATE_AUTO_PROVISION_BUNDLE=""` disables this entirely
- Provisioning failures write `template_provisioning_jobs(status='failed')`
  but never block signup

### `/prompt-configs/*` (workspace editing)

- After PATCH + after POST publish, calls `_recompute_lineage_for_config`
  to keep `workspace_template_links.lineage_state` fresh
- Hook is defensive (try/except logging) — a recompute failure never
  breaks the edit

---

## 11. Key invariants

| # | Invariant | Enforced by |
|---|-----------|-------------|
| I1 | Catalog content matches DB content | Seed script manifest hash check + 8A test #13 |
| I2 | Bundle items reference real definitions | FK constraint + 8A test #16 |
| I3 | `(slug, version)` is unique per definition type | Postgres UNIQUE + 8A test #1 |
| I4 | Workspace links are cross-org isolated | Filter in every router endpoint + 8E test #cross-org |
| I5 | Provisioning is idempotent | Soft-active unique + 8B test |
| I6 | Provisioning serializes per-org | Postgres advisory lock + 8B concurrent test |
| I7 | Reset preserves rollback path | Reset creates new published version + 8C test |
| I8 | Upgrade detector is idempotent | UNIQUE (link, from_v, to_v) + 8D test |
| I9 | Forked state is sticky | Version count check in classification + 8C test |
| I10 | Acceptance routes through Phase 7B publish_version | `_accept_agent_proposal` body + 8D eval-fail test |
| I11 | `template_publish_events` survives org cascade | BIGSERIAL, no FK on org_id + 8D cascade test |
| I12 | Cross-org access returns 404 | router filters + 8D xorg test |

---

## 12. Out of scope (deferred)

These are intentionally not in Phase 8:

- **Phase 8F — Marketplace foundation:** Org-published templates (workspaces ship their own bundles for others to install). Requires bundle authoring UI, template_kind='org_authored', moderation queue.
- **Frontend automated tests:** Vitest + RTL coverage for the templates feature. Currently manual QA only.
- **Code-splitting:** Vite bundle is 640 KB (over 500 KB warn). Lazy-load templates routes in a separate cleanup slice.
- **Email/push notifications:** New upgrade proposal → notify admin. Separate notifications slice.
- **Bulk operations:** "Reset all forked links" / "Accept all fast-forward upgrades". Defer until usage data justifies it.
- **Demo seed meetings:** Sample meeting transcripts for fresh workspaces. Different feature — Phase 8 is templates only.
- **Cross-workspace platform-admin views:** "Which orgs are on v1.0 vs v1.1?" — defer to platform ops tooling.

---

## Summary

105 tests across 5 slices, 9 new tables, zero changes to existing
schema, full backend service layer + REST API + React admin UI.
Total project regression: 542 tests passing across Phases 1–8E.
