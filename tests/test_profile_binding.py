"""`prof` must be bound on EVERY routing path through `process_meeting`.

Why this file exists: `resolve_behavior_profile()` used to be called inside
the `else` arm of the agents_v2 routing branch, but the compliance +
automation block further down uses `prof` regardless of which arm ran. So
every meeting that routed through agents_v2 hit a NameError on
`ComplianceRuntime.apply_to_meeting(db, meeting, prof)` — which landed in
that block's `except Exception: logger.error(...)` and was swallowed.

The visible symptom was nothing at all. PII redaction never ran and no
automation event was ever emitted for those meetings, while the pipeline
reported the meeting as completed.

This is checked structurally rather than by executing the pipeline:
`process_meeting` fetches from Recall, writes transcripts and participants
and calls two orchestrators, so stubbing it end-to-end would cost more than
the bug. The defect is a *binding* defect, and the AST shows binding
directly — an assignment that sits inside one arm of a branch whose other
arm falls through to a use is exactly the shape being banned.

Run: python tests/test_profile_binding.py
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "pipelines", "meeting_pipeline.py",
)

with open(_SRC, encoding="utf-8") as fh:
    _TREE = ast.parse(fh.read())


def _find_routing_branch():
    """The `if v2_orchestrator.has_agent_for_scope(...)` node, plus the
    statement list that holds it."""
    for node in ast.walk(_TREE):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for i, stmt in enumerate(stmts):
                if not isinstance(stmt, ast.If):
                    continue
                if "has_agent_for_scope" in ast.dump(stmt.test):
                    return stmt, stmts, i
    raise AssertionError(
        "no `if ...has_agent_for_scope(...)` branch found — the routing "
        "structure changed, update this test"
    )


def _assigns_prof(node) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "prof":
                    return True
    return False


def test_prof_is_bound_before_the_routing_branch():
    """The real fix: resolve the profile above the `if`, so both arms and
    everything downstream see it."""
    branch, siblings, idx = _find_routing_branch()
    earlier = [s for s in siblings[:idx] if _assigns_prof(s)]
    assert earlier, (
        "`prof` is not assigned before the agents_v2 routing branch — the "
        "agents_v2 arm will reach the compliance block with it unbound"
    )


def test_prof_is_not_bound_only_inside_one_arm():
    """Guard the exact original defect: assigned in `else`, used after."""
    branch, siblings, idx = _find_routing_branch()
    if [s for s in siblings[:idx] if _assigns_prof(s)]:
        return  # bound unconditionally above; arms may do as they like
    in_body = any(_assigns_prof(s) for s in branch.body)
    in_else = any(_assigns_prof(s) for s in branch.orelse)
    assert not (in_body ^ in_else), (
        "`prof` is assigned in only ONE arm of the routing branch — the "
        "other arm falls through to the compliance block and raises "
        "NameError, which that block's `except Exception` swallows"
    )


def test_profile_still_reaches_compliance_and_automation():
    """If these stop using `prof`, the test above is guarding nothing.

    Asserts on the OUTCOME the bug destroyed — redaction and the automation
    emit are the two things that silently stopped happening."""
    src = ast.dump(_TREE)
    assert "apply_to_meeting" in src, (
        "ComplianceRuntime.apply_to_meeting is gone — this test no longer "
        "guards PII redaction, rewrite it"
    )
    uses = 0
    for node in ast.walk(_TREE):
        if not isinstance(node, ast.Call):
            continue
        fn = ast.dump(node.func)
        if "apply_to_meeting" not in fn and "emit" not in fn:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name) and arg.id == "prof":
                uses += 1
    assert uses >= 3, (
        f"expected `prof` to gate redaction + both automation emits "
        f"(>=3 call sites), found {uses}"
    )


def test_resolver_accepts_the_scope_we_pass():
    """Sanity-check the probe, not just the source: the hoisted call must
    still match the resolver's real signature."""
    import inspect
    from app.services.behavior.resolver import resolve_behavior_profile

    params = inspect.signature(resolve_behavior_profile).parameters
    for required in ("organization_id", "category_id", "team_id"):
        assert required in params, (
            f"resolve_behavior_profile lost `{required}` — the hoisted call "
            f"in meeting_pipeline will TypeError"
        )


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
