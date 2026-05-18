"""Phase 7E — playground / sandboxed RAG runner.

Sister to `app/services/rag/ask_pipeline.py` — mirrors its event
shape and pipeline order, but with three strict isolation rules:

  1. NEVER writes to `rag_query_runs`. Writes ONLY to
     `prompt_test_runs` (a separate observability surface).
  2. NEVER logs chunk-access events (Phase 6B). The importance
     signal must not be polluted by admin experimentation.
  3. NEVER touches `rag_conversations`. The playground is a
     stateless surface; conversation threading is for users.

The playground accepts EITHER:
  - A saved profile + (optional) inline overrides on top
  - A pure freeform `ResolvedAgentConfig` (built inline from the
    request body)

Either way we end up with a `ResolvedAgentConfig` in hand; the rest
of the pipeline is identical regardless of source.

Returns an iterator of event dicts in the same shape as
`ask_stream`. The HTTP layer wraps these in SSE bytes.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.models import PromptTestRun
from app.schemas.agent_schema import (
    ModelConfig, ModularPrompt, RetrievalConfig, ToolPermissions,
)
from app.schemas.rag_schema import (
    QueryPlan, RetrievalBundle, ScopeType, SourcesFilter, SynthesisResult,
)
from app.services.embedder import Embedder
from app.services.rag.query_planner import plan_query
from app.services.rag.retrieval import bundle_to_debug_dict, retrieve
from app.services.rag.synthesizer import (
    _build_resolved_prompt, _resolve_org_name, build_context_blocks,
    synthesize_stream,
)
from app.services.agents.resolver import (
    ResolvedAgentConfig, ResolutionStep, _canonical_hash, resolve_agent_runtime_config,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build a ResolvedAgentConfig from playground inputs.
# ---------------------------------------------------------------------------


def _materialize_overrides(
    base: ResolvedAgentConfig, overrides: Optional[dict],
) -> ResolvedAgentConfig:
    """Apply playground inline overrides on top of a saved bundle.
    Plays the same role as a virtual highest-priority resolver layer.

    `overrides` is a dict with possible keys:
      - modular_prompt: dict[str, str]      → per-section dict-merge
      - retrieval_config: dict              → per-key replace
      - model_config: dict                  → per-key replace
      - tool_permissions: {allowed, denied} → union
    """
    if not overrides:
        return base

    merged_modular = dict(base.modular_prompts)
    if isinstance(overrides.get("modular_prompt"), dict):
        for k, v in overrides["modular_prompt"].items():
            if k in ModularPrompt.section_keys():
                merged_modular[k] = v or ""

    retrieval = RetrievalConfig(**{
        k: getattr(base.retrieval_config, k)
        for k in (
            "top_k_vector", "top_k_final", "max_graph_depth",
            "tier_widen_threshold", "rerank_strategy", "sources_filter",
            "include_archived", "citation_strictness",
            "entity_expansion_enabled", "embedding_model",
        )
    })
    retrieval.importance_weight_overrides = dict(
        base.retrieval_config.importance_weight_overrides
    )
    if isinstance(overrides.get("retrieval_config"), dict):
        for k, v in overrides["retrieval_config"].items():
            if hasattr(retrieval, k) and k != "importance_weight_overrides":
                setattr(retrieval, k, v)
        iw = overrides["retrieval_config"].get("importance_weight_overrides")
        if isinstance(iw, dict):
            retrieval.importance_weight_overrides.update(iw)

    model_config = ModelConfig(**{
        k: getattr(base.model_config, k)
        for k in ("model", "temperature", "max_tokens", "response_format")
    })
    if isinstance(overrides.get("model_config"), dict):
        for k, v in overrides["model_config"].items():
            if hasattr(model_config, k):
                setattr(model_config, k, v)

    tool_permissions = ToolPermissions(
        allowed=sorted(set(base.tool_permissions.allowed) | set(
            (overrides.get("tool_permissions") or {}).get("allowed") or []
        )),
        denied=sorted(set(base.tool_permissions.denied) | set(
            (overrides.get("tool_permissions") or {}).get("denied") or []
        )),
    )

    path = list(base.resolution_path)
    path.append(ResolutionStep(
        layer="inline_override",
        fields_contributed=list((overrides.get("modular_prompt") or {}).keys()),
    ))

    return ResolvedAgentConfig(
        agent_profile_id=base.agent_profile_id,
        agent_type=base.agent_type,
        prompt_version_id=base.prompt_version_id,
        version_number=base.version_number,
        label=base.label,
        modular_prompts=merged_modular,
        variables_used=base.variables_used,
        retrieval_config=retrieval,
        model_config=model_config,
        tool_permissions=tool_permissions,
        resolution_path=path,
        config_hash=_canonical_hash(
            merged_modular, retrieval, model_config, tool_permissions,
        ),
        is_default_fallback=False,
        warnings=list(base.warnings),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _persist_test_run(
    db: Session, *, row: PromptTestRun,
) -> Optional[UUID]:
    """Insert one `prompt_test_runs` row. Mirrors the defensive
    pattern in `ask_pipeline._write_audit_row` — try once, retry on
    failure with reduced payload, never propagate the error."""
    try:
        db.add(row); db.commit(); db.refresh(row)
        return row.id
    except Exception as exc:
        db.rollback()
        logger.error(
            "playground: failed to persist test_run: %s", exc, exc_info=True,
        )
        try:
            reduced = PromptTestRun(
                organization_id=row.organization_id,
                query_text=row.query_text,
                assembled_prompt_text=row.assembled_prompt_text,
                status=row.status,
                error_message="audit row reduced after write error",
                created_by=row.created_by,
            )
            db.add(reduced); db.commit(); db.refresh(reduced)
            return reduced.id
        except Exception:
            db.rollback()
            return None


# ---------------------------------------------------------------------------
# Main entry point — SSE generator
# ---------------------------------------------------------------------------


def run_playground(
    db: Session,
    *,
    organization_id: UUID,
    actor_user_id: Optional[UUID],
    query_text: str,
    scope_type: Optional[ScopeType] = None,
    scope_id: Optional[int] = None,
    sources: SourcesFilter = "all",
    agent_profile_slug: Optional[str] = None,
    agent_profile_id: Optional[UUID] = None,
    inline_overrides: Optional[dict] = None,
    simulated_user_id: Optional[UUID] = None,
    embedder: Embedder | None = None,
) -> Iterator[dict]:
    """Run one sandboxed query against the org's real retrieval data.

    Strict isolation guarantees:
      - NO `rag_query_runs` write
      - NO chunk-access event logging (Phase 6B)
      - NO `rag_conversations.updated_at` bump
      - exactly one `prompt_test_runs` row written at `done`

    Yields the same event shape as `ask_stream`:
      plan → retrieved → token (×N) → citations → done

    On any failure (planner crash, retrieval crash, synth crash) the
    generator yields an `error` event then a `done` event with
    `status='failed'` and a `prompt_test_runs` row carrying
    `error_message`.
    """
    started_at = datetime.now(timezone.utc)
    t_total = time.monotonic()
    inline_overrides = inline_overrides or None

    # ---- 1. Resolve baseline config ----
    try:
        base_cfg = resolve_agent_runtime_config(
            db,
            organization_id=organization_id,
            agent_type="rag_synth",
            agent_profile_slug=agent_profile_slug,
            agent_profile_id=agent_profile_id,
            team_id=scope_id if scope_type == "team" else None,
            category_id=scope_id if scope_type == "category" else None,
            current_user_id=simulated_user_id,
        )
        cfg = _materialize_overrides(base_cfg, inline_overrides)
    except Exception as exc:
        logger.error("playground: resolver crashed: %s", exc, exc_info=True)
        yield {"event": "error", "data": {
            "message": "resolver failed", "detail": str(exc),
        }}
        _persist_test_run(db, row=PromptTestRun(
            organization_id=organization_id,
            agent_prompt_config_id=None, prompt_version_id=None,
            inline_overrides_json=inline_overrides,
            simulated_scope_type=scope_type, simulated_scope_id=scope_id,
            simulated_user_id=simulated_user_id,
            query_text=query_text, assembled_prompt_text="",
            status="failed", error_message=f"resolver: {exc}",
            total_duration_ms=int((time.monotonic() - t_total) * 1000),
            created_by=actor_user_id,
        ))
        yield {"event": "done", "data": {
            "status": "failed",
            "duration_ms": int((time.monotonic() - t_total) * 1000),
        }}
        return

    # ---- 2. Plan ----
    t_plan = time.monotonic()
    try:
        plan: QueryPlan = plan_query(
            db,
            organization_id=organization_id,
            query_text=query_text,
            requested_scope_type=scope_type,
            requested_scope_id=scope_id,
        )
    except Exception as exc:
        logger.error("playground: planner crashed: %s", exc, exc_info=True)
        yield {"event": "error", "data": {
            "message": "planner failed", "detail": str(exc),
        }}
        _persist_test_run(db, row=PromptTestRun(
            organization_id=organization_id,
            agent_prompt_config_id=None,
            prompt_version_id=cfg.prompt_version_id,
            inline_overrides_json=inline_overrides,
            simulated_scope_type=scope_type, simulated_scope_id=scope_id,
            simulated_user_id=simulated_user_id,
            query_text=query_text, assembled_prompt_text="",
            status="failed", error_message=f"planner: {exc}",
            planner_duration_ms=int((time.monotonic() - t_plan) * 1000),
            total_duration_ms=int((time.monotonic() - t_total) * 1000),
            created_by=actor_user_id,
        ))
        yield {"event": "done", "data": {
            "status": "failed",
            "duration_ms": int((time.monotonic() - t_total) * 1000),
        }}
        return
    planner_ms = int((time.monotonic() - t_plan) * 1000)

    yield {"event": "plan", "data": {
        "effective_scope_type": plan.effective_scope_type,
        "effective_scope_id": plan.effective_scope_id,
        "query_type": plan.query_type,
        "detected_entity_names": plan.detected_entity_names,
        "confidence": plan.confidence,
        "duration_ms": planner_ms,
    }}

    # ---- 3. Retrieve (real data; honors resolved retrieval_config) ----
    t_retr = time.monotonic()
    try:
        bundle: RetrievalBundle = retrieve(
            db, organization_id=organization_id,
            query_text=query_text, plan=plan, embedder=embedder,
            top_k_final=cfg.retrieval_config.top_k_final,
            sources=sources,
            rerank_strategy=cfg.retrieval_config.rerank_strategy,
        )
    except Exception as exc:
        logger.error("playground: retrieval crashed: %s", exc, exc_info=True)
        yield {"event": "error", "data": {
            "message": "retrieval failed", "detail": str(exc),
        }}
        _persist_test_run(db, row=PromptTestRun(
            organization_id=organization_id,
            agent_prompt_config_id=None,
            prompt_version_id=cfg.prompt_version_id,
            inline_overrides_json=inline_overrides,
            simulated_scope_type=scope_type, simulated_scope_id=scope_id,
            simulated_user_id=simulated_user_id,
            query_text=query_text, assembled_prompt_text="",
            status="failed", error_message=f"retrieval: {exc}",
            planner_duration_ms=planner_ms,
            retrieval_duration_ms=int((time.monotonic() - t_retr) * 1000),
            total_duration_ms=int((time.monotonic() - t_total) * 1000),
            created_by=actor_user_id,
        ))
        yield {"event": "done", "data": {
            "status": "failed",
            "duration_ms": int((time.monotonic() - t_total) * 1000),
        }}
        return
    retr_ms = int((time.monotonic() - t_retr) * 1000)

    yield {"event": "retrieved", "data": {
        "chunks": len(bundle.chunks),
        "entities": len(bundle.entities),
        "relationships": len(bundle.relationships),
        "has_context": bundle.has_context,
        "duration_ms": retr_ms,
    }}

    # ---- 4. Assemble the prompt that WILL be sent (for the preview) ----
    org_name = _resolve_org_name(db, organization_id)
    context_text, _ = build_context_blocks(bundle)
    if cfg.modular_prompts:
        assembled_prompt, _ = _build_resolved_prompt(
            resolved_config=cfg, org_name=org_name,
            context_blocks=context_text, query_text=query_text,
        )
    else:
        # Pure fallback path — same as legacy
        from app.services.rag.synthesizer import (
            _render_synth_prompt,
        )
        from app.ai_agents.prompts.rag import load_synth_prompt
        template = load_synth_prompt(settings.RAG_SYNTH_PROMPT_VERSION)
        assembled_prompt = _render_synth_prompt(
            template=template, org_name=org_name,
            query_text=query_text, context_blocks=context_text,
        )

    # ---- 5. Stream synthesis ----
    t_synth = time.monotonic()
    handle = synthesize_stream(
        db,
        organization_id=organization_id,
        query_text=query_text,
        bundle=bundle,
        resolved_config=cfg if cfg.modular_prompts else None,
    )
    for token in handle:
        yield {"event": "token", "data": {"text": token}}
    synth_result: SynthesisResult = handle.result
    synth_ms = int((time.monotonic() - t_synth) * 1000)

    citations_payload = [
        {
            "index": c.index, "chunk_id": str(c.chunk_id),
            "source_type": c.source_type,
            "meeting_id": c.meeting_id,
            "meeting_title": c.meeting_title,
            "document_id": str(c.document_id) if c.document_id else None,
            "document_name": c.document_name,
            "document_kind": c.document_kind,
            "page_number": c.page_number,
            "section_path": c.section_path,
        }
        for c in synth_result.citations
    ]
    yield {"event": "citations", "data": {
        "citations": citations_payload,
        "bundle_misses": synth_result.bundle_misses,
    }}

    # ---- 6. Determine status + persist (ONLY to prompt_test_runs) ----
    if synth_result.no_context:
        status = "no_context"
    elif synth_result.raw_response.get("error"):
        status = "failed"
    else:
        status = "completed"
    total_ms = int((time.monotonic() - t_total) * 1000)

    run_id = _persist_test_run(db, row=PromptTestRun(
        organization_id=organization_id,
        agent_prompt_config_id=None,  # set if request specified a config_id
        prompt_version_id=cfg.prompt_version_id,
        inline_overrides_json=inline_overrides,
        simulated_scope_type=scope_type,
        simulated_scope_id=scope_id,
        simulated_user_id=simulated_user_id,
        query_text=query_text,
        assembled_prompt_text=assembled_prompt,
        retrieval_bundle_json=bundle_to_debug_dict(bundle),
        answer_text=synth_result.answer_text,
        citations_json=citations_payload,
        input_tokens=synth_result.input_tokens,
        output_tokens=synth_result.output_tokens,
        planner_duration_ms=planner_ms,
        retrieval_duration_ms=retr_ms,
        synth_duration_ms=synth_ms,
        total_duration_ms=total_ms,
        status=status,
        error_message=synth_result.raw_response.get("error"),
        created_by=actor_user_id,
    ))

    # NOTE: No call to `log_chunk_events_batch`. No call to
    # `_touch_conversation`. The playground's isolation contract.

    yield {"event": "done", "data": {
        "run_id": str(run_id) if run_id else None,
        "status": status,
        "duration_ms": total_ms,
        "answer_text": synth_result.answer_text,
    }}
