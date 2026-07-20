"""Continuum Core meeting agent — envelope build + LLM call + board commit.

Entry points:
    run_process(db, client, ...)   -> ContinuumRun   (MODE A — updates board)
    run_brief(db, client, ...)     -> ContinuumRun   (MODE B — read-only)
    confirm_stage(db, client, ...)  -> None           (human drag on the kanban)
    effective_config(db, org_id)   -> dict            (Control Panel read)

Runtime behavior is driven by the per-org `cc_agent_config` row (edited
in the Control Panel): model, max_tokens (token budget), temperature,
and a full master-prompt override. NULL/absent = built-in defaults
(settings.CONTINUUM_MODEL, no cap, model default temp, prompt.md).

Every run is Langfuse-traced through agents_v2.shared.tracing (tag
"continuum") — no-op unless LANGFUSE_* env vars are set.

One hard rule lives in code, not the prompt: the agent never moves
`pipeline.stage` — it only recommends. A human confirms via
confirm_stage() (the kanban drag).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.agents_v2.shared import tracing
from app.config.settings import settings
from app.db.models import ContinuumAgentConfig, ContinuumClient, ContinuumRun

logger = logging.getLogger(__name__)

# Section 2 of the prompt — kanban column order.
STAGES = [
    "DISCOVERY",
    "STRATEGY_PITCH",
    "STRATEGY_DOC",
    "FINANCIALS",
    "HANDOFF",
    "DELIVERY",
]

# Marker that must survive any prompt edit — it anchors the Section 14
# response contract the JSON parser depends on.
_CONTRACT_MARKER = '"package_markdown"'
_CONTRACT_SECTION_HEADER = "## 14. RESPONSE FORMAT"

_openai_client = None


def _get_client():
    """OpenAI client via the tracing wrapper — Langfuse-instrumented
    when enabled, vanilla otherwise."""
    global _openai_client
    if _openai_client is None:
        if not settings.OPEN_API_KEY:
            raise RuntimeError("OPEN_API_KEY is not set")
        openai_mod = tracing.get_openai_client()
        _openai_client = openai_mod.OpenAI(api_key=settings.OPEN_API_KEY)
    return _openai_client


@lru_cache(maxsize=1)
def _default_prompt() -> str:
    return (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _contract_section() -> str:
    """The Section 14 block from the default prompt — re-appended to
    overrides that lost it so a Control Panel edit can't break parsing."""
    text = _default_prompt()
    idx = text.find(_CONTRACT_SECTION_HEADER)
    return text[idx:] if idx != -1 else ""


def _load_config(db: Session, organization_id) -> Optional[ContinuumAgentConfig]:
    return (
        db.query(ContinuumAgentConfig)
        .filter(ContinuumAgentConfig.organization_id == organization_id)
        .first()
    )


def resolve_runtime(db: Session, organization_id) -> dict[str, Any]:
    """Effective runtime knobs for this org: config row over defaults."""
    cfg = _load_config(db, organization_id)
    prompt = _default_prompt()
    prompt_overridden = False
    if cfg is not None and cfg.system_prompt_override:
        prompt = cfg.system_prompt_override
        prompt_overridden = True
        if _CONTRACT_MARKER not in prompt:
            # ponytail: guard, not validation UI — bad edits still work
            prompt = prompt.rstrip() + "\n\n---\n\n" + _contract_section()
    return {
        "model": (cfg.model if cfg and cfg.model else settings.CONTINUUM_MODEL),
        "max_tokens": (cfg.max_tokens if cfg else None),
        "temperature": (cfg.temperature if cfg else None),
        "system_prompt": prompt,
        "prompt_overridden": prompt_overridden,
    }


def current_stage(client_row: ContinuumClient) -> str:
    """Stage shown on the kanban. Falls back to DISCOVERY for new clients."""
    board = client_row.board or {}
    stage = (board.get("pipeline") or {}).get("stage")
    return stage if stage in STAGES else "DISCOVERY"


def _build_envelope(
    client_row: ContinuumClient,
    *,
    mode: str,
    raw_input: str = "",
    attendees: Optional[list[str]] = None,
    salesperson: str = "",
    agenda: Optional[list[str]] = None,
    ideal_outcome: str = "",
    meeting_date: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "client_id": str(client_row.id),
        "client_name": client_row.name,
        # Board version counts processed meetings; next meeting = version + 1.
        "meeting_number": (client_row.board_version or 0) + 1,
        "meeting_date": meeting_date or datetime.now(timezone.utc).date().isoformat(),
        "attendees": attendees or [],
        "salesperson": salesperson,
        "meeting_setup": {
            "agenda": agenda or [],
            "ideal_outcome": ideal_outcome or "",
            # Human-confirmed stage is the authority (Section 4.1).
            "stage_at_setup": current_stage(client_row) if client_row.board else "",
        },
        "raw_input": raw_input if mode == "process" else "",
        "client_board": client_row.board,
        "stage_playbook": None,  # ponytail: playbook consume not wired; deltas stored in cc_runs for later
    }


def _call_llm(envelope: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": runtime["model"],
        "messages": [
            {"role": "system", "content": runtime["system_prompt"]},
            {"role": "user", "content": json.dumps(envelope, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "timeout": 180,
    }
    if runtime.get("max_tokens"):
        kwargs["max_tokens"] = runtime["max_tokens"]
    if runtime.get("temperature") is not None:
        kwargs["temperature"] = runtime["temperature"]

    response = _get_client().chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    parsed = json.loads(content)
    if "package_markdown" not in parsed:
        raise ValueError("LLM response missing package_markdown")
    return parsed


def _sanitize_recommendation(rec: Any, stage_before: str) -> Optional[dict[str, Any]]:
    """Keep only well-formed recommendations for a DIFFERENT valid stage."""
    if not isinstance(rec, dict):
        return None
    target = rec.get("recommended_stage")
    if target not in STAGES or target == stage_before:
        return None
    return {"recommended_stage": target, "rationale": str(rec.get("rationale") or "")}


@tracing.observe(name="continuum.run")
def _execute(
    db: Session,
    client_row: ContinuumClient,
    envelope: dict[str, Any],
    meeting_id: Optional[int] = None,
) -> ContinuumRun:
    runtime = resolve_runtime(db, client_row.organization_id)
    tracing.update_current_trace(
        tags=["continuum"],
        session_id=f"cc-client-{client_row.id}",
        metadata={
            "mode": envelope["mode"],
            "client": client_row.name,
            "meeting_id": meeting_id,
            "model": runtime["model"],
            "prompt_overridden": runtime["prompt_overridden"],
        },
    )

    run = ContinuumRun(
        client_id=client_row.id,
        meeting_id=meeting_id,
        mode=envelope["mode"],
        model=runtime["model"],
        input_envelope=envelope,
    )
    started = time.monotonic()
    try:
        parsed = _call_llm(envelope, runtime)
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:4000]
        run.duration_ms = int((time.monotonic() - started) * 1000)
        db.add(run)
        db.commit()
        db.refresh(run)
        tracing.flush()
        return run

    run.duration_ms = int((time.monotonic() - started) * 1000)
    run.status = "completed"
    run.package_markdown = parsed.get("package_markdown") or ""
    run.playbook_delta = parsed.get("playbook_delta") or []

    board = parsed.get("updated_board")
    if envelope["mode"] == "process" and isinstance(board, dict):
        stage_before = current_stage(client_row)
        had_board = client_row.board is not None

        # HARD RULE (Section 2): the agent recommends stage moves, a human
        # confirms them. Even if the LLM ignored the prompt and advanced
        # pipeline.stage inside the board, pin it back. First-ever board
        # is exempt (there is no prior human-confirmed stage yet).
        if had_board:
            pipeline = board.setdefault("pipeline", {})
            if pipeline.get("stage") != stage_before:
                logger.warning(
                    "continuum: LLM tried to move client %s stage %s -> %s; pinned back",
                    client_row.id, stage_before, pipeline.get("stage"),
                )
                pipeline["stage"] = stage_before

        rec = _sanitize_recommendation(parsed.get("stage_recommendation"), stage_before)
        run.stage_recommendation = rec
        client_row.latest_recommendation = rec

        client_row.board = board
        client_row.board_version = (client_row.board_version or 0) + 1
        run.board_after = board
        run.board_version_after = client_row.board_version

    db.add(run)
    db.commit()
    db.refresh(run)
    tracing.flush()
    return run


def run_process(
    db: Session,
    client_row: ContinuumClient,
    *,
    raw_input: str,
    attendees: Optional[list[str]] = None,
    salesperson: str = "",
    agenda: Optional[list[str]] = None,
    ideal_outcome: str = "",
    meeting_date: Optional[str] = None,
    meeting_id: Optional[int] = None,
) -> ContinuumRun:
    envelope = _build_envelope(
        client_row,
        mode="process",
        raw_input=raw_input,
        attendees=attendees,
        salesperson=salesperson,
        agenda=agenda,
        ideal_outcome=ideal_outcome,
        meeting_date=meeting_date,
    )
    return _execute(db, client_row, envelope, meeting_id=meeting_id)


def run_brief(
    db: Session,
    client_row: ContinuumClient,
    *,
    agenda: Optional[list[str]] = None,
    ideal_outcome: str = "",
) -> ContinuumRun:
    envelope = _build_envelope(
        client_row,
        mode="brief",
        agenda=agenda,
        ideal_outcome=ideal_outcome,
    )
    return _execute(db, client_row, envelope)


def confirm_stage(db: Session, client_row: ContinuumClient, new_stage: str) -> None:
    """Human stage confirmation — the kanban drag. Writes pipeline.stage,
    appends stage_history, clears the pending recommendation."""
    if new_stage not in STAGES:
        raise ValueError(f"Unknown stage '{new_stage}'")

    board = dict(client_row.board or {})
    pipeline = dict(board.get("pipeline") or {})
    old_stage = pipeline.get("stage") if pipeline.get("stage") in STAGES else "DISCOVERY"
    if new_stage == old_stage:
        return

    history = list(pipeline.get("stage_history") or [])
    history.append({
        "from": old_stage,
        "to": new_stage,
        "confirmed_by": "human",
        "at": datetime.now(timezone.utc).isoformat(),
    })
    pipeline["stage"] = new_stage
    pipeline["stage_history"] = history
    pipeline["calls_in_stage"] = 0
    board["pipeline"] = pipeline

    client_row.board = board
    client_row.latest_recommendation = None
    db.commit()
