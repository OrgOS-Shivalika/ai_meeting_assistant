"""Langfuse tracing — safe wrappers.

Any code in agents_v2/ imports observe / langfuse_context / openai_client
FROM HERE (not from langfuse directly) so a missing package or missing
env vars degrades to no-op instead of crashing.

Fail-safe rules:
  1. Missing `langfuse` package → decorators become identity, `openai`
     is the vanilla client. Meetings still process.
  2. Missing LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY env vars → SDK
     init noop, no traces sent, meetings still process.
  3. Langfuse Cloud API down / rate-limited → SDK buffers and drops,
     no exception to the caller.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Try to import the real SDK. If ANY part fails, fall through to no-ops
# so the app is always runnable without Langfuse configured.
# ---------------------------------------------------------------------------

_LANGFUSE_ENABLED = False
_LANGFUSE_CLIENT = None

try:
    if (
        settings.LANGFUSE_PUBLIC_KEY
        and settings.LANGFUSE_SECRET_KEY
    ):
        # v2 API — stable, well-documented. v3 is a chore for later.
        from langfuse import Langfuse
        from langfuse.decorators import observe as _lf_observe
        from langfuse.decorators import langfuse_context as _lf_ctx
        # Drop-in wrapper: `from langfuse.openai import openai` gives an
        # `openai` module whose ChatCompletions call auto-emits Generations.
        from langfuse.openai import openai as _lf_openai

        _LANGFUSE_CLIENT = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST or "https://cloud.langfuse.com",
        )
        _LANGFUSE_ENABLED = True
        # print + logger.info — print survives log-level suppression in
        # Celery workers where third-party loggers may be filtered above INFO.
        _msg = f"[langfuse] Tracing ENABLED (host={settings.LANGFUSE_HOST or 'https://cloud.langfuse.com'})"
        print(_msg, flush=True)
        logger.info(_msg)
    else:
        _msg = (
            "[langfuse] Tracing DISABLED — env vars not set. "
            "Set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY to enable."
        )
        print(_msg, flush=True)
        logger.info(_msg)
except ImportError as exc:
    _msg = f"[langfuse] Package not installed ({exc}). Tracing disabled."
    print(_msg, flush=True)
    logger.warning(_msg)
except Exception as exc:
    _msg = f"[langfuse] SDK init failed ({exc}). Tracing disabled."
    print(_msg, flush=True)
    logger.warning(_msg)


# ---------------------------------------------------------------------------
# Public API — always safe to import + call
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return _LANGFUSE_ENABLED


def observe(
    *args,
    name: str | None = None,
    as_type: str | None = None,
    **kwargs,
) -> Callable:
    """Decorator that becomes a no-op when Langfuse is disabled.

    Usage identical to langfuse.decorators.observe:
        @observe(name="run_meeting_analysis", as_type="trace")
        def run_meeting_analysis(...): ...
    """
    if _LANGFUSE_ENABLED:
        # If args[0] is a callable, someone used @observe without ()
        # → forward to the real decorator with just name/as_type.
        if args and callable(args[0]) and not kwargs and name is None:
            return _lf_observe()(args[0])
        return _lf_observe(name=name, as_type=as_type, **kwargs)

    # No-op path
    def _identity_decorator(fn):
        return fn

    # Support both `@observe` and `@observe(name=...)` shapes
    if args and callable(args[0]):
        return args[0]
    return _identity_decorator


def get_langfuse_client():
    """Return the singleton client, or None if disabled.

    Use only when you need to attach data OUTSIDE of an @observe scope
    (e.g. update_current_trace calls). Prefer the decorator + context
    helpers for anything inside a traced call.
    """
    return _LANGFUSE_CLIENT


def update_current_trace(**kwargs: Any) -> None:
    """Attach fields (metadata, tags, user_id, session_id, ...) to the
    trace we're currently inside. No-op when tracing is disabled or when
    called outside an @observe scope."""
    if not _LANGFUSE_ENABLED:
        return
    try:
        _lf_ctx.update_current_trace(**kwargs)
    except Exception as exc:
        logger.debug("update_current_trace failed (non-fatal): %s", exc)


def update_current_observation(**kwargs: Any) -> None:
    """Attach fields to the current span/generation (metadata, level,
    input, output, usage, ...). No-op outside a traced scope."""
    if not _LANGFUSE_ENABLED:
        return
    try:
        _lf_ctx.update_current_observation(**kwargs)
    except Exception as exc:
        logger.debug("update_current_observation failed (non-fatal): %s", exc)


def get_openai_client():
    """Return the openai module — Langfuse-wrapped when enabled,
    vanilla otherwise. Callers use it exactly like `import openai`:

        openai = tracing.get_openai_client()
        client = openai.OpenAI()
        response = client.chat.completions.create(...)

    When Langfuse is enabled, `chat.completions.create` auto-emits a
    Generation into the active trace. When disabled, behavior is
    identical to bare `import openai`.
    """
    if _LANGFUSE_ENABLED:
        return _lf_openai
    import openai as _oai
    return _oai


def flush() -> None:
    """Force-flush pending observations. Useful in Celery workers
    right before a task returns so the trace is visible immediately."""
    if not _LANGFUSE_ENABLED:
        return
    try:
        _LANGFUSE_CLIENT.flush()
    except Exception as exc:
        logger.debug("Langfuse flush failed (non-fatal): %s", exc)


def fetch_agent_traces(agent_slug: str, limit: int = 50) -> dict:
    """Return recent traces for one agent (filtered by tag=agent_slug),
    with per-trace token totals summed from GENERATION observations.

    Two Langfuse API calls fire in PARALLEL to keep wall-clock down:
      1. fetch_traces(tags=[slug], limit=limit)
      2. fetch_observations(type="GENERATION", from_start_time=now-7d)

    Tokens are summed client-side per trace_id. Observations older than
    7 days won't contribute tokens (trace still returned, tokens = None).
    Upgrade path: widen the window if that becomes a real gap.
    """
    if not _LANGFUSE_ENABLED:
        return {"enabled": False, "host": None, "traces": [], "error": None}

    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone

    host = settings.LANGFUSE_HOST or "https://cloud.langfuse.com"
    obs_window_start = datetime.now(timezone.utc) - timedelta(days=7)

    # Langfuse caps observations limit at 100 per page → paginate.
    # 5 pages × 100 = 500 obs, covers ~70 traces at ~7 generations each.
    # All pages fire in parallel with the traces call so wall clock stays 1× RTT.
    OBS_PAGE_SIZE = 100
    OBS_MAX_PAGES = 5

    def _fetch_traces():
        return _LANGFUSE_CLIENT.fetch_traces(tags=[agent_slug], limit=limit)

    def _fetch_observations_page(page: int):
        return _LANGFUSE_CLIENT.fetch_observations(
            type="GENERATION",
            from_start_time=obs_window_start,
            page=page,
            limit=OBS_PAGE_SIZE,
        )

    try:
        obs_data = []
        with ThreadPoolExecutor(max_workers=1 + OBS_MAX_PAGES) as pool:
            f_traces = pool.submit(_fetch_traces)
            f_obs_pages = [
                pool.submit(_fetch_observations_page, p)
                for p in range(1, OBS_MAX_PAGES + 1)
            ]
            trace_result = f_traces.result()
            for f in f_obs_pages:
                try:
                    r = f.result()
                    obs_data.extend(getattr(r, "data", None) or [])
                except Exception as exc:
                    logger.warning("fetch_observations page failed (tokens partial): %s", exc)

        tokens_by_trace = _sum_tokens_by_trace_from_list(obs_data)

        traces = []
        for t in trace_result.data:
            latency = getattr(t, "latency", None)
            total_cost = getattr(t, "total_cost", None) or getattr(t, "totalCost", None)
            tok = tokens_by_trace.get(t.id, {})
            traces.append({
                "id": t.id,
                "timestamp": t.timestamp.isoformat() if getattr(t, "timestamp", None) else None,
                "name": getattr(t, "name", None),
                "session_id": getattr(t, "session_id", None) or getattr(t, "sessionId", None),
                "latency": latency,
                "total_cost": total_cost,
                "input_tokens": tok.get("input"),
                "output_tokens": tok.get("output"),
                "total_tokens": tok.get("total"),
            })
        return {"enabled": True, "host": host, "traces": traces, "error": None}
    except Exception as exc:
        logger.warning("fetch_agent_traces failed: %s", exc)
        return {"enabled": True, "host": None, "traces": [], "error": str(exc)}


def _sum_tokens_by_trace_from_list(observations) -> dict[str, dict]:
    """Group observations by trace_id, sum their token counts."""
    totals: dict[str, dict[str, int]] = {}
    for o in observations or []:
        tid = getattr(o, "trace_id", None) or getattr(o, "traceId", None)
        if not tid:
            continue
        in_t, out_t, tot_t = _extract_tokens(o)
        if in_t is None and out_t is None and tot_t is None:
            continue
        bucket = totals.setdefault(tid, {"input": 0, "output": 0, "total": 0})
        bucket["input"] += in_t or 0
        bucket["output"] += out_t or 0
        bucket["total"] += tot_t or ((in_t or 0) + (out_t or 0))
    return totals


def _extract_tokens(o) -> tuple:
    """(input, output, total) from Langfuse v2 Observation.

    Two shapes exist in the wild:
      1. `usage_details`: dict (newer). Keys are provider-specific but
         commonly "input"/"output"/"total" (Anthropic-style) or
         "input_tokens"/"output_tokens" etc.
      2. `usage`: `Usage` pydantic MODEL (older; deprecated per Langfuse docs
         but still what our current traces emit). Attribute-access: .input,
         .output, .total.
    """
    # Newer: dict
    ud = getattr(o, "usage_details", None)
    if isinstance(ud, dict) and ud:
        in_t = ud.get("input") or ud.get("input_tokens") or ud.get("prompt_tokens")
        out_t = ud.get("output") or ud.get("output_tokens") or ud.get("completion_tokens")
        tot_t = ud.get("total") or ud.get("total_tokens")
        if in_t is not None or out_t is not None or tot_t is not None:
            return in_t, out_t, tot_t

    # Older: Usage pydantic model
    usage = getattr(o, "usage", None)
    if usage is not None and not isinstance(usage, dict):
        return (
            getattr(usage, "input", None),
            getattr(usage, "output", None),
            getattr(usage, "total", None),
        )
    return None, None, None
