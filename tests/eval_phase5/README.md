# Phase 5F — RAG eval harness

A regression detector for the hybrid graph RAG engine. Not a unit
test — a benchmarking script that runs a hand-curated set of Q&A
pairs against the live engine + canonical fixture and produces a
scored report.

## Why it exists

- **Regression detection**: prompt versions change, rerank weights
  get tuned, retrieval logic evolves. Without a stable benchmark,
  drift is invisible until users complain.
- **Prompt-version safety**: bumping `RAG_SYNTH_PROMPT_VERSION` from
  `v1` to `v2` should keep pass rate ≥ 80%. The harness gates the
  bump.
- **Tuning signal**: the JSON report records per-case retrieval
  metrics; comparing reports across α/β/γ sweeps tells you which
  configuration retrieves better.

## How to run

```bash
# Cheap deterministic mode — uses stub LLMs. Validates retrieval
# only (chunks, entities, relationships, has_context, source filter).
# This is what CI runs.
venv/Scripts/python.exe -m tests.eval_phase5.run_eval --mode stub

# Real mode — calls OpenAI for planner + synth. Validates everything
# including citation precision + answer text. Costs ~$0.005 per case.
venv/Scripts/python.exe -m tests.eval_phase5.run_eval --mode real

# Run a subset
venv/Scripts/python.exe -m tests.eval_phase5.run_eval --filter helios

# Custom pass threshold
venv/Scripts/python.exe -m tests.eval_phase5.run_eval --threshold 0.9
```

## What gets graded

| Assertion | Stub mode | Real mode |
|---|---|---|
| `must_have_context` | Yes | Yes |
| `must_contain_entity_canonical` | Yes | Yes |
| `must_not_contain_entity_canonical` | Yes | Yes |
| `must_contain_relationship` | Yes | Yes |
| `must_contain_chunk_from_meeting_title_contains` | Yes | Yes |
| `must_contain_chunk_from_document_name_contains` | Yes | Yes |
| `sources='documents'` / `'meetings'` filter shape | Yes | Yes |
| `synth.must_contain_text` | No | Yes |
| `synth.must_not_contain_text` | No | Yes |
| `synth.expected_status_one_of` | No | Yes |
| `synth.min_citations` | No | Yes |

## Reading the report

Two outputs:

1. **Terminal** — per-case pass/fail + the failure reasons + a final
   pass rate. Exit code `0` if pass rate ≥ threshold, `1` otherwise.

2. **JSON** — `last_report.json` (or `--report path/to/file.json`)
   with the full structured results. Diff two reports to see how a
   prompt change affected each case.

Example failure message:

```
[FAIL] helios-leader-at-team-scope             status=completed  cit=2  4321ms
       - missing relationship: (alice -- leads --> helios)
```

means: the case ran, the synth answered, but the bundle.relationships
list didn't contain `Alice leads Helios` — retrieval issue, not synth.
Look at the retrieval engine or the case's scope.

## Adding a case

1. Open `cases.py`.
2. Append a new dict to `CASES`. Required: `id`, `query`, `scope`.
3. Pick the assertions that capture intent. Less is more — a single
   `must_contain_entity_canonical` is often enough for factual cases.
4. Run `--filter <your-case-id>` to validate it.

## Pass threshold convention

- Stub mode: ≥ 80% pass before merging.
- Real mode: ≥ 75% pass (real LLM is noisier; the threshold is
  looser to avoid flaky CI).

## Fixture coupling

Every case references the canonical fixture from
`tests/fixtures/canonical_org.py`. If the fixture content changes,
some cases will need updates — the linkage is intentional. Treat
fixture + cases as one versioned dataset.
