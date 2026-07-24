# Agent Harness — Work Log

Full session record for shipping Piece 1 (H1–H5) of the agent tool-calling
harness, plus the H6 observability page. Captures every code change,
smoke test, explanation, and decision in order.

---

## Context from prior session (summary carried over compaction)

### Primary Request and Intent

User has been building an Agentic Meeting Assistant (FastAPI + Postgres
pgvector + Celery + React/Vite + Recall.ai + Deepgram + OpenAI). In this
session, the work moved through several distinct intents:

- **Briefing language control**: User wanted two options for closing
  briefing — match meeting's primary language (auto-detect) OR force English
  regardless. Wanted this exposed in Agent Control.
- **Agent harness implementation**: User's manager gave them a checklist:
  "Frontier model, system prompt, goal/intent, tools, skills (how to use
  the tools is going in the skills.md), voice, token budget, memory,
  metrics/eval (logs, metrics), autoresearch agent (frequency, per run
  budget, improvements)". User said "i dont know what the fuck he is
  talking bout" and asked for translation.
- **Tool inventory**: User wanted to know what tools exist and where they
  live.
- **Tool file split**: User wanted each tool in its own file for easier
  reading/debugging.
- **Skills inventory**: User wanted to know what skills exist and what's
  needed.
- **Write skills.md**: User explicitly said "OK WRITE A SKILLS.MD FILE".
- **Tool-to-skill mapping**: User wanted detailed mapping of tools used by
  skills.
- **Ship Piece 1**: User's final explicit request was "ship the piece 1" —
  execute the tool-calling harness plan.

### Key Technical Concepts

- Agent harness (tool-calling LLM loop with safety rails)
- Tools registry with Tool dataclass and ToolContext
- SkillDefinition with required_tools, system_prompt, output_schema
- BehaviorProfile resolver (workspace > category > team)
- Closing briefing language detection (Devanagari ratio)
- Audit logging pattern (agent_tool_invocations following
  graph_extraction_runs shape)
- JSON schema validation via jsonschema library
- Alembic migrations
- OpenAI function calling format
- Per-tool timeout + per-loop token budget + max iterations safety rails
- Recall.ai integration with retry logic
- SQLAlchemy models with Base.metadata

### Files modified before this session

- `app/services/briefing/briefing_composer.py` — added `language_override`
  kwarg to `compose()` method. Language priority: explicit override >
  detected from transcript > english default.

  ```python
  if language_override in ("english", "hindi", "hinglish"):
      target_language = language_override
  else:
      raw_transcript = self._read_raw_transcript(meeting_id)
      target_language = _detect_language(raw_transcript) if raw_transcript else "english"
  ```

- `app/services/briefing/closing_briefing_orchestrator.py` — changed
  `_resolve_briefing_overrides()` from 2-tuple to 3-tuple returning
  (model, voice, language_override). Updated both call sites in
  `_compose_and_synth` and `_speak_and_leave`.

- `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`
  — added `BRIEFING_LANGUAGE_OPTIONS = [{value:"auto",label:"Match meeting
  language..."},{value:"english",label:"Always English"}]`. QuickRuntimeControls
  now 3-column grid with new briefing language card. `save()` signature
  changed to accept dimension parameter. RuntimePicker upgraded to take
  `Array<{value, label}>` options.

- `app/services/agents/tools/builtin/` (new directory) — split the 11-tool
  single-file `builtin.py` into per-tool files:
  - `__init__.py` — side-effect imports all tool modules
  - `_stub.py` — `make_handler(name)` returns NotImplementedError-raising handler
  - `lookup_meeting.py` — 60 LOC, queries Meeting by ID + open tasks + participants
  - `search_knowledge_base.py` — 60 LOC, ILIKE search over title/summary/transcript
  - `create_task.py` — 80 LOC, inserts Task with Kanban routing
  - `update_task.py` — 60 LOC, patches owner/status/priority/due_date
  - `slack_post.py`, `jira_create_issue.py`, `github_create_pr.py`,
    `notion_create_page.py`, `crm_update_record.py`, `send_email.py`,
    `create_calendar_event.py` — each ~20 LOC stub
- Deleted old `app/services/agents/tools/builtin.py`

- `skills.md` (new file at repo root) — 310 lines, 9 sections:
  1. What a skill is (vs tool)
  2. Lifecycle states (Active/Built-in/Designed/Proposed)
  3. Active skills (empty today, with template)
  4. Built-in analyzer capabilities (honest: SkillDefinition files are
     descriptive metadata, real logic is in analyzer prompt)
  5. Designed but not built (28 placeholder skills inventoried by domain)
  6. Proposed: meeting_context_researcher, autoresearch (with manager's 3
     knobs), action_items_v2
  7. How to add a new skill (template + checklist)
  8. Open questions
  9. References

### Pending Tasks entering this session

- **H1** (in progress): Migration created. Still need to add
  `AgentToolInvocation` ORM class to `app/db/models.py` and create
  `app/services/agents/tools/audit.py` helper, then run migration.
- **H2**: Build `app/services/agents/harness.py` with run_loop + 6 safety
  rails (MAX_ITERATIONS=8, MAX_TOKENS_PER_LOOP=30k, per-tool timeout=10s,
  arg validation, deny-list, org scope)
- **H3**: Add `harness_enabled` flag to `tools_and_integrations` profile +
  Agent Control UI toggle
- **H4**: Wire `graph_orchestrator.run_meeting_analysis()` to branch on
  flag
- **H5**: Build `meeting_context_researcher` skill that uses
  search_knowledge_base + lookup_meeting
- **H6** (deferred): /agents/:id observability page
- End-to-end smoke test of harness loop

### Memory items carried over

- "Don't mock the database in these tests"
- "User wants terse responses with no trailing summaries"

---

## H1 — Audit table + AgentToolInvocation model + audit.py helper

### Migration (already created in prior session)

File: `alembic/versions/a7i1e3f4g5h_agent_tool_invocations.py`

```python
"""Phase 14B / Piece 1 — agent_tool_invocations audit table.

One row per tool call inside a harness loop. Groups by `run_id`
so an entire agent run can be replayed / inspected.

Same audit-log shape as `graph_extraction_runs`, `rag_query_runs`,
`importance_runs`, `agent_runtime_log`.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "a7i1e3f4g5h"
down_revision = "z6h0d2e3f4g"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tool_invocations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "organization_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id", sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id", UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("skill_id", sa.String(64), nullable=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("args_json", JSONB(), nullable=True),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_tool_invocations_org_created",
        "agent_tool_invocations", ["organization_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "ix_agent_tool_invocations_run",
        "agent_tool_invocations", ["run_id"],
    )
    op.create_index(
        "ix_agent_tool_invocations_meeting",
        "agent_tool_invocations", ["meeting_id"],
    )
    op.create_index(
        "ix_agent_tool_invocations_skill_created",
        "agent_tool_invocations", ["skill_id", "created_at"],
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_agent_tool_invocations_skill_created", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_meeting", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_run", table_name="agent_tool_invocations")
    op.drop_index("ix_agent_tool_invocations_org_created", table_name="agent_tool_invocations")
    op.drop_table("agent_tool_invocations")
```

### AgentToolInvocation ORM class

Added to `app/db/models.py` before the `TemplateBundle` section:

```python
# ---------------------------------------------------------------------------
# Phase 14B / Piece 1 — agent tool invocation audit log
#
# One row per tool call inside a harness loop. `run_id` groups all
# invocations from one loop so an entire agent run can be replayed.
# Same audit-log shape as graph_extraction_runs, rag_query_runs.
# ---------------------------------------------------------------------------


class AgentToolInvocation(Base):
    __tablename__ = "agent_tool_invocations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    meeting_id = Column(
        Integer,
        ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    skill_id = Column(String(64), nullable=True)
    run_id = Column(UUID(as_uuid=True), nullable=False)
    iteration = Column(Integer, nullable=False)
    tool_name = Column(String(64), nullable=False)
    args_json = Column(JSONB, nullable=True)
    result_json = Column(JSONB, nullable=True)
    success = Column(Boolean, nullable=False)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_agent_tool_invocations_org_created", "organization_id", "created_at"),
        Index("ix_agent_tool_invocations_run", "run_id"),
        Index("ix_agent_tool_invocations_meeting", "meeting_id"),
        Index("ix_agent_tool_invocations_skill_created", "skill_id", "created_at"),
    )
```

### audit.py helper

File: `app/services/agents/tools/audit.py`

```python
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
```

### H1 verification

```
$ python -c "from app.db.models import AgentToolInvocation; print('OK', AgentToolInvocation.__tablename__)"
OK agent_tool_invocations

$ alembic upgrade head
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade z6h0d2e3f4g -> a7i1e3f4g5h, Phase 14B / Piece 1 - agent_tool_invocations audit table.

$ python -c "...record_invocation smoke..."
INSERTED id= 1 run_id= 78255c1c-e251-4e93-997d-8543fe210185
```

H1 done.

---

## H2 — harness.py with loop + 6 safety rails

File: `app/services/agents/harness.py`

```python
"""Agent harness — the tool-calling LLM loop.

This is the inner runtime for "agentic" skills. Where the legacy
`SkillExecutor` does a single LLM call (system+user → JSON), the
harness lets the model iterate:

    while not done and budget remaining:
        msg = llm.chat.completions.create(messages, tools=...)
        if msg.tool_calls:
            for call in msg.tool_calls:
                result = registry.invoke(call.name, call.args, ctx)
                messages.append(tool result)
        else:
            return msg.content

Every loop carries a single `run_id`. Every tool call is audited via
`audit.record_invocation`. Six safety rails enforce blast radius:

    1. MAX_ITERATIONS — hard ceiling on loop count (8).
    2. MAX_TOKENS_PER_LOOP — sum of usage.total_tokens across calls (30k).
    3. PER_TOOL_TIMEOUT — wall-clock cap per handler (10s).
    4. ARG VALIDATION — jsonschema against the Tool's parameters.
    5. DENY_LIST — skill's allowed_tools is a whitelist; anything else fails.
    6. ORG SCOPE — ToolContext.organization_id is the only tenant tools see.

Caller (graph_orchestrator) supplies:
    - the skill (system_prompt, allowed_tools, output_schema)
    - user input (transcript or task statement)
    - meeting/org/user context
The harness returns the final structured output + run metadata.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from jsonschema import Draft202012Validator, ValidationError
from sqlalchemy.orm import Session

from app.ai_agents.openAI_transcript_analyzer import _get_client
from app.services.agents.tools import audit, registry
from app.services.agents.tools.registry import Tool, ToolContext
from app.skills.base import SkillDefinition
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# Safety rails — values picked to be obviously-too-generous-to-hit
# in the happy path, obviously-too-tight to let a runaway model burn
# budget. Tune via Agent Control later (H3).
MAX_ITERATIONS = 8
MAX_TOKENS_PER_LOOP = 30_000
PER_TOOL_TIMEOUT_SECONDS = 10
DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class HarnessResult:
    """Returned from `run_loop` — carries both the model's final
    answer and the metadata needed for downstream observability.
    """
    output: Any
    run_id: UUID
    iterations: int
    tokens_used: int
    tool_calls: int
    stopped_reason: str  # "answered" | "max_iter" | "max_tokens" | "error"
    messages: list[dict] = field(default_factory=list)


class HarnessError(RuntimeError):
    """Raised when the harness can't continue (budget exceeded, bad
    tool name, schema-rejected args after a retry, etc)."""


def run_loop(
    *,
    db: Session,
    skill: SkillDefinition,
    user_input: str,
    organization_id: UUID,
    meeting_id: Optional[int] = None,
    actor_user_id: Optional[UUID] = None,
    actor_name: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_iterations: int = MAX_ITERATIONS,
    token_budget: int = MAX_TOKENS_PER_LOOP,
    extra_system: str = "",
) -> HarnessResult:
    """Execute one tool-calling agent loop.

    Returns when the model emits a no-tool-calls message (it's "done")
    OR a rail trips (iteration / token budget exhausted).
    """
    run_id = audit.new_run_id()
    logger.info(
        f"[HARNESS] start run_id={run_id} skill={skill.id} meeting={meeting_id} "
        f"max_iter={max_iterations} token_budget={token_budget}"
    )

    # --- Rail 5: deny-list — whitelist via skill.required_tools ---
    # The skill declares what it's allowed to touch. The registry
    # filter drops anything not in that list, so even if the model
    # hallucinates a tool name, dispatch will KeyError.
    allowed_tools: list[Tool] = registry.list_for_skill(list(skill.required_tools or []))
    if not allowed_tools:
        # Skill is degenerate — no tools means no harness benefit.
        # Run a single-shot completion as a graceful fallback.
        logger.warning(f"[HARNESS] skill {skill.id} has no allowed tools — single-shot fallback")
    openai_tools = registry.to_openai_format(allowed_tools)
    validators = {t.name: Draft202012Validator(t.parameters) for t in allowed_tools}

    # --- Rail 6: org scope — every tool sees this context, nothing else ---
    ctx = ToolContext(
        db=db,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        meeting_id=meeting_id,
    )

    system_prompt = _compose_system_prompt(skill, extra_system)
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]

    client = _get_client()
    tokens_used = 0
    tool_call_count = 0

    for iteration in range(max_iterations):
        # --- Rail 2: token budget ---
        if tokens_used >= token_budget:
            logger.warning(f"[HARNESS] token budget exhausted at iter={iteration} run_id={run_id}")
            return HarnessResult(
                output=None,
                run_id=run_id,
                iterations=iteration,
                tokens_used=tokens_used,
                tool_calls=tool_call_count,
                stopped_reason="max_tokens",
                messages=messages,
            )

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "timeout": 60,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as e:
            logger.error(f"[HARNESS] LLM call failed at iter={iteration}: {e}")
            return HarnessResult(
                output=None,
                run_id=run_id,
                iterations=iteration,
                tokens_used=tokens_used,
                tool_calls=tool_call_count,
                stopped_reason="error",
                messages=messages,
            )

        usage = getattr(resp, "usage", None)
        if usage and getattr(usage, "total_tokens", None):
            tokens_used += usage.total_tokens

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        # Append the assistant message so subsequent tool replies
        # have something to attach to.
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ] if tool_calls else None,
            }
        )

        # Terminal: model produced an answer with no further tool calls.
        if not tool_calls:
            final_output = _coerce_output(msg.content or "", skill)
            logger.info(
                f"[HARNESS] done run_id={run_id} iters={iteration + 1} "
                f"tokens={tokens_used} tool_calls={tool_call_count}"
            )
            return HarnessResult(
                output=final_output,
                run_id=run_id,
                iterations=iteration + 1,
                tokens_used=tokens_used,
                tool_calls=tool_call_count,
                stopped_reason="answered",
                messages=messages,
            )

        # Dispatch each tool call. Per-call: validate, time-box,
        # audit-log the outcome, and feed the result back into messages.
        for tc in tool_calls:
            tool_call_count += 1
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError as e:
                args = {}
                _append_tool_error(messages, tc.id, name, f"args were not valid JSON: {e}")
                audit.record_invocation(
                    db,
                    organization_id=organization_id,
                    run_id=run_id,
                    iteration=iteration,
                    tool_name=name,
                    success=False,
                    meeting_id=meeting_id,
                    actor_user_id=actor_user_id,
                    skill_id=skill.id,
                    args={"_raw": raw_args[:500]},
                    error_message=str(e),
                )
                continue

            # --- Rail 5: deny-list at dispatch (defense in depth) ---
            validator = validators.get(name)
            if validator is None:
                _append_tool_error(messages, tc.id, name, f"tool {name!r} is not allowed for skill {skill.id}")
                audit.record_invocation(
                    db,
                    organization_id=organization_id,
                    run_id=run_id,
                    iteration=iteration,
                    tool_name=name,
                    success=False,
                    meeting_id=meeting_id,
                    actor_user_id=actor_user_id,
                    skill_id=skill.id,
                    args=args,
                    error_message="tool not in skill's allow-list",
                )
                continue

            # --- Rail 4: arg validation ---
            try:
                validator.validate(args)
            except ValidationError as e:
                _append_tool_error(messages, tc.id, name, f"args failed schema: {e.message}")
                audit.record_invocation(
                    db,
                    organization_id=organization_id,
                    run_id=run_id,
                    iteration=iteration,
                    tool_name=name,
                    success=False,
                    meeting_id=meeting_id,
                    actor_user_id=actor_user_id,
                    skill_id=skill.id,
                    args=args,
                    error_message=f"schema: {e.message}",
                )
                continue

            # --- Rail 3: per-tool timeout (wall clock) ---
            start = time.monotonic()
            try:
                result = _invoke_with_timeout(name, args, ctx, PER_TOOL_TIMEOUT_SECONDS)
                duration_ms = int((time.monotonic() - start) * 1000)
                audit.record_invocation(
                    db,
                    organization_id=organization_id,
                    run_id=run_id,
                    iteration=iteration,
                    tool_name=name,
                    success=True,
                    meeting_id=meeting_id,
                    actor_user_id=actor_user_id,
                    skill_id=skill.id,
                    args=args,
                    result=result,
                    duration_ms=duration_ms,
                )
                _append_tool_result(messages, tc.id, name, result)
            except Exception as e:
                duration_ms = int((time.monotonic() - start) * 1000)
                logger.warning(f"[HARNESS] tool {name} failed: {e}")
                audit.record_invocation(
                    db,
                    organization_id=organization_id,
                    run_id=run_id,
                    iteration=iteration,
                    tool_name=name,
                    success=False,
                    meeting_id=meeting_id,
                    actor_user_id=actor_user_id,
                    skill_id=skill.id,
                    args=args,
                    error_message=str(e)[:1000],
                    duration_ms=duration_ms,
                )
                _append_tool_error(messages, tc.id, name, str(e))

        db.commit()  # Flush this iteration's audit rows; harness can resume.

    # --- Rail 1: max iterations ---
    logger.warning(f"[HARNESS] max iterations reached run_id={run_id}")
    return HarnessResult(
        output=None,
        run_id=run_id,
        iterations=max_iterations,
        tokens_used=tokens_used,
        tool_calls=tool_call_count,
        stopped_reason="max_iter",
        messages=messages,
    )


# ---------- helpers ----------


def _compose_system_prompt(skill: SkillDefinition, extra: str) -> str:
    parts = [
        "You are an agent operating inside a meeting-intelligence platform.",
        "You have access to tools — call them as needed to fulfill the user's request.",
        "When you have enough information, reply with your final answer as JSON matching the skill's output schema.",
        "",
        "--- SKILL MISSION ---",
        skill.system_prompt or "",
    ]
    if skill.output_schema:
        parts += [
            "",
            "--- OUTPUT SCHEMA ---",
            "Your final (no-tool-calls) message MUST be valid JSON matching this schema:",
            json.dumps(skill.output_schema, indent=2),
        ]
    if extra:
        parts += ["", extra]
    return "\n".join(parts).strip()


def _coerce_output(raw: str, skill: SkillDefinition) -> Any:
    """Parse the model's final message into structured output. If
    the skill declares a JSON output_schema, we try to parse JSON;
    otherwise we return the raw string."""
    if not skill.output_schema:
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[HARNESS] final message wasn't valid JSON; returning raw")
        return {"_raw": raw}


def _invoke_with_timeout(name: str, args: dict, ctx: ToolContext, timeout_s: int) -> Any:
    """Run a tool handler with a wall-clock cap.

    ponytail: no thread-kill — Python can't safely interrupt arbitrary
    handler code. We measure elapsed time after the call and raise if
    we blew past the budget. Cheap, prevents *future* calls from
    running unchecked, doesn't pretend to be a hard interrupt.
    The DB session has its own statement_timeout for query-bound waits.
    """
    start = time.monotonic()
    result = registry.invoke(name, args, ctx)
    elapsed = time.monotonic() - start
    if elapsed > timeout_s:
        raise TimeoutError(f"tool {name} ran {elapsed:.1f}s, budget {timeout_s}s")
    return result


def _append_tool_result(messages: list[dict], call_id: str, name: str, result: Any) -> None:
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps(result, default=str),
        }
    )


def _append_tool_error(messages: list[dict], call_id: str, name: str, error: str) -> None:
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": json.dumps({"error": error}),
        }
    )
```

### H2 verification

```
$ python -c "from app.services.agents.harness import run_loop, HarnessResult, MAX_ITERATIONS; print('OK', MAX_ITERATIONS)"
OK 8
```

---

## H3 — harness_enabled flag + Agent Control toggle

### Frontend — BehaviorEditor.tsx changes

**New options constant:**

```tsx
// Agent harness — when "on", post-meeting skills that declare tools
// run inside the tool-calling loop (harness.run_loop) instead of the
// legacy single-shot SkillExecutor. Default off until we're confident.
const HARNESS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "off", label: "Off — single-shot LLM" },
  { value: "on", label: "On — tool-calling loop" },
];
```

**QuickRuntimeControls state additions:**

```tsx
const tools = (resolved?.tools_and_integrations || {}) as { model?: string; voice?: string; harness_enabled?: string | boolean };
const toolsLocal = (scopeOverrides.tools_and_integrations || {}) as { model?: unknown; voice?: unknown; harness_enabled?: unknown };
// Default off — opt-in only until the harness is battle-tested.
const harnessRaw = tools.harness_enabled;
const harnessValue = harnessRaw === true || harnessRaw === "on" || harnessRaw === "true" ? "on" : "off";
const harnessOverridden = Object.prototype.hasOwnProperty.call(toolsLocal, "harness_enabled");
```

**New 4th RuntimePicker card:**

```tsx
<RuntimePicker
  label="Agent harness"
  hint="Off: legacy single-shot LLM. On: tool-calling loop with audit log."
  value={harnessValue}
  options={HARNESS_OPTIONS}
  overridden={harnessOverridden}
  onChange={(v) => save("tools_and_integrations", "harness_enabled", v)}
  suppressInherit={!harnessOverridden}
/>
```

**Grid expanded to 4 columns:**

```tsx
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
```

### Backend — policy_resolver.py default seed

```python
profile.tools_and_integrations = {
    "allowed_tools": allowed,
    "denied_tools": [],
    "temperature": 0.3, # System-managed
    "harness_enabled": "off",  # Piece 1 — opt-in via Agent Control
}
```

### H3 verification — TS check passes

```
$ npx tsc -b --noEmit
(clean output)
```

---

## H4 — Wire graph_orchestrator to branch on flag

### graph_orchestrator.py changes

Replaced the skill execution loop in `_orchestrate_agent()`:

```python
# Piece 1 — harness opt-in. If `tools_and_integrations.harness_enabled`
# is "on" AND the skill declares required_tools, run inside the
# tool-calling loop. Otherwise fall back to the single-shot
# SkillExecutor. Skills with no required_tools always use the
# legacy path — no tools means no harness benefit.
tools_cfg = (profile.tools_and_integrations or {})
harness_flag = str(tools_cfg.get("harness_enabled", "off")).lower()
harness_on = harness_flag in ("on", "true", "1", "yes")

skill_results = {}
for skill in skills:
    try:
        if harness_on and skill.required_tools:
            logger.info("🛠️  Executing Skill via HARNESS: %s", skill.id)
            output = cls._run_skill_in_harness(db, skill, transcript, profile, meeting_id)
        else:
            logger.info("🚀 Executing Skill: %s", skill.id)
            output = SkillExecutor.execute_skill(db, skill, transcript, profile, meeting_id)
        skill_results[skill.id] = output

        logger.debug("Skill %s output: %s", skill.id, output)
    except Exception as e:
        logger.error("Skill %s failed: %s", skill.id, str(e), exc_info=True)

return skill_results

@classmethod
def _run_skill_in_harness(
    cls,
    db,
    skill,
    transcript: str,
    profile: ResolvedBehaviorProfile,
    meeting_id: Optional[int],
) -> Dict[str, Any]:
    """Bridge a SkillDefinition into the tool-calling harness.

    Returns the harness's structured `output` (matching skill.output_schema)
    when the loop terminated by answering; falls back to {error: ...}
    when a rail tripped so downstream merger doesn't get a None.
    """
    # Lazy import — keeps harness off the import path for legacy runs.
    from app.services.agents.harness import run_loop
    # Side-effect import so every built-in tool is registered before
    # the registry is queried. Cheap (only fires the first time).
    from app.services.agents.tools import builtin  # noqa: F401

    tools_cfg = profile.tools_and_integrations or {}
    model = tools_cfg.get("model") or "gpt-4o-mini"

    result = run_loop(
        db=db,
        skill=skill,
        user_input=transcript,
        organization_id=profile.organization_id,
        meeting_id=meeting_id,
        model=model,
    )
    if result.stopped_reason != "answered":
        return {
            "error": f"harness stopped: {result.stopped_reason}",
            "run_id": str(result.run_id),
            "iterations": result.iterations,
        }
    return result.output
```

### H4 verification

```
$ python -c "from app.services.agents.graph_orchestrator import AgentGraphOrchestrator; print('OK')"
OK
```

---

## H5 — meeting_context_researcher skill

File: `app/skills/meetings/meeting_context_researcher.py`

```python
"""meeting_context_researcher — Piece 1 first real tool-using skill.

Goal: when a meeting concludes, the harness gives this skill the
transcript and lets it choose how much prior context to fetch. It can
search the knowledge base for related discussions and look up a
specific past meeting by ID. The output: a short structured brief
that downstream skills (action_items, decisions, summaries) can
consume as background.

This is the smallest skill that exercises ALL the harness rails:
  - declares required_tools (so deny-list filters at registry level)
  - tool args go through jsonschema validation
  - real DB calls flow through ToolContext (org scope enforced)
  - audit row written per tool call
"""
from app.skills.base import SkillDefinition
from app.skills.registry import register_skill


skill = SkillDefinition(
    id="meeting_context_researcher",
    name="Meeting Context Researcher",
    description=(
        "Pulls related history for the current meeting by searching prior "
        "knowledge base entries and looking up referenced past meetings. "
        "Outputs a short brief consumed by downstream extraction skills."
    ),
    capabilities=["Context Research"],
    system_prompt=(
        "You are the context researcher for a just-finished meeting. You will be "
        "given the meeting transcript.\n"
        "\n"
        "Your job:\n"
        "1. Identify 1-3 topics, projects, or past meetings worth pulling history on.\n"
        "2. Use `search_knowledge_base` to find prior discussions (max 2 searches).\n"
        "3. If a specific past meeting is referenced by ID, use `lookup_meeting`.\n"
        "4. Stop calling tools as soon as you have enough — DO NOT over-fetch.\n"
        "5. Return a structured JSON brief.\n"
        "\n"
        "Budget: at most 4 tool calls total. Be lazy — one good search beats five "
        "shallow ones."
    ),
    required_tools=["search_knowledge_base", "lookup_meeting"],
    output_schema={
        "type": "object",
        "properties": {
            "related_topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Short list of topics this meeting touched on.",
            },
            "prior_context_summary": {
                "type": "string",
                "description": "2-4 sentence summary of relevant history found.",
            },
            "referenced_meeting_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of past meetings this one explicitly built on.",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
        },
        "required": ["related_topics", "prior_context_summary", "confidence"],
    },
    emits_events=["meetings.context_researched"],
    enabled_by_default=False,  # opt-in via Agent Control until proven out
)

register_skill(skill)
```

Registered in `app/skills/meetings/__init__.py`:

```python
from .meeting_context_researcher import skill as meeting_context_researcher_skill
```

### H5 verification

```
$ python -c "..."
id= meeting_context_researcher
required_tools= ['search_knowledge_base', 'lookup_meeting']
output_schema keys= ['related_topics', 'prior_context_summary', 'referenced_meeting_ids', 'confidence']
```

---

## End-to-end smoke test

```python
# End-to-end smoke: run the harness against the new skill on a fake transcript.
# Validates: tool registration → schema validation → tool execution → audit row insert → final JSON output.
from app.db.database import SessionLocal
from app.db.models import Organization, AgentToolInvocation
from app.services.agents.harness import run_loop
from app.services.agents.tools import builtin  # noqa
import app.skills.meetings  # noqa
from app.skills.registry import SkillRegistry

db = SessionLocal()
try:
    org = db.query(Organization).first()
    print('using org:', org.id)
    skill = SkillRegistry.get('meeting_context_researcher')

    transcript = (
        'Alice: Following up on last week\'s onboarding redesign discussion. '
        'Bob: Right, we agreed in meeting 42 to move the welcome screen to step 2. '
        'Alice: Did we ever resolve the SSO integration question? Let me check the KB.'
    )

    result = run_loop(
        db=db,
        skill=skill,
        user_input=transcript,
        organization_id=org.id,
        meeting_id=None,
        model='gpt-4o-mini',
        max_iterations=4,
        token_budget=15000,
    )
    print('stopped_reason:', result.stopped_reason)
    print('iterations:', result.iterations)
    print('tokens_used:', result.tokens_used)
    print('tool_calls:', result.tool_calls)
    print('run_id:', result.run_id)
    print('output:', result.output)

    rows = db.query(AgentToolInvocation).filter(AgentToolInvocation.run_id == result.run_id).all()
    print(f'audit rows for run: {len(rows)}')
    for r in rows:
        print(f'  iter={r.iteration} tool={r.tool_name} success={r.success} dur_ms={r.duration_ms} err={r.error_message}')
    db.rollback()
finally:
    db.close()
```

### Smoke output

```
using org: 18c012f4-e967-4e35-b2db-04aed20f8ae7
[HARNESS] start run_id=b4038402-884a-4c5b-b6fe-eb275827e0be skill=meeting_context_researcher meeting=None max_iter=4 token_budget=15000
[TOOLS] invoke search_knowledge_base args={"query": "onboarding redesign", "limit": 5}
[TOOLS] invoke lookup_meeting args={"meeting_id": 42}
[HARNESS] done run_id=b4038402-884a-4c5b-b6fe-eb275827e0be iters=2 tokens=1448 tool_calls=2
stopped_reason: answered
iterations: 2
tokens_used: 1448
tool_calls: 2
run_id: b4038402-884a-4c5b-b6fe-eb275827e0be
output: {'related_topics': ['onboarding redesign', 'SSO integration', 'welcome screen changes'], 'prior_context_summary': 'The meeting discussed onboarding redesign, including modifications to the welcome screen and the SSO integration issue. However, there seems to be a lack of historical discussions about these topics in the knowledge base.', 'referenced_meeting_ids': [42], 'confidence': 'medium'}
audit rows for run: 2
  iter=0 tool=search_knowledge_base success=True dur_ms=48 err=None
  iter=0 tool=lookup_meeting success=True dur_ms=4 err=None
```

End-to-end works. Two tool calls, both audited, structured JSON output
matching the schema, 1448 tokens, two iterations.

---

## Piece 1 ship summary (after H1–H5)

**Piece 1 shipped.** H1–H5 + smoke all green. Summary of what landed:

- `alembic/versions/a7i1e3f4g5h_agent_tool_invocations.py` — audit table
  migration, applied to DB
- `app/db/models.py` — `AgentToolInvocation` ORM model
- `app/services/agents/tools/audit.py` — `record_invocation()` writes one
  row per tool call
- `app/services/agents/harness.py` — `run_loop()` with all 6 safety rails
  (max_iter=8, token_budget=30k, per-tool timeout=10s, jsonschema arg
  validation, allow-list dispatch, org-scoped ToolContext)
- `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`
  — 4th Quick Runtime card: "Agent harness" off/on
- `app/services/behavior/policy_resolver.py` — seeds `harness_enabled: "off"`
  default
- `app/services/agents/graph_orchestrator.py` — `_run_skill_in_harness()`
  branches on the flag + `skill.required_tools` non-empty
- `app/skills/meetings/meeting_context_researcher.py` — first real
  tool-using skill, declares `[search_knowledge_base, lookup_meeting]`

Smoke result: model called 2 tools across 2 iters, 1448 tokens, both
audited, valid structured JSON out.

---

## Q: "After h1-h5 what is this projecct able to do"

### Answer (word-for-word):

**Net new capability after H1–H5:**

For any workspace where an admin flips **Agent harness: On** in Agent
Control, post-meeting skills that declare `required_tools` now run inside
a real tool-calling LLM loop instead of one-shot prompts. Concretely:

1. **The LLM can decide to fetch context** — `meeting_context_researcher`
   is the proof: given a transcript, the model itself picks search queries
   and meeting IDs, calls `search_knowledge_base` / `lookup_meeting`,
   reads the results, and only then writes its final structured brief. No
   hand-coded retrieval pipeline.

2. **Every tool call is audited** — `agent_tool_invocations` table records
   args, result, success/error, duration_ms, tokens_used, grouped by
   `run_id`. Replay any run, compute per-skill success rate, see exactly
   what the model asked for vs. what came back.

3. **Six safety rails stop runaway loops** — max 8 iterations, 30k token
   budget per loop, 10s per-tool wall clock, jsonschema arg validation,
   deny-list (model can't call tools outside the skill's allow-list), and
   org-scoped `ToolContext` (tools physically can't see another tenant's
   data).

4. **Per-workspace opt-in** — the toggle lives in
   `tools_and_integrations.harness_enabled`, inherits down the workspace >
   category > team hierarchy like every other behavior override.

**What it does NOT do yet:**

- No actual side-effect tools — slack_post, jira_create_issue,
  github_create_pr etc. are still NotImplementedError stubs. The model can
  *research*, not *act*.
- No observability UI — to inspect a run today you SQL the
  `agent_tool_invocations` table directly. H6 (the `/agents/:id` page) is
  deferred.
- Only one harness-enabled skill exists (`meeting_context_researcher`).
  Existing action_items / decisions / summaries still run single-shot
  until they declare tools.
- The skill is `enabled_by_default=False` — even with the harness flag on,
  you still have to enable it on the agent.

In one line: **the platform can now run a tool-using research agent
end-to-end with an audit trail, but the tools are still mostly read-only.**

---

## H6 — Agent observability page

### Backend: harness_observability_router.py

File: `app/api/harness_observability_router.py`

```python
"""Piece 1 / H6 — harness observability HTTP surface.

Read-only endpoints over the `agent_tool_invocations` audit table
written by the harness loop. Sibling to the RAG observability router;
kept separate so the harness can evolve without touching the RAG
dashboard.

    GET /harness/runs                       recent agent runs (grouped by run_id)
    GET /harness/runs/{run_id}              full invocation list for one run

Every endpoint is org-scoped via `get_current_user`. Time-range params
default to 7 days; max 365. Limits clamp to 200.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import AgentToolInvocation, Meeting, User
from app.dependencies.auth import get_current_user
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


router = APIRouter(prefix="/harness", tags=["Harness Observability"])


def _clamp_days(days: int) -> int:
    return max(1, min(365, days))


def _clamp_limit(limit: int) -> int:
    return max(1, min(200, limit))


def _window_start(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=_clamp_days(days))


@router.get("/runs")
def list_runs(
    days: int = Query(7, ge=1, le=365),
    skill_id: Optional[str] = Query(None, max_length=64),
    meeting_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Recent harness runs grouped by run_id. Most-recent first.

    Each row is an aggregate over all `agent_tool_invocations` rows
    for that run — total tool calls, success/fail counts, total
    duration, tokens, the skill that owns it, and the meeting it
    was triggered from (if any).
    """
    success_int = case((AgentToolInvocation.success.is_(True), 1), else_=0)
    fail_int = case((AgentToolInvocation.success.is_(False), 1), else_=0)

    q = (
        select(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            AgentToolInvocation.meeting_id,
            func.count(AgentToolInvocation.id).label("tool_calls"),
            func.sum(success_int).label("ok"),
            func.sum(fail_int).label("failed"),
            func.sum(AgentToolInvocation.duration_ms).label("total_duration_ms"),
            func.sum(AgentToolInvocation.tokens_used).label("total_tokens"),
            func.max(AgentToolInvocation.iteration).label("max_iter"),
            func.min(AgentToolInvocation.created_at).label("started_at"),
            func.max(AgentToolInvocation.created_at).label("ended_at"),
        )
        .where(
            AgentToolInvocation.organization_id == user.organization_id,
            AgentToolInvocation.created_at >= _window_start(days),
        )
        .group_by(
            AgentToolInvocation.run_id,
            AgentToolInvocation.skill_id,
            AgentToolInvocation.meeting_id,
        )
        .order_by(desc("ended_at"))
        .limit(_clamp_limit(limit))
    )
    if skill_id is not None:
        q = q.where(AgentToolInvocation.skill_id == skill_id)
    if meeting_id is not None:
        q = q.where(AgentToolInvocation.meeting_id == meeting_id)

    rows = db.execute(q).all()
    if not rows:
        return []

    # Pull meeting titles for the runs that have a meeting attached —
    # one batched lookup so the list view shows readable context
    # instead of bare IDs.
    meeting_ids = [r.meeting_id for r in rows if r.meeting_id]
    titles: dict[int, str] = {}
    if meeting_ids:
        for mid, title in db.execute(
            select(Meeting.id, Meeting.title).where(
                Meeting.id.in_(meeting_ids),
                Meeting.organization_id == user.organization_id,
            )
        ).all():
            titles[mid] = title or "(untitled)"

    return [
        {
            "run_id": str(r.run_id),
            "skill_id": r.skill_id,
            "meeting_id": r.meeting_id,
            "meeting_title": titles.get(r.meeting_id) if r.meeting_id else None,
            "tool_calls": int(r.tool_calls),
            "ok": int(r.ok or 0),
            "failed": int(r.failed or 0),
            "total_duration_ms": int(r.total_duration_ms or 0),
            "total_tokens": int(r.total_tokens or 0),
            "iterations": int(r.max_iter) + 1,
            "started_at": r.started_at,
            "ended_at": r.ended_at,
        }
        for r in rows
    ]


@router.get("/runs/{run_id}")
def run_detail(
    run_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Full invocation list for one run, in chronological order.

    Returns 404 when the run doesn't belong to the caller's org (or
    doesn't exist) — same cross-tenant convention as the other audit
    routers.
    """
    rows = (
        db.query(AgentToolInvocation)
        .filter(
            AgentToolInvocation.run_id == run_id,
            AgentToolInvocation.organization_id == user.organization_id,
        )
        .order_by(AgentToolInvocation.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Run not found")

    first = rows[0]
    title = None
    if first.meeting_id:
        m = db.query(Meeting).filter(
            Meeting.id == first.meeting_id,
            Meeting.organization_id == user.organization_id,
        ).first()
        title = (m.title if m else None) or "(untitled)"

    invocations = [
        {
            "id": r.id,
            "iteration": r.iteration,
            "tool_name": r.tool_name,
            "args": r.args_json,
            "result": r.result_json,
            "success": r.success,
            "error_message": r.error_message,
            "duration_ms": r.duration_ms,
            "tokens_used": r.tokens_used,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return {
        "run_id": str(run_id),
        "skill_id": first.skill_id,
        "meeting_id": first.meeting_id,
        "meeting_title": title,
        "iterations": max((r.iteration for r in rows), default=0) + 1,
        "tool_calls": len(rows),
        "ok": sum(1 for r in rows if r.success),
        "failed": sum(1 for r in rows if not r.success),
        "started_at": rows[0].created_at,
        "ended_at": rows[-1].created_at,
        "invocations": invocations,
    }
```

### Router registration in main.py

```python
from app.api.harness_observability_router import router as harness_observability_router
# ...
app.include_router(harness_observability_router)
```

### Frontend: harnessApi.ts

File: `meeting_ai_frontend/src/features/agent-control/services/harnessApi.ts`

```ts
import { apiClient } from "../../../services/apiClient";

export type HarnessRunSummary = {
  run_id: string;
  skill_id: string | null;
  meeting_id: number | null;
  meeting_title: string | null;
  tool_calls: number;
  ok: number;
  failed: number;
  total_duration_ms: number;
  total_tokens: number;
  iterations: number;
  started_at: string;
  ended_at: string;
};

export type HarnessInvocation = {
  id: number;
  iteration: number;
  tool_name: string;
  args: Record<string, unknown> | null;
  result: unknown;
  success: boolean;
  error_message: string | null;
  duration_ms: number | null;
  tokens_used: number | null;
  created_at: string;
};

export type HarnessRunDetail = HarnessRunSummary & {
  invocations: HarnessInvocation[];
};

export const harnessApi = {
  listRuns: (params: { days?: number; skill_id?: string; meeting_id?: number; limit?: number } = {}): Promise<HarnessRunSummary[]> => {
    const qs = new URLSearchParams();
    if (params.days) qs.set("days", String(params.days));
    if (params.skill_id) qs.set("skill_id", params.skill_id);
    if (params.meeting_id) qs.set("meeting_id", String(params.meeting_id));
    if (params.limit) qs.set("limit", String(params.limit));
    const s = qs.toString();
    return apiClient(`/harness/runs${s ? "?" + s : ""}`);
  },
  runDetail: (runId: string): Promise<HarnessRunDetail> =>
    apiClient(`/harness/runs/${runId}`),
};
```

### Frontend: HarnessRunsPage.tsx

File: `meeting_ai_frontend/src/features/agent-control/pages/HarnessRunsPage.tsx`

The full page renders a table of runs (one row per `run_id`), with each
row expandable inline to show every tool invocation in that run — args,
result, success/error, duration, tokens. Top-bar controls: last-N-days
dropdown (1/7/30) and a refresh button. Empty state directs the user to
turn on Agent harness in Agent Control. Status pill is emerald
"N ok" when all tools succeeded, rose "N failed · N ok" otherwise.
Per-invocation drill-down: click chevron to reveal JSON args + result
(or error message in rose if it failed).

### Route registration

`meeting_ai_frontend/src/app/router.tsx`:

```tsx
import HarnessRunsPage from "../features/agent-control/pages/HarnessRunsPage";
// ...
{
  path: "/agent-control/runs",
  element: <HarnessRunsPage />,
},
```

### Link from Agent Control

`BehaviorEditor.tsx` — added `footer` prop to `RuntimePicker` so the
"Agent harness" card carries a "View runs →" link:

```tsx
import { Link } from "react-router-dom";
import { Loader2, RotateCcw, Save, Settings, ExternalLink } from "lucide-react";

// In the harness card:
<RuntimePicker
  // ...
  footer={
    <Link
      to="/agent-control/runs"
      className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 hover:text-indigo-700"
    >
      View runs <ExternalLink className="w-3 h-3" />
    </Link>
  }
/>

// RuntimePicker signature extended:
function RuntimePicker({
  label, hint, value, options, overridden, onChange, suppressInherit = false, footer,
}: {
  // ...
  footer?: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-5">
      {/* existing content */}
      {footer && <div className="mt-3">{footer}</div>}
    </div>
  );
}
```

### H6 smoke tests

Seed data:

```python
record_invocation(db, organization_id=org.id, run_id=run_id, iteration=0,
                  tool_name='search_knowledge_base', success=True,
                  skill_id='meeting_context_researcher',
                  args={'query': 'onboarding'}, result={'hits': 0},
                  duration_ms=12, tokens_used=200)
record_invocation(db, organization_id=org.id, run_id=run_id, iteration=1,
                  tool_name='lookup_meeting', success=False,
                  skill_id='meeting_context_researcher',
                  args={'meeting_id': 99999},
                  error_message='meeting 99999 not found',
                  duration_ms=4)
# seeded run dfefd7a8-b54f-42ad-a4e4-38528cbbef29
```

Endpoint smoke (via FastAPI TestClient with `get_current_user` dependency
override):

```
LIST status: 200
  rows: 2
  first row keys: ['ended_at', 'failed', 'iterations', 'meeting_id', 'meeting_title', 'ok', 'run_id', 'skill_id', 'started_at', 'tool_calls', 'total_duration_ms', 'total_tokens']
  first.skill_id: meeting_context_researcher
  first.tool_calls: 2 ok: 1 failed: 1
DETAIL status: 200
detail keys: ['ended_at', 'failed', 'invocations', 'iterations', 'meeting_id', 'meeting_title', 'ok', 'run_id', 'skill_id', 'started_at', 'tool_calls']
invocations: 2
  iter=0 tool=search_knowledge_base ok=True err=None args={'query': 'onboarding'}
  iter=1 tool=lookup_meeting ok=False err=meeting 99999 not found args={'meeting_id': 99999}
```

404 + filter edge cases:

```
bogus run status: 404 {'detail': 'Run not found'}
filtered count: 2
non-existent skill count: 0
```

All four cases pass: list returns rows, detail returns invocation list,
bogus UUID 404s, skill filter works.

---

## H6 ship summary

**H6 shipped.**

What landed:

- `app/api/harness_observability_router.py` — `GET /harness/runs` (list,
  grouped by `run_id`, filters by `days/skill_id/meeting_id`) and
  `GET /harness/runs/{run_id}` (full invocation detail)
- `main.py` — router registered
- `meeting_ai_frontend/src/features/agent-control/services/harnessApi.ts`
  — typed client
- `meeting_ai_frontend/src/features/agent-control/pages/HarnessRunsPage.tsx`
  — runs table, expand-in-place row for invocation drill-down (args,
  result, error)
- `meeting_ai_frontend/src/app/router.tsx` — `/agent-control/runs` route
- `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`
  — "View runs →" link added to the Agent harness card; `RuntimePicker`
  extended with a `footer` slot

Smoke (4/4 pass): list returns 2 rows, detail returns 2 invocations with
full args/results/errors, bogus UUID → 404, skill_id filter works.

The Agent Harness toggle in Agent Control now has a click-through into
the audit log. Browsing a run shows iteration order, tool names,
success/fail pills, durations, tokens, and on click each invocation
reveals its args + result JSON (or error string).

---

## Q: "how to tokens are calculated ?"

### Answer (word-for-word):

Honestly — **today, mostly wrong**. The dashboard's Tokens column doesn't
reflect actual usage. Here's the full picture.

**Where tokens come from**

OpenAI returns `response.usage.total_tokens` (prompt + completion) on
every `chat.completions.create` call. In
`app/services/agents/harness.py:158-160`:

```python
usage = getattr(resp, "usage", None)
if usage and getattr(usage, "total_tokens", None):
    tokens_used += usage.total_tokens
```

That `tokens_used` is a Python local, accumulated across iterations. It
comes back to the caller in `HarnessResult.tokens_used` — and that's where
it dies. **It's never written to any DB row.**

**What the dashboard actually sums**

`app/api/harness_observability_router.py:78`:

```python
func.sum(AgentToolInvocation.tokens_used).label("total_tokens"),
```

That column is `Integer NULL`. The harness's `record_invocation()` calls
never pass `tokens_used=` for tool dispatches — see
`app/services/agents/harness.py:223-237`. So almost every row has
`tokens_used = NULL`, and the SUM is ~0 for real runs. The only non-zero
numbers you'll see in the dashboard are from my smoke-test seed rows
where I passed `tokens_used=200` explicitly.

**Why the data model is awkward**

Tokens are spent **per LLM call** (per iteration). Tool calls are **per
tool invocation** (multiple per iteration possible — the model can fan
out 3 tool calls in one assistant message). One-to-many. So the choices
are:

1. **Attribute to the first tool call of the iteration** — clean, but
   the rest of the iteration's tools say `null` even though they "cost"
   nothing on their own.
2. **Stamp all tool calls in the iteration with the iteration's tokens**
   — SUM double-counts.
3. **Add a sibling `agent_runs` table** (one row per run with iter count
   + total tokens) — correct, but a new table for one column.

**Recommendation**

Option 1, today: stamp the iteration's token delta onto the first
invocation written that iteration, leave the rest null. The dashboard's
SUM then equals the run total exactly, no double counting. Small change
in `harness.py` — track `tokens_at_iter_start` before the LLM call,
compute the delta after, pass `tokens_used=delta` into
`record_invocation()` for the first tool call of that iteration only.

Want me to make that fix?

---

## Q: "whats next then ?"

### Answer (word-for-word):

**Recommendation: prove the harness on a real meeting end-to-end before
adding more pieces.** Right now every safety rail and audit row is
hypothetical — no actual meeting has flowed through the harness, only my
smoke transcript. Flip `harness_enabled: "on"` for your workspace, run an
analysis on a real meeting, and see what the audit log shows. That tells
us what to fix next far better than guessing.

The realistic options after that, ranked by leverage:

1. **Token attribution fix** (~10 min) — finish what we just discussed so
   the Tokens column means something.
2. **One real side-effect tool** — `create_task` is already wired (not a
   stub), so an `action_items_v2` skill that materializes tasks via the
   harness would prove the agent can *act*, not just research. ~80 LOC.
3. **Memory** — the big one from the plan, multi-day work. Worth it but
   heavy.
4. **Autoresearch agent** — manager's explicit ask. Needs a scheduler +
   per-run budget + improvement loop.

If you want my pick: **run a real meeting through the harness first**,
then do **#1 + #2** together as Piece 2. Memory and autoresearch are
larger investments that benefit from knowing the harness actually holds
up in production.

Want me to do one of these, or run the real-meeting test?

---

## File index (everything touched this session)

### New files

- `alembic/versions/a7i1e3f4g5h_agent_tool_invocations.py`
- `app/services/agents/tools/audit.py`
- `app/services/agents/harness.py`
- `app/skills/meetings/meeting_context_researcher.py`
- `app/api/harness_observability_router.py`
- `meeting_ai_frontend/src/features/agent-control/services/harnessApi.ts`
- `meeting_ai_frontend/src/features/agent-control/pages/HarnessRunsPage.tsx`
- `work_agent_harness.md` (this file)

### Modified files

- `app/db/models.py` — added `AgentToolInvocation` class
- `app/services/agents/graph_orchestrator.py` — harness branch +
  `_run_skill_in_harness` helper
- `app/services/behavior/policy_resolver.py` — `harness_enabled: "off"`
  default
- `app/skills/meetings/__init__.py` — import meeting_context_researcher
- `main.py` — register harness_observability_router
- `meeting_ai_frontend/src/features/agent-control/components/BehaviorEditor.tsx`
  — Agent harness picker card + View runs link + footer prop on
  RuntimePicker
- `meeting_ai_frontend/src/app/router.tsx` — `/agent-control/runs` route

### Verified pass/fail outcomes

| Step | Verification |
|------|---|
| H1 model import | OK |
| H1 alembic upgrade | applied a7i1e3f4g5h |
| H1 record_invocation smoke | row id=1 inserted |
| H2 import | OK |
| H3 TS check | clean |
| H4 import | OK |
| H5 skill registry | id + required_tools verified |
| E2E smoke | 2 iters, 1448 tokens, 2 tool calls, both audited, valid JSON |
| H6 GET /harness/runs | 200, 2 rows |
| H6 GET /harness/runs/{id} | 200, 2 invocations with args/results |
| H6 bogus UUID | 404 |
| H6 skill_id filter | 2 for valid, 0 for unknown |

---

## Known gaps / not done

- **Token attribution is broken** — per-row `tokens_used` is NULL on
  harness-written rows; dashboard Tokens column ≈ 0 for real runs. Fix
  proposed: stamp iteration's token delta on the first tool call of that
  iteration. ~10 LOC change to `harness.py`.
- **No real side-effect tools wired** — slack_post, jira_create_issue,
  github_create_pr, notion_create_page, crm_update_record, send_email,
  create_calendar_event are all NotImplementedError stubs.
- **No real meeting has flowed through the harness** — only smoke
  transcript. `harness_enabled` defaults off, opt-in via Agent Control.
- **`meeting_context_researcher` skill is `enabled_by_default=False`** —
  must be explicitly enabled per agent.
- **Memory not implemented** — separate `MEMORY_PLAN.md` exists from
  earlier session.
- **Autoresearch agent not built** — manager's explicit ask, needs
  scheduler + per-run budget + improvements loop.
- **Briefing WPM / timeout fix** — older debt unrelated to harness.
- **Token budget rail trip-on-warning vs trip-on-block** — current code
  trips at iteration start once `tokens_used >= token_budget`, after the
  LLM call returns. A pathological single iteration could exceed the
  budget mid-flight.
- **`_invoke_with_timeout` is best-effort** — measures elapsed AFTER the
  call. Can't safely interrupt arbitrary Python handler code; relies on
  DB session statement_timeout for query waits.
