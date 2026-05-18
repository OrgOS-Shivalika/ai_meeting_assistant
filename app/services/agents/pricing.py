"""Phase 7F — model price table for cost analytics.

Per-model token prices in USD per 1k tokens. Used by the analytics
endpoints to compute per-version cost from `sum_input_tokens` +
`sum_output_tokens`. A `model -> (input_per_1k, output_per_1k)` dict
keeps the surface tiny; unknown models report cost as None so the UI
shows "unknown" instead of crashing.

Numbers reflect the OpenAI public list as of 2026-Q1. Update by
editing this file — no migration required. A future slice will move
this to a `model_prices` DB table for org-specific overrides.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class _Price:
    """USD per 1,000 tokens. Both sides are stored separately because
    output tokens are typically 2-4x more expensive."""
    input_per_1k: float
    output_per_1k: float


# Keep alphabetically sorted. Values are USD per 1k tokens.
_PRICES: dict[str, _Price] = {
    "gpt-4o":               _Price(input_per_1k=0.0025, output_per_1k=0.0100),
    "gpt-4o-mini":          _Price(input_per_1k=0.00015, output_per_1k=0.0006),
    "gpt-4o-2024-08-06":    _Price(input_per_1k=0.0025, output_per_1k=0.0100),
    "gpt-4-turbo":          _Price(input_per_1k=0.0100, output_per_1k=0.0300),
    "text-embedding-3-small": _Price(input_per_1k=0.00002, output_per_1k=0.0),
    "text-embedding-3-large": _Price(input_per_1k=0.00013, output_per_1k=0.0),
}


def cost_for_run(
    *,
    model: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> Optional[float]:
    """Compute USD cost for a single run. Returns None when model or
    token counts are unknown — surfaces as "unknown" in the UI rather
    than a spuriously-zero cost."""
    if not model or input_tokens is None or output_tokens is None:
        return None
    price = _PRICES.get(model)
    if price is None:
        return None
    return (
        (input_tokens / 1000.0) * price.input_per_1k
        + (output_tokens / 1000.0) * price.output_per_1k
    )


def cost_for_bucket(
    *,
    model: Optional[str],
    sum_input_tokens: int,
    sum_output_tokens: int,
) -> Optional[float]:
    """Sum-of-tokens version, used by the rollup aggregation."""
    return cost_for_run(
        model=model,
        input_tokens=sum_input_tokens,
        output_tokens=sum_output_tokens,
    )


def known_models() -> list[str]:
    """Returned by the observability summary endpoint so the UI can
    detect missing prices and prompt the admin to update."""
    return sorted(_PRICES.keys())
