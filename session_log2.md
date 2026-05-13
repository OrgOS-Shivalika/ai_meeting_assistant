# Session Log 2 — Phase 4 (NotebookLM-style Document Ingestion)

**Date:** 2026-05-13
**Branch:** `phase-2`
**Status at end:** 178/178 tests passing across Phase 1 → Phase 4
**Migration head:** `c2b0e7f4a915`

---

## Goal

Ship Phase 4 of the agentic-meeting-assistant ("Enterprise AI Knowledge OS"). Phase 4 takes the system from meetings-only AI memory to multi-source AI memory: PDF, DOCX, and XLSX uploads become first-class citizens of the same embedding + graph layer that already serves meeting transcripts.

User's locked sequencing — strictly followed:

> **4A schema → 4B parsers/chunker → 4C ingestion pipeline → 4D graph integration → 4E search union → 4F backfill**

Phase 4A was already landed at session start (migration `a8b3e7d9f4c1`, models extended, 10/10 ship test passing). This session shipped Phase 4B through 4F.

---

## Architectural commitments (carried from the Phase 4 plan)

1. **Single polymorphic `document_chunks` table** — `document_type` + typed FK pair (`category_document_id`, `team_document_id`) with a CHECK enforcing exactly one is set, matching the type. Rejected the three-tier physical split.
2. **Typed FK rewire of `entity_mentions` / `relationship_mentions`** — Phase 3's un-FK'd `source_document_id` / `source_document_chunk_id` placeholders replaced with cascading typed FKs.
3. **Decoupled lifecycle** per source: `embedding_status` is owned by the ingest task, `graph_status` by the graph task. A failure in one stage does not poison the other.
4. **External call first, then DB** — parse + embed happen before the wipe-and-reinsert transaction opens. A flaky OpenAI call can never leave half-written chunks.
5. **Equal-weighted union search** — `meeting_chunks` and `document_chunks` are queried independently (each under its own HNSW index) and merged by cosine similarity, with no boost or penalty for either side.
6. **Scope is deterministic per doc tier** — `CategoryDocument` → `category` scope, `TeamDocument` → `team` scope. Docs never fall back to `global` the way meetings can.
7. **Source provenance on every row** — entities/relationships/mentions written by the doc pipeline carry `source_type='document'`; meeting pipeline keeps `source_type='meeting'`.
8. **Source-subtype future-proofing** — chunker stashes `source_subtype` (`pdf` / `docx` / `xlsx`) into `metadata_json` on every chunk so Phase 5 reranking and the UI can filter by format without a schema change.

---

## Phase 4A — Schema (recap; landed before this session)

- Migration `a8b3e7d9f4c1_phase4a_document_chunks`
- New table `document_chunks` with 1536-d `VECTOR`, HNSW index (cosine_ops, m=16, ef_construction=64), CHECK constraints, partial unique indexes per branch
- 6 lifecycle columns added to both `category_documents` and `team_documents` (`embedding_status`, `embedded_at`, `graph_status`, `graph_extracted_at`, `chunk_count`, `total_tokens`)
- `entity_mentions` / `relationship_mentions` rewired with typed doc FKs + 4-shape CHECK constraint (meeting / category-doc / team-doc / context-only) + 3 partial unique indexes
- Ship test [tests/test_phase4a.py](tests/test_phase4a.py): **10/10**

---

## Phase 4B — Parsers + DocumentChunker

### What landed

**New package [app/parsers/](app/parsers/)**

- [base.py](app/parsers/base.py): `ParsedBlock` dataclass (the *only* shape the chunker sees), `UnsupportedDocumentError`, and the `parse_document(bytes, mime_type, filename) -> (subtype, blocks)` dispatcher. Picks subtype by mime first, extension as a fallback for the octet-stream-with-extension case.
- [pdf_parser.py](app/parsers/pdf_parser.py): `pypdf` page-per-block extractor. Strips control characters and collapses whitespace. Scanned PDFs (image-only) come back as zero blocks rather than raising — the caller marks them `embedding_status='empty'` with a friendly hint.
- [docx_parser.py](app/parsers/docx_parser.py): `python-docx` walker with a heading section-stack. Heading 1 → top of stack, Heading 2 nests under it, etc. Every paragraph / table row carries the slash-joined `section_path`. Tables are flattened row-by-row as `"col1 | col2 | col3"` so cell adjacency survives embedding.
- [xlsx_parser.py](app/parsers/xlsx_parser.py): `openpyxl` row-per-block extractor with header-attaching. The trick that makes XLSX retrievable: a row in a sheet with a header row becomes `"Region: EU | Q3 Revenue: 1200000 | Owner: Alice"` — never a bare number that can't match a question. Sheets without a header fall back to `col_A` / `col_B` synthesized labels.

**New service [app/services/document_chunker.py](app/services/document_chunker.py)**

Block-aware token chunker. Same shape as the Phase 2 `TranscriptChunker` (`cl100k_base`, 800 tokens target, 100 tokens overlap), but consumes `ParsedBlock`s instead of speaker turns. Key behaviors:

- Greedy-pack consecutive blocks until the next would overflow budget.
- Single oversized block falls back to sentence splitting, then hard token windowing.
- Output `DocChunk` is a transport dataclass (not the SQLAlchemy model). Phase 4C's ingest task translates these into `DocumentChunk` rows.
- **Dominant page/section inheritance**: a chunk's `page_number` / `section_path` come from whichever contributing block donated the most tokens. When a chunk straddles boundaries, `pages_covered` / `sections_covered` lists land in metadata for cross-boundary citation.
- Overlap is plain-text (no speaker prefix to preserve, unlike meetings).

### Dependencies added to [requirements.txt](requirements.txt)

```
pypdf==6.11.0
python-docx==1.2.0
openpyxl==3.1.5
lxml==6.1.0
et-xmlfile==2.0.0
```

### Ship test [tests/test_phase4b.py](tests/test_phase4b.py): **9/9**

Highlights:
- Synthesizes a 3-page handcrafted PDF (no reportlab dep) to exercise page-number preservation
- Round-trips a DOCX with H1 → H2 → paragraph → table to assert section_path lineage
- Round-trips an XLSX with a header row and a no-header sheet to assert both branches
- Chunker tests cover: budget enforcement, overlap shingle survival (4-word overlap test), dominant-page inheritance, empty-block skipping, oversized single-block fallback

---

## Phase 4C — Ingestion pipeline

### What landed

**New module [app/celery_tasks/document_ingest.py](app/celery_tasks/document_ingest.py)**

Unified `_ingest_document_sync(db, doc_kind, doc_id)` shared by both task wrappers. The pipeline:

1. Load the doc row (`CategoryDocument` or `TeamDocument`).
2. Flip `embedding_status='processing'` and commit (so observers see we picked it up).
3. Download bytes via `storage.download_bytes(storage_key)`.
4. Parse via `parse_document(...)`. `UnsupportedDocumentError` → `embedding_status='failed'` with a friendly error.
5. If parser yields zero blocks → `embedding_status='empty'` (friendlier than 'failed' for scanned PDFs).
6. Chunk via `DocumentChunker`.
7. **External call first**: `Embedder.embed(texts)` for the entire chunk list before any DB writes.
8. Single transaction: wipe-existing-chunks → insert new chunks (with proper FK polymorphism via `_chunk_row_kwargs`) → flip status to `embedded` + set `chunk_count` / `total_tokens` / `embedded_at`.
9. Fan-out: best-effort call to `dispatch_extract_document_graph` (Phase 4D). If that module isn't importable yet, log and leave `graph_status='pending'` — graceful degradation.

Idempotency: re-running on the same doc wipes the prior chunk set and reinserts. The Phase 4A partial-unique index on `(category_document_id, chunk_index)` (and team variant) guarantees no partial commits survive a crash.

**Existing wrappers rewritten** [document_tasks.py](app/celery_tasks/document_tasks.py), [team_document_tasks.py](app/celery_tasks/team_document_tasks.py)

Both Celery task functions are now thin shells:

```python
@celery.task(name="meeting_ai.process_document", bind=True)
def process_document(self, document_id: str) -> dict:
    db = SessionLocal()
    try:
        return _ingest_document_sync(db, "category", document_id)
    finally:
        db.close()
```

(team version differs only in `kind="team"` and the task name)

**Retry endpoints**

Mirrored the meeting retry endpoints from Phase 3:

- `POST /categories/{category_id}/documents/{document_id}/retry-embedding`
- `POST /categories/{category_id}/documents/{document_id}/retry-graph`
- `POST /teams/{team_id}/documents/{document_id}/retry-embedding`
- `POST /teams/{team_id}/documents/{document_id}/retry-graph`

The graph retry endpoint pre-checks `embedding_status='embedded'` and returns 400 with a helpful message otherwise.

### Ship test [tests/test_phase4c.py](tests/test_phase4c.py): **5/5**

Uses real MinIO (compose) but a stub `Embedder` (deterministic hash-based 1536-d vectors, no OpenAI):

- Category PDF: 3 pages → chunks land with `document_type='category'`, parent FK set, page_number preserved, `source_subtype='pdf'` in metadata, lifecycle columns updated
- Team DOCX: section_path lineage inherited from headings ("Project Helios / Q3 Milestones")
- Unsupported mime → `embedding_status='failed'` with `"Unsupported document format..."` in error_message
- Empty-text PDF → `embedding_status='empty'` (not 'failed')
- Re-ingest idempotency: second run wipes-and-reinserts cleanly, no duplicate-key crashes, fresh row UUIDs

---

## Phase 4D — Document graph extraction

### What landed

**New migration** [alembic/versions/c2b0e7f4a915_phase4d_doc_extraction_runs.py](alembic/versions/c2b0e7f4a915_phase4d_doc_extraction_runs.py)

Extends `graph_extraction_runs` for polymorphic sources:

- `meeting_id` relaxed to nullable
- Added `source_category_document_id`, `source_team_document_id` (typed FKs, CASCADE)
- New CHECK `ck_graph_extraction_runs_one_source` enforces exactly one of (meeting_id, category-doc, team-doc) is set per row
- Two new btree indexes (`ix_graph_runs_org_category_doc`, `ix_graph_runs_org_team_doc`)

**New module [app/celery_tasks/document_graph_tasks.py](app/celery_tasks/document_graph_tasks.py)**

Sibling of [graph_tasks.py](app/celery_tasks/graph_tasks.py). Deliberately not refactored into a shared base — the meeting path uses `created_from_meeting_id` (a real column) while the doc path leaves it `None`, and forcing them to share a generic upsert helper would have introduced more coupling than it saved. The two files stay diff-comparable instead.

`_extract_graph_for_document_sync(db, doc_kind, doc)`:

- Pre-check: requires `embedding_status='embedded'` (otherwise `graph_status='skipped'`).
- Pulls chunks from `document_chunks` filtered by the parent FK.
- Uses `extract_from_chunks` + `iter_batches` from [graph_extractor.py](app/services/graph_extractor.py) (duck-typed — only reads `.id` and `.text`, so it works for `DocumentChunk` rows).
- Scope is deterministic: cat doc → `("category", category_id)`, team doc → `("team", team_id)`. Never falls back to global.
- All written entities/relationships/mentions carry `source_type='document'`.
- Mentions use the typed doc-branch FKs (`source_category_document_id` or `source_team_document_id` + `source_document_chunk_id`).
- Per-batch commits — partial progress survives a mid-run crash.
- Run-row writer (`_new_run_row`) attaches the appropriate source FK so the CHECK is satisfied.

Plus `extract_document_graph` Celery task and `dispatch_extract_document_graph(doc_kind, doc_id)` helper.

**Model update [app/db/models.py](app/db/models.py)**

`GraphExtractionRun` extended with the two new typed FKs + relationships back to `CategoryDocument` / `TeamDocument`. `meeting_id` flipped to nullable.

### Ship test [tests/test_phase4d.py](tests/test_phase4d.py): **6/6**

Stub extractor returns canned `ExtractionResult` objects (no LLM call). Coverage:

- Cat-doc extraction full path: scope=category, source_type='document' on all rows, mentions use category-branch FKs, run row tagged with `source_category_document_id`
- Team-doc extraction: scope=team, team-branch mentions
- Skip pre-check: not-embedded doc → `graph_status='skipped'`, no run row written
- Cross-doc entity dedup: two cat docs in the same category both mention "Helios" → one entity row, `knowledge_version` bumped on second run, max-confidence wins, aliases unioned in
- Failure path: extractor raises → `graph_status='failed'` + failed run row with error_message
- CHECK guard: `ck_graph_extraction_runs_one_source` rejects mixed sources (both meeting + cat doc) and all-NULL sources

---

## Phase 4E — Unified search

### What landed

**Schema updates [app/schemas/search_schema.py](app/schemas/search_schema.py)**

- `SearchRequest.sources: SearchSourceFilter = "all"` — one of `"all"` / `"meetings"` / `"documents"`
- `SearchHit` is now polymorphic on `source_type: Literal["meeting", "document"]`
  - Meeting-source fields (`meeting_id`, `meeting_title`, `meeting_url`, `scheduled_at`, `speakers`, `start_timestamp`, `end_timestamp`) — populated on meeting hits, `None` on doc hits
  - Document-source fields (`document_id`, `document_name`, `document_kind`, `page_number`, `section_path`, `source_subtype`) — populated on doc hits, `None` on meeting hits
  - Shared scope refs (`category`, `team`) — populated on both
- New `DocumentChunksResponse` for the inspection endpoint

**Router refactor [app/api/search_router.py](app/api/search_router.py)**

`/search` now issues two parallel queries (each top-K under their own HNSW index) and merges by similarity in Python:

```
if sources in ("all", "meetings"): meeting_hits = _search_meeting_chunks(...)
if sources in ("all", "documents"): document_hits = _search_document_chunks(...)
merged = sorted(meeting_hits + document_hits, key=similarity, reverse=True)[:top_k]
```

Why two queries + Python merge instead of SQL UNION: SQLAlchemy UNION semantics with mismatched column types (meeting has `speakers`, doc has `page_number`) gets ugly fast. Two HNSW-indexed queries with 2×top_K candidates is plenty fast and trivially correct.

The doc-side query coalesces `(CategoryDocument, TeamDocument)` parents via outer joins + `func.coalesce` so the hit builder doesn't have to branch on `document_type`.

`access_count` bumps only on chunks that survive the top-K slice — not the 2×top_K pre-merge set. (Important: a doc that ranked 11th out of 20 shouldn't show up as "accessed" in the importance scoring later.)

**New endpoint** `GET /documents/{kind}/{document_id}/chunks` — sibling of `/meetings/{id}/chunks` for inspection / debugging.

### Ship test [tests/test_phase4e.py](tests/test_phase4e.py): **7/7**

Seeds both `meeting_chunks` and `document_chunks` with controlled theme vectors so cosine distances rank predictably:

- `sources='all'` returns both source types interleaved by similarity
- `sources='meetings'` excludes all doc hits; doc fields are `None`
- `sources='documents'` excludes all meeting hits; meeting fields are `None`
- Scope narrowing (`scope='category'`, `scope_id=cat_a`) filters out cat_b's doc chunks and all team chunks
- Polymorphic hit shape: every hit has exactly one set of source-specific fields
- `top_k=1` returns the single best across both sides
- Doc inspection endpoint returns chunks in order with all doc-source fields populated

---

## Phase 4F — Backfill CLI

### What landed

**New module [app/scripts/backfill_documents.py](app/scripts/backfill_documents.py)**

Walks `category_documents` + `team_documents` for rows that need either embedding or graph extraction (or both). Modeled on [backfill_embeddings.py](app/scripts/backfill_embeddings.py) from Phase 2E.

```
python -m app.scripts.backfill_documents [flags]

--kind <category|team|both>     Default: both
--stage <embedding|graph|both>  Default: both
--org-id <uuid>
--limit N                       Cap per (kind, stage)
--dry-run                       Print ids, no dispatch
--inline                        Run sync without Celery
--no-include-failed             Skip 'failed' rows
--no-include-stale              Skip model-upgrade re-embed
```

Eligibility:

- **Embedding**: `embedding_status` in {pending, processing, failed (with `--include-failed`)} OR (with `--include-stale`) any chunk row points at an `embedding_model` different from current
- **Graph**: `embedding_status='embedded'` AND `graph_status` in {pending, processing, failed}. Never dispatches graph for un-embedded docs.

Returns a structured summary dict so callers (tests, scripts) can introspect.

### Ship test [tests/test_phase4f.py](tests/test_phase4f.py): **8/8**

Drives the eligibility queries with a deliberately diverse fixture (one doc at every interesting status, plus a "stale model" doc with old `embedding_model`, plus an other-org doc):

- Embedding picks pending/processing/failed when `--include-failed`; excludes 'failed' otherwise
- `--include-stale` catches the model-upgrade doc (chunks with `OLD-MODEL-NAME`)
- Graph eligibility requires `embedding_status='embedded'` — even a `graph_status='pending'` doc is skipped if not yet embedded
- `--kind` filter never crosses tables
- `--limit` caps per (kind, stage) bucket
- `--org-id` narrows correctly — other-org docs never appear
- `dry_run=True` writes nothing to any row

---

## Regression fixes along the way

### Phase 3A (1 failure → 0)

The Phase 3A ship test referenced `source_document_id`, which Phase 4A renamed to the typed pair `source_category_document_id` / `source_team_document_id`. Updated the test to use the new column on a real `CategoryDocument` row.

### Phase 3D (5 failures → 0)

The graph router and `MentionRef` schema had three call sites still referencing the dropped `source_document_id` column. Fixed:

- [app/schemas/graph_schema.py](app/schemas/graph_schema.py): `MentionRef.source_document_id` → `source_category_document_id` + `source_team_document_id`
- [app/api/graph_router.py](app/api/graph_router.py): three `MentionRef(...)` call sites (entity-detail recent mentions, meeting-graph entity mentions, meeting-graph relationship mentions) updated to pass the typed pair

---

## Final test status

```
tests/test_phase1.py           pass=33  fail=0
tests/test_phase2b.py          pass=14  fail=0
tests/test_phase2c.py          pass=5   fail=0
tests/test_phase2d.py          pass=10  fail=0
tests/test_phase2e.py          pass=7   fail=0
tests/test_phase3a.py          pass=9   fail=0
tests/test_phase3b.py          pass=23  fail=0
tests/test_phase3c.py          pass=8   fail=0
tests/test_phase3d.py          pass=16  fail=0
tests/test_phase3e.py          pass=8   fail=0
tests/test_phase4a.py          pass=10  fail=0
tests/test_phase4b.py          pass=9   fail=0
tests/test_phase4c.py          pass=5   fail=0
tests/test_phase4d.py          pass=6   fail=0
tests/test_phase4e.py          pass=7   fail=0
tests/test_phase4f.py          pass=8   fail=0
---------- TOTAL: pass=178  fail=0 ----------
```

---

## Files touched this session

### New files (12)

```
alembic/versions/c2b0e7f4a915_phase4d_doc_extraction_runs.py
app/celery_tasks/document_graph_tasks.py
app/celery_tasks/document_ingest.py
app/parsers/__init__.py
app/parsers/base.py
app/parsers/docx_parser.py
app/parsers/pdf_parser.py
app/parsers/xlsx_parser.py
app/scripts/backfill_documents.py
app/services/document_chunker.py
tests/test_phase4b.py
tests/test_phase4c.py
tests/test_phase4d.py
tests/test_phase4e.py
tests/test_phase4f.py
```

### Modified files (9)

```
app/api/document_router.py            (added retry-embedding + retry-graph routes)
app/api/graph_router.py               (typed FK update for MentionRef call sites)
app/api/search_router.py              (UNION refactor + doc chunks inspection endpoint)
app/api/team_document_router.py       (added retry-embedding + retry-graph routes)
app/celery_tasks/document_tasks.py    (rewritten as thin wrapper around _ingest_document_sync)
app/celery_tasks/team_document_tasks.py (same)
app/db/models.py                      (GraphExtractionRun extended for polymorphic source)
app/schemas/graph_schema.py           (MentionRef typed FK pair)
app/schemas/search_schema.py          (SearchHit polymorphic, sources filter, DocumentChunksResponse)
requirements.txt                      (pypdf + python-docx + openpyxl + lxml + et-xmlfile)
tests/test_phase3a.py                 (use typed FK column in CHECK test)
```

---

## Diff stats

```
12 files changed, 864 insertions(+), 174 deletions(-)  (modifications only)
+ 15 new files (parsers, chunker, ingest, graph, backfill, 5 new test suites, 2 migrations)
```

---

## What's next — Phase 5: Hybrid Graph RAG

Per the locked roadmap:

- Combine vector search (Phase 4E) with graph traversal (Phase 4D entities + relationships)
- "Scope priority retrieval" — tightest tier wins, then expand outward
- Hybrid ranking: combine semantic similarity, graph proximity, importance score, recency
- Citation surface: every answer cites its chunk + section + page (we already preserve all of this through Phase 4)

Not started in this session.
