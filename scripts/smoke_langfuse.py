"""Smoke test for Langfuse tracing (self-hosted OR cloud — see
agents_v2/shared/tracing for host selection).

Exercises the real ingestion round-trip: writes a trace with a nested LLM
generation, then reads it back through the same API the /agents UI uses.
Requires OPEN_API_KEY + LANGFUSE_PUBLIC_KEY/SECRET_KEY and a reachable
Langfuse host. Costs one tiny gpt-4o-mini call.

Run:
    python -m scripts.smoke_langfuse

Exit code 0 = pass, 1 = fail. Checks:
  1. HOST AGREEMENT — the explicit client and the @observe/openai singleton
     must point at the SAME host. They are separate objects built from
     different sources, and a mismatch silently ships prompts to whichever
     host the singleton defaulted to (cloud) while the config claims
     otherwise. This is the whole reason self-hosting looked broken.
  2. reachable     — the host answers /api/public/health.
  3. round-trip    — a trace written through @observe is readable back.
  4. generation    — the langfuse.openai wrapper records model + tokens.
                     (The decorator working does NOT imply the wrapper does;
                     they are separate integrations.)

Traces are left in place — Langfuse has no cheap per-trace delete and the
rows are harmless. They are tagged so they are easy to spot/filter.
"""
from __future__ import annotations

import sys
import time
import uuid

from app.agents_v2.shared import tracing
from app.config.settings import settings


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _fetch_until(tag: str, pred, *, tries: int = 12, delay: float = 3.0) -> dict:
    """Retry the read — the SDK batches and the server indexes on its own
    schedule, so a just-flushed trace is not instantly queryable."""
    res: dict = {}
    for _ in range(tries):
        res = tracing.fetch_agent_traces(tag, limit=10)
        if pred(res):
            return res
        time.sleep(delay)
    return res


def main() -> None:
    if not settings.OPEN_API_KEY:
        print("SKIP: OPEN_API_KEY not set.")
        return
    if not tracing.is_enabled():
        print("SKIP: tracing disabled — set LANGFUSE_PUBLIC_KEY + "
              "LANGFUSE_SECRET_KEY to enable.")
        return

    host = settings.LANGFUSE_HOST or "https://cloud.langfuse.com"
    print(f"host: {host}")
    print(f"mode: {'CLOUD' if 'cloud.langfuse.com' in host else 'SELF-HOSTED'}")

    # --- 1. host agreement ------------------------------------------------
    from langfuse.decorators import langfuse_context
    explicit = str(tracing.get_langfuse_client().base_url).rstrip("/")
    singleton = str(langfuse_context.client_instance.base_url).rstrip("/")
    if explicit != singleton:
        _fail(
            "HOST MISMATCH — traces will go somewhere other than the "
            f"configured host.\n      explicit client : {explicit}\n"
            f"      @observe client : {singleton}\n"
            "      Fix: tracing.py must call langfuse_context.configure(host=...)."
        )
    print(f"  [ok] host agreement: both clients -> {explicit}")

    # --- 2. reachable -----------------------------------------------------
    try:
        import httpx
        r = httpx.get(f"{explicit}/api/public/health", timeout=10)
        if r.status_code != 200:
            _fail(f"health endpoint returned {r.status_code}")
        print("  [ok] reachable: /api/public/health -> 200")
    except Exception as exc:
        _fail(f"host unreachable: {exc}")

    # --- 3 + 4. round-trip with a real generation -------------------------
    tag = f"smoke-{uuid.uuid4().hex[:8]}"
    session = f"smoke-session-{uuid.uuid4().hex[:6]}"

    @tracing.observe(name="smoke_langfuse.trace", as_type="trace")
    def _run() -> str:
        tracing.update_current_trace(tags=[tag], session_id=session)
        openai = tracing.get_openai_client()
        client = openai.OpenAI(api_key=settings.OPEN_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=5,
        )
        return resp.choices[0].message.content or ""

    answer = _run()
    print(f"  llm replied: {answer.strip()[:20]!r}")
    tracing.flush()
    langfuse_context.flush()

    res = _fetch_until(tag, lambda r: bool(r.get("traces")))
    if res.get("error"):
        _fail(f"fetch_agent_traces errored: {res['error']}")
    traces = res.get("traces") or []
    if not traces:
        _fail(
            f"trace written but never readable back (tag={tag}). "
            "Ingestion is being dropped — check the server logs and that the "
            "API keys belong to THIS instance (keys are per-instance)."
        )
    t = traces[0]
    if t.get("session_id") != session:
        _fail(f"trace session_id mismatch: {t.get('session_id')!r} != {session!r}")
    print(f"  [ok] round-trip: trace readable back "
          f"(name={t.get('name')!r}, latency={t.get('latency')})")

    # --- 4. the openai wrapper actually recorded a generation -------------
    tokens = t.get("total_tokens")
    if not tokens:
        _fail(
            "trace landed but carries NO token totals — the langfuse.openai "
            "wrapper did not emit a GENERATION, so LLM calls are untraced "
            "even though the decorator works."
        )
    print(f"  [ok] generation: tokens={tokens} cost={t.get('total_cost')}")

    print(f"PASS  (trace tagged {tag!r}, left in place)")


if __name__ == "__main__":
    main()
