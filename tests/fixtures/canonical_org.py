"""Canonical fixture org — the reference dataset for Phase 5 retrieval.

Most weak RAG systems are tested with throwaway one-off fixtures, then
prompt-tuned against arbitrary data, and silently regress as soon as
real users hit them. This module produces a single deterministic
dataset that every Phase 5 test reuses:

  - 1 organization
  - 1 owner user (`alice@acme.ai`)
  - 2 categories (`Engineering`, `Sales`)
  - 3 teams (`Backend Team`, `Frontend Team`, `Enterprise Sales`)
  - 4 meetings with chunks + entities + relationships
  - 2 documents (one category-scoped PDF, one team-scoped DOCX), each
    with chunks + entities + relationships
  - Cross-source entity dedup: `Alice` appears in 3 meetings and 0 docs;
    `Helios` appears in 2 meetings and 1 doc — both should collapse to
    single entity rows after the pipeline writes them.

Two modes:

  - **stub (default)**: deterministic stub embeddings (hash-derived,
    1536-d, unit-norm) + hand-curated entities/relationships written
    directly to the tables. No OpenAI call. ~100 ms per build. Used by
    every ship test.
  - **real**: real `Embedder()` + real `extract_from_chunks(...)`
    pipeline. Slow + costs money. Used only by the 5F eval harness and
    occasional demos.

Topology designed to exercise:

  - Tightest-tier-wins scope routing (queries hit different tiers)
  - Cross-source entity dedup
  - 1-hop graph expansion (Alice -> leads -> Helios, Helios -> depends_on
    -> Phoenix)
  - Multi-source citations (same fact in a meeting AND a doc)
  - No-context guardrail (queries about entities that don't exist)
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import (
    Category, CategoryDocument, DocumentChunk, Entity, EntityMention,
    Meeting, MeetingChunk, Organization, Relationship, RelationshipMention,
    Team, TeamDocument, User,
)

logger = logging.getLogger(__name__)

Mode = Literal["stub", "real"]


# ---------------------------------------------------------------------------
# Deterministic stub embedder
# ---------------------------------------------------------------------------

def canonical_stub_embed(text_in: str, *, dims: int = 1536) -> list[float]:
    """Hash-derived deterministic embedding. Words shared between texts
    light up overlapping dimensions, so cosine similarity reflects token
    overlap (not semantic meaning, but that's fine for testing — the
    queries in 5F eval are designed to share vocabulary with the
    fixtures they target).

    Used by `build_canonical_org(mode='stub')` AND by `tests/test_phase5*.py`
    helpers that need a stable query vector aligned with the fixture.
    """
    out = [0.0] * dims
    words = re.findall(r"\w+", (text_in or "").lower())
    for w in words:
        if len(w) < 2:
            continue
        h = int(hashlib.sha256(w.encode()).hexdigest()[:16], 16)
        center = h % dims
        # Each word contributes a small Gaussian-shaped bump so adjacent
        # dimensions correlate weakly — gives slightly smoother cosine
        # behavior than a single-dim spike.
        for offset, weight in ((0, 1.0), (1, 0.55), (-1, 0.55), (2, 0.25), (-2, 0.25)):
            out[(center + offset) % dims] += weight
    norm = sum(x * x for x in out) ** 0.5 or 1.0
    return [x / norm for x in out]


# ---------------------------------------------------------------------------
# Returned fixture handle
# ---------------------------------------------------------------------------

@dataclass
class CanonicalFixture:
    """All ids the caller might need to write assertions against."""
    organization_id: uuid.UUID
    user_id: uuid.UUID

    # Scope hierarchy
    category_engineering_id: int
    category_sales_id: int
    team_backend_id: int
    team_frontend_id: int
    team_sales_id: int

    # Meetings + their chunks
    meeting_q3_planning_id: int
    meeting_design_review_id: int
    meeting_sales_pipeline_id: int
    meeting_backend_arch_id: int
    meeting_chunk_ids: dict[int, list[uuid.UUID]] = field(default_factory=dict)

    # Documents + their chunks
    cat_doc_sales_playbook_id: uuid.UUID | None = None
    team_doc_backend_arch_id: uuid.UUID | None = None
    doc_chunk_ids: dict[str, list[uuid.UUID]] = field(default_factory=dict)

    # Entities by canonical name (lookup helper for ship tests)
    entities_by_canonical: dict[str, uuid.UUID] = field(default_factory=dict)

    mode: Mode = "stub"


# ---------------------------------------------------------------------------
# Fixture content — small enough to read end-to-end, big enough to be
# realistic. Adjust here, not in the builder.
# ---------------------------------------------------------------------------

_MEETING_CHUNKS: dict[str, list[dict]] = {
    "q3_planning": [
        {
            "speakers": ["Alice", "Bob"],
            "text": "Alice: We need to lock the Helios timeline today. I'm proposing end of September for the OAuth2 rollout. "
                    "Bob: That works on the backend side. I'll own the migration plan.",
            "start": 0, "end": 120,
        },
        {
            "speakers": ["Alice"],
            "text": "Alice: Decision — Helios ships by September 30. OAuth2 is the auth path. Bob owns the migration. "
                    "We'll review weekly with the Backend Team.",
            "start": 120, "end": 240,
        },
    ],
    "design_review": [
        {
            "speakers": ["Carol", "Bob"],
            "text": "Carol: The Frontend Team is converging on the accessibility patterns. We've reviewed three component libraries. "
                    "Bob: Backend is ready to wire up the new auth flows once OAuth2 lands.",
            "start": 0, "end": 180,
        },
    ],
    "sales_pipeline": [
        {
            "speakers": ["David", "Alice"],
            "text": "David: NorthStar wants the enterprise tier. They're asking about SSO and custom retention. "
                    "Alice: That's an OAuth2 conversation. We can use Helios SSO once it ships.",
            "start": 0, "end": 180,
        },
        {
            "speakers": ["David"],
            "text": "David: I'll send NorthStar a proposal with the enterprise pricing tier. Target close in Q4.",
            "start": 180, "end": 280,
        },
    ],
    "backend_arch": [
        {
            "speakers": ["Alice", "Bob"],
            "text": "Alice: Helios architecture review. We're depending on Phoenix for the underlying event store. "
                    "Bob: Phoenix should be stable enough by then. I've benchmarked the throughput.",
            "start": 0, "end": 180,
        },
        {
            "speakers": ["Alice"],
            "text": "Alice: Decision — Helios depends on Phoenix. We'll coordinate the Phoenix v2 cutover with the Helios launch.",
            "start": 180, "end": 240,
        },
    ],
}


# Per-meeting graph: (entities_to_create, relationships).
# canonical_name lookups make the cross-meeting dedup automatic — second
# time we mention "Alice" the upsert finds the existing row.
_MEETING_GRAPH: dict[str, dict] = {
    "q3_planning": {
        "entities": [
            ("Alice", "person", "Engineering lead"),
            ("Bob", "person", "Backend engineer"),
            ("Helios", "project", "Authentication overhaul project"),
            ("OAuth2", "topic", "OAuth2 authentication protocol"),
            ("September 30 Helios ship date", "commitment", "Ship Helios by end of September"),
        ],
        "relationships": [
            ("Alice", "leads", "Helios"),
            ("Bob", "works_with", "Alice"),
            ("Bob", "owns", "Helios"),  # owns the migration
        ],
    },
    "design_review": {
        "entities": [
            ("Carol", "person", "Frontend lead"),
            ("Bob", "person", None),       # dedup with q3_planning's Bob
            ("Accessibility patterns", "topic", "WCAG-compliant UI patterns"),
        ],
        "relationships": [
            ("Carol", "leads", "Accessibility patterns"),
            ("Bob", "works_with", "Carol"),
        ],
    },
    "sales_pipeline": {
        "entities": [
            ("David", "person", "Enterprise sales"),
            ("Alice", "person", None),
            ("NorthStar", "project", "Enterprise customer account"),
            ("Enterprise tier", "topic", "Top-tier pricing plan"),
        ],
        "relationships": [
            ("David", "owns", "NorthStar"),
            ("David", "mentions", "Enterprise tier"),
        ],
    },
    "backend_arch": {
        "entities": [
            ("Alice", "person", None),
            ("Bob", "person", None),
            ("Helios", "project", None),
            ("Phoenix", "project", "Event store microservice"),
        ],
        "relationships": [
            ("Helios", "depends_on", "Phoenix"),
        ],
    },
}


_DOC_CHUNKS: dict[str, list[dict]] = {
    "sales_playbook": [
        {
            "text": "Enterprise tier pricing: starts at $24,000/year base plus per-seat. Includes SSO, audit logs, "
                    "and 90-day data retention. NorthStar is the lead reference account.",
            "page_number": 1,
            "section_path": "1. Pricing Tiers",
        },
        {
            "text": "Customer onboarding: dedicated SE for enterprise accounts. NorthStar onboarding kicked off Q2.",
            "page_number": 2,
            "section_path": "2. Onboarding",
        },
    ],
    "backend_arch": [
        {
            "text": "Helios authentication uses OAuth2 with token-bound sessions. The auth service depends on "
                    "Phoenix for the event store. PKCE flow for SPA clients.",
            "page_number": None,
            "section_path": "1. Authentication / Helios",
        },
        {
            "text": "Phoenix is the underlying event store. It exposes idempotent append + range-scan APIs. "
                    "Helios writes auth events here.",
            "page_number": None,
            "section_path": "2. Phoenix",
        },
    ],
}


_DOC_GRAPH: dict[str, dict] = {
    "sales_playbook": {
        "entities": [
            ("NorthStar", "project", None),
            ("Enterprise tier", "topic", None),
        ],
        "relationships": [
            ("NorthStar", "mentions", "Enterprise tier"),  # weak link, mostly for graph expansion
        ],
        "scope": ("category", "Sales"),
    },
    "backend_arch": {
        "entities": [
            ("Helios", "project", None),
            ("OAuth2", "topic", None),
            ("Phoenix", "project", None),
        ],
        "relationships": [
            ("Helios", "depends_on", "Phoenix"),  # confirms the meeting fact
        ],
        "scope": ("team", "Backend Team"),
    },
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _ensure_entity(
    db: Session, fixture: CanonicalFixture, *,
    scope_type: str, scope_id: int | None,
    name: str, entity_type: str, description: str | None,
    source_type: str,
) -> Entity:
    """Idempotent upsert by (org, scope, type, canonical_name). Mirrors the
    real `_upsert_entity` semantics from graph_tasks / document_graph_tasks
    so dedup behaves identically."""
    canonical = name.strip().lower()
    existing = db.query(Entity).filter(
        Entity.organization_id == fixture.organization_id,
        Entity.entity_type == entity_type,
        Entity.canonical_name == canonical,
        Entity.scope_type == scope_type,
        Entity.scope_id.is_(None) if scope_type == "global" else Entity.scope_id == scope_id,
    ).first()
    if existing:
        if description and not existing.description:
            existing.description = description
        existing.knowledge_version = (existing.knowledge_version or 1) + 1
        db.flush()
        return existing
    ent = Entity(
        organization_id=fixture.organization_id,
        scope_type=scope_type,
        scope_id=None if scope_type == "global" else scope_id,
        source_type=source_type,
        entity_type=entity_type,
        name=name.strip(),
        canonical_name=canonical,
        description=description,
        confidence_score=0.85,
        knowledge_version=1,
    )
    db.add(ent)
    db.flush()
    fixture.entities_by_canonical[canonical] = ent.id
    return ent


def _ensure_relationship(
    db: Session, fixture: CanonicalFixture, *,
    scope_type: str, scope_id: int | None,
    subject: Entity, predicate: str, obj: Entity,
    source_type: str,
) -> Relationship:
    existing = db.query(Relationship).filter(
        Relationship.organization_id == fixture.organization_id,
        Relationship.scope_type == scope_type,
        Relationship.scope_id.is_(None) if scope_type == "global" else Relationship.scope_id == scope_id,
        Relationship.subject_entity_id == subject.id,
        Relationship.predicate == predicate,
        Relationship.object_entity_id == obj.id,
    ).first()
    if existing:
        existing.knowledge_version = (existing.knowledge_version or 1) + 1
        db.flush()
        return existing
    rel = Relationship(
        organization_id=fixture.organization_id,
        scope_type=scope_type,
        scope_id=None if scope_type == "global" else scope_id,
        source_type=source_type,
        subject_entity_id=subject.id,
        predicate=predicate,
        object_entity_id=obj.id,
        confidence_score=0.8,
        knowledge_version=1,
    )
    db.add(rel)
    db.flush()
    return rel


def _embed_for_mode(text_in: str, mode: Mode) -> list[float]:
    if mode == "stub":
        return canonical_stub_embed(text_in)
    # Lazy import so stub-mode doesn't require OPEN_API_KEY.
    from app.services.embedder import Embedder
    return Embedder().embed([text_in])[0]


def _meeting_scope(team_id: int | None, category_id: int | None) -> tuple[str, int | None]:
    """Tightest-tier-wins scope routing for entities/relationships
    attached to a meeting. Matches `graph_tasks._scope_for`."""
    if team_id is not None:
        return "team", team_id
    if category_id is not None:
        return "category", category_id
    return "global", None


def build_canonical_org(
    db: Session,
    *,
    mode: Mode = "stub",
    embedding_model: str | None = None,
) -> CanonicalFixture:
    """Materialize the canonical org. Returns a `CanonicalFixture` with
    every id the caller might assert on.

    Idempotent at the entity-dedup level but NOT at the org level — calling
    twice produces two orgs. Use `cleanup_canonical_org` between runs.
    """
    model_name = embedding_model or ("stub-canonical" if mode == "stub" else "text-embedding-3-small")

    # --- Org / user / categories / teams ----------------------------------
    org = Organization(name=f"Acme AI ({mode})")
    db.add(org); db.commit(); db.refresh(org)

    user = User(
        name="Alice Park",
        email=f"alice-{uuid.uuid4()}@acme.ai",
        password="x",
        organization_id=org.id,
    )
    db.add(user); db.commit(); db.refresh(user)

    cat_eng = Category(name="Engineering", organization_id=org.id, user_id=user.id, color="#4F46E5")
    cat_sales = Category(name="Sales", organization_id=org.id, user_id=user.id, color="#10B981")
    db.add_all([cat_eng, cat_sales]); db.commit()
    db.refresh(cat_eng); db.refresh(cat_sales)

    team_backend = Team(name="Backend Team", category_id=cat_eng.id)
    team_frontend = Team(name="Frontend Team", category_id=cat_eng.id)
    team_sales = Team(name="Enterprise Sales", category_id=cat_sales.id)
    db.add_all([team_backend, team_frontend, team_sales]); db.commit()
    for t in (team_backend, team_frontend, team_sales):
        db.refresh(t)

    fixture = CanonicalFixture(
        organization_id=org.id,
        user_id=user.id,
        category_engineering_id=cat_eng.id,
        category_sales_id=cat_sales.id,
        team_backend_id=team_backend.id,
        team_frontend_id=team_frontend.id,
        team_sales_id=team_sales.id,
        meeting_q3_planning_id=0,
        meeting_design_review_id=0,
        meeting_sales_pipeline_id=0,
        meeting_backend_arch_id=0,
        mode=mode,
    )

    team_by_name = {
        "Backend Team": team_backend.id,
        "Frontend Team": team_frontend.id,
        "Enterprise Sales": team_sales.id,
    }
    cat_by_name = {"Engineering": cat_eng.id, "Sales": cat_sales.id}

    # --- Meetings ---------------------------------------------------------
    meeting_specs = [
        ("q3_planning", "Q3 Planning Sync", team_backend.id, cat_eng.id),
        ("design_review", "Frontend Design Review", team_frontend.id, cat_eng.id),
        ("sales_pipeline", "Enterprise Pipeline Q3", None, cat_sales.id),
        ("backend_arch", "Backend Architecture Review", team_backend.id, cat_eng.id),
    ]
    meeting_ids: dict[str, int] = {}
    for slug, title, team_id, category_id in meeting_specs:
        m = Meeting(
            meeting_url=f"https://example.com/canonical/{slug}-{uuid.uuid4().hex[:8]}",
            title=title,
            organization_id=org.id, user_id=user.id,
            category_id=category_id, team_id=team_id,
            status="completed",
            scheduled_at=datetime.now(timezone.utc),
            embedding_status="embedded",
            embedded_at=datetime.now(timezone.utc),
            graph_status="extracted",
            graph_extracted_at=datetime.now(timezone.utc),
            transcript_raw=[{
                "participant": {"name": spk},
                "words": [{"text": ch["text"]}],
            } for ch in _MEETING_CHUNKS[slug] for spk in ch["speakers"]],
        )
        db.add(m); db.commit(); db.refresh(m)
        meeting_ids[slug] = m.id

        # Insert chunks
        chunk_ids: list[uuid.UUID] = []
        for idx, ch in enumerate(_MEETING_CHUNKS[slug]):
            mc = MeetingChunk(
                organization_id=org.id,
                meeting_id=m.id,
                category_id=category_id,
                team_id=team_id,
                chunk_index=idx,
                text=ch["text"],
                token_count=len(ch["text"].split()),
                speakers=ch["speakers"],
                start_timestamp=ch["start"],
                end_timestamp=ch["end"],
                embedding=_embed_for_mode(ch["text"], mode),
                embedding_model=model_name,
                created_from_meeting_id=m.id,
            )
            db.add(mc); db.flush()
            chunk_ids.append(mc.id)
        db.commit()
        fixture.meeting_chunk_ids[m.id] = chunk_ids

        # Insert entities + relationships for this meeting
        graph = _MEETING_GRAPH[slug]
        scope_type, scope_id = _meeting_scope(team_id, category_id)
        ents_by_name: dict[str, Entity] = {}
        for name, etype, desc in graph["entities"]:
            ent = _ensure_entity(
                db, fixture,
                scope_type=scope_type, scope_id=scope_id,
                name=name, entity_type=etype, description=desc,
                source_type="meeting",
            )
            ents_by_name[name] = ent
            # One mention per first-chunk-of-meeting (mirrors the per-batch
            # representative-chunk convention in graph_tasks).
            db.add(EntityMention(
                organization_id=org.id,
                entity_id=ent.id,
                source_type="meeting",
                source_meeting_id=m.id,
                source_chunk_id=chunk_ids[0],
                confidence=0.85,
            ))
        for subj_name, predicate, obj_name in graph["relationships"]:
            subj = ents_by_name[subj_name]
            obj = ents_by_name[obj_name]
            rel = _ensure_relationship(
                db, fixture,
                scope_type=scope_type, scope_id=scope_id,
                subject=subj, predicate=predicate, obj=obj,
                source_type="meeting",
            )
            db.add(RelationshipMention(
                organization_id=org.id,
                relationship_id=rel.id,
                source_type="meeting",
                source_meeting_id=m.id,
                source_chunk_id=chunk_ids[0],
                confidence=0.8,
            ))
        db.commit()

    fixture.meeting_q3_planning_id = meeting_ids["q3_planning"]
    fixture.meeting_design_review_id = meeting_ids["design_review"]
    fixture.meeting_sales_pipeline_id = meeting_ids["sales_pipeline"]
    fixture.meeting_backend_arch_id = meeting_ids["backend_arch"]

    # --- Documents --------------------------------------------------------
    # Category-scoped: Sales Playbook (PDF)
    cat_doc = CategoryDocument(
        organization_id=org.id,
        category_id=cat_sales.id,
        uploaded_by_user_id=user.id,
        name="Sales Playbook.pdf",
        original_filename="Sales Playbook.pdf",
        mime_type="application/pdf",
        size_bytes=12345,
        storage_key=f"canonical/sales-playbook-{uuid.uuid4().hex[:8]}.pdf",
        status="uploaded",
        embedding_status="embedded",
        embedded_at=datetime.now(timezone.utc),
        graph_status="extracted",
        graph_extracted_at=datetime.now(timezone.utc),
        chunk_count=len(_DOC_CHUNKS["sales_playbook"]),
        total_tokens=sum(len(c["text"].split()) for c in _DOC_CHUNKS["sales_playbook"]),
    )
    db.add(cat_doc); db.commit(); db.refresh(cat_doc)
    fixture.cat_doc_sales_playbook_id = cat_doc.id
    cat_doc_chunk_ids: list[uuid.UUID] = []
    for idx, ch in enumerate(_DOC_CHUNKS["sales_playbook"]):
        dc = DocumentChunk(
            organization_id=org.id,
            document_type="category",
            category_document_id=cat_doc.id,
            category_id=cat_sales.id,
            chunk_index=idx,
            text=ch["text"],
            token_count=len(ch["text"].split()),
            page_number=ch["page_number"],
            section_path=ch["section_path"],
            embedding=_embed_for_mode(ch["text"], mode),
            embedding_model=model_name,
            metadata_json={"source_subtype": "pdf"},
        )
        db.add(dc); db.flush()
        cat_doc_chunk_ids.append(dc.id)
    db.commit()
    fixture.doc_chunk_ids["sales_playbook"] = cat_doc_chunk_ids

    # Team-scoped: Backend Architecture (DOCX)
    team_doc = TeamDocument(
        organization_id=org.id,
        team_id=team_backend.id,
        uploaded_by_user_id=user.id,
        name="Backend Architecture.docx",
        original_filename="Backend Architecture.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=23456,
        storage_key=f"canonical/backend-arch-{uuid.uuid4().hex[:8]}.docx",
        status="uploaded",
        embedding_status="embedded",
        embedded_at=datetime.now(timezone.utc),
        graph_status="extracted",
        graph_extracted_at=datetime.now(timezone.utc),
        chunk_count=len(_DOC_CHUNKS["backend_arch"]),
        total_tokens=sum(len(c["text"].split()) for c in _DOC_CHUNKS["backend_arch"]),
    )
    db.add(team_doc); db.commit(); db.refresh(team_doc)
    fixture.team_doc_backend_arch_id = team_doc.id
    team_doc_chunk_ids: list[uuid.UUID] = []
    for idx, ch in enumerate(_DOC_CHUNKS["backend_arch"]):
        dc = DocumentChunk(
            organization_id=org.id,
            document_type="team",
            team_document_id=team_doc.id,
            team_id=team_backend.id,
            chunk_index=idx,
            text=ch["text"],
            token_count=len(ch["text"].split()),
            page_number=ch["page_number"],
            section_path=ch["section_path"],
            embedding=_embed_for_mode(ch["text"], mode),
            embedding_model=model_name,
            metadata_json={"source_subtype": "docx"},
        )
        db.add(dc); db.flush()
        team_doc_chunk_ids.append(dc.id)
    db.commit()
    fixture.doc_chunk_ids["backend_arch"] = team_doc_chunk_ids

    # --- Document entities + relationships --------------------------------
    for doc_slug, graph in _DOC_GRAPH.items():
        scope_type, scope_name = graph["scope"]
        scope_id = (
            team_by_name[scope_name] if scope_type == "team"
            else cat_by_name[scope_name]
        )
        is_cat = doc_slug == "sales_playbook"
        doc_id = cat_doc.id if is_cat else team_doc.id
        doc_chunk_ids = cat_doc_chunk_ids if is_cat else team_doc_chunk_ids

        ents_by_name: dict[str, Entity] = {}
        for name, etype, desc in graph["entities"]:
            ent = _ensure_entity(
                db, fixture,
                scope_type=scope_type, scope_id=scope_id,
                name=name, entity_type=etype, description=desc,
                source_type="document",
            )
            ents_by_name[name] = ent
            db.add(EntityMention(
                organization_id=org.id,
                entity_id=ent.id,
                source_type="document",
                source_category_document_id=doc_id if is_cat else None,
                source_team_document_id=doc_id if not is_cat else None,
                source_document_chunk_id=doc_chunk_ids[0],
                confidence=0.85,
            ))
        for subj_name, predicate, obj_name in graph["relationships"]:
            subj = ents_by_name[subj_name]
            obj = ents_by_name[obj_name]
            rel = _ensure_relationship(
                db, fixture,
                scope_type=scope_type, scope_id=scope_id,
                subject=subj, predicate=predicate, obj=obj,
                source_type="document",
            )
            db.add(RelationshipMention(
                organization_id=org.id,
                relationship_id=rel.id,
                source_type="document",
                source_category_document_id=doc_id if is_cat else None,
                source_team_document_id=doc_id if not is_cat else None,
                source_document_chunk_id=doc_chunk_ids[0],
                confidence=0.8,
            ))
        db.commit()

    logger.info(
        "canonical fixture built: org=%s mode=%s meetings=4 docs=2 entities=%d",
        org.id, mode, db.query(Entity).filter(Entity.organization_id == org.id).count(),
    )
    return fixture


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _table_exists(db: Session, table_name: str) -> bool:
    return bool(db.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
        {"n": table_name},
    ).first())


def cleanup_canonical_org(db: Session, fixture: CanonicalFixture) -> None:
    """Wipe everything the fixture wrote. Order matters — drop dependents
    before parents to keep cascade FKs happy.

    Tolerant of pre-5A schema state: the rag_* tables only exist after
    the Phase 5A migration lands, so we probe before deleting. This lets
    the fixture (and its tests) run cleanly during the 5A development
    loop and against fresh databases that don't yet have the migration.
    """
    org_id = fixture.organization_id
    if _table_exists(db, "rag_query_runs"):
        db.execute(text("DELETE FROM rag_query_runs WHERE organization_id = :o"), {"o": org_id})
    if _table_exists(db, "rag_conversations"):
        db.execute(text("DELETE FROM rag_conversations WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM graph_extraction_runs WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM relationship_mentions WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM entity_mentions WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM relationships WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM entities WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM document_chunks WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM team_documents WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM category_documents WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM meeting_chunks WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM meetings WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM teams WHERE category_id IN (SELECT id FROM categories WHERE organization_id = :o)"), {"o": org_id})
    db.execute(text("DELETE FROM categories WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM users WHERE organization_id = :o"), {"o": org_id})
    db.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org_id})
    db.commit()
