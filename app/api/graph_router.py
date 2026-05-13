"""Phase 3D — graph read API.

Endpoints (all org-scoped via `get_current_user`):

    GET  /entities                — paginated list with scope/type/q filters
    GET  /entities/{entity_id}    — detail: row + both-direction rels + recent mentions
    GET  /meetings/{meeting_id}/graph — debug/inspection: everything a meeting emitted

Tenant isolation contract (carried over from `/search` in Phase 2D):

- `scope_id` belonging to a sibling org returns 404, not "0 results".
- An `entity_id` from a sibling org returns 404.
- A `meeting_id` from a sibling org returns 404.

Access tracking (Phase 6 will read these):

- `/entities` and `/entities/{id}` bump `last_accessed_at` and
  `access_count` on the entities they return.
- `/meetings/{id}/graph` does NOT bump — it's a debug/admin view and we
  don't want it skewing the ranking signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.db_dependency import get_db
from app.db.models import (
    Category,
    Entity,
    EntityMention,
    Meeting,
    Relationship,
    RelationshipMention,
    Team,
)
from app.dependencies.auth import get_current_user
from app.schemas.graph_schema import (
    EntityDetail,
    EntityHit,
    EntityListResponse,
    EntityRef,
    MeetingGraphResponse,
    MeetingRelationshipEdge,
    MentionRef,
    RelationshipDetail,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(tags=["Graph"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_scope(
    db: Session, user, scope: Optional[str], scope_id: Optional[int]
) -> None:
    """If a scope filter is supplied, prove the scope_id belongs to the
    requesting user's org. 404 on mismatch — never leak existence."""
    if scope is None:
        return
    if scope == "global":
        if scope_id is not None:
            raise HTTPException(
                status_code=422,
                detail="scope_id must be null when scope='global'",
            )
        return
    if scope_id is None:
        raise HTTPException(
            status_code=422,
            detail=f"scope_id is required when scope='{scope}'",
        )
    if scope == "category":
        row = db.execute(
            select(Category.id).where(
                Category.id == scope_id,
                Category.organization_id == user.organization_id,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Category not found")
    elif scope == "team":
        row = db.execute(
            select(Team.id)
            .join(Category, Team.category_id == Category.id)
            .where(
                Team.id == scope_id,
                Category.organization_id == user.organization_id,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Team not found")


def _entity_to_hit(e: Entity) -> EntityHit:
    """ORM -> Pydantic for the list/detail surfaces. Pulling this into a
    helper because pydantic's `from_attributes` mode can't reliably
    coerce `aliases=None` to `[]` or `attributes=None` to `{}`."""
    return EntityHit(
        id=e.id,
        entity_type=e.entity_type,
        name=e.name,
        canonical_name=e.canonical_name,
        scope_type=e.scope_type,
        scope_id=e.scope_id,
        source_type=e.source_type,
        description=e.description,
        aliases=list(e.aliases or []),
        attributes=dict(e.attributes or {}),
        importance_score=e.importance_score,
        confidence_score=e.confidence_score,
        knowledge_version=e.knowledge_version,
        created_from_meeting_id=e.created_from_meeting_id,
        last_accessed_at=e.last_accessed_at,
        access_count=e.access_count,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _bump_access(db: Session, entity_ids: list) -> None:
    if not entity_ids:
        return
    now = datetime.now(timezone.utc)
    db.query(Entity).filter(Entity.id.in_(entity_ids)).update(
        {
            Entity.last_accessed_at: now,
            Entity.access_count: Entity.access_count + 1,
        },
        synchronize_session=False,
    )
    db.commit()


# ---------------------------------------------------------------------------
# GET /entities — paginated list
# ---------------------------------------------------------------------------

@router.get("/entities", response_model=EntityListResponse)
def list_entities(
    scope: Optional[str] = Query(default=None, pattern="^(team|category|global)$"),
    scope_id: Optional[int] = Query(default=None),
    entity_type: Optional[str] = Query(
        default=None, pattern="^(person|project|topic|decision|commitment)$",
    ),
    q: Optional[str] = Query(default=None, min_length=1, max_length=200,
                             description="Substring match against name or canonical_name (case-insensitive)."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _validate_scope(db, user, scope, scope_id)

    where = [Entity.organization_id == user.organization_id]
    if entity_type is not None:
        where.append(Entity.entity_type == entity_type)
    if scope == "global":
        where.append(Entity.scope_type == "global")
        where.append(Entity.scope_id.is_(None))
    elif scope == "category":
        where.append(Entity.scope_type == "category")
        where.append(Entity.scope_id == scope_id)
    elif scope == "team":
        where.append(Entity.scope_type == "team")
        where.append(Entity.scope_id == scope_id)
    if q is not None:
        like = f"%{q.lower()}%"
        # canonical_name is already lowercased; `name` (display form) is
        # not — use ILIKE on both so a query like "Alice" still matches
        # an entity stored with display name "Alice Chen".
        where.append(or_(
            Entity.canonical_name.like(like),
            Entity.name.ilike(f"%{q}%"),
        ))

    total = db.execute(
        select(func.count(Entity.id)).where(and_(*where))
    ).scalar_one()

    rows: list[Entity] = db.execute(
        select(Entity)
        .where(and_(*where))
        .order_by(Entity.updated_at.desc(), Entity.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    items = [_entity_to_hit(e) for e in rows]
    _bump_access(db, [e.id for e in rows])

    logger.info(
        "list_entities(org=%s scope=%s type=%s q=%s): %d/%d",
        user.organization_id, scope, entity_type, q, len(items), total,
    )
    return EntityListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# GET /entities/{id} — detail with both-direction relationships + recent mentions
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}", response_model=EntityDetail)
def get_entity(
    entity_id: str,
    mentions_limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    entity: Optional[Entity] = db.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.organization_id == user.organization_id,
        )
    ).scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Outgoing: this entity is the subject.
    out_rels = db.execute(
        select(Relationship, Entity)
        .join(Entity, Relationship.object_entity_id == Entity.id)
        .where(
            Relationship.organization_id == user.organization_id,
            Relationship.subject_entity_id == entity.id,
        )
        .order_by(Relationship.updated_at.desc())
    ).all()

    # Incoming: this entity is the object.
    in_rels = db.execute(
        select(Relationship, Entity)
        .join(Entity, Relationship.subject_entity_id == Entity.id)
        .where(
            Relationship.organization_id == user.organization_id,
            Relationship.object_entity_id == entity.id,
        )
        .order_by(Relationship.updated_at.desc())
    ).all()

    relationships: list[RelationshipDetail] = []
    for rel, other in out_rels:
        relationships.append(RelationshipDetail(
            id=rel.id,
            predicate=rel.predicate,
            direction="outgoing",
            scope_type=rel.scope_type,
            scope_id=rel.scope_id,
            source_type=rel.source_type,
            attributes=dict(rel.attributes or {}),
            confidence_score=rel.confidence_score,
            knowledge_version=rel.knowledge_version,
            other_entity=EntityRef(
                id=other.id,
                entity_type=other.entity_type,
                name=other.name,
                canonical_name=other.canonical_name,
                scope_type=other.scope_type,
                scope_id=other.scope_id,
            ),
            created_at=rel.created_at,
            updated_at=rel.updated_at,
        ))
    for rel, other in in_rels:
        relationships.append(RelationshipDetail(
            id=rel.id,
            predicate=rel.predicate,
            direction="incoming",
            scope_type=rel.scope_type,
            scope_id=rel.scope_id,
            source_type=rel.source_type,
            attributes=dict(rel.attributes or {}),
            confidence_score=rel.confidence_score,
            knowledge_version=rel.knowledge_version,
            other_entity=EntityRef(
                id=other.id,
                entity_type=other.entity_type,
                name=other.name,
                canonical_name=other.canonical_name,
                scope_type=other.scope_type,
                scope_id=other.scope_id,
            ),
            created_at=rel.created_at,
            updated_at=rel.updated_at,
        ))

    # Recent mentions, newest first.
    mention_rows = db.execute(
        select(EntityMention, Meeting.title)
        .outerjoin(Meeting, EntityMention.source_meeting_id == Meeting.id)
        .where(EntityMention.entity_id == entity.id)
        .order_by(EntityMention.created_at.desc())
        .limit(mentions_limit)
    ).all()
    recent_mentions = [
        MentionRef(
            id=m.id,
            source_type=m.source_type,
            source_meeting_id=m.source_meeting_id,
            source_meeting_title=title,
            source_chunk_id=m.source_chunk_id,
            source_category_document_id=m.source_category_document_id,
            source_team_document_id=m.source_team_document_id,
            source_document_chunk_id=m.source_document_chunk_id,
            span=m.span,
            confidence=m.confidence,
            created_at=m.created_at,
        )
        for m, title in mention_rows
    ]

    # Build detail by extending the list-view payload.
    base = _entity_to_hit(entity)
    detail = EntityDetail(
        **base.model_dump(),
        relationships=relationships,
        recent_mentions=recent_mentions,
    )
    _bump_access(db, [entity.id])

    logger.info(
        "get_entity(org=%s id=%s): rels=%d mentions=%d",
        user.organization_id, entity.id, len(relationships), len(recent_mentions),
    )
    return detail


# ---------------------------------------------------------------------------
# GET /meetings/{id}/graph — everything emitted by a meeting
# ---------------------------------------------------------------------------

@router.get("/meetings/{meeting_id}/graph", response_model=MeetingGraphResponse)
def get_meeting_graph(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    meeting: Optional[Meeting] = db.execute(
        select(Meeting).where(
            Meeting.id == meeting_id,
            Meeting.organization_id == user.organization_id,
        )
    ).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")

    # Entities surfaced through any mention sourced from this meeting.
    entity_rows: list[Entity] = db.execute(
        select(Entity).where(
            Entity.organization_id == user.organization_id,
            Entity.id.in_(
                select(EntityMention.entity_id).where(
                    EntityMention.source_meeting_id == meeting_id,
                )
            ),
        ).order_by(Entity.updated_at.desc())
    ).scalars().all()

    # Relationships with a mention sourced from this meeting. We render
    # both endpoints so a node-link diagram needs no extra fetches.
    rel_rows = db.execute(
        select(Relationship).where(
            Relationship.organization_id == user.organization_id,
            Relationship.id.in_(
                select(RelationshipMention.relationship_id).where(
                    RelationshipMention.source_meeting_id == meeting_id,
                )
            ),
        )
    ).scalars().all()

    # Single batch fetch for relationship endpoint entities.
    endpoint_ids = set()
    for r in rel_rows:
        endpoint_ids.add(r.subject_entity_id)
        endpoint_ids.add(r.object_entity_id)
    endpoint_map: dict = {}
    if endpoint_ids:
        for e in db.execute(
            select(Entity).where(Entity.id.in_(endpoint_ids))
        ).scalars().all():
            endpoint_map[e.id] = e

    edges: list[MeetingRelationshipEdge] = []
    for r in rel_rows:
        subj = endpoint_map.get(r.subject_entity_id)
        obj = endpoint_map.get(r.object_entity_id)
        if subj is None or obj is None:
            continue  # endpoint was cascade-deleted between queries (unlikely)
        edges.append(MeetingRelationshipEdge(
            id=r.id,
            predicate=r.predicate,
            scope_type=r.scope_type,
            scope_id=r.scope_id,
            confidence_score=r.confidence_score,
            knowledge_version=r.knowledge_version,
            subject=EntityRef(
                id=subj.id, entity_type=subj.entity_type, name=subj.name,
                canonical_name=subj.canonical_name,
                scope_type=subj.scope_type, scope_id=subj.scope_id,
            ),
            object=EntityRef(
                id=obj.id, entity_type=obj.entity_type, name=obj.name,
                canonical_name=obj.canonical_name,
                scope_type=obj.scope_type, scope_id=obj.scope_id,
            ),
            attributes=dict(r.attributes or {}),
            created_at=r.created_at,
        ))

    entity_mention_rows = db.execute(
        select(EntityMention).where(
            EntityMention.source_meeting_id == meeting_id,
        ).order_by(EntityMention.created_at.desc())
    ).scalars().all()
    relationship_mention_rows = db.execute(
        select(RelationshipMention).where(
            RelationshipMention.source_meeting_id == meeting_id,
        ).order_by(RelationshipMention.created_at.desc())
    ).scalars().all()

    return MeetingGraphResponse(
        meeting_id=meeting.id,
        graph_status=meeting.graph_status,
        graph_extracted_at=meeting.graph_extracted_at,
        entities=[_entity_to_hit(e) for e in entity_rows],
        relationships=edges,
        entity_mentions=[
            MentionRef(
                id=m.id, source_type=m.source_type,
                source_meeting_id=m.source_meeting_id,
                source_chunk_id=m.source_chunk_id,
                source_category_document_id=m.source_category_document_id,
                source_team_document_id=m.source_team_document_id,
                source_document_chunk_id=m.source_document_chunk_id,
                span=m.span, confidence=m.confidence,
                created_at=m.created_at,
            )
            for m in entity_mention_rows
        ],
        relationship_mentions=[
            MentionRef(
                id=m.id, source_type=m.source_type,
                source_meeting_id=m.source_meeting_id,
                source_chunk_id=m.source_chunk_id,
                source_category_document_id=m.source_category_document_id,
                source_team_document_id=m.source_team_document_id,
                source_document_chunk_id=m.source_document_chunk_id,
                span=m.span, confidence=m.confidence,
                created_at=m.created_at,
            )
            for m in relationship_mention_rows
        ],
    )
