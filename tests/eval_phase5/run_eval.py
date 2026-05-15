"""Phase 5F — eval harness.

Runs each case in `cases.CASES` against the live engine + canonical
fixture and produces a scored report. NOT a unit test — a benchmarking
script.

Modes:
  --mode stub  (default): canned planner + synth responses. Validates
                          ONLY retrieval-shape assertions. Cheap +
                          deterministic. Used by the 5F ship test.
  --mode real:            real OpenAI planner + synth. Validates synth
                          assertions too (citations, must_contain_text).
                          Costs money. Used for actual quality review.

Outputs:
  - Terminal: per-case verdict + summary.
  - JSON:     tests/eval_phase5/last_report.json with full structured
              results (so CI / dashboards can diff regressions).

CLI:
  python -m tests.eval_phase5.run_eval [flags]

  --mode stub|real           default: stub
  --filter <regex>           run cases whose id matches
  --threshold 0.0..1.0       overall pass rate to declare success
  --report path/to/file.json default: tests/eval_phase5/last_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case_id: str
    description: str
    query: str
    scope: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    duration_ms: int = 0
    status: str = ""             # final RagQueryRun status
    answer_text: Optional[str] = None
    citations_count: int = 0
    error: Optional[str] = None


@dataclass
class EvalReport:
    mode: str
    case_results: list[CaseResult]
    total_cases: int
    passed_cases: int
    threshold: float
    pass_rate: float
    overall_passed: bool
    duration_ms: int
    timestamp: str


# ---------------------------------------------------------------------------
# Scope resolver — translate symbolic ids to fixture-derived ids.
# ---------------------------------------------------------------------------

def _resolve_scope(case_scope: str, fixture) -> tuple[Optional[str], Optional[int]]:
    """Returns (requested_scope_type, requested_scope_id) for the
    pipeline. `auto` -> (None, None); `global` -> ('global', None);
    team/category symbols -> (type, fixture-assigned numeric id)."""
    if case_scope == "auto":
        return None, None
    if case_scope == "global":
        return "global", None
    mapping = {
        "team_backend": ("team", fixture.team_backend_id),
        "team_frontend": ("team", fixture.team_frontend_id),
        "team_sales": ("team", fixture.team_sales_id),
        "cat_engineering": ("category", fixture.category_engineering_id),
        "cat_sales": ("category", fixture.category_sales_id),
    }
    if case_scope not in mapping:
        raise ValueError(f"Unknown symbolic scope: {case_scope!r}")
    return mapping[case_scope]


# ---------------------------------------------------------------------------
# Stub seam — for mode=stub we pre-queue canned LLM responses that pass
# every case (the harness validates retrieval, not LLM quality).
# ---------------------------------------------------------------------------

def _seed_stub_responses_for_case(case, fixture):
    """Queue ONE planner response + ONE synth response. The planner
    response mirrors a sensible plan for the case so retrieval has
    room to work. The synth response is generic — synth assertions
    are skipped in stub mode."""
    from app.services.rag.query_planner import _set_test_responses as _set_planner
    from app.services.rag.synthesizer import _set_test_responses as _set_synth

    scope_type, scope_id = _resolve_scope(case.get("scope", "auto"), fixture)
    detected = case.get("must_contain_entity_canonical", [])
    plan = {
        "query_type": "factual",
        "effective_scope_type": scope_type or "global",
        "effective_scope_id": scope_id,
        "detected_entity_names": [n.title() for n in detected],
        "time_hint": None,
        "confidence": 0.9,
    }
    _set_planner([json.dumps(plan)])
    # Canned answer that always cites [1] — satisfies a minimal
    # presence assertion if any synth checks slip into stub mode.
    _set_synth([f"Evaluator stub answer for {case['id']} [1]."])


# ---------------------------------------------------------------------------
# Grading helpers
# ---------------------------------------------------------------------------

def _has_entity(bundle, canonical_name: str) -> bool:
    target = canonical_name.strip().lower()
    return any(e.canonical_name == target for e in bundle.entities)


def _has_relationship(bundle, expected: dict) -> bool:
    s, p, o = (
        expected["subject"].lower(),
        expected["predicate"].lower(),
        expected["object"].lower(),
    )

    # Lookup helper: entity_id -> canonical
    canonical_by_id = {e.entity_id: e.canonical_name for e in bundle.entities}

    for r in bundle.relationships:
        subj = canonical_by_id.get(r.subject_entity_id, r.subject_name.lower())
        obj = canonical_by_id.get(r.object_entity_id, r.object_name.lower())
        if (
            subj.lower() == s
            and r.predicate.lower() == p
            and obj.lower() == o
        ):
            return True
    return False


def _has_chunk_from_meeting(bundle, title_substr: str) -> bool:
    needle = title_substr.lower()
    return any(
        c.source_type == "meeting"
        and c.meeting_title
        and needle in c.meeting_title.lower()
        for c in bundle.chunks
    )


def _has_chunk_from_document(bundle, name_substr: str) -> bool:
    needle = name_substr.lower()
    return any(
        c.source_type == "document"
        and c.document_name
        and needle in c.document_name.lower()
        for c in bundle.chunks
    )


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------

def _run_case(case: dict, fixture, mode: str) -> CaseResult:
    """Execute one case through the full ask_stream pipeline and grade."""
    from app.db.database import SessionLocal
    from app.db.models import RagQueryRun
    from app.services.rag.ask_pipeline import ask_stream
    from tests.fixtures import canonical_stub_embed

    case_id = case["id"]
    started = time.monotonic()
    failures: list[str] = []
    metrics: dict = {}

    scope_type, scope_id = _resolve_scope(case.get("scope", "auto"), fixture)

    # Stub vs real wiring
    if mode == "stub":
        _seed_stub_responses_for_case(case, fixture)
        class _Embed:
            model = "stub-canonical"
            def embed(self, texts):
                return [canonical_stub_embed(t) for t in texts]
        embedder = _Embed()
    else:
        from app.services.embedder import Embedder
        embedder = Embedder()

    # Run pipeline
    db = SessionLocal()
    final_status = ""
    answer_text = None
    citations_count = 0
    run_id = None
    bundle = None

    try:
        events = list(ask_stream(
            db,
            organization_id=fixture.organization_id,
            user_id=fixture.user_id,
            query_text=case["query"],
            requested_scope_type=scope_type,
            requested_scope_id=scope_id,
            sources=case.get("sources", "all"),
            embedder=embedder,
        ))
        done = next((e for e in events if e["event"] == "done"), None)
        if not done:
            failures.append("no done event received")
            final_status = "failed"
        else:
            final_status = done["data"]["status"]
            answer_text = done["data"].get("answer_text")
            run_id = done["data"]["run_id"]

        cit_evt = next((e for e in events if e["event"] == "citations"), None)
        if cit_evt:
            citations_count = len(cit_evt["data"].get("citations", []))

        # We need the bundle to grade retrieval assertions. Easiest:
        # re-call retrieve() with the same plan. But we already ran
        # ask_stream which stored the bundle in audit. Read from there.
        if run_id:
            row = db.query(RagQueryRun).filter(RagQueryRun.id == run_id).first()
            if row:
                metrics["retrieved_chunks"] = row.retrieved_chunks
                metrics["retrieved_entities"] = row.retrieved_entities
                metrics["retrieved_relationships"] = row.retrieved_relationships
        # For richer retrieval-shape grading we run retrieve() directly
        # so we get the in-memory dataclasses (the audit JSON is lossy
        # for our purposes — names are nested differently).
        bundle = _replay_bundle(
            db, fixture, case, mode, scope_type, scope_id, embedder,
        )
    except Exception as e:
        failures.append(f"pipeline crashed: {e}")
        logger.error("case %s crashed:\n%s", case_id, traceback.format_exc())
        final_status = "failed"
    finally:
        db.close()

    # -------- Grade retrieval assertions (run in both modes) --------
    if bundle is None:
        failures.append("could not materialize retrieval bundle for grading")
    else:
        if case.get("must_have_context") is True and not bundle.has_context:
            failures.append("expected has_context=True, got False")

        for canonical in case.get("must_contain_entity_canonical", []):
            if not _has_entity(bundle, canonical):
                failures.append(f"missing entity (canonical): {canonical!r}")

        for canonical in case.get("must_not_contain_entity_canonical", []):
            if _has_entity(bundle, canonical):
                failures.append(f"entity present but should be absent: {canonical!r}")

        for rel in case.get("must_contain_relationship", []):
            if not _has_relationship(bundle, rel):
                failures.append(
                    f"missing relationship: ({rel['subject']} -- {rel['predicate']} --> {rel['object']})"
                )

        for needle in case.get("must_contain_chunk_from_meeting_title_contains", []):
            if not _has_chunk_from_meeting(bundle, needle):
                failures.append(f"no chunk from meeting matching {needle!r}")

        for needle in case.get("must_contain_chunk_from_document_name_contains", []):
            if not _has_chunk_from_document(bundle, needle):
                failures.append(f"no chunk from document matching {needle!r}")

        # Source-filter shape check
        if case.get("sources") == "documents":
            if any(c.source_type == "meeting" for c in bundle.chunks):
                failures.append("sources='documents' but bundle contains meeting chunk")
        if case.get("sources") == "meetings":
            if any(c.source_type == "document" for c in bundle.chunks):
                failures.append("sources='meetings' but bundle contains document chunk")

    # -------- Grade synth assertions (real mode only) --------
    if mode == "real":
        synth = case.get("synth", {}) or {}
        expected_status = synth.get("expected_status_one_of") or ["completed"]
        if final_status not in expected_status:
            failures.append(
                f"status={final_status!r} not in expected {expected_status!r}"
            )
        for s in synth.get("must_contain_text", []):
            if s.lower() not in (answer_text or "").lower():
                failures.append(f"answer missing required text {s!r}")
        for s in synth.get("must_not_contain_text", []):
            if s.lower() in (answer_text or "").lower():
                failures.append(f"answer contains forbidden text {s!r}")
        min_cit = synth.get("min_citations", 0)
        if citations_count < min_cit:
            failures.append(
                f"citations={citations_count} below min_citations={min_cit}"
            )

    duration_ms = int((time.monotonic() - started) * 1000)
    return CaseResult(
        case_id=case_id,
        description=case.get("description", ""),
        query=case["query"],
        scope=case.get("scope", "auto"),
        passed=not failures,
        failures=failures,
        metrics=metrics,
        duration_ms=duration_ms,
        status=final_status,
        answer_text=answer_text,
        citations_count=citations_count,
    )


def _replay_bundle(db, fixture, case, mode, scope_type, scope_id, embedder):
    """Re-run plan + retrieve so we get an in-memory RetrievalBundle to
    grade retrieval-shape assertions. The audit-row JSON is lossy
    (no entity-name lookups) for that purpose."""
    from app.services.rag.query_planner import plan_query
    from app.services.rag.retrieval import retrieve
    # Stub seam already consumed by ask_stream; for retrieve we need a
    # fresh canned plan in stub mode. Real mode pays one extra LLM call;
    # that's the cost of a thorough replay grade.
    if mode == "stub":
        # Re-seed the planner so plan_query gets a deterministic plan
        # aligned with the case (since we already used the previous
        # canned response in ask_stream).
        _seed_stub_responses_for_case(case, fixture)
    plan = plan_query(
        db,
        organization_id=fixture.organization_id,
        query_text=case["query"],
        requested_scope_type=scope_type,
        requested_scope_id=scope_id,
    )
    return retrieve(
        db,
        organization_id=fixture.organization_id,
        query_text=case["query"],
        plan=plan,
        embedder=embedder,
        sources=case.get("sources", "all"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_eval(
    *,
    mode: str = "stub",
    filter_regex: Optional[str] = None,
    threshold: float = 0.8,
    cases_override: Optional[list] = None,
) -> EvalReport:
    """Programmatic entry. Builds the canonical fixture, runs each case
    (filtered if a regex is given), grades, returns an EvalReport.

    Used by both the CLI (`main`) and the 5F ship test."""
    from app.db.database import SessionLocal
    from datetime import datetime, timezone
    from tests.fixtures import build_canonical_org, cleanup_canonical_org
    from tests.eval_phase5.cases import CASES

    started = time.monotonic()
    cases = cases_override or CASES
    if filter_regex:
        rx = re.compile(filter_regex)
        cases = [c for c in cases if rx.search(c["id"])]

    db = SessionLocal()
    try:
        fixture = build_canonical_org(db, mode="stub")
    finally:
        db.close()

    results: list[CaseResult] = []
    try:
        for case in cases:
            try:
                res = _run_case(case, fixture, mode=mode)
            except Exception as e:
                res = CaseResult(
                    case_id=case.get("id", "?"),
                    description=case.get("description", ""),
                    query=case.get("query", ""),
                    scope=case.get("scope", "auto"),
                    passed=False,
                    failures=[f"runner crash: {e}"],
                    error=str(e),
                )
            results.append(res)
    finally:
        db = SessionLocal()
        try:
            cleanup_canonical_org(db, fixture)
        finally:
            db.close()

    n = len(results)
    n_passed = sum(1 for r in results if r.passed)
    pass_rate = (n_passed / n) if n else 1.0
    return EvalReport(
        mode=mode,
        case_results=results,
        total_cases=n,
        passed_cases=n_passed,
        threshold=threshold,
        pass_rate=pass_rate,
        overall_passed=pass_rate >= threshold,
        duration_ms=int((time.monotonic() - started) * 1000),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


# ---------------------------------------------------------------------------
# Pretty printer + JSON writer
# ---------------------------------------------------------------------------

def print_report(report: EvalReport) -> None:
    print()
    print(f"=== Phase 5F eval report (mode={report.mode}) ===")
    for r in report.case_results:
        tag = "PASS" if r.passed else "FAIL"
        print(f"  [{tag}] {r.case_id:42s}  status={r.status:10s}  cit={r.citations_count}  {r.duration_ms}ms")
        if not r.passed:
            for f in r.failures:
                print(f"          - {f}")
    print()
    print(
        f"Pass rate: {report.passed_cases}/{report.total_cases} "
        f"= {report.pass_rate:.1%}  (threshold {report.threshold:.0%})"
    )
    print(f"Overall: {'OK' if report.overall_passed else 'FAIL'}")
    print(f"Duration: {report.duration_ms} ms  ({report.timestamp})")


def save_report_json(report: EvalReport, path: str) -> None:
    blob = {
        "mode": report.mode,
        "total_cases": report.total_cases,
        "passed_cases": report.passed_cases,
        "pass_rate": report.pass_rate,
        "threshold": report.threshold,
        "overall_passed": report.overall_passed,
        "duration_ms": report.duration_ms,
        "timestamp": report.timestamp,
        "cases": [asdict(r) for r in report.case_results],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(blob, fh, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_eval", description="Phase 5F RAG eval harness.",
    )
    p.add_argument("--mode", choices=["stub", "real"], default="stub")
    p.add_argument("--filter", dest="filter_regex", default=None,
                   help="Only run cases whose id matches this regex.")
    p.add_argument("--threshold", type=float, default=0.8)
    p.add_argument(
        "--report",
        default=os.path.join(_HERE, "last_report.json"),
        help="Path to write structured JSON report.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.getLogger().setLevel(logging.WARNING)
    args = _build_parser().parse_args(argv)
    report = run_eval(
        mode=args.mode,
        filter_regex=args.filter_regex,
        threshold=args.threshold,
    )
    print_report(report)
    save_report_json(report, args.report)
    print(f"\nWrote JSON report -> {args.report}")
    return 0 if report.overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
