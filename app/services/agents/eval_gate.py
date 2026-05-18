"""Phase 7H — eval-gate service.

Wraps the Phase 5F eval harness as a publish-time gate AND a
manually-triggerable surface. Three public entry points:

  - `run_eval_for_version(...)`  — execute Phase 5F's `run_eval()`
    against the org's data, persist an `agent_eval_runs` row, return
    the result.

  - `run_if_required(...)`       — called by `publish_version`. When
    the profile's `eval_gate_required` flag is set, runs an eval
    against the candidate version + threshold. Returns the score;
    raises `EvalGateFailed` when the score is below threshold.

  - `list_runs_for_agent(...)`   — read-only history for the
    dashboard's Eval tab.

7H ships **stub mode** by default — Phase 5F's stub mode doesn't make
LLM calls and exercises only retrieval shape. That's a degenerate
quality signal per-version (the score is essentially constant) but a
useful safety net against catastrophic retrieval regressions: if
retrieval is broken across the board, every publish fails until it's
fixed.

**Real mode** (full LLM-based quality check against the version's
modular prompt) requires patching the synth's prompt source to use a
specific version's content. That wiring is a follow-up slice; 7H's
real-mode entry point exists but the dashboard surfaces it as
"experimental".
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AgentEvalRun, AgentProfile, PromptVersion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EvalGateError(RuntimeError):
    """Base for eval-gate failures. Carries an HTTP status hint so
    callers can map cleanly. Mirrors the `PublishError` shape."""

    def __init__(self, message: str, *, http_status: int = 422) -> None:
        super().__init__(message)
        self.http_status = http_status


class EvalGateFailed(EvalGateError):
    """Score below threshold. Score is recorded on the exception so
    `publish_version` can surface it in the deployment audit row."""

    def __init__(
        self, *, score: Optional[float], threshold: float,
        eval_run_id: Optional[UUID] = None,
    ) -> None:
        super().__init__(
            f"Eval gate score {score!r} below threshold {threshold:.3f}",
            http_status=422,
        )
        self.score = score
        self.threshold = threshold
        self.eval_run_id = eval_run_id


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_run(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: Optional[UUID],
    prompt_version_id: Optional[UUID],
    mode: str,
    threshold: float,
    score: Optional[float],
    overall_passed: bool,
    total_cases: int,
    passed_cases: int,
    duration_ms: int,
    report_json: dict,
    error_message: Optional[str],
    triggered_by: str,
    triggered_by_user_id: Optional[UUID],
    started_at: datetime,
    completed_at: Optional[datetime],
) -> Optional[AgentEvalRun]:
    """Insert one `agent_eval_runs` row. Defensive: a persistence
    failure logs + returns None. The eval result is already in the
    return value of `run_eval_for_version`; persistence is for the
    UI's history view."""
    row = AgentEvalRun(
        organization_id=organization_id,
        agent_profile_id=agent_profile_id,
        prompt_version_id=prompt_version_id,
        mode=mode,
        threshold=threshold,
        score=score,
        overall_passed=overall_passed,
        total_cases=total_cases,
        passed_cases=passed_cases,
        duration_ms=duration_ms,
        report_json=report_json or {},
        error_message=error_message,
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    try:
        db.add(row); db.commit(); db.refresh(row)
        return row
    except Exception as exc:
        logger.error(
            "eval_gate: failed to persist run row: %s", exc, exc_info=True,
        )
        db.rollback()
        return None


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_eval_for_version(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: Optional[UUID],
    prompt_version_id: Optional[UUID],
    mode: str = "stub",
    threshold: float = 0.8,
    triggered_by: str = "manual",
    triggered_by_user_id: Optional[UUID] = None,
) -> AgentEvalRun:
    """Execute the Phase 5F harness, persist the result, return the
    `AgentEvalRun` row.

    Never raises on eval failure — eval failures are recorded as
    `overall_passed=False` rows with `error_message` populated. Only
    raises on argument errors (bad mode, missing inputs).
    """
    if mode not in ("stub", "real"):
        raise EvalGateError(f"Unknown eval mode: {mode!r}", http_status=400)
    if mode == "real":
        # Real-mode wiring (patching synth to a specific version)
        # is deferred to a follow-up slice. Document explicitly so the
        # caller chooses to coerce to stub or wait for the follow-up.
        logger.warning(
            "eval_gate: 'real' mode runs against current resolved synth, "
            "NOT the supplied version. Quality signal may be coarse.",
        )

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    error_message: Optional[str] = None
    score: Optional[float] = None
    overall_passed = False
    total = 0
    passed = 0
    report_blob: dict = {}
    try:
        from tests.eval_phase5.run_eval import run_eval as _run_eval
        report = _run_eval(mode=mode, threshold=threshold)
        score = report.pass_rate
        overall_passed = report.overall_passed
        total = report.total_cases
        passed = report.passed_cases
        report_blob = {
            "mode": report.mode,
            "total_cases": report.total_cases,
            "passed_cases": report.passed_cases,
            "pass_rate": report.pass_rate,
            "threshold": report.threshold,
            "overall_passed": report.overall_passed,
            "duration_ms": report.duration_ms,
            "timestamp": report.timestamp,
            # Per-case results are slim — include the case_id + pass
            # flag + first-failure snippet so the dashboard can
            # render a table without re-running.
            "cases": [
                {
                    "case_id": c.case_id,
                    "passed": c.passed,
                    "first_failure": (
                        c.failures[0] if c.failures else None
                    ),
                    "citations_count": c.citations_count,
                    "duration_ms": c.duration_ms,
                }
                for c in report.case_results
            ],
        }
    except Exception as exc:
        logger.error("eval_gate: harness crashed: %s", exc, exc_info=True)
        error_message = f"harness crashed: {exc}"

    completed_at = datetime.now(timezone.utc)
    duration_ms = int((time.monotonic() - t0) * 1000)

    row = _persist_run(
        db,
        organization_id=organization_id,
        agent_profile_id=agent_profile_id,
        prompt_version_id=prompt_version_id,
        mode=mode,
        threshold=threshold,
        score=score,
        overall_passed=overall_passed,
        total_cases=total,
        passed_cases=passed,
        duration_ms=duration_ms,
        report_json=report_blob,
        error_message=error_message,
        triggered_by=triggered_by,
        triggered_by_user_id=triggered_by_user_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    if row is None:
        # Even if persistence failed, return a transient object so
        # the caller has something to inspect.
        return AgentEvalRun(
            organization_id=organization_id,
            agent_profile_id=agent_profile_id,
            prompt_version_id=prompt_version_id,
            mode=mode, threshold=threshold, score=score,
            overall_passed=overall_passed,
            total_cases=total, passed_cases=passed,
            duration_ms=duration_ms,
            report_json=report_blob, error_message=error_message,
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            started_at=started_at, completed_at=completed_at,
        )
    return row


def run_if_required(
    db: Session,
    *,
    profile: AgentProfile,
    version: PromptVersion,
    actor_user_id: Optional[UUID],
) -> Optional[AgentEvalRun]:
    """Called by `publish_version`. When the profile has
    `eval_gate_required=True`, runs the eval (defaults to stub mode)
    against the candidate version and raises `EvalGateFailed` if the
    score is below the profile's `eval_min_score`.

    Returns the `AgentEvalRun` on success (so the caller can stamp
    `version.eval_run_id` + `version.eval_score`).

    Returns None when the gate is not required — caller proceeds
    without raising.
    """
    if not profile.eval_gate_required:
        return None

    threshold = (
        profile.eval_min_score
        if profile.eval_min_score is not None
        else 0.8
    )

    run = run_eval_for_version(
        db,
        organization_id=profile.organization_id,
        agent_profile_id=profile.id,
        prompt_version_id=version.id,
        mode="stub",
        threshold=threshold,
        triggered_by="publish_gate",
        triggered_by_user_id=actor_user_id,
    )

    # Decide pass/fail. We use `overall_passed` from the harness when
    # available, else compute from score >= threshold.
    if run.error_message is not None:
        raise EvalGateFailed(
            score=run.score, threshold=threshold,
            eval_run_id=run.id if run.id else None,
        )
    if run.score is None:
        # Defensive — shouldn't happen unless the harness returned
        # without error_message but also no score.
        raise EvalGateFailed(
            score=None, threshold=threshold,
            eval_run_id=run.id if run.id else None,
        )
    if run.score < threshold:
        raise EvalGateFailed(
            score=run.score, threshold=threshold,
            eval_run_id=run.id if run.id else None,
        )

    return run


def list_runs_for_agent(
    db: Session,
    *,
    organization_id: UUID,
    agent_profile_id: UUID,
    limit: int = 50,
) -> list[AgentEvalRun]:
    """Most-recent first. Read-only — used by the dashboard's Eval
    tab + the GET endpoint."""
    return (
        db.query(AgentEvalRun)
        .filter(
            AgentEvalRun.organization_id == organization_id,
            AgentEvalRun.agent_profile_id == agent_profile_id,
        )
        .order_by(AgentEvalRun.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
