"""Phase 4B document chunker.

Mirrors the Phase 2 `TranscriptChunker` shape (~800 tokens with 100-token
overlap under `cl100k_base`) but consumes `ParsedBlock`s instead of
speaker turns. Block-aware: chunks prefer to start at block boundaries,
and inherit `page_number` + `section_path` from whichever block
contributed the most tokens.

The output `DocumentChunk` dataclass is *not* the SQLAlchemy model — it
is a transport object for the Phase 4C ingestion task, which embeds them
and writes to `document_chunks` rows. Keeping them separate means we
can unit-test chunking without touching the DB.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

import tiktoken

from app.config.settings import settings
from app.parsers import ParsedBlock

logger = logging.getLogger(__name__)

# Sentence boundary detector for over-budget single blocks.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class DocChunk:
    """One embedding-ready chunk of a document. The Phase 4C task is
    responsible for translating these into `DocumentChunk` rows."""

    chunk_index: int
    text: str
    token_count: int
    page_number: int | None = None
    section_path: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class _PreBlock:
    """A normalized parsed block — already token-counted, with its
    parent block_index preserved for the inheritance heuristic."""

    text: str
    tokens: list[int]
    page_number: int | None
    section_path: str | None
    metadata: dict


class DocumentChunker:
    """Block-aware token chunker for documents. Construct once and reuse
    across docs; tiktoken encodings are thread-safe."""

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
    def chunk(self, blocks: Iterable[ParsedBlock] | None) -> list[DocChunk]:
        if not blocks:
            return []

        pre_blocks = self._normalize_blocks(blocks)
        if not pre_blocks:
            return []

        # 1. Fan out any single block that exceeds the budget into
        #    sub-blocks. Each sub-block inherits the parent's metadata.
        flat: list[_PreBlock] = []
        for b in pre_blocks:
            if len(b.tokens) <= self.target_tokens:
                flat.append(b)
            else:
                flat.extend(self._split_long_block(b))

        # 2. Greedy pack: combine consecutive blocks until the next
        #    would overflow.
        chunks: list[DocChunk] = []
        cursor_tokens: list[int] = []
        cursor_pieces: list[str] = []
        cursor_blocks: list[_PreBlock] = []

        def emit():
            if not cursor_tokens:
                return
            text = "\n\n".join(cursor_pieces).strip()
            page, section, meta = self._dominant_metadata(cursor_blocks)
            chunks.append(
                DocChunk(
                    chunk_index=len(chunks),
                    text=text,
                    token_count=len(cursor_tokens),
                    page_number=page,
                    section_path=section,
                    metadata=meta,
                )
            )

        for b in flat:
            if cursor_tokens and len(cursor_tokens) + len(b.tokens) > self.target_tokens:
                emit()
                tail_tokens, tail_text = self._tail_overlap(cursor_pieces)
                cursor_tokens = list(tail_tokens)
                cursor_pieces = [tail_text] if tail_text else []
                # Overlap text is a *suffix* of the previous chunk — it
                # inherits no fresh metadata. The next real block will
                # contribute the page/section for the new chunk.
                cursor_blocks = []

            cursor_tokens.extend(b.tokens)
            cursor_pieces.append(b.text)
            cursor_blocks.append(b)

        emit()
        logger.info(
            "document chunked into %d chunks (target=%d overlap=%d, %d blocks in)",
            len(chunks), self.target_tokens, self.overlap_tokens, len(flat),
        )
        return chunks

    # ----------------------------------------------------------------- helpers
    def _normalize_blocks(self, blocks: Iterable[ParsedBlock]) -> list[_PreBlock]:
        out: list[_PreBlock] = []
        for b in blocks:
            text = (b.text or "").strip()
            if not text:
                continue
            tokens = self.encoding.encode(text)
            if not tokens:
                continue
            out.append(_PreBlock(
                text=text,
                tokens=tokens,
                page_number=b.page_number,
                section_path=b.section_path,
                metadata=dict(b.metadata or {}),
            ))
        return out

    def _split_long_block(self, block: _PreBlock) -> list[_PreBlock]:
        """Break one over-budget block into sentence-aligned sub-blocks,
        falling back to hard token windowing for runaway sentences."""
        sentences = _SENTENCE_SPLIT.split(block.text)
        subs: list[_PreBlock] = []
        buf: list[str] = []
        buf_token_count = 0

        def flush():
            nonlocal buf, buf_token_count
            if not buf:
                return
            piece = " ".join(buf).strip()
            subs.append(_PreBlock(
                text=piece,
                tokens=self.encoding.encode(piece),
                page_number=block.page_number,
                section_path=block.section_path,
                metadata=dict(block.metadata),
            ))
            buf = []
            buf_token_count = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            sent_tokens = self.encoding.encode(sentence)
            if len(sent_tokens) > self.target_tokens:
                flush()
                subs.extend(self._hard_window(sentence, block))
                continue
            if buf_token_count + len(sent_tokens) > self.target_tokens:
                flush()
            buf.append(sentence)
            buf_token_count += len(sent_tokens)
        flush()
        return subs or list(self._hard_window(block.text, block))

    def _hard_window(self, text: str, block: _PreBlock) -> Iterable[_PreBlock]:
        """Last-resort window splitter for monster sentences."""
        body_tokens = self.encoding.encode(text)
        step = self.target_tokens
        for i in range(0, len(body_tokens), step):
            slice_tokens = body_tokens[i : i + step]
            slice_text = self.encoding.decode(slice_tokens).strip()
            yield _PreBlock(
                text=slice_text,
                tokens=slice_tokens,
                page_number=block.page_number,
                section_path=block.section_path,
                metadata=dict(block.metadata),
            )

    def _dominant_metadata(
        self, contributing: list[_PreBlock]
    ) -> tuple[int | None, str | None, dict]:
        """Pick the page/section that contributed the most tokens to
        this chunk. Falls back to "first non-null" when ties happen.
        Also merges per-block metadata into a chunk-level dict, keeping
        `source_subtype` (always uniform) and collecting `pages_covered`
        / `sections_covered` lists for citations that span boundaries."""
        if not contributing:
            return None, None, {}

        page_tokens: Counter = Counter()
        section_tokens: Counter = Counter()
        subtypes: set[str] = set()
        pages_covered: list[int] = []
        sections_covered: list[str] = []

        for b in contributing:
            tok = len(b.tokens)
            if b.page_number is not None:
                page_tokens[b.page_number] += tok
                if b.page_number not in pages_covered:
                    pages_covered.append(b.page_number)
            if b.section_path:
                section_tokens[b.section_path] += tok
                if b.section_path not in sections_covered:
                    sections_covered.append(b.section_path)
            sub = b.metadata.get("source_subtype")
            if sub:
                subtypes.add(sub)

        dominant_page = page_tokens.most_common(1)[0][0] if page_tokens else None
        dominant_section = section_tokens.most_common(1)[0][0] if section_tokens else None

        meta: dict = {}
        if len(subtypes) == 1:
            meta["source_subtype"] = next(iter(subtypes))
        elif subtypes:
            meta["source_subtype"] = sorted(subtypes)
        if len(pages_covered) > 1:
            meta["pages_covered"] = pages_covered
        if len(sections_covered) > 1:
            meta["sections_covered"] = sections_covered
        return dominant_page, dominant_section, meta

    def _tail_overlap(self, pieces: list[str]) -> tuple[list[int], str]:
        """Pull the last `overlap_tokens` tokens off the just-emitted
        chunk and return them as the head of the next chunk. Plain text
        carry — documents have no speaker labels to preserve."""
        if not pieces or self.overlap_tokens <= 0:
            return [], ""
        last_piece = pieces[-1]
        last_tokens = self.encoding.encode(last_piece)
        if not last_tokens:
            return [], ""
        tail_slice = last_tokens[-self.overlap_tokens :]
        tail_text = self.encoding.decode(tail_slice).strip()
        if not tail_text:
            return [], ""
        return self.encoding.encode(tail_text), tail_text
