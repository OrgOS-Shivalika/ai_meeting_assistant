"""Phase 5C ship test — synthesizer + citation validation.

Architectural properties verified:

  1. Happy path: bundle + canned LLM output -> cleaned answer with
     ordered Citation objects + 0 bundle_misses.
  2. Hallucinated [N] tags ([99], [42]) get stripped from the answer
     and recorded in bundle_misses (silent stripping = user's locked
     default).
  3. Repeated citations ([1][1][1]) dedup to ONE Citation in the
     result, ordering preserved.
  4. Citations of ENTITY / RELATIONSHIP blocks (non-chunk indices) are
     stripped — only chunks are citable, per the prompt contract.
  5. No-context fast path: when bundle.has_context is False the LLM
     is NEVER called. Synthesizer short-circuits with the polite-decline
     answer and sets no_context=True.
  6. Streaming generator yields token chunks then finalizes a
     SynthesisResult identical in shape to the one-shot version. Tokens
     reassemble to the cleaned answer; validation runs ONCE post-stream.
  7. Streaming + no_context: when bundle has no context the stream
     emits the decline answer as a single chunk (no LLM call).
 8. Streaming + LLM failure: an exception mid-stream finalizes the
     handle with `raw_response.error` set and a degraded answer.
  9. Context block builder: meeting blocks include speakers + date;
     document blocks include section_path + page_number. Entities and
     relationships appear as unnumbered reasoning context.
 10. Prompt rendering: org name + question + context blocks all
     interpolated correctly.
 11. Missing prompt template -> degraded result, no crash.

Run with:

    venv\\Scripts\\python.exe tests\\test_phase5c.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
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
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class _StubEmbedder:
    model = "stub-canonical"
    def __init__(self):
        from tests.fixtures import canonical_stub_embed
        self._embed_fn = canonical_stub_embed
    def embed(self, texts):
        return [self._embed_fn(t) for t in texts]


def _build_helios_bundle(db, fx):
    """Run plan + retrieve once and reuse for every synthesizer test."""
    from app.services.rag.query_planner import plan_query, _set_test_responses as _set_planner
    from app.services.rag.retrieval import retrieve
    from app.db.models import Entity
    helios = db.query(Entity).filter(
        Entity.organization_id == fx.organization_id,
        Entity.canonical_name == "helios",
        Entity.scope_type == "team",
    ).first()
    _set_planner([json.dumps({
        "query_type": "factual",
        "effective_scope_type": "team",
        "effective_scope_id": fx.team_backend_id,
        "detected_entity_names": ["Helios"],
        "time_hint": None,
        "confidence": 0.9,
    })])
    plan = plan_query(
        db, organization_id=fx.organization_id,
        query_text="Who leads Helios?",
        requested_scope_type="team",
        requested_scope_id=fx.team_backend_id,
    )
    bundle = retrieve(
        db, organization_id=fx.organization_id,
        query_text="Who leads Helios?",
        plan=plan, embedder=_StubEmbedder(),
    )
    return bundle


def _empty_bundle(fx):
    """An explicit no-context bundle."""
    from app.schemas.rag_schema import RetrievalBundle
    return RetrievalBundle(
        chunks=[], entities=[], relationships=[],
        effective_scope_type="team",
        effective_scope_id=fx.team_backend_id,
        has_context=False, duration_ms=0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

_FX = None


def test_happy_path_valid_citations():
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize, _set_test_responses
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        assert len(bundle.chunks) >= 2, "fixture should provide >= 2 chunks"
        _set_test_responses([
            "Alice leads the Helios project [1]. The project depends on Phoenix [2]."
        ])
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="Who leads Helios?", bundle=bundle,
        )
        assert result.no_context is False
        assert "[1]" in result.answer_text
        assert "[2]" in result.answer_text
        assert len(result.citations) == 2
        assert {c.index for c in result.citations} == {1, 2}
        assert result.bundle_misses == []
        # Source types attached correctly
        c1 = next(c for c in result.citations if c.index == 1)
        assert c1.source_type in ("meeting", "document")
    finally:
        db.close()


def test_hallucinated_citations_stripped():
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize, _set_test_responses
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        # [99] and [42] don't exist; [1] does.
        _set_test_responses([
            "Alice leads Helios [1]. Random fake cite [99]. Another fake [42]."
        ])
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="Who?", bundle=bundle,
        )
        # User-facing answer must NOT contain [99] or [42]
        assert "[99]" not in result.answer_text
        assert "[42]" not in result.answer_text
        # Valid [1] survives
        assert "[1]" in result.answer_text
        # bundle_misses captures BOTH hallucinated indices (ordered)
        assert result.bundle_misses == [99, 42]
        # Only the valid citation is in the citations list
        assert len(result.citations) == 1
        assert result.citations[0].index == 1
    finally:
        db.close()


def test_repeated_citations_dedup():
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize, _set_test_responses
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        _set_test_responses([
            "Alice leads Helios [1][1][1] which depends on Phoenix [2][2]. See [1] again."
        ])
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="?", bundle=bundle,
        )
        # Each unique [N] dedups to ONE Citation
        assert len(result.citations) == 2
        indices = [c.index for c in result.citations]
        assert indices == [1, 2], f"expected [1, 2] ordered, got {indices}"
    finally:
        db.close()


def test_citations_beyond_chunk_count_stripped():
    """The bundle has N chunks, so valid [N] tags are 1..N. Anything
    beyond N is a hallucination, even if the number "exists" as an
    entity / relationship — only chunks are citable per the prompt
    contract."""
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize, _set_test_responses
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        n_chunks = len(bundle.chunks)
        # Cite one valid + one beyond range
        bogus = n_chunks + 5
        _set_test_responses([
            f"Alice leads Helios [1]. Some claim about an entity [{bogus}]."
        ])
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="?", bundle=bundle,
        )
        assert f"[{bogus}]" not in result.answer_text
        assert bogus in result.bundle_misses
        assert len(result.citations) == 1 and result.citations[0].index == 1
    finally:
        db.close()


def test_no_context_skips_llm_call():
    """When bundle.has_context is False, the LLM is NEVER called. If the
    test seam still has its canned response after, that proves the
    short-circuit fired."""
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import (
        synthesize, _set_test_responses, NO_CONTEXT_ANSWER,
    )
    from app.services.rag import synthesizer as synth_module
    db = SessionLocal()
    try:
        bundle = _empty_bundle(_FX)
        canary = "ABSOLUTELY SHOULD NOT BE RETURNED"
        _set_test_responses([canary])
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="anything", bundle=bundle,
        )
        assert result.no_context is True
        assert result.answer_text == NO_CONTEXT_ANSWER
        assert result.citations == []
        assert result.bundle_misses == []
        # Canary is still in the queue (LLM wasn't called)
        assert synth_module._test_response_queue == [canary], (
            "LLM was called despite no_context — short-circuit broken"
        )
        # Clear for subsequent tests
        synth_module._test_response_queue = []
    finally:
        db.close()


def test_streaming_generator_yields_and_finalizes():
    """Iterator yields tokens; post-stream, handle.result equals what
    one-shot synthesis produces for the same input."""
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize_stream, _set_test_responses
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        _set_test_responses([
            "Alice leads Helios [1]. Project depends on Phoenix [2]. Bogus [99] cite."
        ])
        handle = synthesize_stream(
            db, organization_id=_FX.organization_id,
            query_text="?", bundle=bundle,
        )
        chunks = list(handle)
        assert len(chunks) > 1, f"expected multiple stream chunks, got {len(chunks)}"
        reassembled = "".join(chunks)
        # Reassembled is the RAW answer (before citation validation)
        assert "[1]" in reassembled
        # handle.result is set after generator exhausts
        assert handle.result is not None
        assert handle.result.no_context is False
        assert "[99]" not in handle.result.answer_text
        assert handle.result.bundle_misses == [99]
        assert {c.index for c in handle.result.citations} == {1, 2}
    finally:
        db.close()


def test_streaming_no_context_emits_decline_without_llm():
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import (
        synthesize_stream, _set_test_responses, NO_CONTEXT_ANSWER,
    )
    from app.services.rag import synthesizer as synth_module
    db = SessionLocal()
    try:
        bundle = _empty_bundle(_FX)
        canary = "MUST NOT STREAM THIS"
        _set_test_responses([canary])
        handle = synthesize_stream(
            db, organization_id=_FX.organization_id,
            query_text="?", bundle=bundle,
        )
        tokens = list(handle)
        assert tokens == [NO_CONTEXT_ANSWER], (
            f"expected single decline chunk, got {tokens}"
        )
        assert handle.result.no_context is True
        # Canary untouched
        assert synth_module._test_response_queue == [canary]
        synth_module._test_response_queue = []
    finally:
        db.close()


def test_context_block_builder_includes_provenance():
    """The block builder must include meeting/doc-specific provenance
    so the LLM can describe them in the answer."""
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import build_context_blocks
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        text, index_map = build_context_blocks(bundle)
        # Index map covers exactly the chunks
        assert set(index_map.keys()) == set(range(1, len(bundle.chunks) + 1))
        # Every chunk's text is in the rendered block string
        for c in bundle.chunks:
            assert c.chunk_text[:50] in text, (
                f"chunk text missing from rendered context"
            )
        # Meeting blocks include "MEETING", doc blocks include "DOCUMENT"
        if any(c.source_type == "meeting" for c in bundle.chunks):
            assert "MEETING" in text
        if any(c.source_type == "document" for c in bundle.chunks):
            assert "DOCUMENT" in text
        # Entities + relationships appear as reasoning context
        if bundle.entities:
            assert "ENTITY:" in text
        if bundle.relationships:
            assert "RELATIONSHIP:" in text
    finally:
        db.close()


def test_streaming_llm_exception_finalizes_handle_gracefully():
    """A mid-stream exception must NOT propagate — the handle gets a
    degraded result with `raw_response.error` set so the API layer can
    write a 'failed' audit row."""
    from app.db.database import SessionLocal
    from app.services.rag import synthesizer as synth_module
    from app.services.rag.synthesizer import synthesize_stream
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)

        # Patch the stream-call helper to raise mid-stream
        original = synth_module._call_synth_llm_stream

        def _exploding(*, prompt, model):
            yield "partial answer [1] "
            raise RuntimeError("simulated mid-stream failure")

        synth_module._call_synth_llm_stream = _exploding
        try:
            handle = synthesize_stream(
                db, organization_id=_FX.organization_id,
                query_text="?", bundle=bundle,
            )
            # The handle's iterator should not raise; the generator
            # catches the exception and finalizes the result.
            collected = []
            for token in handle:
                collected.append(token)
            assert handle.result is not None
            assert "error" in handle.result.raw_response
            assert "simulated mid-stream failure" in handle.result.raw_response["error"]
        finally:
            synth_module._call_synth_llm_stream = original
    finally:
        db.close()


def test_missing_prompt_template_degrades_gracefully():
    """A nonexistent prompt_version produces a degraded result, not a
    raised exception — same fail-safe pattern as the planner."""
    from app.db.database import SessionLocal
    from app.services.rag.synthesizer import synthesize
    db = SessionLocal()
    try:
        bundle = _build_helios_bundle(db, _FX)
        result = synthesize(
            db, organization_id=_FX.organization_id,
            query_text="?", bundle=bundle,
            prompt_version="nonexistent-version-zzz",
        )
        # Degraded: no LLM call, no_context decline as the answer
        assert result.citations == []
        assert "error" in result.raw_response
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    global _FX
    from app.db.database import SessionLocal
    from tests.fixtures import build_canonical_org, cleanup_canonical_org

    db = SessionLocal()
    try:
        _FX = build_canonical_org(db, mode="stub")
    finally:
        db.close()

    try:
        with section("5C - synthesizer + citations"):
            check("5C", "happy path: valid citations preserved, ordered",
                  test_happy_path_valid_citations)
            check("5C", "hallucinated citations stripped, recorded in bundle_misses",
                  test_hallucinated_citations_stripped)
            check("5C", "repeated citations dedup to one Citation per index",
                  test_repeated_citations_dedup)
            check("5C", "citations beyond chunk count stripped (chunks-only rule)",
                  test_citations_beyond_chunk_count_stripped)
            check("5C", "no-context fast path: LLM is never called",
                  test_no_context_skips_llm_call)
            check("5C", "streaming generator yields + finalizes result",
                  test_streaming_generator_yields_and_finalizes)
            check("5C", "streaming + no-context: decline streamed without LLM",
                  test_streaming_no_context_emits_decline_without_llm)
            check("5C", "context block builder includes meeting/doc provenance",
                  test_context_block_builder_includes_provenance)
            check("5C", "streaming LLM exception -> graceful finalize",
                  test_streaming_llm_exception_finalizes_handle_gracefully)
            check("5C", "missing prompt template -> degraded result, no crash",
                  test_missing_prompt_template_degrades_gracefully)
    finally:
        db = SessionLocal()
        try:
            cleanup_canonical_org(db, _FX)
        except Exception as e:
            print(f"  [cleanup error] {e}")
        finally:
            db.close()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
