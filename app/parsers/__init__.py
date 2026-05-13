"""Phase 4B document parsers.

Each parser ingests raw bytes (whatever shape MinIO hands back) and emits
a flat sequence of `ParsedBlock`s — the chunker's input contract. Parsers
are deliberately dumb: they preserve block-level provenance (page,
heading path, sheet row) and do no chunking of their own.

Public API:

    from app.parsers import parse_document, ParsedBlock, UnsupportedDocumentError

    blocks = parse_document(raw_bytes, mime_type, original_filename)

`parse_document` is the single entry point used by the Phase 4C
`process_document` task. It picks the right parser by mime_type (with
extension as a fallback) and never raises for partial extraction — a doc
that yields zero blocks comes back as an empty list, leaving the caller
to decide whether to mark the doc `failed` or `ready_empty`.
"""
from app.parsers.base import (
    ParsedBlock,
    DocumentSubtype,
    UnsupportedDocumentError,
    parse_document,
)

__all__ = [
    "ParsedBlock",
    "DocumentSubtype",
    "UnsupportedDocumentError",
    "parse_document",
]
