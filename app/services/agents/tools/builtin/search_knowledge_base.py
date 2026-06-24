"""search_knowledge_base — org-scoped meeting search.

Text-matches title + summary + transcript via ILIKE. Cheap and
predictable. Returns the most recent matching meetings.

ponytail: ILIKE not pgvector — for v1 the LLM mostly wants "find
recent meetings about X" and substring match handles 90% of that.
Swap to vector search via the existing RAG retriever when the harness
lands and we know query patterns.
"""
from __future__ import annotations

from sqlalchemy import or_

from app.db.models import Meeting
from app.services.agents.tools.registry import Tool, ToolContext, register


def handler(args: dict, ctx: ToolContext) -> dict:
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit", 5))
    limit = max(1, min(20, limit))
    if not query:
        return {"results": [], "count": 0, "query": ""}

    like = f"%{query}%"
    rows = (
        ctx.db.query(Meeting)
        .filter(Meeting.organization_id == ctx.organization_id)
        .filter(
            or_(
                Meeting.title.ilike(like),
                Meeting.summary.ilike(like),
                Meeting.transcript_text.ilike(like),
            )
        )
        .order_by(Meeting.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "query": query,
        "count": len(rows),
        "results": [
            {
                "meeting_id": m.id,
                "title": m.title,
                "summary": (m.summary or "")[:280],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in rows
        ],
    }


register(Tool(
    name="search_knowledge_base",
    description=(
        "Search this org's meetings by free-text query. Matches against "
        "title, summary, and transcript. Returns up to `limit` recent "
        "meetings. Use when looking for prior context on a topic."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search query."},
            "limit": {"type": "integer", "description": "Max meetings to return (1-20).", "default": 5},
        },
        "required": ["query"],
    },
    handler=handler,
    tags=["read", "search"],
))
