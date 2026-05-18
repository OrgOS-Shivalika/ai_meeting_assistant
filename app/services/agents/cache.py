"""Phase 7C — in-process resolver cache with TTL + epoch-aware invalidation.

The resolver call shape:

  1. Compute cache key from inputs.
  2. Look up. On miss, fall through.
  3. On hit, read `agent_config_epochs.epoch` for (org, profile) and
     compare against the snapshot stored with the entry. If the DB
     epoch is higher, evict and recompute. Otherwise return.
  4. Honor TTL — even with no publishes, the cache eventually
     re-evaluates so new bindings (e.g. a new team-scoped config the
     resolver should now see) take effect.

Capacity: bounded LFU-ish via `collections.OrderedDict` move-to-end
on hit. When capacity is exceeded, the least-recently-used entry is
evicted. Plain Python — no extra deps.

Stampede protection: per-key `threading.Lock`. First thread through
on a miss computes; others wait. The lock map is itself sized so it
doesn't grow unbounded.

Public surface:

  ResolverCache.get(key) -> tuple[snapshot_epoch, value] | None
  ResolverCache.put(key, snapshot_epoch, value)
  ResolverCache.invalidate(key)
  ResolverCache.locked(key)        # context manager
  ResolverCache.clear()            # tests
  ResolverCache.stats()            # observability hook

The resolver is responsible for the SELECT that reads the current
epoch from `agent_config_epochs`; the cache itself only stores the
snapshot. This keeps the cache pure-in-memory and dependency-free,
which makes it dead simple to test.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Hashable, Iterator, Optional

from app.config.settings import settings


@dataclass
class _Entry:
    """One cached resolution. `epoch` is the DB-side counter at the
    time of caching; the resolver compares it against the live value
    on every hit."""
    epoch: int
    expires_at: float
    value: Any


class ResolverCache:
    """Thread-safe in-process cache. One instance per process —
    module-level singleton is created at the bottom of this file."""

    def __init__(self, *, max_entries: int, ttl_seconds: float) -> None:
        self._data: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._locks: dict[Hashable, threading.Lock] = {}
        self._meta_lock = threading.Lock()
        # `max_entries` for both data and lock dicts. The lock dict is
        # cleaned up on cache eviction (one-to-one with entries).
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    # ---------------------------------------------------------------
    # Stampede protection
    # ---------------------------------------------------------------

    @contextmanager
    def locked(self, key: Hashable) -> Iterator[None]:
        """Acquire the per-key lock. On a miss, hold this lock across
        the DB read + put() so concurrent callers don't all hammer
        the DB. The lock is NOT held across the cache lookup itself
        (that would defeat the point of caching)."""
        with self._meta_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    # ---------------------------------------------------------------
    # Get / put / invalidate
    # ---------------------------------------------------------------

    def get(self, key: Hashable) -> Optional[tuple[int, Any]]:
        """Return `(snapshot_epoch, value)` if present + not expired.
        Caller compares the returned epoch against the live DB epoch
        to decide whether to use the cached value or recompute."""
        with self._meta_lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            now = time.monotonic()
            if entry.expires_at <= now:
                # Expired — drop.
                self._data.pop(key, None)
                self._locks.pop(key, None)
                self._misses += 1
                return None
            # LRU touch.
            self._data.move_to_end(key)
            self._hits += 1
            return entry.epoch, entry.value

    def put(
        self, key: Hashable, snapshot_epoch: int, value: Any,
    ) -> None:
        with self._meta_lock:
            self._data[key] = _Entry(
                epoch=snapshot_epoch,
                expires_at=time.monotonic() + self._ttl,
                value=value,
            )
            self._data.move_to_end(key)
            # Evict LRU if over capacity.
            while len(self._data) > self._max_entries:
                evict_key, _ = self._data.popitem(last=False)
                self._locks.pop(evict_key, None)

    def invalidate(self, key: Hashable) -> None:
        with self._meta_lock:
            self._data.pop(key, None)
            self._locks.pop(key, None)

    def clear(self) -> None:
        """For tests + admin tooling. Not used in the hot path."""
        with self._meta_lock:
            self._data.clear()
            self._locks.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        with self._meta_lock:
            return {
                "size": len(self._data),
                "max_entries": self._max_entries,
                "hits": self._hits,
                "misses": self._misses,
            }


# ---------------------------------------------------------------------------
# Settings-aware singleton.
# ---------------------------------------------------------------------------

# Defaults match plan §6.5 — 60s TTL, 2048 entries.
_DEFAULT_TTL = float(getattr(settings, "AGENT_RESOLVER_CACHE_TTL_S", 60))
_DEFAULT_SIZE = int(getattr(settings, "AGENT_RESOLVER_CACHE_SIZE", 2048))

# Module-level singleton. Workers each get their own. The
# `agent_config_epochs` table is the cross-worker invalidation
# transport (plan §6.5).
resolver_cache = ResolverCache(
    max_entries=_DEFAULT_SIZE, ttl_seconds=_DEFAULT_TTL,
)


def reset_for_tests() -> None:
    """Tests call this between fixtures to keep cache state isolated.
    Do NOT use in production paths."""
    resolver_cache.clear()
