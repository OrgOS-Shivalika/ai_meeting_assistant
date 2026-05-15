"""Phase 5F ship test — eval harness mechanics.

NOT a test of the RAG engine's quality (that's what `run_eval.py`
itself measures). This is a test that the eval harness's grader,
loader, and reporter work correctly:

  1. Real cases.CASES run cleanly in stub mode at >= 80% pass rate
     against the canonical fixture (the design contract — if this
     fails, either the fixture or the cases drifted).
  2. A deliberately impossible case fails — proves the grader isn't
     a no-op.
  3. A deliberately satisfiable case passes — proves the grader
     recognizes success.
  4. `--filter` regex narrows the run.
  5. `--threshold` controls the overall_passed flag.
  6. JSON report writer produces a parseable file with every
     case_id present.
  7. Stub mode skips synth assertions (proves the mode gate).
  8. Real-mode case shape is well-formed (we don't actually call
     OpenAI — we just verify the harness accepts the shape).

Run with:

    venv\\Scripts\\python.exe tests\\test_phase5f.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
        msg = traceback.format_exc(limit=4).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_real_cases_pass_at_threshold():
    """The committed CASES must produce >= 80% pass rate against the
    canonical fixture in stub mode. If this regresses, either the
    fixture drifted OR a real-world retrieval bug landed."""
    from tests.eval_phase5.run_eval import run_eval
    report = run_eval(mode="stub", threshold=0.8)
    assert report.total_cases >= 8, (
        f"expected at least 8 committed cases, got {report.total_cases}"
    )
    assert report.overall_passed, (
        f"committed cases regressed to {report.pass_rate:.0%} "
        f"(threshold {report.threshold:.0%}). "
        f"Failures: {[r.case_id for r in report.case_results if not r.passed]}"
    )


def test_deliberately_impossible_case_fails():
    """Sanity check: an impossible assertion must be reported as failing.
    Otherwise the harness is silently passing everything."""
    from tests.eval_phase5.run_eval import run_eval
    impossible = [{
        "id": "impossible-entity-by-design",
        "description": "Entity that does NOT exist in the fixture.",
        "query": "Tell me about Helios",
        "scope": "team_backend",
        "must_contain_entity_canonical": [
            "thisentitydoesnotexistinanyfixturexyz_abcdef",
        ],
    }]
    report = run_eval(mode="stub", threshold=0.0, cases_override=impossible)
    assert report.total_cases == 1
    r = report.case_results[0]
    assert r.passed is False, "grader should have failed the case"
    assert any("missing entity" in f for f in r.failures), (
        f"expected 'missing entity' in failures, got {r.failures}"
    )


def test_deliberately_satisfiable_case_passes():
    """An obviously-satisfiable assertion must be reported as passing."""
    from tests.eval_phase5.run_eval import run_eval
    trivial = [{
        "id": "trivial-only-has-context",
        "description": "Just expects bundle.has_context=True for a known scope.",
        "query": "Helios",
        "scope": "team_backend",
        "must_have_context": True,
    }]
    report = run_eval(mode="stub", threshold=0.0, cases_override=trivial)
    r = report.case_results[0]
    assert r.passed, f"trivial case should have passed; failures: {r.failures}"


def test_filter_narrows_run():
    """`filter_regex` only runs matching case ids."""
    from tests.eval_phase5.run_eval import run_eval
    report = run_eval(mode="stub", filter_regex="helios", threshold=0.0)
    assert report.total_cases > 0
    for r in report.case_results:
        assert "helios" in r.case_id, (
            f"filter='helios' returned non-matching case: {r.case_id}"
        )


def test_threshold_gates_overall_passed():
    """A high threshold + an impossible case should mark overall_passed=False."""
    from tests.eval_phase5.run_eval import run_eval
    bad = [{
        "id": "impossible-2",
        "description": "Always fails.",
        "query": "Helios",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["definitelynotinfixture_xyz"],
    }]
    report = run_eval(mode="stub", threshold=0.99, cases_override=bad)
    assert report.pass_rate == 0.0
    assert report.overall_passed is False


def test_json_report_writer_round_trips():
    from tests.eval_phase5.run_eval import run_eval, save_report_json
    report = run_eval(mode="stub", threshold=0.0)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "report.json")
        save_report_json(report, path)
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["total_cases"] == report.total_cases
        assert data["mode"] == "stub"
        ids = {c["case_id"] for c in data["cases"]}
        assert len(ids) == report.total_cases
        # Sanity: structured fields per case
        for c in data["cases"]:
            for k in ("case_id", "passed", "failures", "duration_ms", "status"):
                assert k in c, f"case row missing {k!r}"


def test_stub_mode_skips_synth_assertions():
    """A case with a synth assertion that the stub answer would VIOLATE
    must still pass in stub mode (synth grading is gated to real mode).
    """
    from tests.eval_phase5.run_eval import run_eval
    # Stub mode emits "Evaluator stub answer for ... [1].". A synth.
    # must_contain_text="thismagicstringneverappears" should normally
    # fail — but stub mode must skip the check entirely.
    case = [{
        "id": "synth-only-asserts",
        "description": "Stub mode should ignore synth assertions.",
        "query": "Helios",
        "scope": "team_backend",
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["thismagicstringneverappears"],
            "min_citations": 1_000_000,
        },
    }]
    report = run_eval(mode="stub", threshold=0.0, cases_override=case)
    r = report.case_results[0]
    assert r.passed, (
        f"stub mode should skip synth assertions; failures: {r.failures}"
    )


def test_real_mode_case_shape_accepted():
    """We can't actually call OpenAI here, but the case shape must be
    accepted by the harness when we declare mode='real'. Stub the LLMs
    at the seam to keep the test offline."""
    import json as _json
    from tests.eval_phase5.run_eval import run_eval
    from app.services.rag.query_planner import _set_test_responses as _set_p
    from app.services.rag.synthesizer import _set_test_responses as _set_s

    # Pre-seed enough responses for one case (ask_stream + replay_bundle
    # each call planner once; synth once for ask_stream). 4 plan + 2
    # synth covers worst-case branching.
    plan_blob = _json.dumps({
        "query_type": "factual",
        "effective_scope_type": "team",
        "effective_scope_id": None,  # resolver overrides anyway
        "detected_entity_names": ["Helios"],
        "time_hint": None, "confidence": 0.9,
    })
    _set_p([plan_blob] * 6)
    _set_s(["Alice leads Helios [1]."] * 3)

    case = [{
        "id": "real-mode-shape-only",
        "description": "Just exercise the real-mode code path.",
        "query": "Who leads Helios?",
        "scope": "team_backend",
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["Alice"],
            "min_citations": 1,
        },
    }]
    # We override mode='real' but with both LLMs stubbed; cleaner than
    # mocking OpenAI directly.
    report = run_eval(mode="real", threshold=0.0, cases_override=case)
    r = report.case_results[0]
    # Don't strictly require pass here — real-mode synth grading
    # consumes the queued response and depends on it matching the
    # synth.must_contain_text. We DO require: no harness crash, and
    # if it failed it should be a recognizable grader failure not
    # a runner crash.
    assert r.error is None, f"real-mode harness crashed: {r.error}"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    with section("5F - eval harness mechanics"):
        check("5F", "committed CASES pass at >= 80% in stub mode",
              test_real_cases_pass_at_threshold)
        check("5F", "deliberately impossible case is FAILED by grader",
              test_deliberately_impossible_case_fails)
        check("5F", "deliberately satisfiable case is PASSED by grader",
              test_deliberately_satisfiable_case_passes)
        check("5F", "filter narrows run to matching case ids",
              test_filter_narrows_run)
        check("5F", "threshold gates overall_passed flag",
              test_threshold_gates_overall_passed)
        check("5F", "JSON report writer round-trips with every case_id",
              test_json_report_writer_round_trips)
        check("5F", "stub mode skips synth assertions (mode gate works)",
              test_stub_mode_skips_synth_assertions)
        check("5F", "real-mode case shape accepted (no runner crash)",
              test_real_mode_case_shape_accepted)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
