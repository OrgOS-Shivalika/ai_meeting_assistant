"""Phase 4B parser base types + dispatcher.

The `ParsedBlock` schema is the *only* shape the chunker ever sees, so
parsers are responsible for everything format-specific: PDF page numbers,
DOCX heading hierarchy, XLSX sheet/row addresses. Anything that can't be
expressed via `page_number` + `section_path` + `metadata` is dropped on
purpose — preserve provenance, not formatting.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


DocumentSubtype = Literal["pdf", "docx", "xlsx"]


# Mime -> subtype map. Browsers sometimes hand us the generic
# "application/octet-stream" with an extension hint instead, so the
# dispatcher falls back to the original filename extension.
_MIME_MAP: dict[str, DocumentSubtype] = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "docx",  # legacy hint; we still try python-docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",  # legacy hint
}

_EXT_MAP: dict[str, DocumentSubtype] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
}


class UnsupportedDocumentError(Exception):
    """Raised when we cannot dispatch the document to any parser. The
    caller should mark the doc `failed` with a friendly error."""


@dataclass
class ParsedBlock:
    """One semantic unit emitted by a parser.

    `block_index` is the *parser-local* order — Phase 4B's chunker only
    uses it for stable sort, not for storage. `page_number` is 1-indexed
    for PDF; absent for DOCX/XLSX. `section_path` is a slash-joined trail
    of headings (DOCX), sheet name (XLSX), or empty (PDF).
    `metadata` is a kitchen sink for parser-specific hints that flow
    into the chunk's `metadata_json` column unchanged."""

    block_index: int
    text: str
    page_number: int | None = None
    section_path: str | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Strip aggressively but don't drop here — the chunker decides
        # what counts as empty after de-duping whitespace.
        self.text = self.text.strip()


def _subtype_for(mime_type: str | None, filename: str | None) -> DocumentSubtype:
    """Resolve the parser subtype. Mime wins; extension is the fallback
    for the octet-stream + .pdf-ish case."""
    if mime_type:
        sub = _MIME_MAP.get(mime_type.strip().lower())
        if sub:
            return sub
    if filename:
        _, ext = os.path.splitext(filename)
        sub = _EXT_MAP.get(ext.lower())
        if sub:
            return sub
    raise UnsupportedDocumentError(
        f"no parser registered for mime_type={mime_type!r} filename={filename!r}"
    )


def parse_document(
    raw_bytes: bytes,
    mime_type: str | None,
    original_filename: str | None,
) -> tuple[DocumentSubtype, list[ParsedBlock]]:
    """Top-level dispatcher. Returns `(subtype, blocks)` so the caller
    can stash `subtype` into `metadata_json.source_subtype` for every
    chunk (one of the architectural commitments — Phase 5 reranking and
    the UI both want to know if a result is from PDF vs DOCX vs XLSX).
    Empty `blocks` is a valid outcome (corrupt or scanned doc); the
    caller marks the doc `failed`/`empty`."""
    subtype = _subtype_for(mime_type, original_filename)

    # Late imports so a missing optional dep only blows up if you
    # actually try to parse that format.
    if subtype == "pdf":
        from app.parsers.pdf_parser import parse_pdf
        blocks = parse_pdf(raw_bytes)
    elif subtype == "docx":
        from app.parsers.docx_parser import parse_docx
        blocks = parse_docx(raw_bytes)
    elif subtype == "xlsx":
        from app.parsers.xlsx_parser import parse_xlsx
        blocks = parse_xlsx(raw_bytes)
    else:  # pragma: no cover - exhaustive
        raise UnsupportedDocumentError(f"unhandled subtype {subtype!r}")

    blocks = [b for b in blocks if b.text]
    for i, b in enumerate(blocks):
        b.block_index = i
    logger.info(
        "parsed %s: %d non-empty blocks (mime=%s filename=%s)",
        subtype, len(blocks), mime_type, original_filename,
    )
    return subtype, blocks
