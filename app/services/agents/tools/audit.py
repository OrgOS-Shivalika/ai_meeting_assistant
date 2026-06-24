"""Audit-log writer for tool invocations inside the harness.

Every tool call the LLM makes inside `harness.run_loop()` writes one
row here. The `run_id` groups all calls from a single loop so we can:
  - Replay an agent run end-to-end
  - Compute per-skill success rate / avg iterations / avg cost
  - Surface in the /agents/:id observability page (H6)

Same audit-log shape as `graph_extraction_runs` / `rag_query_runs`:
append-only, never updated, indexed by org + time.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AgentToolInvocation
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def new_run_id() -> UUID:
    """Generate a fresh run_id for a harness loop. The same run_id
    threads through every tool call in that loop, so all rows for one
    run share it."""
    return uuid.uuid4()


def _jsonable(value: Any) -> Any:
    """Coerce SQLAlchemy / pydantic / Python values to JSON-safe types
    before inserting into JSONB. Same shape as activity.py's helper."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def record_invocation(
    db: Session,
    *,
    organization_id: UUID,
    run_id: UUID,
    iteration: int,
    tool_name: str,
    success: bool,
    meeting_id: Optional[int] = None,
    actor_user_id: Optional[UUID] = None,
    skill_id: Optional[str] = None,
    args: Optional[dict] = None,
    result: Optional[Any] = None,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
    tokens_used: Optional[int] = None,
) -> AgentToolInvocation:
    """Append one tool-invocation row. Caller controls the transaction
    (flush — don't commit here, the harness may need to roll back the
    whole run).
    """
    row = AgentToolInvocation(
        organization_id=organization_id,
        meeting_id=meeting_id,
        actor_user_id=actor_user_id,
        skill_id=skill_id,
        run_id=run_id,
        iteration=iteration,
        tool_name=tool_name,
        args_json=_jsonable(args) if args is not None else None,
        # JSONB has a max practical size; truncate huge result blobs.
        # 10k chars is generous for any sane tool return.
        result_json=_truncate_result(result),
        success=success,
        error_message=(error_message or None) if not success else None,
        duration_ms=duration_ms,
        tokens_used=tokens_used,
    )
    db.add(row)
    db.flush()
    return row


def _truncate_result(result: Any, max_chars: int = 10_000) -> Optional[Any]:
    """JSONB-coerce a result. If the JSON form exceeds `max_chars`,
    stash a sentinel + the prefix instead — avoids ballooning the
    audit table when a tool returns a huge payload (e.g. a 50-meeting
    search result with full summaries)."""
    if result is None:
        return None
    coerced = _jsonable(result)
    try:
        encoded = json.dumps(coerced)
    except (TypeError, ValueError):
        return {"_audit_note": "result was not JSON-serializable", "repr": str(result)[:max_chars]}
    if len(encoded) <= max_chars:
        return coerced
    return {
        "_audit_note": f"result truncated from {len(encoded)} chars",
        "_preview": encoded[:max_chars],
    }
