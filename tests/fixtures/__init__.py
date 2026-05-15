"""Test fixtures used by Phase 5+ ship tests and the 5F eval harness.

The headline export is `build_canonical_org` (see `canonical_org.py`):
one richly-populated org that exercises every retrieval topology Phase 5
cares about — multi-tier scopes, mixed sources, cross-source entity
dedup, relationships connecting meetings and documents — without
spending money on real embeddings or LLM calls.
"""
from tests.fixtures.canonical_org import (
    CanonicalFixture,
    build_canonical_org,
    canonical_stub_embed,
    cleanup_canonical_org,
)

__all__ = [
    "CanonicalFixture",
    "build_canonical_org",
    "canonical_stub_embed",
    "cleanup_canonical_org",
]
