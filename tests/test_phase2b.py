"""Phase 2B verification — chunker + embedder unit tests.

Run from the project root with:

    venv\\Scripts\\python.exe tests\\test_phase2b.py

No pytest dependency, no DB / network access. The embedder tests stub the
OpenAI client via `monkeypatching` `app.services.embedder._get_client`."""
from __future__ import annotations

import os
import sys
import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Tiny test harness (mirrors tests/test_phase1.py style).
# ---------------------------------------------------------------------------

results: List[Tuple[str, str, str, str]] = []  # (slice, name, status, msg)


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
        msg = traceback.format_exc(limit=2).strip().splitlines()[-1]
        results.append((slice_id, name, "FAIL", msg))
        print(f"  [ERROR] {name} :: {msg}")
        return
    results.append((slice_id, name, "PASS", ""))
    print(f"  [PASS] {name}")


# ---------------------------------------------------------------------------
# Chunker tests
# ---------------------------------------------------------------------------

def _turn(speaker: str, text: str, t_start: int | None = None, t_end: int | None = None) -> dict:
    words = []
    for w in text.split():
        wd: dict = {"text": w}
        if t_start is not None:
            wd["start_timestamp"] = {"absolute": t_start}
            wd["end_timestamp"] = {"absolute": t_end if t_end is not None else t_start}
        words.append(wd)
    return {"participant": {"name": speaker, "id": speaker.lower()}, "words": words}


def chunker_empty_input():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=100, overlap_tokens=10)
    assert c.chunk(None) == []
    assert c.chunk([]) == []


def chunker_single_short_turn():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=100, overlap_tokens=10)
    chunks = c.chunk([_turn("Alice", "Hello world this is a short meeting.")])
    assert len(chunks) == 1, f"expected 1 chunk, got {len(chunks)}"
    assert chunks[0].chunk_index == 0
    assert chunks[0].speakers == ["Alice"]
    assert chunks[0].text.startswith("Alice: ")
    assert chunks[0].token_count > 0


def chunker_packs_multiple_turns():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=200, overlap_tokens=10)
    chunks = c.chunk([
        _turn("Alice", "Hello team."),
        _turn("Bob", "Hey Alice good to see you."),
        _turn("Alice", "Let's start the sync."),
    ])
    assert len(chunks) == 1, "small turns should pack into a single chunk"
    # Speakers list preserves first-seen order and dedupes.
    assert chunks[0].speakers == ["Alice", "Bob"], chunks[0].speakers
    assert "Alice:" in chunks[0].text and "Bob:" in chunks[0].text


def chunker_emits_multiple_chunks_under_budget():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=40, overlap_tokens=5)
    turns = [_turn(f"Spkr{i}", "alpha bravo charlie delta echo foxtrot") for i in range(8)]
    chunks = c.chunk(turns)
    assert len(chunks) >= 2, "expected to spill into multiple chunks"
    # chunk_index strictly ascends from 0.
    for i, ch in enumerate(chunks):
        assert ch.chunk_index == i, f"chunk_index expected {i}, got {ch.chunk_index}"
    # Every chunk's token_count must respect the budget (plus a small
    # slack for the overlap prefix).
    for ch in chunks:
        assert ch.token_count <= c.target_tokens + c.overlap_tokens + 5, (
            f"chunk {ch.chunk_index} too big: {ch.token_count}"
        )


def chunker_overlap_carries_text():
    from app.services.chunker import TranscriptChunker
    # Use small windows so overlap is easy to verify.
    c = TranscriptChunker(target_tokens=30, overlap_tokens=8)
    # Two distinct turns with marker words we can spot in the next chunk.
    turns = [
        _turn("Alice", "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"),
        _turn("Bob", "mike november oscar papa quebec romeo sierra tango uniform"),
    ]
    chunks = c.chunk(turns)
    assert len(chunks) >= 2, "expected at least 2 chunks for overlap test"
    # The second chunk's head should contain tokens from the tail of the
    # first chunk (i.e. some of Alice's later words).
    second_head = chunks[1].text.lower()
    assert "alice" in second_head, (
        "overlap should re-introduce the speaker label of the previous turn"
    )


def chunker_splits_long_turn_on_sentence_boundary():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=40, overlap_tokens=5)
    long_text = (
        "Sentence one with several words. "
        "Sentence two follows the first one carefully. "
        "Sentence three keeps going about the project plan. "
        "Sentence four wraps things up with more context. "
        "Sentence five concludes the speaker's long monologue here."
    )
    chunks = c.chunk([_turn("Alice", long_text)])
    assert len(chunks) >= 2, "long monologue should split into multiple chunks"
    # Each chunk should be Alice-only and labeled.
    for ch in chunks:
        assert ch.speakers == ["Alice"], f"speakers should remain Alice, got {ch.speakers}"
        assert ch.text.startswith("Alice: ")


def chunker_hard_windows_oversize_sentence():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=20, overlap_tokens=3)
    # One sentence, no punctuation, way over budget. Chunker must still
    # produce output (it falls back to hard token windowing).
    huge = " ".join(f"word{i}" for i in range(200))
    chunks = c.chunk([_turn("Alice", huge)])
    assert len(chunks) >= 2, "oversize sentence should still be windowed"
    # Reconstruct loosely — make sure we got a meaningful spread.
    total_text_len = sum(len(c.text) for c in chunks)
    assert total_text_len > 100, "hard-windowed output should preserve most content"


def chunker_records_timestamps():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=200, overlap_tokens=10)
    chunks = c.chunk([
        _turn("Alice", "first turn here", t_start=100, t_end=110),
        _turn("Bob", "second turn there", t_start=120, t_end=130),
    ])
    assert len(chunks) == 1
    ch = chunks[0]
    assert ch.start_timestamp == 100, f"expected start=100, got {ch.start_timestamp}"
    assert ch.end_timestamp == 130, f"expected end=130, got {ch.end_timestamp}"


def chunker_skips_empty_blocks():
    from app.services.chunker import TranscriptChunker
    c = TranscriptChunker(target_tokens=100, overlap_tokens=10)
    chunks = c.chunk([
        {"participant": {"name": "Ghost"}, "words": []},
        _turn("Alice", "Real content here."),
        {"participant": {"name": "Ghost"}, "words": [{"text": ""}]},
    ])
    assert len(chunks) == 1
    assert chunks[0].speakers == ["Alice"]


# ---------------------------------------------------------------------------
# Embedder tests
# ---------------------------------------------------------------------------

class _FakeUsage:
    def __init__(self, prompt_tokens, total_tokens):
        self.prompt_tokens = prompt_tokens
        self.total_tokens = total_tokens


class _FakeEmbeddingItem:
    def __init__(self, vec):
        self.embedding = vec


class _FakeEmbeddingResponse:
    def __init__(self, vecs):
        self.data = [_FakeEmbeddingItem(v) for v in vecs]
        self.usage = _FakeUsage(prompt_tokens=len(vecs) * 5, total_tokens=len(vecs) * 5)


class _FakeEmbeddings:
    def __init__(self, vector_dim: int, fail_first_n: int = 0, fail_with=None):
        self.calls: list[list[str]] = []
        self.vector_dim = vector_dim
        self._fail_first_n = fail_first_n
        self._fail_with = fail_with

    def create(self, *, model, input, dimensions):
        self.calls.append(list(input))
        if self._fail_first_n > 0:
            self._fail_first_n -= 1
            raise self._fail_with
        assert dimensions == self.vector_dim, f"dimensions={dimensions} != {self.vector_dim}"
        # Deterministic vectors: dimension-0 = hash of the input text mod
        # 1000, rest zeros. Lets us verify input-order preservation.
        out = []
        for text in input:
            v = [0.0] * self.vector_dim
            v[0] = float(hash(text) % 1000)
            out.append(v)
        return _FakeEmbeddingResponse(out)


class _FakeClient:
    def __init__(self, embeddings):
        self.embeddings = embeddings


def _install_fake_client(monkey_embeddings):
    """Replace `app.services.embedder._get_client` so tests don't touch
    the real OpenAI SDK."""
    from app.services import embedder as emb
    fake = _FakeClient(monkey_embeddings)
    emb._client = None  # reset the lazy singleton
    emb._get_client = lambda: fake  # type: ignore[assignment]
    # Also bypass sleeps inside the retry loop to keep tests fast.
    import time as _time
    emb.time = type("T", (), {"sleep": staticmethod(lambda _s: None)})


def embedder_empty_returns_empty():
    from app.services.embedder import Embedder
    fake = _FakeEmbeddings(vector_dim=1536)
    _install_fake_client(fake)
    e = Embedder(dimensions=1536, batch_size=100, max_retries=0)
    assert e.embed([]) == []
    assert fake.calls == [], "no API call should be made for empty input"


def embedder_whitespace_input_raises():
    from app.services.embedder import Embedder
    fake = _FakeEmbeddings(vector_dim=1536)
    _install_fake_client(fake)
    e = Embedder(dimensions=1536, batch_size=100, max_retries=0)
    raised = False
    try:
        e.embed(["valid text", "  ", "more text"])
    except ValueError:
        raised = True
    assert raised, "expected ValueError on whitespace-only input"


def embedder_batches_inputs():
    from app.services.embedder import Embedder
    fake = _FakeEmbeddings(vector_dim=1536)
    _install_fake_client(fake)
    e = Embedder(dimensions=1536, batch_size=100, max_retries=0)
    texts = [f"text-{i}" for i in range(250)]
    vectors = e.embed(texts)
    assert len(vectors) == 250
    assert len(fake.calls) == 3, f"expected 3 batches, got {len(fake.calls)}"
    assert [len(c) for c in fake.calls] == [100, 100, 50]
    # Order preservation: dim[0] follows hash(text-i) mod 1000.
    for i, v in enumerate(vectors):
        expected = float(hash(f"text-{i}") % 1000)
        assert v[0] == expected, f"order mismatch at index {i}"


def embedder_retries_on_ratelimit():
    from openai import RateLimitError
    from app.services.embedder import Embedder
    # RateLimitError takes (message, response, body) in some versions; we
    # only need an instance the isinstance check will recognize, so build
    # it via __new__ to skip the constructor signature drift.
    err = RateLimitError.__new__(RateLimitError)
    err.args = ("simulated",)
    fake = _FakeEmbeddings(vector_dim=1536, fail_first_n=2, fail_with=err)
    _install_fake_client(fake)
    e = Embedder(dimensions=1536, batch_size=100, max_retries=3, initial_backoff=0)
    vectors = e.embed(["one", "two"])
    assert len(vectors) == 2
    assert len(fake.calls) == 3, "should have retried twice then succeeded"


def embedder_gives_up_after_max_retries():
    from openai import RateLimitError
    from app.services.embedder import Embedder
    err = RateLimitError.__new__(RateLimitError)
    err.args = ("simulated",)
    fake = _FakeEmbeddings(vector_dim=1536, fail_first_n=5, fail_with=err)
    _install_fake_client(fake)
    e = Embedder(dimensions=1536, batch_size=100, max_retries=2, initial_backoff=0)
    raised = False
    try:
        e.embed(["one"])
    except RateLimitError:
        raised = True
    assert raised, "expected RateLimitError after max_retries exhausted"
    assert len(fake.calls) == 3, "should have attempted initial + 2 retries"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    with section("2B - Chunker"):
        check("2B", "chunker: empty input returns []", chunker_empty_input)
        check("2B", "chunker: single short turn", chunker_single_short_turn)
        check("2B", "chunker: packs multiple short turns", chunker_packs_multiple_turns)
        check("2B", "chunker: multi-chunk output under budget", chunker_emits_multiple_chunks_under_budget)
        check("2B", "chunker: overlap carries speaker label forward", chunker_overlap_carries_text)
        check("2B", "chunker: long turn splits on sentence boundary", chunker_splits_long_turn_on_sentence_boundary)
        check("2B", "chunker: oversize sentence hard-windowed", chunker_hard_windows_oversize_sentence)
        check("2B", "chunker: timestamps min/max across turns", chunker_records_timestamps)
        check("2B", "chunker: empty blocks ignored", chunker_skips_empty_blocks)

    with section("2B - Embedder"):
        check("2B", "embedder: empty input -> no API call", embedder_empty_returns_empty)
        check("2B", "embedder: whitespace-only input raises", embedder_whitespace_input_raises)
        check("2B", "embedder: batches 250 -> 3 API calls", embedder_batches_inputs)
        check("2B", "embedder: retries on RateLimitError then succeeds", embedder_retries_on_ratelimit)
        check("2B", "embedder: gives up after max_retries", embedder_gives_up_after_max_retries)

    print("\n=== Summary ===")
    n_pass = sum(1 for r in results if r[2] == "PASS")
    n_fail = sum(1 for r in results if r[2] != "PASS")
    print(f"PASS: {n_pass}   FAIL: {n_fail}   TOTAL: {len(results)}")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
