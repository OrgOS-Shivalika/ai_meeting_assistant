"""Phase 2 transcript chunker.

Takes a Recall.ai-style `transcript_raw` (list of `{participant, words}`
blocks) and produces a sequence of semantic `Chunk`s, each ~`target_tokens`
long under the embedding model's tokenizer, with `overlap_tokens` carried
into the head of the next chunk.

Design notes:

- Speaker-turn aware. Chunks pack consecutive turns together and prefer
  to cut at turn boundaries. A single speaker turn that exceeds
  `target_tokens` is split on sentence boundaries; if a single sentence
  is still over budget we fall back to hard token windowing rather than
  refuse to chunk.
- The overlap carries the last `overlap_tokens` tokens of the previous
  chunk into the head of the next chunk, **with the original speaker
  label**, so that cross-chunk references survive retrieval.
- Timestamps are best-effort. Recall provides `start_timestamp.absolute`
  and `end_timestamp.absolute` (epoch seconds, sometimes ISO strings) on
  word objects; we expose the chunk's earliest start and latest end as
  integer seconds when convertible.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

import tiktoken

from app.config.settings import settings

logger = logging.getLogger(__name__)

# Sentence-end finder used when a single turn overflows `target_tokens`.
# Conservative — matches `.`, `!`, `?` followed by whitespace. We don't
# try to be clever about abbreviations because transcript text is mostly
# spoken language where dotted abbreviations are rare.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    """A single embedding-ready segment of a transcript."""
    chunk_index: int
    text: str
    token_count: int
    speakers: list[str] = field(default_factory=list)
    start_timestamp: int | None = None
    end_timestamp: int | None = None


@dataclass
class _Turn:
    """Normalized view of one transcript block."""
    speaker: str
    text: str
    tokens: list[int]
    start: int | None
    end: int | None


def _coerce_timestamp(value) -> int | None:
    """Recall sometimes hands back ISO strings, sometimes epoch numbers.
    Return integer seconds or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        # Accept "2026-05-11T12:00:00Z" style and bare numeric strings.
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _word_timestamps(words: list[dict]) -> tuple[int | None, int | None]:
    """Pluck the earliest start and latest end timestamp out of a Recall
    word list. Recall nests them under `start_timestamp.absolute` /
    `end_timestamp.absolute`."""
    start: int | None = None
    end: int | None = None
    for w in words:
        ws = w.get("start_timestamp") or {}
        we = w.get("end_timestamp") or {}
        s = _coerce_timestamp(ws.get("absolute") if isinstance(ws, dict) else ws)
        e = _coerce_timestamp(we.get("absolute") if isinstance(we, dict) else we)
        if s is not None and (start is None or s < start):
            start = s
        if e is not None and (end is None or e > end):
            end = e
    return start, end


class TranscriptChunker:
    """Speaker-aware token chunker. Construct with an optional encoding
    name (defaults to OpenAI's `cl100k_base`). Reuse the instance across
    meetings — `tiktoken` encoding objects are thread-safe."""

    def __init__(
        self,
        *,
        encoding_name: str = "cl100k_base",
        target_tokens: int | None = None,
        overlap_tokens: int | None = None,
    ):
        self.encoding = tiktoken.get_encoding(encoding_name)
        self.target_tokens = target_tokens or settings.CHUNK_SIZE_TOKENS
        self.overlap_tokens = overlap_tokens or settings.CHUNK_OVERLAP_TOKENS
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError(
                "overlap_tokens must be smaller than target_tokens "
                f"(got overlap={self.overlap_tokens}, target={self.target_tokens})"
            )

    # ------------------------------------------------------------------ public
    def chunk(self, transcript_raw: Iterable[dict] | None) -> list[Chunk]:
        if not transcript_raw:
            return []

        turns = self._normalize_turns(transcript_raw)
        if not turns:
            return []

        # 1. Pre-split: any turn > target_tokens is fanned out into
        #    sub-turns that each fit. Speaker + timestamps are preserved.
        flat_turns: list[_Turn] = []
        for turn in turns:
            if len(turn.tokens) <= self.target_tokens:
                flat_turns.append(turn)
            else:
                flat_turns.extend(self._split_long_turn(turn))

        # 2. Greedy pack: pile consecutive turns into the current chunk
        #    until the next one would push it over budget, then emit.
        chunks: list[Chunk] = []
        cursor_tokens: list[int] = []          # tokens of the current chunk
        cursor_pieces: list[str] = []           # rendered "Speaker: text" pieces
        cursor_speakers: list[str] = []         # ordered, dedup-on-add
        cursor_start: int | None = None
        cursor_end: int | None = None

        def emit():
            if not cursor_tokens:
                return
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    text="\n".join(cursor_pieces).strip(),
                    token_count=len(cursor_tokens),
                    speakers=list(cursor_speakers),
                    start_timestamp=cursor_start,
                    end_timestamp=cursor_end,
                )
            )

        for turn in flat_turns:
            piece_text = f"{turn.speaker}: {turn.text}"
            piece_tokens = self.encoding.encode(piece_text)

            # If adding this turn would overflow the chunk AND we already
            # have content, emit, then start a fresh chunk seeded with the
            # overlap tail of what we just emitted.
            if cursor_tokens and len(cursor_tokens) + len(piece_tokens) > self.target_tokens:
                emit()
                tail_tokens, tail_text, tail_speaker = self._tail_overlap(
                    cursor_pieces, cursor_speakers
                )
                cursor_tokens = list(tail_tokens)
                cursor_pieces = [tail_text] if tail_text else []
                cursor_speakers = [tail_speaker] if tail_speaker else []
                # Overlap text doesn't carry forward timestamps — start
                # fresh from the next turn.
                cursor_start = None
                cursor_end = None

            cursor_tokens.extend(piece_tokens)
            cursor_pieces.append(piece_text)
            if turn.speaker not in cursor_speakers:
                cursor_speakers.append(turn.speaker)
            if turn.start is not None and (cursor_start is None or turn.start < cursor_start):
                cursor_start = turn.start
            if turn.end is not None and (cursor_end is None or turn.end > cursor_end):
                cursor_end = turn.end

        emit()
        logger.info(
            "Chunked transcript into %d chunks (target=%d overlap=%d, %d turns in)",
            len(chunks),
            self.target_tokens,
            self.overlap_tokens,
            len(flat_turns),
        )
        return chunks

    # ----------------------------------------------------------------- helpers
    def _normalize_turns(self, transcript_raw: Iterable[dict]) -> list[_Turn]:
        out: list[_Turn] = []
        for block in transcript_raw:
            participant = block.get("participant") or {}
            speaker = (participant.get("name") or "Unknown").strip() or "Unknown"
            words = block.get("words") or []
            text = " ".join(w.get("text", "") for w in words).strip()
            text = re.sub(r"\s+([.,!?])", r"\1", text)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            tokens = self.encoding.encode(f"{speaker}: {text}")
            start, end = _word_timestamps(words)
            out.append(_Turn(speaker=speaker, text=text, tokens=tokens, start=start, end=end))
        return out

    def _split_long_turn(self, turn: _Turn) -> list[_Turn]:
        """Break one over-budget turn into smaller sub-turns. Tries
        sentence boundaries first; falls back to fixed-window token
        slicing for sentences that themselves exceed `target_tokens`."""
        # Carve out the actual prose tokens (i.e. exclude the
        # "Speaker: " prefix from the budget math) by re-encoding.
        prefix = f"{turn.speaker}: "
        prefix_token_len = len(self.encoding.encode(prefix))
        budget = self.target_tokens - prefix_token_len
        if budget <= 0:
            # Pathological — speaker label alone is over budget. Surrender
            # to hard token windowing on the whole encoded turn.
            return list(self._hard_window(turn))

        sentences = _SENTENCE_SPLIT.split(turn.text)
        sub_turns: list[_Turn] = []
        buf: list[str] = []
        buf_token_count = 0

        def flush_buf():
            nonlocal buf, buf_token_count
            if not buf:
                return
            sub_text = " ".join(buf).strip()
            full_tokens = self.encoding.encode(f"{turn.speaker}: {sub_text}")
            sub_turns.append(
                _Turn(
                    speaker=turn.speaker,
                    text=sub_text,
                    tokens=full_tokens,
                    # Timestamps only on the first sub-turn; we can't
                    # interpolate accurately from sentence offsets.
                    start=turn.start if not sub_turns else None,
                    end=turn.end if not sub_turns else None,
                )
            )
            buf = []
            buf_token_count = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sent_tokens = self.encoding.encode(sentence)
            if len(sent_tokens) > budget:
                # Single sentence is bigger than a chunk — flush whatever
                # we have, then hard-window the oversize sentence.
                flush_buf()
                solo = _Turn(
                    speaker=turn.speaker,
                    text=sentence,
                    tokens=self.encoding.encode(f"{turn.speaker}: {sentence}"),
                    start=turn.start if not sub_turns else None,
                    end=turn.end if not sub_turns else None,
                )
                sub_turns.extend(self._hard_window(solo))
                continue
            if buf_token_count + len(sent_tokens) > budget:
                flush_buf()
            buf.append(sentence)
            buf_token_count += len(sent_tokens)
        flush_buf()
        return sub_turns or list(self._hard_window(turn))

    def _hard_window(self, turn: _Turn) -> Iterable[_Turn]:
        """Last-resort splitter for sentences that bust the budget. Yields
        token-aligned sub-turns whose decoded text is reassembled by
        tiktoken. Loses sentence boundaries; only used when there are no
        better seams."""
        prefix = f"{turn.speaker}: "
        prefix_tokens = self.encoding.encode(prefix)
        body_tokens = self.encoding.encode(turn.text)
        step = self.target_tokens - len(prefix_tokens)
        if step <= 0:
            step = self.target_tokens  # speaker label alone is too long
        first = True
        for i in range(0, len(body_tokens), step):
            slice_tokens = body_tokens[i : i + step]
            slice_text = self.encoding.decode(slice_tokens).strip()
            yield _Turn(
                speaker=turn.speaker,
                text=slice_text,
                tokens=prefix_tokens + slice_tokens,
                start=turn.start if first else None,
                end=turn.end if not body_tokens[i + step:] else None,
            )
            first = False

    def _tail_overlap(
        self,
        pieces: list[str],
        speakers: list[str],
    ) -> tuple[list[int], str, str | None]:
        """Pull the last `overlap_tokens` tokens off the just-emitted
        chunk, preserving the last speaker's label so the carry-over reads
        cleanly. Returns (overlap_tokens_ids, overlap_text, overlap_speaker)."""
        if not pieces or self.overlap_tokens <= 0:
            return [], "", None
        last_piece = pieces[-1]
        last_tokens = self.encoding.encode(last_piece)
        if not last_tokens:
            return [], "", None
        tail_slice = last_tokens[-self.overlap_tokens :]
        tail_text = self.encoding.decode(tail_slice).strip()
        if not tail_text:
            return [], "", None
        # The last piece is shaped "Speaker: ..." — strip the prefix from
        # the overlap text if it survived the slice, then re-wrap with
        # the same speaker so the overlap renders as a real turn.
        speaker = speakers[-1] if speakers else None
        if speaker and tail_text.startswith(f"{speaker}: "):
            tail_text = tail_text[len(speaker) + 2 :]
        if speaker:
            piece = f"{speaker}: {tail_text}"
        else:
            piece = tail_text
        piece_tokens = self.encoding.encode(piece)
        return piece_tokens, piece, speaker
