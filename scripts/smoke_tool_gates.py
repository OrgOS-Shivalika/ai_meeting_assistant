"""Smoke test for tool_runner gating logic.

Verifies:
  1. Unknown tool id → ToolNotFoundError
  2. Known tool NOT in allowed_tools → ToolNotAllowedError
  3. Known tool IN allowed_tools → tool.execute is called

Does NOT hit the real DB/OpenAI — uses a fake in-memory tool so the
runner logic is exercised in isolation. Run from repo root:

    python -m scripts.smoke_tool_gates
"""
from __future__ import annotations

from uuid import UUID

from app.agents_v2.shared.tool_context import ToolContext
from app.agents_v2.shared.tool_runner import (
    ToolNotAllowedError,
    ToolNotFoundError,
    invoke,
)
from app.agents_v2.tools.base import Tool, register


_CALLS: list[dict] = []


def _fake_execute(inputs: dict, ctx: ToolContext) -> dict:
    _CALLS.append({"inputs": inputs, "team_id": ctx.team_id})
    return {"echoed": inputs}


register(Tool(
    id="_smoke_fake_tool",
    name="Fake Tool",
    description="For gate testing only.",
    execute=_fake_execute,
    scope="shared",
    side_effect="read",
))


def _ctx(allowed: list[str]) -> ToolContext:
    return ToolContext(
        meeting_id=1,
        agent_row_id=1,
        agent_slug="hr_learning_and_development",
        organization_id=UUID("00000000-0000-0000-0000-000000000000"),
        category_id=None,
        team_id=3864,
        caller_skill_id="test",
        allowed_tools=allowed,
    )


def main() -> None:
    # 1. Unknown id
    try:
        invoke("does_not_exist", {}, _ctx(["_smoke_fake_tool"]))
    except ToolNotFoundError:
        print("[OK] Unknown tool id raises ToolNotFoundError")
    else:
        raise AssertionError("Expected ToolNotFoundError")

    # 2. Not in allowed_tools
    try:
        invoke("_smoke_fake_tool", {}, _ctx(allowed=[]))
    except ToolNotAllowedError:
        print("[OK] Disallowed tool raises ToolNotAllowedError")
    else:
        raise AssertionError("Expected ToolNotAllowedError")

    # 3. Allowed → calls through
    _CALLS.clear()
    out = invoke("_smoke_fake_tool", {"q": "hi"}, _ctx(["_smoke_fake_tool"]))
    assert out == {"echoed": {"q": "hi"}}, f"unexpected output: {out}"
    assert _CALLS == [{"inputs": {"q": "hi"}, "team_id": 3864}], f"unexpected calls: {_CALLS}"
    print("[OK] Allowed tool invokes execute with correct inputs + ctx")

    print("All gate checks passed.")


if __name__ == "__main__":
    main()
