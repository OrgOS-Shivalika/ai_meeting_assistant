"""The four admin-only sections are enforced on the SERVER, not just hidden.

Hiding a nav entry and adding a client route guard are navigation. This
asserts the thing that actually holds: a MEMBER calling those endpoints
directly gets 403.

Just as important is the second half. Three of these routers carry routes a
member legitimately hits, and gating them wholesale would have broken pages
members keep — the Dashboard fetches `/entities` inside a `Promise.all`, so a
403 there takes the whole page down, not one tile. Those are asserted OPEN.

Needs a live Postgres (reads real users; writes nothing).

    export PYTHONIOENCODING=utf-8
    python tests/test_member_gating.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.db.database import SessionLocal  # noqa: E402
from app.db.models import User  # noqa: E402
from app.dependencies.auth import require_access_admin  # noqa: E402
from app.utils.admin_enums import AccessRole  # noqa: E402

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (_passed if ok else _failed).append(name if ok else f"{name} - {detail}")
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def _refused(user) -> bool:
    """Does the gate reject this user?"""
    try:
        require_access_admin(user=user)
        return False
    except HTTPException as e:
        return e.status_code == 403


def main() -> int:
    db = SessionLocal()
    try:
        member = db.query(User).filter(
            User.access_role == AccessRole.MEMBER.value).first()
        admin = db.query(User).filter(
            User.access_role.in_([AccessRole.ADMIN.value,
                                  AccessRole.ORG_ADMIN.value])).first()
        assert member is not None, "no MEMBER account in this database"
        assert admin is not None, "no ADMIN account in this database"

        print("\nThe gate itself")
        check("  a member is refused", _refused(member))
        check("  an admin is let through", not _refused(admin))

        print("\nIt reads access_role, NOT users.role")
        # These are different columns that share the value 'ORG_ADMIN'.
        # `require_org_admin` (prompt rank) would answer a different
        # question, and wiring these pages to it would gate them on whether
        # somebody may edit prompts.
        import inspect
        from app.dependencies import auth as auth_mod
        src = inspect.getsource(auth_mod.require_access_admin)
        check("  delegates to permissions.require_admin_role",
              "permissions.require_admin_role" in src)
        check("  does NOT use the prompt-rank helper",
              "_user_rank" not in src and "PromptRole" not in src)

        print("\nEvery gated route refuses a member")
        from main import app
        gated = {
            "/api/templates/bundles", "/api/templates/install",
            "/api/behavior/scopes", "/api/harness/runs",
            "/api/search", "/api/entities/{entity_id}",
            "/api/meetings/{meeting_id}/graph", "/api/agents_v2",
            "/api/agents_v2/skills", "/api/continuum/traces",
            "/api/continuum/config",
        }
        by_path = {}
        for r in app.routes:
            if hasattr(r, "path"):
                by_path.setdefault(r.path, []).append(r)
        for path in sorted(gated):
            routes = by_path.get(path)
            if not routes:
                check(f"  {path}", False, "route not found")
                continue
            # Router-level dependencies land on the route's dependant too, so
            # walking the tree covers both styles of gating.
            names = set()
            deep = set()
            for r in routes:
                stack = list(getattr(r.dependant, "dependencies", []))
                while stack:
                    d = stack.pop()
                    if d.call is not None:
                        deep.add(getattr(d.call, '__name__', type(d.call).__name__))
                    stack.extend(d.dependencies)
            check(f"  {path}", "require_access_admin" in (names | deep),
                  str(sorted(names | deep))[:90])

        print("\nMember-facing routes stay OPEN (the regressions to avoid)")
        open_paths = {
            "/api/entities": "the Dashboard's entity count, inside a Promise.all",
            "/api/agents_v2/meetings/{meeting_id}/insights": "the meeting page",
            "/api/boards": "boards",
            "/api/rag/conversations": "Ask AI",
        }
        for path, why in open_paths.items():
            routes = by_path.get(path)
            if not routes:
                check(f"  {path}", False, "route not found")
                continue
            deep = set()
            for r in routes:
                stack = list(getattr(r.dependant, "dependencies", []))
                while stack:
                    d = stack.pop()
                    if d.call is not None:
                        deep.add(getattr(d.call, '__name__', type(d.call).__name__))
                    stack.extend(d.dependencies)
            check(f"  {path}  ({why})",
                  "require_access_admin" not in deep,
                  "IS GATED - this breaks a member page")
    finally:
        db.close()

    print("=" * 62)
    if _failed:
        print(f"FAILED {len(_failed)}/{len(_passed) + len(_failed)}")
        for f in _failed:
            print("  -", f)
        return 1
    print(f"PASSED {len(_passed)}/{len(_passed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
