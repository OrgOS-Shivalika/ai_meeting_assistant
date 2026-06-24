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
