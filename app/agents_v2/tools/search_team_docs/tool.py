"""search_team_docs — pgvector search over team-scoped documents.

Inputs:
    {"query": "string", "k": int (default 5, max 20)}

Output:
    {"chunks": [
        {"text": "...", "document_name": "...", "document_id": "uuid",
         "page_number": 3, "section_path": "Chapter 2 › Onboarding",
         "score": 0.82}
    ]}

Scoping rules:
  - team_id required (from ToolContext).
  - organization_id enforced too — belt + suspenders in case a team
    id somehow crosses orgs.
  - Only returns chunks with `document_type='team'`.
  - Empty result when no docs match / team has no uploaded docs.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.agents_v2.shared.tool_context import ToolContext
from app.agents_v2.tools.base import Tool, register
from app.db.database import SessionLocal
from app.services.embedder import Embedder

logger = logging.getLogger(__name__)

_MAX_K = 20
_DEFAULT_K = 5


def _execute(inputs: dict, ctx: ToolContext) -> dict:
    query = (inputs or {}).get("query")
    if not query or not isinstance(query, str) or not query.strip():
        raise ValueError("search_team_docs: 'query' is required and must be a non-empty string")
    query = query.strip()

    k = int((inputs or {}).get("k") or _DEFAULT_K)
    k = max(1, min(k, _MAX_K))

    if ctx.team_id is None:
        # Tool is team-scoped by design; if the caller has no team,
        # return empty rather than fall back to org-wide (would be a
        # different tool: search_org_docs, not built yet).
        logger.info("search_team_docs: no team_id on context — returning empty")
        return {"chunks": []}

    # Embed the query.
    vector = Embedder().embed([query])[0]
    vector_literal = "[" + ",".join(str(v) for v in vector) + "]"

    db = SessionLocal()
    try:
        # Cosine distance via pgvector's <=> operator. Lower = closer.
        # We convert to a similarity score = 1 - distance for the caller.
        rows = db.execute(
            text("""
                SELECT
                    dc.id::text                            AS chunk_id,
                    dc.text                                AS chunk_text,
                    dc.page_number                         AS page_number,
                    dc.section_path                        AS section_path,
                    td.id::text                            AS document_id,
                    td.name                                AS document_name,
                    (dc.embedding <=> CAST(:qv AS vector)) AS distance
                FROM document_chunks dc
                JOIN team_documents td ON td.id = dc.team_document_id
                WHERE dc.document_type = 'team'
                  AND dc.team_id = :team_id
                  AND dc.organization_id = :org_id
                ORDER BY dc.embedding <=> CAST(:qv AS vector)
                LIMIT :k
            """),
            {"qv": vector_literal, "team_id": ctx.team_id,
             "org_id": str(ctx.organization_id), "k": k},
        ).mappings().all()
    finally:
        db.close()

    chunks = []
    for r in rows:
        score = 1.0 - float(r["distance"])
        chunks.append({
            "text": r["chunk_text"],
            "document_name": r["document_name"],
            "document_id": r["document_id"],
            "page_number": r["page_number"],
            "section_path": r["section_path"],
            "score": round(score, 4),
        })

    logger.info(
        "search_team_docs: team=%s query=%r → %d chunks",
        ctx.team_id, query[:60], len(chunks),
    )
    return {"chunks": chunks}


TOOL = register(Tool(
    id="search_team_docs",
    name="Search Team Documents",
    description="Semantic search over documents uploaded to the current team.",
    execute=_execute,
    scope="shared",
    side_effect="read",
    tags=["shared", "retrieval"],
))
