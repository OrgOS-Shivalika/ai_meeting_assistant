"""PDF parser — pypdf with one block per page.

We deliberately do *not* split a page into paragraphs at parse time: PDF
"paragraphs" are an illusion built on visual layout, and pypdf's text
extraction often interleaves columns into a single line stream. The
chunker handles cross-page splitting on token boundaries; the parser
just guarantees we never lose the page number for citation purposes.

Scanned PDFs (image-only) yield empty strings here — by design. OCR is a
Phase 4+ concern; for now the caller flips `embedding_status='failed'`
with a friendly "Looks like a scanned PDF — OCR not yet supported" hint.
"""
from __future__ import annotations

import io
import logging
import re

from app.parsers.base import ParsedBlock

logger = logging.getLogger(__name__)

# pypdf occasionally injects null bytes / control chars when a font map
# is missing — strip them so they don't break tiktoken downstream.
_CONTROL_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WS_RX = re.compile(r"\s+")


def parse_pdf(raw_bytes: bytes) -> list[ParsedBlock]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except PdfReadError as e:
        logger.warning("pypdf rejected file (%s) — returning empty blocks", e)
        return []
    except Exception as e:  # noqa: BLE001 — defensive guard
        logger.warning("pypdf unexpected error (%s) — returning empty blocks", e)
        return []

    blocks: list[ParsedBlock] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:  # noqa: BLE001
            logger.warning("pypdf page %d extract_text failed: %s", page_num, e)
            text = ""
        text = _CONTROL_RX.sub("", text)
        text = _WS_RX.sub(" ", text).strip()
        if not text:
            # Don't append — base.parse_document already filters empties,
            # but skipping here keeps block_index dense across real pages.
            continue
        blocks.append(
            ParsedBlock(
                block_index=len(blocks),
                text=text,
                page_number=page_num,
                section_path=None,
                metadata={"source_subtype": "pdf"},
            )
        )
    return blocks
