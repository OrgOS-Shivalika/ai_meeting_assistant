"""An empty memory query means "recent facts for this scope" — it is a
contract, not a caller mistake.

`MemoryAccess.search` documents it: "if query is non-empty: embed and rank
by cosine distance; if query is empty: rank by last_referenced_at
descending". Both agent orchestrators rely on it —
`agents_v2/orchestrator._build_knowledge` and
`services/agents/graph_orchestrator.run_meeting_analysis` each call
`search_for_meeting(..., query="")` to mean "whatever we know about this
scope", because at that point in the pipeline the meeting has no title or
summary yet.

The mem0 backend forwarded that blank string to the managed API, which
raises `ValueError: Invalid query: cannot be empty or whitespace-only`.
Every memory wire-in is wrapped in `except Exception: logger.warning(...)`,
so the failure was invisible: under MEMORY_BACKEND=mem0 both agent paths
received ZERO prior facts on every single meeting while the facts sat in
the store perfectly retrievable. Found 2026-08-03; before the fix
`_build_knowledge` returned prior_facts=0, after it returns 10.

No network: mem0 is stubbed. This asserts the ROUTING decision, which is
the part that regressed.

Run: python tests/test_memory_empty_query.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.services.memory.mem0_backend as mb  # noqa: E402

ORG = uuid.uuid4()


class _StubMem:
    """Stands in for the mem0 client. Records what it was asked."""

    def __init__(self):
        self.search_calls = []

    def search(self, query, **kwargs):
        # Mirror the real contract: mem0 refuses a blank query.
        if not (query or "").strip():
            raise ValueError("Invalid query: cannot be empty or whitespace-only.")
        self.search_calls.append((query, kwargs))
        return {"results": []}


def _patched(*, get_all_result=("SENTINEL",)):
    """Swap out `_mem` and `get_all`; return (stub_mem, get_all_calls, restore)."""
    original_mem, original_get_all = mb._mem, mb.get_all
    stub = _StubMem()
    calls = []

    def fake_get_all(**kwargs):
        calls.append(kwargs)
        return list(get_all_result)

    mb._mem = lambda: stub
    mb.get_all = fake_get_all

    def restore():
        mb._mem, mb.get_all = original_mem, original_get_all

    return stub, calls, restore


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def test_blank_query_never_reaches_mem0_search():
    """The regression itself: '' / whitespace / None must route to the
    scope fetch instead of the ranked search that rejects them."""
    for blank in ("", "   ", "\n\t ", None):
        stub, calls, restore = _patched()
        try:
            out = mb.search(query=blank, org_id=ORG, limit=5)
        finally:
            restore()
        assert out == ["SENTINEL"], f"query={blank!r} did not route to get_all: {out}"
        assert stub.search_calls == [], f"query={blank!r} still hit mem0 search"
        assert len(calls) == 1, f"query={blank!r} expected one get_all call, got {calls}"


def test_blank_query_forwards_scope_and_limit():
    """Routing is only correct if the scope survives it — otherwise a
    team's facts leak across scopes or the limit is ignored."""
    stub, calls, restore = _patched()
    try:
        mb.search(
            query="", org_id=ORG, category_id=4554, team_id=3864,
            agent_id="agent-7", limit=9,
        )
    finally:
        restore()
    kw = calls[0]
    assert kw["org_id"] == ORG
    assert kw["category_id"] == 4554, kw
    assert kw["team_id"] == 3864, kw
    assert kw["agent_id"] == "agent-7", kw
    assert kw["limit"] == 9, kw


def test_real_query_still_uses_ranked_search():
    """The fix must not swallow real questions into the unranked path —
    that would silently drop semantic ranking for every /ask call."""
    stub, calls, restore = _patched()
    try:
        out = mb.search(query="who owns the OAuth migration", org_id=ORG, limit=4)
    finally:
        restore()
    assert calls == [], "a real query was diverted to get_all"
    assert len(stub.search_calls) == 1, "a real query never reached mem0 search"
    sent_query, kwargs = stub.search_calls[0]
    assert sent_query == "who owns the OAuth migration"
    # Tenant isolation rides in `filters` — the managed API rejects a
    # top-level user_id, so losing this silently un-scopes the search.
    assert kwargs["filters"]["user_id"] == str(ORG), kwargs


def test_stub_reproduces_the_original_failure():
    """Guard on the guard: if the stub stopped rejecting blank queries,
    the first check above would pass for the wrong reason."""
    raised = False
    try:
        _StubMem().search("   ")
    except ValueError:
        raised = True
    assert raised, "stub no longer models mem0's blank-query rejection"


if __name__ == "__main__":
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for check in checks:
        try:
            check()
            print(f"  ok  {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {check.__name__}: {exc}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
