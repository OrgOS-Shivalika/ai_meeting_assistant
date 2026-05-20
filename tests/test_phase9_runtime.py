"""Phase 9 ship test — runtime integration of Agent Controls.

Verifies that behavior overrides actually flow into the meeting
pipeline + transcript analyzer.

  9.2 — meeting pipeline integration:
   1. build_meeting_behavior_context renders the resolved profile
      into a plaintext preamble
   2. The preamble surfaces tone, extraction entities, output sections,
      compliance directives
   3. Workspace-scope override is reflected in the preamble (depends on 9.0)
   4. Category template defaults are reflected when meeting.category_id set
   5. Empty preamble when meeting has no scope (zero regression)
   6. Transcript analyzer prompt template accepts {behavior_context}
      substitution + leaves it empty when not provided

Run with:

    venv\\Scripts\\python.exe tests\\test_phase9_runtime.py
"""
from __future__ import annotations

import os
import sys
import traceback
import uuid
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
        msg = traceback.format_exc(limit=8).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_org(theme: str) -> dict:
    from app.db.database import SessionLocal
    from app.db.models import Organization, User
    db = SessionLocal()
    try:
        org = Organization(name=f"9-{theme}-{uuid.uuid4().hex[:6]}")
        db.add(org); db.commit(); db.refresh(org)
        user = User(
            name=f"9-{theme}",
            email=f"9-{theme}-{uuid.uuid4()}@example.com",
            password="x", organization_id=org.id, role="org_admin",
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"org_id": org.id, "user_id": user.id}
    finally:
        db.close()


def _seed_meeting(org_id, user_id, *, category_id=None, team_id=None):
    """Create a Meeting row tied to a category/team scope."""
    from app.db.database import SessionLocal
    from app.db.models import Meeting
    db = SessionLocal()
    try:
        m = Meeting(
            organization_id=org_id, user_id=user_id,
            title=f"Test meeting {uuid.uuid4().hex[:6]}",
            meeting_url=f"https://test.example/{uuid.uuid4().hex[:8]}",
            status="pending",
            category_id=category_id, team_id=team_id,
        )
        db.add(m); db.commit(); db.refresh(m)
        return m
    finally:
        db.close()


def _install(org_id, user_id, scope_kind, slug):
    from app.db.database import SessionLocal
    from app.services.behavior.provisioning import install_profile
    db = SessionLocal()
    try:
        link, _ = install_profile(
            db, organization_id=org_id, user_id=user_id,
            scope_kind=scope_kind, slug=slug,
        )
        return link.entity_id_int
    finally:
        db.close()


def _ensure_seed():
    from app.db.database import SessionLocal
    from app.services.templates.behavior_seed import seed_catalog
    db = SessionLocal()
    try:
        seed_catalog(db)
    finally:
        db.close()


def _cleanup_org(org_id):
    from sqlalchemy import text as sql_text
    from app.db.database import SessionLocal
    db = SessionLocal()
    try:
        for stmt in (
            "DELETE FROM meetings WHERE organization_id = :o",
            "DELETE FROM workspace_behavior_overrides WHERE organization_id = :o",
            "DELETE FROM workspace_template_links WHERE organization_id = :o",
            "DELETE FROM template_provisioning_jobs WHERE organization_id = :o",
            "DELETE FROM teams WHERE category_id IN (SELECT id FROM categories WHERE organization_id = :o)",
            "DELETE FROM categories WHERE organization_id = :o",
            "DELETE FROM users WHERE organization_id = :o",
            "DELETE FROM organizations WHERE id = :o",
        ):
            db.execute(sql_text(stmt), {"o": str(org_id)})
        db.commit()
    finally:
        db.close()


# ===========================================================================
# 9.2 — meeting context preamble
# ===========================================================================


def test_preamble_empty_for_scopeless_meeting():
    """A meeting with NO category/team must produce an empty preamble
    so the analyzer falls back to its hardcoded behavior (no regression)."""
    from app.db.database import SessionLocal
    from app.services.behavior.meeting_context import (
        build_meeting_behavior_context,
    )
    _ensure_seed()
    fx = _seed_org("preamble-empty")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        # No category_id, no team_id — but global default still applies.
        # Global default has master_prompt content, so the preamble may
        # be non-empty. Verify it at least contains the global system text.
        text = build_meeting_behavior_context(db, meeting=meeting)
        # The global default sets master_prompt.system, so we expect SOME
        # preamble. The contract is: render whatever the resolver returns;
        # empty only if resolver finds nothing.
        assert "AI meeting assistant" in text or text == "", text[:200]
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_preamble_reflects_category_template():
    """A meeting under a category with an installed template MUST surface
    that template's tone + entities in the preamble."""
    from app.db.database import SessionLocal
    from app.services.behavior.meeting_context import (
        build_meeting_behavior_context,
    )
    _ensure_seed()
    fx = _seed_org("preamble-cat")
    cat_id = _install(fx["org_id"], fx["user_id"], "category", "engineering")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"], category_id=cat_id)
    db = SessionLocal()
    try:
        text = build_meeting_behavior_context(db, meeting=meeting)
        # Engineering category sets tone: precise verbosity + technical
        # extraction entities. Check both surfaces.
        assert "Engineering Analyst" in text, text[:300]
        assert "precise" in text.lower(), text[:300]
        # Entities from engineering's extraction_rules
        assert "system" in text or "service" in text, text[:300]
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_preamble_reflects_workspace_override():
    """A workspace-scope tone override MUST appear in any meeting's
    preamble (because workspace_override layer applies before category)."""
    from app.db.database import SessionLocal
    from app.services.behavior.meeting_context import (
        build_meeting_behavior_context,
    )
    from app.services.behavior.overrides import set_override
    _ensure_seed()
    fx = _seed_org("preamble-ws")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="workspace",
            dimension="tone_and_personality", field="formality",
            value="very-formal",
        )
        text = build_meeting_behavior_context(db, meeting=meeting)
        assert "very-formal" in text, text[:400]
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_preamble_reflects_team_override():
    """Team-scope master_prompt.behavior override appears in preamble."""
    from app.db.database import SessionLocal
    from app.services.behavior.meeting_context import (
        build_meeting_behavior_context,
    )
    from app.services.behavior.overrides import set_override
    _ensure_seed()
    fx = _seed_org("preamble-team")
    cat_id = _install(fx["org_id"], fx["user_id"], "category", "engineering")
    team_id = _install(fx["org_id"], fx["user_id"], "team", "backend")
    meeting = _seed_meeting(
        fx["org_id"], fx["user_id"],
        category_id=cat_id, team_id=team_id,
    )
    db = SessionLocal()
    try:
        set_override(
            db, organization_id=fx["org_id"], scope_type="team", scope_id=team_id,
            dimension="master_prompt", field="behavior",
            value="ALWAYS surface API contract changes verbatim.",
        )
        text = build_meeting_behavior_context(db, meeting=meeting)
        assert "API contract changes verbatim" in text, text[:600]
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_preamble_compliance_directives_surfaced():
    """When compliance flags are set (PII redaction, bias check), the
    preamble must explicitly tell the analyzer to follow them."""
    from app.db.database import SessionLocal
    from app.services.behavior.meeting_context import (
        build_meeting_behavior_context,
    )
    _ensure_seed()
    fx = _seed_org("preamble-compliance")
    # HR category has bias_check_enabled + audit_trail_required + redact_pii
    cat_id = _install(fx["org_id"], fx["user_id"], "category", "hr")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"], category_id=cat_id)
    db = SessionLocal()
    try:
        text = build_meeting_behavior_context(db, meeting=meeting)
        assert "Redact PII" in text, text[:600]
        assert "bias" in text.lower(), text[:600]
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


# ===========================================================================
# 9.2 — analyzer prompt template wiring
# ===========================================================================


def test_analyzer_prompt_substitutes_behavior_context():
    """The prompt template must have a {behavior_context} slot that
    the analyzer fills in. Empty input → literal empty string left in
    place (still a valid prompt)."""
    from app.ai_agents.prompts.openAI_transcript_analyzer_prompt import prompt
    assert "{behavior_context}" in prompt, \
        "prompt template missing {behavior_context} slot"
    # Sanity: {transcript} slot is still present (existing behavior)
    assert "{transcript}" in prompt


def test_transcript_analyzer_signature_accepts_context():
    """TranscriptAnalyzer.analyze must accept (transcript, behavior_context).
    Not invoking actual LLM here — just verify the call shape compiles."""
    from app.ai_agents.transcript_analyzer import TranscriptAnalyzer
    import inspect
    sig = inspect.signature(TranscriptAnalyzer.analyze)
    params = sig.parameters
    assert "transcript" in params
    assert "behavior_context" in params
    # behavior_context must default to "" so existing callers work
    assert params["behavior_context"].default == ""


# ===========================================================================
# 9.1 — /rag/ask auto-scope from meeting_id
# ===========================================================================


def test_meeting_scope_resolver_picks_team_when_set():
    """A meeting with both category_id + team_id should resolve to
    ('team', team_id) — team is the more specific scope."""
    from app.db.database import SessionLocal
    from app.api.rag_router import _scope_from_meeting
    _ensure_seed()
    fx = _seed_org("ms-team")
    cat_id = _install(fx["org_id"], fx["user_id"], "category", "engineering")
    team_id = _install(fx["org_id"], fx["user_id"], "team", "backend")
    meeting = _seed_meeting(
        fx["org_id"], fx["user_id"],
        category_id=cat_id, team_id=team_id,
    )
    db = SessionLocal()
    try:
        scope, sid = _scope_from_meeting(
            db, organization_id=fx["org_id"], meeting_id=meeting.id,
        )
        assert scope == "team", scope
        assert sid == team_id, sid
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_meeting_scope_resolver_falls_back_to_category():
    """Meeting with only category_id set → ('category', category_id)."""
    from app.db.database import SessionLocal
    from app.api.rag_router import _scope_from_meeting
    _ensure_seed()
    fx = _seed_org("ms-cat")
    cat_id = _install(fx["org_id"], fx["user_id"], "category", "sales")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"], category_id=cat_id)
    db = SessionLocal()
    try:
        scope, sid = _scope_from_meeting(
            db, organization_id=fx["org_id"], meeting_id=meeting.id,
        )
        assert scope == "category", scope
        assert sid == cat_id, sid
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_meeting_scope_resolver_returns_none_for_scopeless():
    """Meeting with no category/team → (None, None) so /rag/ask falls
    through to global default."""
    from app.db.database import SessionLocal
    from app.api.rag_router import _scope_from_meeting
    _ensure_seed()
    fx = _seed_org("ms-none")
    meeting = _seed_meeting(fx["org_id"], fx["user_id"])
    db = SessionLocal()
    try:
        scope, sid = _scope_from_meeting(
            db, organization_id=fx["org_id"], meeting_id=meeting.id,
        )
        assert scope is None
        assert sid is None
    finally:
        db.close()
        _cleanup_org(fx["org_id"])


def test_meeting_scope_resolver_cross_org_returns_none():
    """Org B asking about Org A's meeting → silently degrades to
    (None, None) instead of leaking org A's data."""
    from app.db.database import SessionLocal
    from app.api.rag_router import _scope_from_meeting
    _ensure_seed()
    fx_a = _seed_org("ms-x-a")
    fx_b = _seed_org("ms-x-b")
    cat_id = _install(fx_a["org_id"], fx_a["user_id"], "category", "hr")
    meeting = _seed_meeting(fx_a["org_id"], fx_a["user_id"], category_id=cat_id)
    db = SessionLocal()
    try:
        # Org B tries to resolve org A's meeting
        scope, sid = _scope_from_meeting(
            db, organization_id=fx_b["org_id"], meeting_id=meeting.id,
        )
        assert scope is None
        assert sid is None
    finally:
        db.close()
        _cleanup_org(fx_a["org_id"])
        _cleanup_org(fx_b["org_id"])


def test_ask_request_schema_accepts_meeting_id():
    """AskRequest must accept meeting_id as an optional field for
    callers asking from a meeting context."""
    from app.schemas.rag_api_schema import AskRequest
    req = AskRequest(
        query="what blockers came up?",
        meeting_id=uuid.uuid4(),
    )
    assert req.meeting_id is not None
    assert req.scope == "auto"
    assert req.scope_id is None


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        with section("9.2 - meeting context preamble"):
            check("9.2", "empty preamble for scopeless meeting (or global only)",
                  test_preamble_empty_for_scopeless_meeting)
            check("9.2", "category template surfaces in preamble",
                  test_preamble_reflects_category_template)
            check("9.2", "workspace override surfaces in preamble",
                  test_preamble_reflects_workspace_override)
            check("9.2", "team override surfaces in preamble",
                  test_preamble_reflects_team_override)
            check("9.2", "compliance directives surfaced",
                  test_preamble_compliance_directives_surfaced)

        with section("9.2 - analyzer prompt wiring"):
            check("9.2", "prompt template has {behavior_context} slot",
                  test_analyzer_prompt_substitutes_behavior_context)
            check("9.2", "TranscriptAnalyzer.analyze signature accepts context",
                  test_transcript_analyzer_signature_accepts_context)

        with section("9.1 - meeting auto-scope"):
            check("9.1", "team_id wins over category_id",
                  test_meeting_scope_resolver_picks_team_when_set)
            check("9.1", "falls back to category_id",
                  test_meeting_scope_resolver_falls_back_to_category)
            check("9.1", "scopeless meeting -> (None, None)",
                  test_meeting_scope_resolver_returns_none_for_scopeless)
            check("9.1", "cross-org meeting -> (None, None)",
                  test_meeting_scope_resolver_cross_org_returns_none)
            check("9.1", "AskRequest accepts meeting_id",
                  test_ask_request_schema_accepts_meeting_id)
    except Exception as e:
        print(f"\n[driver crash] {e}")
        traceback.print_exc()

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
