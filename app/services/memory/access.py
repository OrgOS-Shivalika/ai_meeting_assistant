"""Phase M1 — read/write surface over org_memory_facts.

Single owner of the table. ALL other services route through here. Mirrors
the retrieval.py pattern (cosine_distance + scope filter + tenant guard)
but cheaper — no graph expansion, no rerank, no LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.db.models import Meeting, OrgMemoryFact
from app.services.embedder import Embedder

logger = logging.getLogger(__name__)

Window = Literal["short_term", "long_term", "all"]

# Tuning constants — module-level so they're greppable and trivially
# overridable in tests via monkeypatch.
SHORT_TERM_DAYS = 60
SIM_FLOOR = 0.30          # below this cosine sim, drop the row entirely
DEFAULT_LIMIT = 10


class MemoryAccess:
    """Static class — namespace, no state. Reuse one Session per request
    (the caller's). The class never opens/closes its own transaction."""

    # ------------------------------------------------------------------
    # READ — primary entry point
    # ------------------------------------------------------------------
    @staticmethod
    def search(
        db: Session,
        organization_id: UUID,
        query: str = "",
        *,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
        fact_types: Optional[Sequence[str]] = None,
        window: Window = "short_term",
        limit: int = DEFAULT_LIMIT,
        # Performance escape hatches
        qvec: Optional[list[float]] = None,
        embedder: Optional[Embedder] = None,
        # Side-effect control
        bump: bool = False,
        sim_floor: float = SIM_FLOOR,
    ) -> list[OrgMemoryFact]:
        """Retrieve up to `limit` active org_memory_facts ordered by cosine
        similarity to `query`. Scope-narrow with category_id/team_id.

        Algorithm:
          1. If query is non-empty: embed (or use provided qvec) and rank
             by cosine distance ascending.
             If query is empty:    rank by last_referenced_at descending.
          2. Filter: org_id + archive_status='active' + scope + fact_types + window.
          3. Drop rows with similarity < sim_floor (skip when window='all').
          4. If bump=True: bump_access() best-effort.

        Returns ORM objects — caller may read any column without re-query.
        NEVER raises on bump failure (logged + swallowed).
        """
        q = query.strip()
        stmt = select(OrgMemoryFact).where(
            OrgMemoryFact.organization_id == organization_id,
            OrgMemoryFact.archive_status == "active",
        )

        # --- scope filter ---
        if category_id is not None:
            stmt = stmt.where(OrgMemoryFact.category_id == category_id)
        if team_id is not None:
            stmt = stmt.where(OrgMemoryFact.team_id == team_id)

        # --- fact_type filter ---
        if fact_types:
            stmt = stmt.where(OrgMemoryFact.fact_type.in_(tuple(fact_types)))

        # --- temporal window ---
        if window == "short_term":
            cutoff = datetime.now(timezone.utc) - timedelta(days=SHORT_TERM_DAYS)
            stmt = stmt.where(OrgMemoryFact.last_referenced_at >= cutoff)
        # 'long_term' and 'all' are no-ops (we may add long_term=>>SHORT_TERM later)

        # --- ranking branch ---
        if q:
            if qvec is None:
                emb = embedder or Embedder()
                try:
                    qvec = emb.embed([q])[0]
                except Exception:
                    # Embedder unavailable -> degrade gracefully to ILIKE
                    logger.warning("MemoryAccess.search: embed failed, falling back to ILIKE", exc_info=True)
                    qvec = None

            if qvec is not None:
                distance = OrgMemoryFact.embedding.cosine_distance(qvec).label("distance")
                stmt = stmt.add_columns(distance).order_by(distance).limit(limit * 2)
                # Fetch 2x and apply sim_floor in Python — pgvector cannot
                # filter on distance + use the HNSW index in one shot.
                rows = db.execute(stmt).all()
                results: list[OrgMemoryFact] = []
                for row in rows:
                    fact = row[0]
                    dist = float(row.distance)
                    sim = max(0.0, 1.0 - dist)
                    if window != "all" and sim < sim_floor:
                        continue
                    results.append(fact)
                    if len(results) >= limit:
                        break
            else:
                # ILIKE fallback
                pattern = f"%{q}%"
                stmt = stmt.where(
                    or_(
                        OrgMemoryFact.fact.ilike(pattern),
                        OrgMemoryFact.subject.ilike(pattern),
                    )
                ).order_by(OrgMemoryFact.last_referenced_at.desc()).limit(limit)
                results = list(db.execute(stmt).scalars().all())
        else:
            # No query -> recency-sorted listing (observability page, master analyzer top-N)
            stmt = stmt.order_by(OrgMemoryFact.last_referenced_at.desc()).limit(limit)
            results = list(db.execute(stmt).scalars().all())

        if bump and results:
            MemoryAccess.bump_access(db, [f.id for f in results])

        return results

    # ------------------------------------------------------------------
    # READ — convenience wrappers
    # ------------------------------------------------------------------
    @staticmethod
    def search_for_meeting(
        db: Session, meeting_id: int, query: str, limit: int = DEFAULT_LIMIT,
        *, qvec: Optional[list[float]] = None, bump: bool = True,
    ) -> list[OrgMemoryFact]:
        """Auto-scope from the meeting's organization/category/team.

        Two queries: one to resolve scope (~1ms), one to search. We could
        JOIN through Meeting in the same SQL, but that requires a NOT NULL
        meeting_id, breaks the org-only org-wide path, and costs the
        HNSW-friendly query shape — not worth the savings.

        Defaults bump=True — this IS the real-user signal.
        """
        row = db.execute(
            select(Meeting.organization_id, Meeting.category_id, Meeting.team_id)
            .where(Meeting.id == meeting_id)
        ).first()
        if row is None:
            logger.warning("search_for_meeting: meeting %s not found", meeting_id)
            return []
        org_id, cat_id, team_id = row
        return MemoryAccess.search(
            db, org_id, query,
            category_id=cat_id, team_id=team_id,
            limit=limit, qvec=qvec, bump=bump,
        )

    @staticmethod
    def get_recent(
        db: Session, organization_id: UUID,
        *, category_id: Optional[int] = None, team_id: Optional[int] = None,
        fact_type: Optional[str] = None, limit: int = 20,
    ) -> list[OrgMemoryFact]:
        """Recency-sorted; used by distiller for the 'top-20 most recent
        for this scope' input window, and by the master-analyzer context
        builder. Never bumps — these are *context* reads, not consumption."""
        stmt = select(OrgMemoryFact).where(
            OrgMemoryFact.organization_id == organization_id,
            OrgMemoryFact.archive_status == "active",
        )
        if category_id is not None:
            stmt = stmt.where(OrgMemoryFact.category_id == category_id)
        if team_id is not None:
            stmt = stmt.where(OrgMemoryFact.team_id == team_id)
        if fact_type:
            stmt = stmt.where(OrgMemoryFact.fact_type == fact_type)
        stmt = stmt.order_by(OrgMemoryFact.last_referenced_at.desc()).limit(limit)
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_by_subject(
        db: Session, organization_id: UUID, subject: str,
    ) -> list[OrgMemoryFact]:
        """Exact (case-insensitive) subject match on the partial
        ix_memory_facts_subject_active index. Returns ALL matches ordered
        by last_referenced_at DESC. Used by the dedup loop in the distiller
        and by 'who owns X?' shortcut paths.

        Fuzzy match is INTENTIONALLY excluded — pg_trgm would force a new
        index and pollute results with adjacent strings. The distiller's
        cosine search already covers fuzzy semantics; this method is the
        cheap exact-hit shortcut."""
        s = (subject or "").strip().lower()
        if not s:
            return []
        stmt = (
            select(OrgMemoryFact)
            .where(
                OrgMemoryFact.organization_id == organization_id,
                OrgMemoryFact.archive_status == "active",
                func.lower(OrgMemoryFact.subject) == s,
            )
            .order_by(OrgMemoryFact.last_referenced_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # WRITE
    # ------------------------------------------------------------------
    @staticmethod
    def insert(
        db: Session,
        *,
        organization_id: UUID,
        fact: str,
        fact_type: str,
        category_id: Optional[int] = None,
        team_id: Optional[int] = None,
        subject: Optional[str] = None,
        source_meeting_id: Optional[int] = None,
        source_excerpt: Optional[str] = None,
        importance_score: float = 0.5,
        confidence_score: float = 0.7,
        embedding: Optional[list[float]] = None,
        embedding_model: Optional[str] = None,
        metadata_json: Optional[dict] = None,
        embedder: Optional[Embedder] = None,
    ) -> OrgMemoryFact:
        """Insert ONE fact. Caller owns flush/commit. If `embedding` is
        None, embed `fact` on the fly — convenient for tests; in the
        distiller hot path always pass a pre-computed vector to keep the
        batch (~10 facts in one HTTP call) intact."""
        if embedding is None:
            emb = embedder or Embedder()
            embedding = emb.embed([fact])[0]
            if embedding_model is None:
                embedding_model = "text-embedding-3-small"
        row = OrgMemoryFact(
            organization_id=organization_id,
            category_id=category_id,
            team_id=team_id,
            fact=fact,
            fact_type=fact_type,
            subject=subject,
            source_meeting_id=source_meeting_id,
            source_excerpt=source_excerpt,
            importance_score=importance_score,
            confidence_score=confidence_score,
            embedding=embedding,
            embedding_model=embedding_model,
            metadata_json=metadata_json,
            archive_status="active",
        )
        db.add(row)
        db.flush()   # populate row.id without committing
        return row

    @staticmethod
    def mark_archived(db: Session, fact_id: UUID) -> None:
        """Soft-archive. Row stays for audit/restoration but disappears
        from active search. Caller commits."""
        db.execute(
            update(OrgMemoryFact)
            .where(OrgMemoryFact.id == fact_id)
            .values(archive_status="archived",
                    updated_at=datetime.now(timezone.utc))
        )

    @staticmethod
    def mark_superseded(db: Session, old_id: UUID, new_id: UUID) -> None:
        """Two-step state — old fact becomes 'superseded' and points at
        the row that replaced it. Used by the distiller when a new fact
        clearly subsumes an older one (e.g., 'Sarah owns OAuth' -> 'Mike
        owns OAuth')."""
        db.execute(
            update(OrgMemoryFact)
            .where(OrgMemoryFact.id == old_id)
            .values(
                archive_status="superseded",
                superseded_by_id=new_id,
                updated_at=datetime.now(timezone.utc),
            )
        )

    # ------------------------------------------------------------------
    # WRITE — side-effect of read
    # ------------------------------------------------------------------
    @staticmethod
    def bump_access(db: Session, fact_ids: Sequence[UUID]) -> None:
        """Best-effort write of (last_referenced_at=now, access_count += 1).

        Wrapped in a SAVEPOINT so a failure here cannot poison the
        caller's transaction. The whole call is also try/except — under
        no circumstance does a read fail because the bump failed.

        DO NOT call this for observability/debug reads — it pollutes the
        recency signal that the improvement loop (Phase 3) and the
        master-analyzer recency rerank rely on."""
        if not fact_ids:
            return
        try:
            with db.begin_nested():
                db.execute(
                    update(OrgMemoryFact)
                    .where(OrgMemoryFact.id.in_(tuple(fact_ids)))
                    .values(
                        last_referenced_at=datetime.now(timezone.utc),
                        access_count=OrgMemoryFact.access_count + 1,
                    )
                )
        except Exception:
            logger.warning(
                "bump_access failed for %d facts (swallowed)", len(fact_ids),
                exc_info=True,
            )
