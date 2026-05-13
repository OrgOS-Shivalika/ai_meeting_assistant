"""Phase 4C — unified document ingestion worker.

The same parse + chunk + embed + persist pipeline runs against
`CategoryDocument` and `TeamDocument`. Rather than duplicating the body
across `document_tasks.py` and `team_document_tasks.py`, this module
holds the sync worker (`_ingest_document_sync`) and a small dispatch
helper. The two Celery wrappers become thin shells around it.

Design notes (mirrors `embedding_tasks._embed_meeting_sync`):

- **Decoupled lifecycle.** The doc's storage-level `status` (uploaded /
  ready / failed) is untouched here. We only mutate `embedding_status`,
  `embedded_at`, `chunk_count`, `total_tokens` — and later `graph_status`
  (Phase 4D). A parse / embed failure marks the doc `embedding_status=
  'failed'` with `error_message` set, without rolling back the upload.
- **External call first, then DB.** Storage download + parse + embed all
  happen before the wipe-and-insert transaction opens, so a flaky
  OpenAI call cannot leave half-inserted chunks behind.
- **Idempotent.** Re-running for the same doc deletes its existing
  `document_chunks` rows in the same transaction as the new insert. The
  partial-unique index on `(category_document_id, chunk_index)` (and
  the team variant) guarantees no partial inserts survive a crash.
- **Symmetry with meeting_chunks.** Knowledge-metadata defaults
  (`knowledge_version=1`, `access_count=0`) come from the schema; we
  don't set them here. Phase 6 reranking treats meeting and document
  chunks uniformly because their column shape is identical.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Literal, Union

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.database import SessionLocal
from app.db.models import CategoryDocument, DocumentChunk, TeamDocument
from app.parsers import parse_document, UnsupportedDocumentError
from app.services.document_chunker import DocumentChunker
from app.services.embedder import Embedder
from app.services.storage_service import storage, StorageNotConfigured
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

DocKind = Literal["category", "team"]
_DocRow = Union[CategoryDocument, TeamDocument]


def _load_doc(db: Session, doc_kind: DocKind, doc_id: str) -> _DocRow | None:
    if doc_kind == "category":
        return db.query(CategoryDocument).filter(CategoryDocument.id == doc_id).first()
    return db.query(TeamDocument).filter(TeamDocument.id == doc_id).first()


def _chunk_row_kwargs(doc_kind: DocKind, doc: _DocRow) -> dict:
    """Build the per-chunk FK + denormalized scope kwargs. Keeps the
    polymorphism out of the hot loop and lets the CHECK constraint do
    its job (only one of category_document_id / team_document_id will
    ever be set)."""
    if doc_kind == "category":
        return {
            "document_type": "category",
            "category_document_id": doc.id,
            "team_document_id": None,
            "category_id": doc.category_id,
            "team_id": None,
        }
    return {
        "document_type": "team",
        "category_document_id": None,
        "team_document_id": doc.id,
        "category_id": None,
        "team_id": doc.team_id,
    }


def _wipe_existing_chunks(db: Session, doc_kind: DocKind, doc: _DocRow) -> int:
    """Delete prior chunks for this doc. Returns the count of rows wiped
    so we can log it. Runs in the same transaction as the fresh insert."""
    q = db.query(DocumentChunk).filter(
        DocumentChunk.organization_id == doc.organization_id,
    )
    if doc_kind == "category":
        q = q.filter(DocumentChunk.category_document_id == doc.id)
    else:
        q = q.filter(DocumentChunk.team_document_id == doc.id)
    return q.delete(synchronize_session=False)


def _ingest_document_sync(
    db: Session,
    doc_kind: DocKind,
    doc_id: str,
    *,
    chunker: DocumentChunker | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """Parse + chunk + embed + persist a single doc.

    Caller owns the session lifecycle. Never re-raises — any failure
    flips the doc's `embedding_status` to `failed` and records
    `error_message` for the UI. Returns a stats dict.

    The `chunker` / `embedder` kwargs exist so tests (and the Phase 4F
    backfill CLI) can inject stubs and skip the OpenAI call.
    """
    doc = _load_doc(db, doc_kind, doc_id)
    if not doc:
        logger.error("ingest(%s, %s): document not found", doc_kind, doc_id)
        return {"status": "missing", "doc_kind": doc_kind, "doc_id": str(doc_id)}

    if not storage.is_configured:
        msg = "Document storage not configured on this worker."
        logger.error("ingest(%s, %s): %s", doc_kind, doc_id, msg)
        try:
            doc.embedding_status = "failed"
            doc.error_message = msg
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "failed", "doc_kind": doc_kind, "doc_id": str(doc_id), "error": msg}

    # Flip to processing first so observers see we picked it up.
    doc.embedding_status = "processing"
    doc.error_message = None
    db.commit()

    chunker = chunker or DocumentChunker()
    embedder = embedder or Embedder()
    started = time.monotonic()

    try:
        # 1. Download.
        raw_bytes = storage.download_bytes(doc.storage_key)
        if not raw_bytes:
            raise RuntimeError("Storage returned 0 bytes; object may be missing.")

        # 2. Parse. Unsupported types are deterministic failures — flag and bail.
        try:
            subtype, blocks = parse_document(
                raw_bytes,
                mime_type=doc.mime_type,
                original_filename=doc.original_filename,
            )
        except UnsupportedDocumentError as parser_err:
            raise RuntimeError(f"Unsupported document format: {parser_err}") from parser_err

        if not blocks:
            # Parser ran clean but produced nothing — most likely a scanned
            # PDF. Mark as `empty` so the UI shows a friendly hint instead
            # of a red `failed` badge.
            logger.info(
                "ingest(%s, %s): parser %s yielded 0 blocks — marking embedding_status=empty",
                doc_kind, doc_id, subtype,
            )
            doc.embedding_status = "empty"
            doc.embedded_at = datetime.now(timezone.utc)
            doc.chunk_count = 0
            doc.total_tokens = 0
            doc.error_message = "No extractable text — looks like a scanned or empty document."
            db.commit()
            return {
                "status": "empty",
                "doc_kind": doc_kind,
                "doc_id": str(doc_id),
                "subtype": subtype,
                "chunks": 0,
            }

        # 3. Chunk.
        chunks = chunker.chunk(blocks)
        if not chunks:
            # Almost-empty: blocks existed but every one fell below the
            # whitespace threshold. Same outcome as no-blocks.
            doc.embedding_status = "empty"
            doc.embedded_at = datetime.now(timezone.utc)
            doc.chunk_count = 0
            doc.total_tokens = 0
            db.commit()
            return {
                "status": "empty",
                "doc_kind": doc_kind,
                "doc_id": str(doc_id),
                "subtype": subtype,
                "chunks": 0,
            }

        # 4. Embed. Single external call — if it raises we never touched
        #    the chunks table.
        texts = [c.text for c in chunks]
        vectors = embedder.embed(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"ingest({doc_kind}, {doc_id}): vector/chunk count mismatch "
                f"({len(vectors)} vectors for {len(chunks)} chunks)"
            )

        # 5. Persist. Single transaction: wipe -> insert -> flip status.
        wiped = _wipe_existing_chunks(db, doc_kind, doc)
        if wiped:
            logger.info(
                "ingest(%s, %s): wiped %d pre-existing chunks before re-insert",
                doc_kind, doc_id, wiped,
            )

        fk_kwargs = _chunk_row_kwargs(doc_kind, doc)
        for chunk, vector in zip(chunks, vectors):
            # Stamp the doc subtype onto every chunk's metadata, even if
            # the chunker already merged a per-block hint — having
            # `source_subtype` on every row simplifies Phase 5 filters.
            chunk_meta = dict(chunk.metadata or {})
            chunk_meta.setdefault("source_subtype", subtype)
            db.add(
                DocumentChunk(
                    organization_id=doc.organization_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    section_path=chunk.section_path,
                    embedding=vector,
                    embedding_model=embedder.model,
                    metadata_json=chunk_meta,
                    **fk_kwargs,
                )
            )

        total_tokens = sum(c.token_count for c in chunks)
        doc.embedding_status = "embedded"
        doc.embedded_at = datetime.now(timezone.utc)
        doc.chunk_count = len(chunks)
        doc.total_tokens = total_tokens
        doc.error_message = None
        db.commit()

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "ingest(%s, %s): inserted %d chunks subtype=%s tokens=%d model=%s duration_ms=%d",
            doc_kind, doc_id, len(chunks), subtype, total_tokens,
            embedder.model, duration_ms,
        )

        # 6. Fan-out to graph extraction (Phase 4D). Best-effort — same
        #    contract as the meeting pipeline: a graph dispatch failure
        #    must never invalidate the embedding success we just committed.
        try:
            from app.celery_tasks.document_graph_tasks import (
                dispatch_extract_document_graph,
            )
            dispatch_extract_document_graph(doc_kind, str(doc_id))
        except ImportError:
            # Phase 4D not landed yet — leave graph_status='pending' and
            # the doc shows "Graph: queued" in the UI until 4D ships.
            logger.info(
                "ingest(%s, %s): graph extraction module not present yet "
                "(Phase 4D), leaving graph_status=pending",
                doc_kind, doc_id,
            )
        except Exception as graph_err:
            logger.error(
                "ingest(%s, %s): failed to dispatch graph extraction: %s",
                doc_kind, doc_id, graph_err,
            )

        return {
            "status": "embedded",
            "doc_kind": doc_kind,
            "doc_id": str(doc_id),
            "subtype": subtype,
            "chunks": len(chunks),
            "tokens": total_tokens,
            "model": embedder.model,
            "duration_ms": duration_ms,
        }

    except StorageNotConfigured as exc:
        return _record_failure(db, doc, "Storage not configured.", exc, started, doc_kind, doc_id)
    except Exception as exc:
        return _record_failure(db, doc, str(exc), exc, started, doc_kind, doc_id)


def _record_failure(
    db: Session, doc: _DocRow, message: str, exc: Exception,
    started: float, doc_kind: DocKind, doc_id: str,
) -> dict:
    db.rollback()
    try:
        doc.embedding_status = "failed"
        doc.error_message = message[:1000]
        db.commit()
    except Exception:
        db.rollback()
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.error(
        "ingest(%s, %s) failed after %dms: %s",
        doc_kind, doc_id, duration_ms, exc, exc_info=True,
    )
    return {
        "status": "failed",
        "doc_kind": doc_kind,
        "doc_id": str(doc_id),
        "error": message,
        "duration_ms": duration_ms,
    }


def dispatch_ingest_document(doc_kind: DocKind, doc_id: str) -> None:
    """Single dispatch entry. Picks Celery vs inline based on `USE_CELERY`,
    swallows its own errors so the caller never sees one."""
    try:
        if settings.USE_CELERY:
            if doc_kind == "category":
                from app.celery_tasks.document_tasks import process_document
                process_document.delay(doc_id)
            else:
                from app.celery_tasks.team_document_tasks import process_team_document
                process_team_document.delay(doc_id)
            logger.info(
                "ingest dispatch: queued %s document %s on Celery",
                doc_kind, doc_id,
            )
            return
        # Inline path — fresh session.
        db = SessionLocal()
        try:
            _ingest_document_sync(db, doc_kind, doc_id)
        finally:
            db.close()
    except Exception as exc:
        logger.error(
            "dispatch_ingest_document(%s, %s) crashed: %s",
            doc_kind, doc_id, exc, exc_info=True,
        )
