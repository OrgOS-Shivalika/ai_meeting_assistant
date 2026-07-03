"""Phase 5D — end-to-end ask pipeline.

Composes the three Phase 5 services into one streaming generator:

    plan_query() -> retrieve() -> synthesize_stream() -> write_audit_row()

The generator yields SSE-shaped event dicts:

    {"event": "<name>", "data": {...}}

The HTTP layer (rag_router) wraps these in actual SSE bytes; ship tests
consume the dicts directly. Decoupling the event production from SSE
serialization lets us assert event sequence + payload shape without
parsing SSE in tests.

Event sequence on a normal run:

    plan        — {effective_scope_type, effective_scope_id, detected_entities}
    retrieved   — {chunks, entities, relationships, has_context}
    token       — {text}   (repeated)
    citations   — {citations: [...]}     (post-stream)
    done        — {run_id, status, duration_ms}

On a no-context run the `token` events still fire (one event with the
polite-decline text), but `citations` is empty and `status='no_context'`.

On a failure the sequence may terminate at any point with:

    error       — {message}
    done        — {run_id, status: 'failed', duration_ms}

The audit row is written in `done`. Even failures get a row — the API
layer never silently drops a query.
"""
from __future__ import annotations

import json
import logging
import time
import uuid as _uuid
from datetime import datetime, timezone
from typing import Iterator, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import RagConversation, RagQueryRun
from app.schemas.rag_schema import (
    QueryPlan, RagRunRecord, RetrievalBundle, ScopeType, SourcesFilter,
    SynthesisResult,
)
from app.services.embedder import Embedder
from app.services.rag.query_planner import plan_query
from app.services.rag.retrieval import bundle_to_debug_dict, retrieve
from app.services.rag.synthesizer import synthesize_stream

logger = logging.getLogger(__name__)


def _serialize_citations(result: SynthesisResult) -> list[dict]:
    """Flatten Citation dataclasses to dicts (UUIDs -> strings). The
    same shape is used for both the SSE `citations` event AND the audit
    row's `citations` JSONB column."""
    out = []
    for c in result.citations:
        out.append({
            "index": c.index,
            "chunk_id": str(c.chunk_id),
            "source_type": c.source_type,
            "meeting_id": c.meeting_id,
            "meeting_title": c.meeting_title,
            "document_id": str(c.document_id) if c.document_id else None,
            "document_name": c.document_name,
            "document_kind": c.document_kind,
            "page_number": c.page_number,
            "section_path": c.section_path,
        })
    return out


def _write_audit_row(
    db: Session, record: RagRunRecord,
) -> UUID:
    """Persist one `rag_query_runs` row. Returns the new row id.

    Wraps the commit in try/except so a misshapen JSONB blob never
    crashes the request — we'd rather degrade the audit log than fail
    the user's response."""
    row = RagQueryRun(
        organization_id=record.organization_id,
        user_id=record.user_id,
        conversation_id=record.conversation_id,
        query_text=record.query_text,
        requested_scope_type=record.requested_scope_type,
        requested_scope_id=record.requested_scope_id,
        effective_scope_type=record.effective_scope_type,
        effective_scope_id=record.effective_scope_id,
        planner_model=record.planner_model,
        planner_prompt_version=record.planner_prompt_version,
        synth_model=record.synth_model,
        synth_prompt_version=record.synth_prompt_version,
        retrieved_chunks=record.retrieved_chunks,
        retrieved_entities=record.retrieved_entities,
        retrieved_relationships=record.retrieved_relationships,
        planner_duration_ms=record.planner_duration_ms,
        retrieval_duration_ms=record.retrieval_duration_ms,
        synth_duration_ms=record.synth_duration_ms,
        total_duration_ms=record.total_duration_ms,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        status=record.status,
        answer_text=record.answer_text,
        citations=record.citations,
        retrieval_bundle=record.retrieval_bundle,
        error_message=record.error_message,
        rerank_strategy=record.rerank_strategy,
        agent_profile_id=record.agent_profile_id,
        prompt_version_id=record.prompt_version_id,
        resolution_path_hash=record.resolution_path_hash,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception as e:
        db.rollback()
        logger.error("ask_pipeline: failed to write audit row: %s", e, exc_info=True)
        # Fall back: try once more with citations/bundle dropped, in case
        # one of the JSONB payloads was the problem.
        try:
            row = RagQueryRun(
                organization_id=record.organization_id,
                user_id=record.user_id,
                conversation_id=record.conversation_id,
                query_text=record.query_text,
                status=record.status,
                started_at=record.started_at,
                completed_at=record.completed_at,
                error_message=(record.error_message or "audit row reduced after write error"),
            )
            db.add(row); db.commit(); db.refresh(row)
        except Exception:
            db.rollback()
            return _uuid.uuid4()  # synthetic id, returned to client; not in DB
    return row.id


def _touch_conversation(db: Session, conversation_id: UUID, query_text: str) -> None:
    """Bump `updated_at` and auto-title the conversation from its first
    query. Fire-and-forget: if it fails the run still completes."""
    try:
        conv = db.query(RagConversation).filter(
            RagConversation.id == conversation_id,
        ).first()
        if not conv:
            return
        if not conv.title:
            # Truncate to ~80 chars; the UI shortens further.
            conv.title = query_text.strip()[:200] or "Untitled chat"
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("ask_pipeline: failed to touch conversation %s: %s",
                       conversation_id, e)


def ask_stream(
    db: Session,
    *,
    organization_id: UUID,
    user_id: Optional[UUID],
    query_text: str,
    requested_scope_type: Optional[ScopeType] = None,
    requested_scope_id: Optional[int] = None,
    conversation_id: Optional[UUID] = None,
    sources: SourcesFilter = "all",
    top_k_final: Optional[int] = None,
    embedder: Embedder | None = None,
    rerank_strategy: Optional[str] = None,
    agent_profile_slug: Optional[str] = None,
    # Memory Phase 2 — pre-formatted live-meeting state block. /rag/ask-live
    # passes this when the meeting is in-progress; the synthesizer renders
    # it ABOVE prior_facts + chunks. Empty string for completed meetings.
    live_state_block: str = "",
    # Memory Phase 3 — pre-formatted long-term memory block: recent
    # meeting summaries + tasks in scope. /rag/ask-live builds this from
    # LongTermMemory and passes it; the synthesizer renders it BELOW
    # short-term facts and ABOVE chunks. Empty string skips rendering.
    long_term_block: str = "",
) -> Iterator[dict]:
    """Run plan -> retrieve -> stream synth -> audit. Yields event dicts.

    `embedder` is injectable so ship tests can use the canonical stub.
    The HTTP layer never passes it — production uses the lazy OpenAI
    client.

    Phase 7C SHADOW MODE: the resolver runs and its result is logged
    to `agent_runtime_logs` + back-referenced on `rag_query_runs`,
    but the synth still uses the filesystem prompts. 7D flips the
    consumption switch.
    """
    started_at = datetime.now(timezone.utc)
    t_total_start = time.monotonic()

    # -------- 0. Resolve runtime config (shadow mode) --------
    # Fire-and-forget: a resolver failure must never affect the user
    # response. Wrapped defensively. `resolved` is captured for the
    # audit-row back-references + the runtime-log insert, but NOT
    # used to drive prompts/retrieval in 7C.
    resolved = None
    try:
        from app.services.agents.resolver import (
            resolve_agent_runtime_config,
        )
        # Translate the request's scope into resolver inputs. Scope=team
        # gives team_id; scope=category gives category_id. Scope=global
        # leaves both None and the resolver uses only the
        # organization-scoped layer.
        team_id = (
            requested_scope_id if requested_scope_type == "team" else None
        )
        category_id = (
            requested_scope_id if requested_scope_type == "category" else None
        )
        resolved = resolve_agent_runtime_config(
            db,
            organization_id=organization_id,
            agent_type="rag_synth",
            agent_profile_slug=agent_profile_slug,
            team_id=team_id,
            category_id=category_id,
            current_user_id=user_id,
        )
    except Exception as exc:
        logger.warning("ask_stream: resolver failed in shadow mode: %s", exc)

    # -------- 1. Plan --------
    t_plan_start = time.monotonic()
    plan: QueryPlan
    try:
        plan = plan_query(
            db,
            organization_id=organization_id,
            query_text=query_text,
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
        )
    except Exception as e:
        logger.error("ask_stream: planner crashed: %s", e, exc_info=True)
        yield {"event": "error", "data": {"message": "planner failed", "detail": str(e)}}
        run_id = _write_audit_row(db, RagRunRecord(
            organization_id=organization_id, user_id=user_id,
            conversation_id=conversation_id, query_text=query_text,
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            effective_scope_type=None, effective_scope_id=None,
            planner_model=None, planner_prompt_version=None,
            synth_model=None, synth_prompt_version=None,
            retrieved_chunks=0, retrieved_entities=0, retrieved_relationships=0,
            planner_duration_ms=int((time.monotonic() - t_plan_start) * 1000),
            retrieval_duration_ms=None, synth_duration_ms=None,
            total_duration_ms=int((time.monotonic() - t_total_start) * 1000),
            input_tokens=None, output_tokens=None,
            status="failed", answer_text=None, citations=None,
            retrieval_bundle=None, error_message=f"planner: {e}",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
        ))
        yield {"event": "done", "data": {
            "run_id": str(run_id), "status": "failed",
            "duration_ms": int((time.monotonic() - t_total_start) * 1000),
        }}
        return
    planner_ms = int((time.monotonic() - t_plan_start) * 1000)

    yield {"event": "plan", "data": {
        "effective_scope_type": plan.effective_scope_type,
        "effective_scope_id": plan.effective_scope_id,
        "query_type": plan.query_type,
        "detected_entity_names": plan.detected_entity_names,
        "resolved_entity_count": len(plan.resolved_entity_ids),
        "confidence": plan.confidence,
        "duration_ms": planner_ms,
    }}

    # -------- 2. Retrieve --------
    t_retr_start = time.monotonic()
    bundle: RetrievalBundle
    try:
        bundle = retrieve(
            db, organization_id=organization_id,
            query_text=query_text, plan=plan, embedder=embedder,
            top_k_final=top_k_final, sources=sources,
            rerank_strategy=rerank_strategy,
        )
    except Exception as e:
        logger.error("ask_stream: retrieval crashed: %s", e, exc_info=True)
        yield {"event": "error", "data": {"message": "retrieval failed", "detail": str(e)}}
        run_id = _write_audit_row(db, RagRunRecord(
            organization_id=organization_id, user_id=user_id,
            conversation_id=conversation_id, query_text=query_text,
            requested_scope_type=requested_scope_type,
            requested_scope_id=requested_scope_id,
            effective_scope_type=plan.effective_scope_type,
            effective_scope_id=plan.effective_scope_id,
            planner_model=plan.model,
            planner_prompt_version=plan.prompt_version,
            synth_model=None, synth_prompt_version=None,
            retrieved_chunks=0, retrieved_entities=0, retrieved_relationships=0,
            planner_duration_ms=planner_ms,
            retrieval_duration_ms=int((time.monotonic() - t_retr_start) * 1000),
            synth_duration_ms=None,
            total_duration_ms=int((time.monotonic() - t_total_start) * 1000),
            input_tokens=None, output_tokens=None,
            status="failed", answer_text=None, citations=None,
            retrieval_bundle=None, error_message=f"retrieval: {e}",
            started_at=started_at, completed_at=datetime.now(timezone.utc),
        ))
        yield {"event": "done", "data": {
            "run_id": str(run_id), "status": "failed",
            "duration_ms": int((time.monotonic() - t_total_start) * 1000),
        }}
        return
    retr_ms = int((time.monotonic() - t_retr_start) * 1000)

    # Memory wire-in — distilled facts answer "who owns X?" / "what did we
    # decide about Y?" with one row instead of synthesizing across 5 chunks.
    # Facts go in a parallel bundle field (NOT citations) so the existing
    # citation validator is untouched. Synth prompt renders them ABOVE
    # chunks in the context. Wrapped non-fatal — a memory miss degrades
    # to pre-memory /ask behavior.
    try:
        from app.services.memory.access import MemoryAccess
        cat_id = (
            plan.effective_scope_id
            if plan.effective_scope_type == "category" else None
        )
        team_id = (
            plan.effective_scope_id
            if plan.effective_scope_type == "team" else None
        )
        bundle.prior_facts = MemoryAccess.search(
            db, organization_id=organization_id, query=query_text,
            category_id=cat_id, team_id=team_id, limit=5, bump=True,
        )
        if bundle.prior_facts:
            logger.info(
                "💭 Memory wire-in (/ask): injected %d facts (scope=%s/%s)",
                len(bundle.prior_facts), cat_id, team_id,
            )
    except Exception as exc:
        logger.warning("memory wire-in (/ask) skipped: %s", exc)
        if not hasattr(bundle, "prior_facts"):
            bundle.prior_facts = []

    # Memory Phase 2 — stamp the live-meeting state block (if any) onto
    # the bundle. /rag/ask-live passes this when the meeting is still
    # in-progress; for completed meetings (and /rag/ask) it's "" and the
    # synthesizer renders nothing. Also forces has_context=True so the
    # synth doesn't take its no-context fast path when live state is the
    # only signal we have.
    if live_state_block:
        bundle.live_state_block = live_state_block
        if not bundle.has_context:
            bundle.has_context = True
        logger.info(
            "💭 Memory wire-in (/ask): live state injected (%d chars)",
            len(live_state_block),
        )

    # Memory Phase 3 — long-term block from /rag/ask-live (recent meeting
    # summaries + tasks). Also force has_context so a query with only
    # long-term signal still gets synthesized instead of hitting the
    # no-context fast path.
    if long_term_block:
        bundle.long_term_block = long_term_block
        if not bundle.has_context:
            bundle.has_context = True
        logger.info(
            "💭 Memory wire-in (/ask): long-term injected (%d chars)",
            len(long_term_block),
        )

    yield {"event": "retrieved", "data": {
        "chunks": len(bundle.chunks),
        "entities": len(bundle.entities),
        "relationships": len(bundle.relationships),
        "has_context": bundle.has_context,
        "effective_scope_type": bundle.effective_scope_type,
        "effective_scope_id": bundle.effective_scope_id,
        "duration_ms": retr_ms,
    }}

    # -------- 3. Stream synthesis --------
    t_synth_start = time.monotonic()
    # Phase 7D — pass the resolved config to the synthesizer. The synth
    # picks the resolved-path (composer) when modular_prompts has
    # content; otherwise it stays on the legacy filesystem template.
    # `AGENT_RESOLVER_SHADOW_MODE=true` forces the legacy path even
    # when a resolved bundle is available — the kill switch for
    # rolling back consumption without a code change.
    synth_resolved = (
        resolved
        if (resolved is not None
            and not getattr(settings, "AGENT_RESOLVER_SHADOW_MODE", False))
        else None
    )
    handle = synthesize_stream(
        db, organization_id=organization_id,
        query_text=query_text, bundle=bundle,
        resolved_config=synth_resolved,
    )
    for token in handle:
        yield {"event": "token", "data": {"text": token}}
    synth_result: SynthesisResult = handle.result
    synth_ms = int((time.monotonic() - t_synth_start) * 1000)

    citations_payload = _serialize_citations(synth_result)
    yield {"event": "citations", "data": {
        "citations": citations_payload,
        "bundle_misses": synth_result.bundle_misses,
    }}

    # -------- 4. Determine final status --------
    if synth_result.no_context:
        status = "no_context"
    elif synth_result.raw_response.get("error"):
        status = "failed"
    else:
        status = "completed"

    # -------- 5. Write audit row + touch conversation --------
    total_ms = int((time.monotonic() - t_total_start) * 1000)
    record = RagRunRecord(
        organization_id=organization_id, user_id=user_id,
        conversation_id=conversation_id, query_text=query_text,
        requested_scope_type=requested_scope_type,
        requested_scope_id=requested_scope_id,
        effective_scope_type=bundle.effective_scope_type,
        effective_scope_id=bundle.effective_scope_id,
        planner_model=plan.model,
        planner_prompt_version=plan.prompt_version,
        synth_model=synth_result.model,
        synth_prompt_version=synth_result.prompt_version,
        retrieved_chunks=len(bundle.chunks),
        retrieved_entities=len(bundle.entities),
        retrieved_relationships=len(bundle.relationships),
        planner_duration_ms=planner_ms,
        retrieval_duration_ms=retr_ms,
        synth_duration_ms=synth_ms,
        total_duration_ms=total_ms,
        input_tokens=synth_result.input_tokens,
        output_tokens=synth_result.output_tokens,
        status=status,
        answer_text=synth_result.answer_text,
        citations=citations_payload,
        retrieval_bundle=bundle_to_debug_dict(bundle),
        error_message=synth_result.raw_response.get("error"),
        rerank_strategy=bundle.debug.get("rerank_strategy"),
        agent_profile_id=(resolved.agent_profile_id if resolved else None),
        prompt_version_id=(resolved.prompt_version_id if resolved else None),
        resolution_path_hash=(resolved.config_hash if resolved else None),
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )
    run_id = _write_audit_row(db, record)

    # Phase 7C — write the resolver's observability row, tied back to
    # the just-written audit row. Fire-and-forget: a log failure must
    # not affect the user's response.
    if resolved is not None:
        try:
            from app.services.agents.resolver import log_resolution
            log_resolution(
                db,
                organization_id=organization_id,
                resolved=resolved,
                rag_query_run_id=run_id,
                requested_scope_type=requested_scope_type,
                requested_scope_id=requested_scope_id,
            )
        except Exception as exc:
            logger.warning("ask_stream: log_resolution failed: %s", exc)

    if conversation_id is not None:
        _touch_conversation(db, conversation_id, query_text)

    # Phase 6B — log access events tied to this run. Both event types
    # reference run_id which only exists after the audit row is written.
    # Fire-and-forget; a logging failure cannot affect the `done` event.
    if bundle.chunks:
        try:
            from app.services.importance.access_log import log_chunk_events_batch
            log_chunk_events_batch(
                db,
                organization_id=organization_id,
                user_id=user_id,
                event_type="rag_retrieve",
                run_id=run_id,
                chunks=[(c.chunk_id, c.source_type, rank)
                        for rank, c in enumerate(bundle.chunks)],
            )
            # Cited chunks subset — only the ones the synth actually
            # cited get the 'rag_cited' flag, which is the stronger
            # signal for 6C's importance scorer.
            if synth_result.citations:
                cited_chunk_lookup = {
                    c.chunk_id: c.source_type for c in bundle.chunks
                }
                cited_rows = []
                for cit in synth_result.citations:
                    kind = cited_chunk_lookup.get(cit.chunk_id)
                    if kind:
                        cited_rows.append((cit.chunk_id, kind, cit.index))
                if cited_rows:
                    log_chunk_events_batch(
                        db,
                        organization_id=organization_id,
                        user_id=user_id,
                        event_type="rag_cited",
                        run_id=run_id,
                        chunks=cited_rows,
                    )
        except Exception as exc:
            logger.warning(
                "ask_pipeline: access event logging failed: %s", exc,
            )

    yield {"event": "done", "data": {
        "run_id": str(run_id),
        "status": status,
        "duration_ms": total_ms,
        "answer_text": synth_result.answer_text,
    }}


# ---------------------------------------------------------------------------
# SSE byte formatter — used by the HTTP layer in rag_router.
# ---------------------------------------------------------------------------

def event_to_sse_bytes(event: dict) -> bytes:
    """Render one event dict as an SSE message. Conforms to the spec
    that the API contract publishes."""
    name = event.get("event", "message")
    data = event.get("data", {})
    payload = json.dumps(data, default=str)
    return f"event: {name}\ndata: {payload}\n\n".encode("utf-8")
