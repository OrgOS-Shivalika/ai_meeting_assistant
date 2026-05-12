"""Phase 3B unit tests — extractor layers in isolation, no DB, no network.

Layered surface coverage (matches the architecture from feedback):

  - graph_normalizer.normalize_entity_name         (normalization rules)
  - prompts.graph.load_prompt                       (versioned prompt loader)
  - graph_extractor.build_prompt                    (template + chunks)
  - graph_extractor_llm.extract_raw                 (strict JSON + 1 retry)
  - graph_extractor.normalize                       (intra-batch dedup +
                                                     temp_id resolution +
                                                     dangling-ref filter +
                                                     self-loop filter)
  - graph_extractor.iter_batches                    (multi-batch driver)
  - graph_extractor.extract_from_chunks             (end-to-end with stub LLM)

Run with:

    venv\\Scripts\\python.exe tests\\test_phase3b.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


results: List[Tuple[str, str, str, str]] = []


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except AssertionError as e:
        msg = str(e) or "assertion failed"
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [FAIL] {name} :: {msg}")
        return
    except Exception:
        msg = traceback.format_exc(limit=3).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fake chunk — duck-types MeetingChunk's `.text` for build_prompt.
# ---------------------------------------------------------------------------

class _FakeChunk:
    def __init__(self, text: str):
        self.text = text


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

def test_normalizer_basics():
    from app.services.graph_normalizer import normalize_entity_name
    cases = [
        ("Sarah Chen", "sarah chen"),
        ("  Sarah  Chen  ", "sarah chen"),
        ("SARAH CHEN", "sarah chen"),
        ('"Phoenix"', "phoenix"),
        # Leading `(` is stripped, the now-internal `)` stays. Edge-only
        # punctuation peeling is the locked rule.
        ("(Project) Phoenix", "project) phoenix"),
        ("Phoenix.", "phoenix"),
        ("Acme, Inc.", "acme, inc"),                    # internal comma kept
        ("", ""),
        ("   ", ""),
    ]
    for raw, expected in cases:
        got = normalize_entity_name(raw)
        assert got == expected, f"normalize({raw!r}) = {got!r}, expected {expected!r}"


def test_normalizer_unicode_nfkc():
    from app.services.graph_normalizer import normalize_entity_name
    # NFKC folds the wide "Ｓ" to ASCII "S" and the ligature "ﬁ" to "fi".
    assert normalize_entity_name("Ｓarah") == "sarah"
    assert normalize_entity_name("ﬁnance") == "finance"


# ---------------------------------------------------------------------------
# Prompt loader + builder tests
# ---------------------------------------------------------------------------

def test_prompt_loader_caches_and_lists():
    from app.ai_agents.prompts.graph import load_prompt, available_versions
    text = load_prompt("v1")
    assert "{transcript_text}" in text, "v1 prompt missing the substitution marker"
    assert "v1" in available_versions()
    # Cache hit returns the same string instance.
    assert load_prompt("v1") is text


def test_prompt_loader_unknown_version_errors():
    from app.ai_agents.prompts.graph import load_prompt
    raised = False
    try:
        load_prompt("does-not-exist")
    except FileNotFoundError as e:
        raised = True
        assert "Available versions" in str(e), "error should list available versions"
    assert raised


def test_build_prompt_substitutes_chunks():
    from app.services.graph_extractor import build_prompt
    chunks = [_FakeChunk("Alice: Hello team."), _FakeChunk("Bob: Hi Alice.")]
    p = build_prompt(chunks, prompt_version="v1")
    assert "{transcript_text}" not in p, "transcript placeholder should be substituted"
    assert "Alice: Hello team." in p
    assert "Bob: Hi Alice." in p


# ---------------------------------------------------------------------------
# LLM client tests — strict JSON + 1 retry via the test response queue.
# ---------------------------------------------------------------------------

def test_llm_strict_json_happy_path():
    from app.ai_agents import graph_extractor_llm as llm
    payload = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Sarah Chen", "confidence": 0.9},
        ],
        "relationships": [],
    })
    llm._set_test_responses([payload])
    result = llm.extract_raw(prompt="ignored", model="stub")
    assert len(result.entities) == 1
    assert result.entities[0].name == "Sarah Chen"
    assert result.entities[0].type == "person"


def test_llm_retries_on_invalid_json_then_succeeds():
    """First response is garbage prose, second is valid JSON. The retry
    path must accept the second response without raising."""
    from app.ai_agents import graph_extractor_llm as llm
    bad = "Sure! Here you go: not actually JSON at all"
    good = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "topic", "name": "Q3 Roadmap", "confidence": 0.8},
        ],
        "relationships": [],
    })
    llm._set_test_responses([bad, good])
    result = llm.extract_raw(prompt="ignored", model="stub")
    assert result.entities[0].name == "Q3 Roadmap"


def test_llm_gives_up_after_two_failures():
    from app.ai_agents import graph_extractor_llm as llm
    llm._set_test_responses(["not json", "still not json"])
    raised = False
    try:
        llm.extract_raw(prompt="ignored", model="stub")
    except llm.ExtractionLLMError as e:
        raised = True
        assert "after 2 attempts" in str(e)
    assert raised


def test_llm_drops_unknown_entity_type():
    """Per-row lenient parsing: an LLM that emits `type='deadline'` (not
    in the closed vocab) drops the offending row instead of failing the
    whole batch. The drop surfaces in `dropped_entities` so prompt
    iteration has full ground truth."""
    from app.ai_agents import graph_extractor_llm as llm
    payload = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "deadline", "name": "Friday", "confidence": 0.9},
            {"temp_id": "e2", "type": "person", "name": "Alice", "confidence": 0.9},
        ],
        "relationships": [],
    })
    llm._set_test_responses([payload])
    result = llm.extract_raw(prompt="ignored", model="stub")
    # Valid row survives.
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"
    # Invalid row recorded with its raw JSON + error.
    assert len(result.dropped_entities) == 1
    dropped = result.dropped_entities[0]
    assert dropped["raw"]["type"] == "deadline"
    assert "literal" in dropped["error"].lower() or "deadline" in dropped["error"].lower()


def test_llm_drops_unknown_predicate():
    """Same lenient semantics for relationships: bad predicate drops
    that one row, keeps everything else."""
    from app.ai_agents import graph_extractor_llm as llm
    payload = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
            {"temp_id": "e2", "type": "project", "name": "Phoenix", "confidence": 0.9},
        ],
        "relationships": [
            {"subject_temp_id": "e1", "predicate": "loves", "object_temp_id": "e2", "confidence": 0.5},
            {"subject_temp_id": "e1", "predicate": "leads", "object_temp_id": "e2", "confidence": 0.8},
        ],
    })
    llm._set_test_responses([payload])
    result = llm.extract_raw(prompt="ignored", model="stub")
    assert len(result.entities) == 2
    assert len(result.relationships) == 1
    assert result.relationships[0].predicate == "leads"
    assert len(result.dropped_relationships) == 1
    assert result.dropped_relationships[0]["raw"]["predicate"] == "loves"


def test_llm_strips_code_fences():
    """Some models still wrap JSON in ```json ... ``` despite the
    response_format hint. The parser peels fences before json.loads so
    we don't waste a retry on cosmetic wrapping."""
    from app.ai_agents import graph_extractor_llm as llm
    body = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
        ],
        "relationships": [],
    })
    fenced = f"```json\n{body}\n```"
    llm._set_test_responses([fenced])
    result = llm.extract_raw(prompt="ignored", model="stub")
    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"


def test_llm_rejects_wrong_envelope_shape():
    """The envelope is still strict — a JSON array at the top level (not
    an object), or missing `entities`/`relationships`, raises after the
    retry."""
    from app.ai_agents import graph_extractor_llm as llm
    # Top-level array, not an object.
    llm._set_test_responses([json.dumps([{"x": 1}]), json.dumps([{"x": 2}])])
    raised = False
    try:
        llm.extract_raw(prompt="ignored", model="stub")
    except llm.ExtractionLLMError:
        raised = True
    assert raised, "wrong envelope shape should raise after both retries"


def test_llm_accepts_extra_keys_on_entity():
    """LLMs sometimes volunteer extra keys (e.g. 'source_sentence').
    The model allows them (model_config extra='allow') so we don't drop
    information that a future schema rev might consume."""
    from app.ai_agents import graph_extractor_llm as llm
    payload = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Alice",
             "confidence": 0.9, "source_sentence": "Alice spoke up"},
        ],
        "relationships": [],
    })
    llm._set_test_responses([payload])
    result = llm.extract_raw(prompt="ignored", model="stub")
    assert len(result.entities) == 1


# ---------------------------------------------------------------------------
# Normalize tests — the meat of the layered design.
# ---------------------------------------------------------------------------

def _raw(entities, relationships):
    from app.schemas.graph_extraction import RawExtraction
    return RawExtraction.model_validate({"entities": entities, "relationships": relationships})


def test_normalize_within_batch_dedup():
    """Two entities with the same canonical_name + type collapse to one
    `NormalizedEntity` with both temp_ids."""
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "Sarah Chen", "confidence": 0.9},
            {"temp_id": "e2", "type": "person", "name": "sarah  chen", "confidence": 0.7},
        ],
        relationships=[],
    )
    out = normalize(raw)
    assert len(out.entities) == 1, f"expected dedup to 1 entity, got {len(out.entities)}"
    merged = out.entities[0]
    assert sorted(merged.temp_ids) == ["e1", "e2"]
    # Max-confidence aggregation (recall-friendly).
    assert merged.confidence == 0.9
    # First display name wins.
    assert merged.name == "Sarah Chen"


def test_normalize_does_not_merge_across_types():
    """Same canonical_name but different entity_type is two different
    rows — the dedup key is (entity_type, canonical_name)."""
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "Phoenix", "confidence": 0.9},
            {"temp_id": "e2", "type": "project", "name": "Phoenix", "confidence": 0.9},
        ],
        relationships=[],
    )
    out = normalize(raw)
    assert len(out.entities) == 2


def test_normalize_relationships_resolve_via_temp_id():
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
            {"temp_id": "e2", "type": "project", "name": "Phoenix", "confidence": 0.9},
        ],
        relationships=[
            {"subject_temp_id": "e1", "predicate": "leads", "object_temp_id": "e2", "confidence": 0.85},
        ],
    )
    out = normalize(raw)
    assert len(out.relationships) == 1
    rel = out.relationships[0]
    assert rel.subject_temp_id == "e1"
    assert rel.object_temp_id == "e2"
    assert rel.predicate == "leads"


def test_normalize_drops_dangling_relationship():
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
        ],
        relationships=[
            {"subject_temp_id": "e1", "predicate": "leads",
             "object_temp_id": "e_ghost", "confidence": 0.85},
        ],
    )
    out = normalize(raw)
    assert len(out.relationships) == 0
    assert out.dropped_relationships == 1


def test_normalize_drops_self_loop():
    """A relationship where subject and object resolve to the same
    NormalizedEntity is dropped — almost always extractor confusion."""
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "Alice", "confidence": 0.9},
            {"temp_id": "e2", "type": "person", "name": "alice", "confidence": 0.9},  # merges with e1
        ],
        relationships=[
            {"subject_temp_id": "e1", "predicate": "works_with",
             "object_temp_id": "e2", "confidence": 0.5},
        ],
    )
    out = normalize(raw)
    assert len(out.entities) == 1
    assert len(out.relationships) == 0
    assert out.dropped_relationships == 1


def test_normalize_drops_blank_canonical_name():
    """An entity whose name normalizes to empty (e.g. "   .   ") should
    be silently dropped — keeping it would violate the NOT NULL
    canonical_name column downstream."""
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "person", "name": "   .   ", "confidence": 0.9},
            {"temp_id": "e2", "type": "person", "name": "Alice", "confidence": 0.9},
        ],
        relationships=[],
    )
    out = normalize(raw)
    names = [e.canonical_name for e in out.entities]
    assert names == ["alice"], f"expected only alice, got {names}"


def test_normalize_merges_aliases_and_attributes():
    from app.services.graph_extractor import normalize
    raw = _raw(
        entities=[
            {"temp_id": "e1", "type": "project", "name": "Phoenix",
             "aliases": ["Project Phoenix"],
             "attributes": {"owner": "Alice"},
             "confidence": 0.9},
            {"temp_id": "e2", "type": "project", "name": "phoenix",
             "aliases": ["Phoenix Initiative"],
             "attributes": {"deadline": "2026-02-01"},
             "confidence": 0.8},
        ],
        relationships=[],
    )
    out = normalize(raw)
    assert len(out.entities) == 1
    merged = out.entities[0]
    assert set(merged.aliases) == {"Project Phoenix", "Phoenix Initiative"}
    # First seen wins for attributes (setdefault), and both keys land.
    assert merged.attributes["owner"] == "Alice"
    assert merged.attributes["deadline"] == "2026-02-01"


# ---------------------------------------------------------------------------
# iter_batches + end-to-end
# ---------------------------------------------------------------------------

def test_iter_batches():
    from app.services.graph_extractor import iter_batches
    chunks = [_FakeChunk(f"c{i}") for i in range(13)]
    sizes = [len(b) for b in iter_batches(chunks, batch_size=5)]
    assert sizes == [5, 5, 3]


def test_iter_batches_invalid_size():
    from app.services.graph_extractor import iter_batches
    raised = False
    try:
        list(iter_batches([_FakeChunk("x")], batch_size=0))
    except ValueError:
        raised = True
    assert raised


def test_extract_from_chunks_end_to_end():
    """Full pipeline with a stubbed LLM. Verifies:
      - prompt_version + model travel through to the result
      - chunks_processed equals input length
      - raw + normalized payloads are both surfaced
      - normalization runs (dedup + temp_id resolution)
    """
    from app.ai_agents import graph_extractor_llm as llm
    from app.services.graph_extractor import extract_from_chunks

    canned = json.dumps({
        "entities": [
            {"temp_id": "e1", "type": "person", "name": "Sarah Chen", "confidence": 0.95},
            {"temp_id": "e2", "type": "person", "name": "sarah chen", "confidence": 0.7},
            {"temp_id": "e3", "type": "project", "name": "Phoenix", "confidence": 0.9},
        ],
        "relationships": [
            {"subject_temp_id": "e1", "predicate": "leads",
             "object_temp_id": "e3", "confidence": 0.85},
        ],
    })
    llm._set_test_responses([canned])

    chunks = [_FakeChunk("Alice: Hello team."), _FakeChunk("Bob: Hey.")]
    result = extract_from_chunks(chunks, prompt_version="v1", model="stub-model")

    assert result.prompt_version == "v1"
    assert result.model == "stub-model"
    assert result.chunks_processed == 2
    # Raw kept verbatim.
    assert len(result.raw.entities) == 3
    # Normalized deduped + relationship resolved.
    assert len(result.normalized.entities) == 2
    assert len(result.normalized.relationships) == 1


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    with section("3B - normalizer"):
        check("3B", "normalize_entity_name basic rules", test_normalizer_basics)
        check("3B", "normalize_entity_name unicode NFKC", test_normalizer_unicode_nfkc)

    with section("3B - prompt loader + builder"):
        check("3B", "load_prompt caches and lists versions", test_prompt_loader_caches_and_lists)
        check("3B", "load_prompt unknown version errors clearly", test_prompt_loader_unknown_version_errors)
        check("3B", "build_prompt substitutes chunks", test_build_prompt_substitutes_chunks)

    with section("3B - LLM client (strict JSON + retry)"):
        check("3B", "happy path returns RawExtraction", test_llm_strict_json_happy_path)
        check("3B", "retries on invalid JSON then succeeds", test_llm_retries_on_invalid_json_then_succeeds)
        check("3B", "gives up after two failures", test_llm_gives_up_after_two_failures)
        check("3B", "drops unknown entity_type, keeps the rest", test_llm_drops_unknown_entity_type)
        check("3B", "drops unknown predicate, keeps the rest", test_llm_drops_unknown_predicate)
        check("3B", "strips ```json fences before parsing", test_llm_strips_code_fences)
        check("3B", "rejects wrong envelope shape after retry", test_llm_rejects_wrong_envelope_shape)
        check("3B", "accepts extra keys on entities (extra='allow')", test_llm_accepts_extra_keys_on_entity)

    with section("3B - normalize"):
        check("3B", "within-batch dedup merges temp_ids", test_normalize_within_batch_dedup)
        check("3B", "different entity_type does not merge", test_normalize_does_not_merge_across_types)
        check("3B", "relationships resolve via temp_id", test_normalize_relationships_resolve_via_temp_id)
        check("3B", "drops dangling relationships", test_normalize_drops_dangling_relationship)
        check("3B", "drops self-loop after merge", test_normalize_drops_self_loop)
        check("3B", "drops blank canonical_name entities", test_normalize_drops_blank_canonical_name)
        check("3B", "merges aliases and attributes", test_normalize_merges_aliases_and_attributes)

    with section("3B - batching + end-to-end"):
        check("3B", "iter_batches slices correctly", test_iter_batches)
        check("3B", "iter_batches rejects invalid size", test_iter_batches_invalid_size)
        check("3B", "extract_from_chunks end-to-end with stub", test_extract_from_chunks_end_to_end)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
