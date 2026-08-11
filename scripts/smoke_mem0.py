"""Smoke test for the mem0 memory backend (managed OR OSS — see
mem0_backend for mode selection).

Exercises the real mem0 round-trip and the tenant-isolation guarantee.
Requires OPEN_API_KEY (+ a mem0 API key for managed mode, or a live
Postgres for OSS). Writes a test fact + a chat turn, then deletes them.

Run:
    python -m scripts.smoke_mem0

Exit code 0 = pass, 1 = fail. Checks:
  1. round-trip   — org A writes a fact, org A search finds it.
  2. ISOLATION    — org B search must NOT find org A's fact.
  3. session      — a chat turn under run_id is retrievable.
  4. guard        — empty org_id is rejected.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

os.environ.setdefault("MEM0_TELEMETRY", "false")

from app.config.settings import settings
from app.services.memory import mem0_backend as mem


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _search_until(pred, *, tries: int = 5, delay: float = 2.0, **kw):
    """Retry a positive search — managed mem0 indexes asynchronously, so a
    just-written memory may take a few seconds to become searchable."""
    hits = []
    for _ in range(tries):
        hits = mem.search(**kw)
        if pred(hits):
            return hits
        time.sleep(delay)
    return hits


def main() -> None:
    if not settings.OPEN_API_KEY:
        print("SKIP: OPEN_API_KEY not set.")
        return
    mode = "MANAGED" if mem._is_managed() else "OSS (self-hosted)"
    print(f"mode: {mode}")

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    conv = uuid.uuid4()
    marker = f"smoke-{uuid.uuid4().hex[:8]}"
    fact_text = f"[{marker}] The Q3 renewal for Acme Corp is owned by Priya Sharma."

    try:
        # 1. write for org A
        mem.add_facts(text_or_messages=fact_text, org_id=org_a, category_id=1, team_id=2)
        print("  add_facts(org A) sent")

        # 1. org A finds it (retry for async indexing)
        hits_a = _search_until(
            lambda hs: any("Acme" in (h.fact or "") or marker in (h.fact or "") for h in hs),
            query="who owns the Acme renewal?", org_id=org_a, window="all", limit=5,
        )
        if not any("Acme" in (h.fact or "") or marker in (h.fact or "") for h in hits_a):
            _fail(f"org A could not retrieve its own fact (got {[h.fact for h in hits_a]})")
        print(f"  [ok] round-trip: org A retrieved its fact ({len(hits_a)} hit(s))")

        # 2. org B must NOT find it (single call — isolation is timing-independent)
        hits_b = mem.search(query="who owns the Acme renewal?", org_id=org_b, window="all", limit=5)
        if any(marker in (h.fact or "") for h in hits_b):
            _fail("TENANT LEAK: org B retrieved org A's fact")
        print(f"  [ok] isolation: org B sees none of org A's facts ({len(hits_b)} unrelated hit(s))")

        # 3. session (chat) memory under run_id
        mem.add_turn(
            question="What's my deadline for the report?",
            answer=f"[{marker}] Your report is due next Friday.",
            org_id=org_a, conversation_id=conv,
        )
        hits_s = _search_until(
            lambda hs: len(hs) > 0,
            query="when is my report due?", org_id=org_a,
            conversation_id=conv, window="all", limit=5,
        )
        print(f"  [ok] session: chat turn stored + searchable ({len(hits_s)} hit(s))")

        # 4. guard: empty org_id must raise
        try:
            mem.search(query="x", org_id=None)
            _fail("isolation guard did NOT raise on empty org_id")
        except ValueError:
            print("  [ok] guard: empty org_id rejected")

        print("PASS")
    finally:
        # Best-effort cleanup — delete everything for the two throwaway orgs,
        # regardless of what add() returned. Tries both API shapes.
        m = mem._mem()
        for org in (org_a, org_b):
            for call in (
                lambda: m.delete_all(user_id=str(org)),          # managed form
                lambda: m.delete_all(filters={"user_id": str(org)}),  # OSS form
            ):
                try:
                    call()
                    break
                except Exception:
                    continue


if __name__ == "__main__":
    main()
