from sqlalchemy import (
    BigInteger, Boolean, Column, Date, String, Integer, ForeignKey, DateTime,
    Text, UniqueConstraint, Float, CheckConstraint, Index, text,
)
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID, ARRAY
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector
from .database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True)
    meeting_url = Column(String, nullable=False)
    bot_id = Column(String, nullable=True)

    status = Column(String, default="pending")
    summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    transcript_raw = Column(JSON)      # full Recall response
    transcript_text = Column(Text)     # formatted version
    transcript = Column(Text, nullable=True) # live transcript lines

    # Lifecycle / scheduling metadata (Meeting Types feature)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    meeting_platform = Column(String, nullable=True)  # google_meet | zoom | teams | webex

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    user = relationship("User", back_populates="meetings")

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization = relationship("Organization", back_populates="meetings")

    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    category = relationship("Category", back_populates="meetings")
    team = relationship("Team", back_populates="meetings")

    tasks = relationship("Task", back_populates="meeting", cascade="all, delete-orphan")
    participants = relationship("Participant", back_populates="meeting", cascade="all, delete-orphan")

    # Phase 2 vector memory: every completed meeting becomes a sequence of
    # embedded chunks. `embedding_status` lets the embedding pipeline run
    # independently of the main meeting lifecycle, so an embedding failure
    # doesn't roll back the meeting itself.
    embedding_status = Column(String, nullable=False, default="pending", server_default="pending")
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    chunks = relationship(
        "MeetingChunk",
        foreign_keys="[MeetingChunk.meeting_id]",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )

    # Phase 3 graph extraction lifecycle. Same decoupled-status pattern
    # as `embedding_status`: an extraction failure flips this column to
    # 'failed' but leaves `status` and `embedding_status` untouched.
    # Values: 'pending' | 'processing' | 'extracted' | 'failed' | 'skipped'.
    graph_status = Column(String, nullable=False, default="pending", server_default="pending")
    graph_extracted_at = Column(DateTime(timezone=True), nullable=True)

    google_event_id = Column(String, unique=True)
    google_event_data = Column(JSON)      # Full event details including attendees

    # Phase 12A — closing-briefing lifecycle.
    # State machine for the AI's end-of-meeting verbal recap:
    #   'pending'       — default; meeting has not ended yet (or briefing
    #                     disabled at config time)
    #   'winding_down'  — advisory signal received (participant drop OR
    #                     wrap-up phrase detected). Phase 12D uses this to
    #                     pre-compose + pre-TTS the briefing.
    #   'ended'         — authoritative `call_ended` status received; the
    #                     briefing orchestrator should fire NOW.
    #   'spoken'        — briefing was successfully played to the meeting.
    #   'skipped'       — briefing intentionally skipped (disabled, empty
    #                     state, unsupported platform, no audio output, etc.).
    #   'failed'        — briefing pipeline errored (TTS down, Recall play
    #                     failed, etc.). The bot still leaves the call.
    # Also acts as the idempotency guard: webhook handlers refuse to
    # re-emit MEETING_ENDED when the row is already past 'pending'.
    closing_briefing_status = Column(
        String(24),
        nullable=False,
        default="pending",
        server_default="pending",
    )

class Participant(Base):
    __tablename__ = "participants"

    id = Column(Integer, primary_key=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"))

    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    recall_id = Column(String, nullable=True)  # Unique ID from Recall.ai
    is_organizer = Column(String, default=False)
    avatar_url = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    meeting = relationship("Meeting", back_populates="participants")

class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)

    meeting_id = Column(Integer, ForeignKey("meetings.id"))

    task = Column(String, nullable=False)
    owner_name = Column(String, nullable=True)
    priority = Column(String, default="medium")
    due_date = Column(DateTime(timezone=True), nullable=True)
    is_completed = Column(Integer, default=0) # Using Integer as boolean for SQLite/generic compat if needed, but standard is Column(Boolean)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    meeting = relationship("Meeting", back_populates="tasks")


class Organization(Base):
    """Tenancy boundary. Every user belongs to exactly one organization;
    every category and meeting is scoped to an organization.

    For existing single-user installs the migration creates one org per user,
    so behaviour is unchanged today but the queries are correct for multi-user
    orgs once that surface lands."""
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="organization")
    categories = relationship("Category", back_populates="organization")
    meetings = relationship("Meeting", back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)

    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True)
    organization = relationship("Organization", back_populates="users")

    # Phase 7E RBAC. Nullable for backward compat: a NULL row is
    # treated as 'viewer' (the safe-deny default) by
    # `dependencies/auth.py`. The 7E migration backfills existing
    # users to 'org_admin' so they keep their pre-7E privileges.
    # Values: 'viewer' | 'prompt_editor' | 'org_admin'.
    role = Column(String(24), nullable=True)

    google_access_token = Column(String)
    google_refresh_token = Column(String)
    google_token_expires_at = Column(DateTime(timezone=True))
    google_profile_name = Column(String)
    google_profile_picture = Column(String)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    meetings = relationship("Meeting", back_populates="user")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")


class CategoryDocument(Base):
    """A user-uploaded document scoped to a single category. Phase 1D persists
    the file to object storage and records metadata. Phase 2 picks these up
    via the `process_document` Celery task to chunk + embed + ingest into the
    category knowledge graph."""
    __tablename__ = "category_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    name = Column(String, nullable=False)                 # display name (defaults to filename)
    original_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)

    # Lifecycle. Phase 1 only flips between `uploaded` and `failed`; Phase 2
    # adds `processing` -> `ready` once chunking lands.
    status = Column(String, nullable=False, default="uploaded")
    error_message = Column(Text, nullable=True)

    # Light-weight access tracking — useful even before the graph layer
    # exists (e.g. "show recently used docs").
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0)

    # Phase 4 AI memory lifecycle — same decoupled-status pattern as
    # Meeting in Phase 2/3. `status` above stays for upload/storage;
    # these two columns track the ingestion pipeline independently so a
    # parser failure doesn't poison the storage-level state.
    embedding_status = Column(String, nullable=False, default="pending", server_default="pending")
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    graph_status = Column(String, nullable=False, default="pending", server_default="pending")
    graph_extracted_at = Column(DateTime(timezone=True), nullable=True)
    # Caches refreshed by the ingestion task so the UI doesn't need a
    # JOIN to render chunk counts in the documents panel.
    chunk_count = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    category = relationship("Category", back_populates="documents")
    organization = relationship("Organization")
    chunks = relationship(
        "DocumentChunk",
        foreign_keys="[DocumentChunk.category_document_id]",
        back_populates="category_document",
        cascade="all, delete-orphan",
    )


class Category(Base):
    """Meeting type / category (per meeting-types-architecture.md, this is `meeting_types`)."""
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_category_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, nullable=True)
    icon = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization", back_populates="categories")
    user = relationship("User", back_populates="categories")
    teams = relationship("Team", back_populates="category", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="category")
    documents = relationship("CategoryDocument", back_populates="category", cascade="all, delete-orphan")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("category_id", "name", name="uq_team_category_name"),)

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    category = relationship("Category", back_populates="teams")
    meetings = relationship("Meeting", back_populates="team")
    documents = relationship("TeamDocument", back_populates="team", cascade="all, delete-orphan")


class TeamDocument(Base):
    """Team-scoped knowledge document. Mirrors CategoryDocument but lives in
    a separate physical table per the architecture spec's level isolation
    rule ("DO NOT use one giant table"). Phase 2 picks these up via the
    `process_team_document` Celery task to feed the team knowledge graph."""
    __tablename__ = "team_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    name = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    storage_key = Column(String, nullable=False, unique=True)

    status = Column(String, nullable=False, default="uploaded")
    error_message = Column(Text, nullable=True)

    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0)

    # Phase 4 AI memory lifecycle (mirrors CategoryDocument).
    embedding_status = Column(String, nullable=False, default="pending", server_default="pending")
    embedded_at = Column(DateTime(timezone=True), nullable=True)
    graph_status = Column(String, nullable=False, default="pending", server_default="pending")
    graph_extracted_at = Column(DateTime(timezone=True), nullable=True)
    chunk_count = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    team = relationship("Team", back_populates="documents")
    organization = relationship("Organization")
    chunks = relationship(
        "DocumentChunk",
        foreign_keys="[DocumentChunk.team_document_id]",
        back_populates="team_document",
        cascade="all, delete-orphan",
    )


class MeetingChunk(Base):
    """A semantic chunk of a meeting transcript with its 1536-d embedding.

    Phase 2 vector memory. Each completed meeting becomes a sequence of
    chunks (~800 tokens with 100-token overlap, speaker-turn aware). Scope
    columns (organization / category / team) are denormalized so Phase 5
    scope-priority retrieval can filter without joining.

    The six knowledge-metadata columns (`importance_score`,
    `confidence_score`, `knowledge_version`, `created_from_meeting_id`,
    `last_accessed_at`, `access_count`) are present from row one per the
    locked Phase 2+ architecture, so Phase 3 (graph) and Phase 6 (reranking
    + memory optimization) have a stable shape to fill in."""
    __tablename__ = "meeting_chunks"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "meeting_id",
            "chunk_index",
            name="uq_meeting_chunks_org_meeting_chunk",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_id = Column(
        Integer,
        ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id = Column(
        Integer,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    team_id = Column(
        Integer,
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )

    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    speakers = Column(ARRAY(String), nullable=True)
    start_timestamp = Column(Integer, nullable=True)
    end_timestamp = Column(Integer, nullable=True)

    embedding = Column(Vector(1536), nullable=False)
    embedding_model = Column(String, nullable=False)

    importance_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    knowledge_version = Column(Integer, nullable=False, default=1, server_default="1")
    # Provenance — distinct from `meeting_id` so future derived rows
    # (entities/relationships) can record original origin even after a
    # later meeting updates them.
    created_from_meeting_id = Column(
        Integer,
        ForeignKey("meetings.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0, server_default="0")
    # Phase 6D — consolidation lifecycle. 'active' (default) means
    # visible to retrieval; 'archived' means hidden (rehydratable).
    # 'merged_into' is entity-only — never applies to chunks.
    archive_status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )

    metadata_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    meeting = relationship(
        "Meeting",
        foreign_keys=[meeting_id],
        back_populates="chunks",
    )
    created_from_meeting = relationship(
        "Meeting",
        foreign_keys=[created_from_meeting_id],
    )
    organization = relationship("Organization")


# ---------------------------------------------------------------------------
# Phase 3 — Graph foundation
#
# Single-table-per-concept design (rejected three-tier physical split).
# Scope is encoded via `scope_type` + `scope_id`; partial unique indexes
# enforce dedup correctly across the NULL scope_id of `scope_type='global'`.
#
# `source_type` is on entities + mentions from day one so Phase 4 documents
# plug in without a schema rev. Mention tables carry typed nullable source
# FK columns + a CHECK constraint that ties them to `source_type`.
#
# Every knowledge-tier row carries the six metadata-mandate columns.
# Phase 5/6 will read them; Phase 3 only writes them.
# ---------------------------------------------------------------------------


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('team','category','global')",
            name="ck_entities_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type IN ('team','category') AND scope_id IS NOT NULL)",
            name="ck_entities_scope_id_matches_type",
        ),
        # Partial unique indexes (created in the migration; declared here
        # so SQLAlchemy is aware of them and ORM-level constraint hints
        # work).
        Index(
            "uq_entities_scoped",
            "organization_id", "scope_type", "scope_id", "entity_type", "canonical_name",
            unique=True, postgresql_where="scope_id IS NOT NULL",
        ),
        Index(
            "uq_entities_global",
            "organization_id", "entity_type", "canonical_name",
            unique=True, postgresql_where="scope_type = 'global'",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type = Column(String, nullable=False)
    scope_id = Column(Integer, nullable=True)
    source_type = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    aliases = Column(ARRAY(String), nullable=True)
    attributes = Column(JSONB, nullable=True)

    # 6-column metadata mandate
    importance_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    knowledge_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_from_meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True,
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0, server_default="0")
    # Phase 6D — consolidation lifecycle. Entities can be 'merged_into'
    # in addition to 'active' / 'archived'; the `merged_into_entity_id`
    # pointer below records the survivor. CHECK constraint
    # `ck_entities_merged_into_consistency` enforces the invariant:
    # status='merged_into' iff merged_into_entity_id IS NOT NULL.
    archive_status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )
    merged_into_entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")
    created_from_meeting = relationship("Meeting", foreign_keys=[created_from_meeting_id])
    merged_into = relationship(
        "Entity", remote_side="Entity.id", foreign_keys=[merged_into_entity_id],
    )
    mentions = relationship(
        "EntityMention", back_populates="entity", cascade="all, delete-orphan",
    )
    # Outgoing relationships (this entity is the subject).
    outgoing_relationships = relationship(
        "Relationship",
        foreign_keys="[Relationship.subject_entity_id]",
        back_populates="subject_entity",
        cascade="all, delete-orphan",
    )
    incoming_relationships = relationship(
        "Relationship",
        foreign_keys="[Relationship.object_entity_id]",
        back_populates="object_entity",
        cascade="all, delete-orphan",
    )


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('team','category','global')",
            name="ck_relationships_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'global' AND scope_id IS NULL) OR "
            "(scope_type IN ('team','category') AND scope_id IS NOT NULL)",
            name="ck_relationships_scope_id_matches_type",
        ),
        Index(
            "uq_relationships_scoped",
            "organization_id", "scope_type", "scope_id",
            "subject_entity_id", "predicate", "object_entity_id",
            unique=True, postgresql_where="scope_id IS NOT NULL",
        ),
        Index(
            "uq_relationships_global",
            "organization_id", "subject_entity_id", "predicate", "object_entity_id",
            unique=True, postgresql_where="scope_type = 'global'",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type = Column(String, nullable=False)
    scope_id = Column(Integer, nullable=True)
    source_type = Column(String, nullable=False)
    subject_entity_id = Column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False,
    )
    predicate = Column(String, nullable=False)
    object_entity_id = Column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False,
    )
    attributes = Column(JSONB, nullable=True)

    importance_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    knowledge_version = Column(Integer, nullable=False, default=1, server_default="1")
    created_from_meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True,
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0, server_default="0")
    # Phase 6D — consolidation lifecycle. Relationships are 'active'
    # or 'archived' — no 'merged_into' (only entities merge).
    archive_status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")
    created_from_meeting = relationship("Meeting", foreign_keys=[created_from_meeting_id])
    subject_entity = relationship(
        "Entity", foreign_keys=[subject_entity_id], back_populates="outgoing_relationships",
    )
    object_entity = relationship(
        "Entity", foreign_keys=[object_entity_id], back_populates="incoming_relationships",
    )
    mentions = relationship(
        "RelationshipMention", back_populates="parent_relationship",
        cascade="all, delete-orphan",
    )


class EntityMention(Base):
    """One (entity, source) tuple. Provenance for graph rows.

    Polymorphic source: `source_type` ∈ {meeting, document, chat, email, task}.
    The CHECK constraint enforces exactly one of the four legal shapes:
      - meeting: `source_meeting_id` set, all doc FKs null.
      - document (category): `source_category_document_id` set, others null.
      - document (team): `source_team_document_id` set, others null.
      - chat/email/task: all source FKs null (context-only — provenance
        lives in the row's other metadata).

    Typed FKs (CASCADE on parent delete) replace the un-FK'd Phase 3
    placeholders, so deleting a doc atomically wipes its mentions.
    Phase 4 ingestion is the first writer for the document branches."""
    __tablename__ = "entity_mentions"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'meeting' "
            " AND source_meeting_id IS NOT NULL "
            " AND source_category_document_id IS NULL "
            " AND source_team_document_id IS NULL) "
            "OR (source_type = 'document' "
            " AND source_meeting_id IS NULL "
            " AND (    (source_category_document_id IS NOT NULL AND source_team_document_id IS NULL) "
            "       OR (source_category_document_id IS NULL AND source_team_document_id IS NOT NULL))) "
            "OR (source_type IN ('chat','email','task') "
            " AND source_meeting_id IS NULL "
            " AND source_category_document_id IS NULL "
            " AND source_team_document_id IS NULL)",
            name="ck_entity_mentions_source_typed",
        ),
        # One row per (entity, source) — meeting branch.
        Index(
            "uq_entity_mentions_meeting",
            "entity_id", "source_meeting_id", "source_chunk_id",
            unique=True,
            postgresql_where="source_type = 'meeting' AND source_chunk_id IS NOT NULL",
        ),
        # Document branches.
        Index(
            "uq_entity_mentions_category_doc",
            "entity_id", "source_category_document_id", "source_document_chunk_id",
            unique=True,
            postgresql_where=(
                "source_type = 'document' "
                "AND source_category_document_id IS NOT NULL "
                "AND source_document_chunk_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_entity_mentions_team_doc",
            "entity_id", "source_team_document_id", "source_document_chunk_id",
            unique=True,
            postgresql_where=(
                "source_type = 'document' "
                "AND source_team_document_id IS NOT NULL "
                "AND source_document_chunk_id IS NOT NULL"
            ),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String, nullable=False)
    source_meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True,
    )
    source_chunk_id = Column(
        UUID(as_uuid=True), ForeignKey("meeting_chunks.id", ondelete="SET NULL"), nullable=True,
    )
    # Typed doc FKs — replaces Phase 3 placeholders. CASCADE so mention
    # rows die with their parent doc.
    source_category_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("category_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_team_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("team_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_document_chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    span = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    entity = relationship("Entity", back_populates="mentions")
    organization = relationship("Organization")
    source_meeting = relationship("Meeting", foreign_keys=[source_meeting_id])
    source_chunk = relationship("MeetingChunk", foreign_keys=[source_chunk_id])
    source_category_document = relationship(
        "CategoryDocument", foreign_keys=[source_category_document_id],
    )
    source_team_document = relationship(
        "TeamDocument", foreign_keys=[source_team_document_id],
    )
    source_document_chunk = relationship(
        "DocumentChunk", foreign_keys=[source_document_chunk_id],
    )


class RelationshipMention(Base):
    """Same shape + CHECK contract as `EntityMention` — see that class
    for the rationale on the typed FK layout."""
    __tablename__ = "relationship_mentions"
    __table_args__ = (
        CheckConstraint(
            "(source_type = 'meeting' "
            " AND source_meeting_id IS NOT NULL "
            " AND source_category_document_id IS NULL "
            " AND source_team_document_id IS NULL) "
            "OR (source_type = 'document' "
            " AND source_meeting_id IS NULL "
            " AND (    (source_category_document_id IS NOT NULL AND source_team_document_id IS NULL) "
            "       OR (source_category_document_id IS NULL AND source_team_document_id IS NOT NULL))) "
            "OR (source_type IN ('chat','email','task') "
            " AND source_meeting_id IS NULL "
            " AND source_category_document_id IS NULL "
            " AND source_team_document_id IS NULL)",
            name="ck_relationship_mentions_source_typed",
        ),
        Index(
            "uq_relationship_mentions_meeting",
            "relationship_id", "source_meeting_id", "source_chunk_id",
            unique=True,
            postgresql_where="source_type = 'meeting' AND source_chunk_id IS NOT NULL",
        ),
        Index(
            "uq_relationship_mentions_category_doc",
            "relationship_id", "source_category_document_id", "source_document_chunk_id",
            unique=True,
            postgresql_where=(
                "source_type = 'document' "
                "AND source_category_document_id IS NOT NULL "
                "AND source_document_chunk_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_relationship_mentions_team_doc",
            "relationship_id", "source_team_document_id", "source_document_chunk_id",
            unique=True,
            postgresql_where=(
                "source_type = 'document' "
                "AND source_team_document_id IS NOT NULL "
                "AND source_document_chunk_id IS NOT NULL"
            ),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_id = Column(
        UUID(as_uuid=True),
        ForeignKey("relationships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String, nullable=False)
    source_meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=True,
    )
    source_chunk_id = Column(
        UUID(as_uuid=True), ForeignKey("meeting_chunks.id", ondelete="SET NULL"), nullable=True,
    )
    source_category_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("category_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_team_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("team_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_document_chunk_id = Column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
    )

    span = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # `relationship` shadows the imported function name; using
    # `parent_relationship` keeps the class body sane. `back_populates`
    # on `Relationship.mentions` points at this attr.
    parent_relationship = relationship(
        "Relationship", back_populates="mentions",
    )
    organization = relationship("Organization")
    source_meeting = relationship("Meeting", foreign_keys=[source_meeting_id])
    source_chunk = relationship("MeetingChunk", foreign_keys=[source_chunk_id])
    source_category_document = relationship(
        "CategoryDocument", foreign_keys=[source_category_document_id],
    )
    source_team_document = relationship(
        "TeamDocument", foreign_keys=[source_team_document_id],
    )
    source_document_chunk = relationship(
        "DocumentChunk", foreign_keys=[source_document_chunk_id],
    )


class GraphExtractionRun(Base):
    """One row per `extract_graph` invocation. Captures the prompt
    version, model, counts, duration, status, and raw LLM response —
    so prompt iteration in Phase 3.5+ has full ground truth without
    needing to re-run the model.

    Phase 4D extension: the source is now polymorphic. Exactly one of
    `meeting_id`, `source_category_document_id`, `source_team_document_id`
    is set per row, enforced by `ck_graph_extraction_runs_one_source`.
    Same audit-log shape; the source FK identifies which knowledge tier
    a given run wrote to.

    NOT a knowledge-tier table — it has no metadata-mandate columns,
    no `created_from_meeting_id`, no `last_accessed_at`. It's pure
    observability."""
    __tablename__ = "graph_extraction_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Polymorphic source — exactly one of these three is set per row.
    meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    source_category_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("category_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_team_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("team_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    prompt_version = Column(String, nullable=False, index=True)
    model = Column(String, nullable=False)
    chunks_processed = Column(Integer, nullable=False, default=0, server_default="0")
    entities_found = Column(Integer, nullable=False, default=0, server_default="0")
    relationships_found = Column(Integer, nullable=False, default=0, server_default="0")
    mentions_found = Column(Integer, nullable=False, default=0, server_default="0")
    duration_ms = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(String, nullable=False)  # 'completed' | 'failed'
    error_message = Column(Text, nullable=True)
    raw_response = Column(JSONB, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")
    meeting = relationship("Meeting", foreign_keys=[meeting_id])
    source_category_document = relationship(
        "CategoryDocument", foreign_keys=[source_category_document_id],
    )
    source_team_document = relationship(
        "TeamDocument", foreign_keys=[source_team_document_id],
    )


# ---------------------------------------------------------------------------
# Phase 4 — Document chunks
#
# Single polymorphic table. `document_type` + the typed FK pair
# (category_document_id, team_document_id) carry the parent. CHECK
# enforces exactly one is set, matching the type. Both FKs CASCADE so
# deleting a doc atomically wipes its chunks.
#
# Same scope-denormalization story as `meeting_chunks` (Phase 2A) — the
# `category_id` / `team_id` columns let Phase 5 hybrid retrieval filter
# without joining the doc parent.
#
# Same embedding dimensionality (1536) as `meeting_chunks` is
# non-negotiable: Phase 5 unions both tables in one ORDER BY.
# ---------------------------------------------------------------------------


class DocumentChunk(Base):
    """A semantic chunk of a document with its 1536-d embedding.

    Phase 4 vector memory. Each ingested doc becomes a sequence of
    chunks (~800 tokens, 100-token overlap, block-aware via the
    document chunker). `page_number` and `section_path` carry
    block-level provenance for retrieval citations.

    The six knowledge-metadata columns mirror `meeting_chunks` exactly,
    so Phase 6 reranking treats meeting and document chunks uniformly."""
    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('category','team')",
            name="ck_document_chunks_document_type",
        ),
        CheckConstraint(
            "(document_type = 'category' "
            " AND category_document_id IS NOT NULL "
            " AND team_document_id IS NULL) "
            "OR (document_type = 'team' "
            " AND team_document_id IS NOT NULL "
            " AND category_document_id IS NULL)",
            name="ck_document_chunks_typed_parent",
        ),
        Index(
            "uq_doc_chunks_category",
            "category_document_id", "chunk_index",
            unique=True,
            postgresql_where="document_type = 'category'",
        ),
        Index(
            "uq_doc_chunks_team",
            "team_document_id", "chunk_index",
            unique=True,
            postgresql_where="document_type = 'team'",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_type = Column(String, nullable=False)
    category_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("category_documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    team_document_id = Column(
        UUID(as_uuid=True),
        ForeignKey("team_documents.id", ondelete="CASCADE"),
        nullable=True,
    )

    category_id = Column(
        Integer,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    team_id = Column(
        Integer,
        ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
    )

    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    section_path = Column(Text, nullable=True)

    embedding = Column(Vector(1536), nullable=False)
    embedding_model = Column(String, nullable=False)

    # Knowledge-metadata mandate (mirrors meeting_chunks).
    importance_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    knowledge_version = Column(Integer, nullable=False, default=1, server_default="1")
    # Always NULL on doc chunks; the column is kept for schema symmetry
    # with meeting_chunks so Phase 6's reranker can treat both tables
    # uniformly.
    created_from_meeting_id = Column(
        Integer, ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True,
    )
    last_accessed_at = Column(DateTime(timezone=True), nullable=True)
    access_count = Column(Integer, nullable=False, default=0, server_default="0")
    # Phase 6D — consolidation lifecycle. Same semantics as meeting_chunks.
    archive_status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )

    # Free-form so the parsers can stash source_subtype (pdf/docx/xlsx),
    # original mime_type, truncation flags, etc. without a schema rev.
    metadata_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization")
    category_document = relationship(
        "CategoryDocument",
        foreign_keys=[category_document_id],
        back_populates="chunks",
    )
    team_document = relationship(
        "TeamDocument",
        foreign_keys=[team_document_id],
        back_populates="chunks",
    )


# ---------------------------------------------------------------------------
# Phase 5 — RAG conversations + query runs
#
# Conversations are the parent (one per chat thread). Query runs are an
# append-only audit log — one row per `/rag/ask` invocation. The audit
# row captures the full retrieval bundle + cited answer + per-stage
# timings, so 5F eval and Phase 6 reranking can replay queries without
# re-running the LLM.
#
# Conversations cascade with their owning user (your private chat dies
# with you). Runs cascade with their conversation.
# ---------------------------------------------------------------------------


class RagConversation(Base):
    """One chat thread. Title is auto-derived from the first query.
    `pinned_scope_*` is a UX convenience — the chat panel re-opens with
    the right scope picker; it does NOT bias retrieval, which always
    honors the request's explicit scope.
    """
    __tablename__ = "rag_conversations"
    __table_args__ = (
        CheckConstraint(
            "pinned_scope_type IS NULL "
            "OR pinned_scope_type IN ('team','category','global')",
            name="ck_rag_conversations_pinned_scope_type",
        ),
        CheckConstraint(
            "(pinned_scope_type IS NULL AND pinned_scope_id IS NULL) "
            "OR (pinned_scope_type = 'global' AND pinned_scope_id IS NULL) "
            "OR (pinned_scope_type IN ('team','category') AND pinned_scope_id IS NOT NULL)",
            name="ck_rag_conversations_pinned_scope_id_matches",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(Text, nullable=True)
    pinned_scope_type = Column(String(16), nullable=True)
    pinned_scope_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization")
    user = relationship("User", foreign_keys=[user_id])
    runs = relationship(
        "RagQueryRun",
        foreign_keys="[RagQueryRun.conversation_id]",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="RagQueryRun.created_at",
    )


class RagQueryRun(Base):
    """One `/rag/ask` invocation. Pure observability — no
    knowledge-metadata columns; never participates in retrieval. The
    retrieval_bundle JSONB is the eval harness's input: chunk_ids +
    entity_ids + per-chunk retrieval_reasons + retrieval_stage_scores.
    """
    __tablename__ = "rag_query_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed','no_context','failed')",
            name="ck_rag_query_runs_status",
        ),
        CheckConstraint(
            "effective_scope_type IS NULL "
            "OR effective_scope_type IN ('team','category','global')",
            name="ck_rag_query_runs_scope_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL so the audit row survives a user deletion (org may want
    # the historical query for compliance / debugging).
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rag_conversations.id", ondelete="CASCADE"),
        nullable=True,
    )

    query_text = Column(Text, nullable=False)
    requested_scope_type = Column(String(16), nullable=True)
    requested_scope_id = Column(Integer, nullable=True)
    effective_scope_type = Column(String(16), nullable=True)
    effective_scope_id = Column(Integer, nullable=True)

    planner_model = Column(String(64), nullable=True)
    planner_prompt_version = Column(String(32), nullable=True)
    synth_model = Column(String(64), nullable=True)
    synth_prompt_version = Column(String(32), nullable=True)

    retrieved_chunks = Column(Integer, nullable=False, default=0, server_default="0")
    retrieved_entities = Column(Integer, nullable=False, default=0, server_default="0")
    retrieved_relationships = Column(Integer, nullable=False, default=0, server_default="0")
    planner_duration_ms = Column(Integer, nullable=True)
    retrieval_duration_ms = Column(Integer, nullable=True)
    synth_duration_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    status = Column(String(16), nullable=False)
    answer_text = Column(Text, nullable=True)
    citations = Column(JSONB, nullable=True)
    retrieval_bundle = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)

    # Phase 6C — which reranker produced this run's ordering. NULL on
    # rows from Phase 5/6A/6B (those always used legacy_weighted).
    rerank_strategy = Column(String(24), nullable=True)

    # Phase 7C — backrefs to the resolver. NULL for pre-7C rows; also
    # NULL while the resolver runs in shadow mode if the resolution
    # fell all the way through to filesystem.
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Denormalized for cardinality counting: distinct hashes per day
    # ≈ distinct configs that ran.
    resolution_path_hash = Column(String(64), nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")
    user = relationship("User", foreign_keys=[user_id])
    conversation = relationship(
        "RagConversation",
        foreign_keys=[conversation_id],
        back_populates="runs",
    )


# ---------------------------------------------------------------------------
# Phase 6 — Importance scoring audit
#
# `importance_score` is a column on every knowledge-tier table since Phase 1.
# Phase 6A is the first slice that actually computes values into it.
# `importance_runs` records EVERY scoring pass:
#
#   - algorithm_version + weights_json: every score is replayable
#   - score_distribution_json: min/max/p50/p95/mean per run — sentinel
#     for silent drift (importance systems regress quietly otherwise)
#   - org-scoped — never cross-tenant
#
# Read-only after insert; same audit-log shape as graph_extraction_runs
# and rag_query_runs.
# ---------------------------------------------------------------------------


class ImportanceRun(Base):
    """One row per importance-scoring batch. Pure observability —
    never participates in retrieval."""
    __tablename__ = "importance_runs"
    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('meeting_chunk','document_chunk','entity','relationship')",
            name="ck_importance_runs_target_kind",
        ),
        CheckConstraint(
            "status IN ('completed','failed')",
            name="ck_importance_runs_status",
        ),
        CheckConstraint(
            "target_scope_type IS NULL OR target_scope_type IN ('team','category','global')",
            name="ck_importance_runs_scope_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_kind = Column(String(32), nullable=False)
    target_scope_type = Column(String(16), nullable=True)
    target_scope_id = Column(Integer, nullable=True)

    algorithm_version = Column(String(32), nullable=False)
    weights_json = Column(JSONB, nullable=False)

    rows_scored = Column(Integer, nullable=False, default=0, server_default="0")
    rows_updated = Column(Integer, nullable=False, default=0, server_default="0")
    duration_ms = Column(Integer, nullable=False)

    # Drift sentinel — see migration docstring.
    score_distribution_json = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )

    status = Column(String(16), nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    organization = relationship("Organization")


# ---------------------------------------------------------------------------
# Phase 6B — chunk access + citation click event logs
#
# Append-only event tables that drive Phase 6C's citation_count /
# access_count signals. See the migration docstring for the design
# rationale (no FK to chunks, BIGSERIAL ids, cascade behavior).
# ---------------------------------------------------------------------------


class ChunkAccessEvent(Base):
    """One row per time a chunk was surfaced.

    `event_type`:
      - 'search_hit'   — surfaced in /search top-K
      - 'rag_retrieve' — in a RAG retrieval bundle
      - 'rag_cited'    — made it into the final cited answer
    """
    __tablename__ = "rag_chunk_access_events"
    __table_args__ = (
        CheckConstraint(
            "chunk_kind IN ('meeting','document')",
            name="ck_chunk_access_chunk_kind",
        ),
        CheckConstraint(
            "event_type IN ('search_hit','rag_retrieve','rag_cited')",
            name="ck_chunk_access_event_type",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NO FK on chunk_id — chunks may be wiped + re-inserted; events outlive them.
    chunk_id = Column(UUID(as_uuid=True), nullable=False)
    chunk_kind = Column(String(16), nullable=False)
    event_type = Column(String(16), nullable=False)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rag_query_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    rank_position = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization")


class CitationClickEvent(Base):
    """User clicked a [N] citation chip in the chat UI. Separate from
    `ChunkAccessEvent` because the schema differs — clicks always
    belong to a run, carry a citation_index, and have no rank position.
    """
    __tablename__ = "rag_citation_click_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rag_query_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    citation_index = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization")


# ---------------------------------------------------------------------------
# Phase 6D — Entity merge suggestions
#
# Append-only candidate queue. The consolidation pass produces rows
# with status='pending'; a future UI surfaces them for human approval.
# Until then, suggestions just queue.
#
# Sticky rejection: the partial unique index on the unordered pair
# prevents re-proposing the same merge across consolidation runs.
# Status transitions are 'pending' -> 'merged' | 'rejected'; the
# transition recorder lives on this row (decided_by_user_id +
# decided_at) so rejected pairs stay rejected on re-run.
# ---------------------------------------------------------------------------


class EntityMergeSuggestion(Base):
    """One row per candidate duplicate pair."""
    __tablename__ = "entity_merge_suggestions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','merged','rejected')",
            name="ck_merge_suggestions_status",
        ),
        CheckConstraint(
            "candidate_a_id <> candidate_b_id",
            name="ck_merge_suggestions_distinct_pair",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_a_id = Column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_b_id = Column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity_score = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(
        String(16), nullable=False, default="pending", server_default="pending",
    )
    decided_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    organization = relationship("Organization")
    candidate_a = relationship("Entity", foreign_keys=[candidate_a_id])
    candidate_b = relationship("Entity", foreign_keys=[candidate_b_id])


# ---------------------------------------------------------------------------
# Phase 7A — Agent Control Dashboard: profiles + scoped bindings + epochs
#
# The runtime configuration layer that sits on top of the existing RAG
# pipeline. See `plan_phase_7_agent_control.md` for the full architecture.
#
#   - `AgentProfile`        — reusable identity for an LLM-driven service.
#   - `AgentPromptConfig`   — binding of a profile to a scope (org/category/
#                             team/meeting). Carries the `active_version_id`
#                             pointer once Phase 7B lands `prompt_versions`.
#   - `AgentConfigEpoch`    — monotonic counter per (org, profile) used by
#                             the resolver cache for cross-worker
#                             invalidation. Bumped under advisory lock
#                             every publish/rollback.
#
# Phase 7A intentionally ships ZERO consumers of these tables — runtime
# behavior is bit-for-bit identical to Phase 6 until 7D wires the
# resolver into `ask_stream`. Tables exist now so 7B can add
# `prompt_versions` with a clean FK target.
# ---------------------------------------------------------------------------


class AgentProfile(Base):
    """One reusable agent identity (e.g. `sales_copilot`).

    `agent_type` is the bridge to existing services. Allowed values
    track the agent-type matrix in the plan (rag_synth, rag_planner,
    graph_extractor, transcript_analyzer, importance_scorer,
    summarizer, live_copilot). New types require a CHECK update.

    Soft-active uniqueness on `(organization_id, slug)` lets admins
    archive a profile and re-create one with the same slug — same
    pattern as 6D chunk archival.
    """
    __tablename__ = "agent_profiles"
    __table_args__ = (
        CheckConstraint(
            "agent_type IN ("
            "'rag_synth','rag_planner','graph_extractor','transcript_analyzer',"
            "'importance_scorer','summarizer','live_copilot'"
            ")",
            name="ck_agent_profiles_agent_type",
        ),
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_agent_profiles_status",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug = Column(String(64), nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    agent_type = Column(String(32), nullable=False)
    status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )
    # 8-section modular prompt starter, surfaced in the editor on
    # profile creation. {} until 7B writes a draft. Stored on the
    # profile (not on versions) so duplicating a profile carries its
    # template forward.
    default_modular_prompt_json = Column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"),
    )
    # 7H — eval-gated publish. Scaffolded now so 7B doesn't need a
    # schema migration; defaults to off.
    eval_gate_required = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    eval_fixture_set_id = Column(UUID(as_uuid=True), nullable=True)
    eval_min_score = Column(Float, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    organization = relationship("Organization")
    creator = relationship("User", foreign_keys=[created_by])
    prompt_configs = relationship(
        "AgentPromptConfig",
        back_populates="agent_profile",
        cascade="all, delete-orphan",
    )


class AgentPromptConfig(Base):
    """Binding of an agent profile to a scope.

    One row per (agent_profile, scope) tuple. `scope_type` enumerates
    the resolution layer:

      - `organization`      → applies org-wide; `scope_id` is NULL
      - `category`          → meeting-type override; `scope_id` is the
                              `categories.id`
      - `team`              → team override; `scope_id` is `teams.id`
      - `meeting_specific`  → reserved for Phase 8; `scope_id` stays NULL
                              (Phase 8 will add a sibling scope_uuid)

    `active_version_id` is the pointer to the currently-published
    `prompt_versions` row; it stays NULL throughout 7A (versions land
    in 7B). The FK is added in the 7B migration.
    """
    __tablename__ = "agent_prompt_configs"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('organization','category','team','meeting_specific')",
            name="ck_agent_prompt_configs_scope_type",
        ),
        CheckConstraint(
            "(scope_type IN ('organization','meeting_specific') AND scope_id IS NULL) "
            "OR (scope_type IN ('category','team') AND scope_id IS NOT NULL)",
            name="ck_agent_prompt_configs_scope_id",
        ),
        CheckConstraint(
            "status IN ('active','archived')",
            name="ck_agent_prompt_configs_status",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope_type = Column(String(32), nullable=False)
    # BigInteger to give headroom; today's Category/Team PKs are Integer
    # but BigInt accepts those values fine. Phase 8 may move to UUIDs;
    # that lands as a sibling `scope_uuid` column, not a type change.
    scope_id = Column(BigInteger, nullable=True)
    # Pointer to the published version. FK added in 7B once
    # `prompt_versions` exists. Until then the column carries no
    # constraint beyond nullability.
    active_version_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(
        String(16), nullable=False, default="active", server_default="active",
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    organization = relationship("Organization")
    agent_profile = relationship("AgentProfile", back_populates="prompt_configs")
    creator = relationship("User", foreign_keys=[created_by])


class AgentConfigEpoch(Base):
    """Monotonic counter per (organization, agent_profile).

    Bumped on every publish/rollback. The resolver cache reads this on
    every cache hit; if the row's epoch exceeds the cached entry's
    snapshot the entry is evicted and recomputed. Cross-worker
    invalidation without a pub/sub transport — at the cost of one
    indexed SELECT per resolver call.

    Inserted lazily by the publish flow (Phase 7B) under a Postgres
    advisory lock so concurrent publishes serialize.
    """
    __tablename__ = "agent_config_epochs"

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    epoch = Column(
        BigInteger, nullable=False, default=0, server_default=text("0"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    organization = relationship("Organization")
    agent_profile = relationship("AgentProfile")


# ---------------------------------------------------------------------------
# Phase 7B — Immutable prompt versions + deployment audit
#
# `prompt_versions` is the immutable snapshot — modular prompts +
# retrieval/model/tool configs + lifecycle state. The trigger in the
# 7B migration enforces body immutability for non-draft rows.
#
# `prompt_deployments` is append-only audit. BIGSERIAL, no FK on the
# config pointer so history outlives cascade. Same shape as 6B access
# events.
#
# Version numbering is application-managed under a per-config advisory
# lock; see `app/services/agents/publish.py`.
# ---------------------------------------------------------------------------


class PromptVersion(Base):
    """One snapshot of a `agent_prompt_config`. Immutable once published.

    The 8 modular prompt sections live inside `modular_prompt_json` as a
    flat dict keyed by section name (`system`, `behavior`, `retrieval`,
    `citation`, `output`, `team_rules`, `meeting_type`, `guardrails`).
    Composition (7B+) reads this dict, interpolates variables, and
    concatenates in a fixed order.

    `seeded_from_filesystem` is the 7D guard — the seed migration sets
    it true so re-running the seed script is idempotent and a human-
    authored version never collides with a seed.
    """
    __tablename__ = "prompt_versions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('draft','published','archived')",
            name="ck_prompt_versions_state",
        ),
        CheckConstraint(
            "(state = 'published' AND published_at IS NOT NULL) "
            "OR (state <> 'published' AND published_at IS NULL)",
            name="ck_prompt_versions_published_consistency",
        ),
        UniqueConstraint(
            "agent_prompt_config_id", "version_number",
            name="uq_prompt_versions_config_version_number",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_prompt_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_prompt_configs.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number = Column(Integer, nullable=False)
    label = Column(String(120), nullable=True)
    modular_prompt_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    variables_schema_json = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    retrieval_config_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    model_config_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    tool_permissions_json = Column(
        JSONB, nullable=False,
        default=lambda: {"allowed": [], "denied": []},
        server_default=text("""'{"allowed":[],"denied":[]}'::jsonb"""),
    )
    meta_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    state = Column(
        String(16), nullable=False, default="draft", server_default="draft",
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    eval_score = Column(Float, nullable=True)
    eval_run_id = Column(UUID(as_uuid=True), nullable=True)
    seeded_from_filesystem = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

    organization = relationship("Organization")
    config = relationship(
        "AgentPromptConfig",
        foreign_keys=[agent_prompt_config_id],
    )
    publisher = relationship("User", foreign_keys=[published_by])
    creator = relationship("User", foreign_keys=[created_by])


class PromptDeployment(Base):
    """Append-only deployment audit. BIGSERIAL PK; no FK on
    `agent_prompt_config_id` so history outlives cascades.

    `action`:
      - 'publish'           — draft → published, set active_version_id
      - 'rollback'          — different published version → active
      - 'unpublish'         — clear active_version_id (rare)
      - 'eval_gate_failed'  — refused publish; from_version_id is the
                              candidate, to_version_id is NULL
    """
    __tablename__ = "prompt_deployments"
    __table_args__ = (
        CheckConstraint(
            "action IN ('publish','rollback','unpublish','eval_gate_failed')",
            name="ck_prompt_deployments_action",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # No FK — audit history outlives cascades.
    agent_prompt_config_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(24), nullable=False)
    from_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason = Column(Text, nullable=True)
    metadata_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    actor = relationship("User", foreign_keys=[actor_user_id])


# ---------------------------------------------------------------------------
# Phase 7F — Daily performance rollup
#
# Materialized aggregate over `rag_query_runs`, keyed by
# (organization, agent_profile, prompt_version, bucket_date). Built
# nightly by the Celery task `aggregate_agent_performance_daily` and
# read by the analytics endpoints. Idempotent rebuild: deleting a
# day's rows + re-inserting produces the same numbers because the
# source `rag_query_runs` is append-only.
#
# Null-handling on the natural-key index: a `/rag/ask` that resolved
# to the filesystem floor lands NULL for both `agent_profile_id` and
# `prompt_version_id`. The 7F migration's UNIQUE index uses COALESCE
# so a "no profile, no version" bucket still dedups.
# ---------------------------------------------------------------------------


class AgentPerformanceDaily(Base):
    """One row per (org, agent_profile, prompt_version, day) bucket.
    Read-only from the app's perspective — the only writer is the
    `aggregate_agent_performance_daily` Celery task. Direct queries
    against `rag_query_runs` are still allowed for the
    "recent-runs" detail view but not for the dashboard's headline
    metrics."""
    __tablename__ = "agent_performance_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    bucket_date = Column(Date, nullable=False)
    runs_total = Column(Integer, nullable=False, default=0, server_default="0")
    runs_completed = Column(Integer, nullable=False, default=0, server_default="0")
    runs_no_context = Column(Integer, nullable=False, default=0, server_default="0")
    runs_failed = Column(Integer, nullable=False, default=0, server_default="0")
    avg_total_duration_ms = Column(Integer, nullable=True)
    p50_total_duration_ms = Column(Integer, nullable=True)
    p95_total_duration_ms = Column(Integer, nullable=True)
    sum_input_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    sum_output_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    avg_citation_count = Column(Float, nullable=True)
    avg_chunks_retrieved = Column(Float, nullable=True)
    distinct_users = Column(Integer, nullable=False, default=0, server_default="0")
    computed_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    agent_profile = relationship("AgentProfile", foreign_keys=[agent_profile_id])
    prompt_version = relationship("PromptVersion", foreign_keys=[prompt_version_id])


# ---------------------------------------------------------------------------
# Phase 7C — Runtime resolution observability
#
# One row per resolver call. Lives alongside `rag_query_runs` (which
# records per-query observability); the two surfaces are parallel and
# joinable via `rag_query_run_id` when the resolver fires inside a
# /rag/ask. Append-only; no body mutations after insert.
#
# Architectural notes:
#   - `resolution_path_json` is the ordered audit trail — which layer
#     contributed which fields. Lets admins debug "why is my prompt
#     acting like this" by reading the resolution.
#   - `resolved_config_hash` is the deterministic sha256 of the final
#     bundle. Counts of distinct hashes ≈ distinct configs running.
#   - `cache_hit` records whether the resolver returned from cache.
#     Used to estimate cache effectiveness in production.
#   - `warnings_json` collects non-fatal issues (e.g. missing-variable
#     placeholders the composer had to inject).
# ---------------------------------------------------------------------------


class AgentRuntimeLog(Base):
    """One row per `resolve_agent_runtime_config(...)` call.

    Independent of `rag_query_runs` so the resolver can fire from
    non-query paths (the /agent-runtime-config debug endpoint, future
    Celery tasks, the playground). `rag_query_run_id` is set when the
    call is part of an /rag/ask.
    """
    __tablename__ = "agent_runtime_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    rag_query_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rag_query_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_type = Column(String(32), nullable=False)
    requested_scope_type = Column(String(32), nullable=True)
    requested_scope_id = Column(BigInteger, nullable=True)
    resolution_path_json = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    resolved_config_hash = Column(String(64), nullable=False)
    cache_hit = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    resolve_duration_ms = Column(Integer, nullable=False)
    warnings_json = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    agent_profile = relationship("AgentProfile", foreign_keys=[agent_profile_id])
    prompt_version = relationship("PromptVersion", foreign_keys=[prompt_version_id])


# ---------------------------------------------------------------------------
# Phase 7E — Playground + audit events
#
# Two tables:
#
#   - `prompt_test_runs`: append-only observability for the playground.
#     One row per sandboxed run. Carries the assembled prompt, retrieved
#     bundle, answer, citations, latency, tokens. Strictly isolated
#     from production observability: the playground never writes to
#     `rag_query_runs`, never logs chunk-access events, never touches
#     `rag_conversations`.
#
#   - `agent_audit_events`: append-only audit log for non-publish
#     mutations on agent surfaces. Complements `prompt_deployments`
#     (which is publish-specific) by capturing profile + config
#     create / update / archive / duplicate actions.
# ---------------------------------------------------------------------------


class PromptTestRun(Base):
    """One sandbox run. Mirrors `RagQueryRun`'s shape for the fields
    that matter to dashboards (timings, tokens, citations) plus the
    playground-specific `assembled_prompt_text` and
    `inline_overrides_json`."""
    __tablename__ = "prompt_test_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed','no_context','failed')",
            name="ck_prompt_test_runs_status",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_prompt_config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_prompt_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    inline_overrides_json = Column(JSONB, nullable=True)
    simulated_scope_type = Column(String(16), nullable=True)
    simulated_scope_id = Column(BigInteger, nullable=True)
    simulated_user_id = Column(UUID(as_uuid=True), nullable=True)
    query_text = Column(Text, nullable=False)
    assembled_prompt_text = Column(Text, nullable=False)
    retrieval_bundle_json = Column(JSONB, nullable=True)
    answer_text = Column(Text, nullable=True)
    citations_json = Column(JSONB, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    planner_duration_ms = Column(Integer, nullable=True)
    retrieval_duration_ms = Column(Integer, nullable=True)
    synth_duration_ms = Column(Integer, nullable=True)
    total_duration_ms = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False)
    error_message = Column(Text, nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    creator = relationship("User", foreign_keys=[created_by])


class AgentAuditEvent(Base):
    """Append-only audit log for non-publish mutations. Captures
    profile + config CRUD. Publish/rollback audit lives on
    `prompt_deployments`."""
    __tablename__ = "agent_audit_events"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('agent_profile','agent_prompt_config','prompt_version')",
            name="ck_agent_audit_events_entity_type",
        ),
        CheckConstraint(
            "action IN ('create','update','archive','unarchive','duplicate','delete')",
            name="ck_agent_audit_events_action",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_type = Column(String(32), nullable=False)
    # No FK on entity_id — audit outlives cascades, matches the
    # `prompt_deployments` pattern.
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(24), nullable=False)
    before_json = Column(JSONB, nullable=True)
    after_json = Column(JSONB, nullable=True)
    metadata_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    actor = relationship("User", foreign_keys=[actor_user_id])


# ---------------------------------------------------------------------------
# Phase 7H — Eval-gate runs
#
# One row per eval invocation. Triggered manually
# (POST /agents/{id}/eval/run), automatically by publish_version when
# the profile's `eval_gate_required` flag is set, or by a future
# Celery beat job for periodic regression checks.
#
# `report_json` carries the full Phase 5F EvalReport so the dashboard
# can render per-case results without re-running. `score` is the
# pass_rate from the report (0.0..1.0).
# ---------------------------------------------------------------------------


class AgentEvalRun(Base):
    """One eval run against a (profile, version) pair. Append-only;
    no body mutations after insert."""
    __tablename__ = "agent_eval_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('stub','real')",
            name="ck_agent_eval_runs_mode",
        ),
        CheckConstraint(
            "triggered_by IN ('manual','publish_gate','celery','script')",
            name="ck_agent_eval_runs_triggered_by",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode = Column(String(16), nullable=False)
    threshold = Column(Float, nullable=False)
    score = Column(Float, nullable=True)
    overall_passed = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    total_cases = Column(Integer, nullable=False, default=0, server_default="0")
    passed_cases = Column(Integer, nullable=False, default=0, server_default="0")
    duration_ms = Column(Integer, nullable=True)
    report_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_message = Column(Text, nullable=True)
    triggered_by = Column(
        String(24), nullable=False, default="manual",
        server_default="manual",
    )
    triggered_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    agent_profile_rel = relationship(
        "AgentProfile", foreign_keys=[agent_profile_id],
    )
    prompt_version_rel = relationship(
        "PromptVersion", foreign_keys=[prompt_version_id],
    )
    triggered_by_user = relationship(
        "User", foreign_keys=[triggered_by_user_id],
    )


# ---------------------------------------------------------------------------
# Phase 8A — Global template registry (platform-owned, immutable assets)
#
# Five tables. All platform-owned: no `organization_id`. Read by the
# provisioning service when materializing workspace rows; never read
# by the runtime.
#
# Versioning is application-managed — a new version is a NEW row with
# the same slug + bumped `version`. Lookups happen by slug+version
# (or slug+'latest' which the service resolves).
# ---------------------------------------------------------------------------


class TemplateBundle(Base):
    """A starter pack — the unit a workspace installs. Carries
    metadata (slug, version, category) and links to a set of
    `template_bundle_items` rows describing what's inside.

    `is_recommended_on_signup` flags bundles that auto-provision on
    new-org signup. The auth_router hook picks ONE by env var.
    """
    __tablename__ = "template_bundles"
    __table_args__ = (
        UniqueConstraint(
            "slug", "version", name="uq_template_bundles_slug_version",
        ),
        CheckConstraint(
            "state IN ('draft','published','deprecated')",
            name="ck_template_bundles_state",
        ),
        CheckConstraint(
            r"version ~ '^\d+\.\d+\.\d+$'",
            name="ck_template_bundles_version_semver",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    slug = Column(String(64), nullable=False)
    display_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(32), nullable=True)
    version = Column(String(32), nullable=False)
    state = Column(
        String(16), nullable=False, default="draft", server_default="draft",
    )
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(UUID(as_uuid=True), nullable=True)
    signature = Column(Text, nullable=True)
    manifest_hash = Column(String(64), nullable=True)
    is_recommended_on_signup = Column(
        Boolean, nullable=False, default=False, server_default=text("false"),
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    items = relationship(
        "TemplateBundleItem", back_populates="bundle",
        cascade="all, delete-orphan",
    )


class TemplateBundleItem(Base):
    """Join row — bundle ↔ (team|category|agent) definition.
    `item_version` null means "latest"; the registry resolves the
    actual version at provisioning time."""
    __tablename__ = "template_bundle_items"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id", "item_type", "item_slug",
            name="uq_template_bundle_items_bundle_type_slug",
        ),
        CheckConstraint(
            "item_type IN ('team','category','agent')",
            name="ck_template_bundle_items_type",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bundle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_bundles.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_type = Column(String(16), nullable=False)
    item_slug = Column(String(64), nullable=False)
    item_version = Column(String(32), nullable=True)
    provisioning_hints_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    ordering = Column(Integer, nullable=False, default=0, server_default="0")

    bundle = relationship("TemplateBundle", back_populates="items")


# ---------------------------------------------------------------------------
# Phase 8B — Workspace provisioning + lineage
#
# `template_provisioning_jobs` — append-only audit of every
# provisioning invocation. One row per call to
# `provision_bundle_for_org()` or `provision_items_for_org()`.
#
# `workspace_template_links` — the lineage join table. One row per
# provisioned workspace entity (Category, AgentProfile,
# AgentPromptConfig, PromptVersion). Carries the source template's
# kind + slug + version + bundle, and the lineage_state (8C
# populates this).
# ---------------------------------------------------------------------------


class TemplateProvisioningJob(Base):
    """One row per provisioning invocation. Append-only.

    `triggered_by` enumerates: 'auto_signup' (from auth_router:register),
    'manual' (admin UI), 'admin_api' (platform-staff bulk invocation),
    'celery' (background backfill task).
    """
    __tablename__ = "template_provisioning_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','completed','partial','failed')",
            name="ck_template_provisioning_jobs_status",
        ),
        CheckConstraint(
            "mode IN ('bundle','item_list','auto_signup')",
            name="ck_template_provisioning_jobs_mode",
        ),
        CheckConstraint(
            "triggered_by IN ('auto_signup','manual','admin_api','celery')",
            name="ck_template_provisioning_jobs_trigger",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    bundle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_bundles.id", ondelete="SET NULL"),
        nullable=True,
    )
    bundle_slug = Column(String(64), nullable=True)
    bundle_version = Column(String(32), nullable=True)
    mode = Column(String(24), nullable=False)
    requested_items_json = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    status = Column(String(16), nullable=False)
    items_created = Column(Integer, nullable=False, default=0, server_default="0")
    items_skipped = Column(Integer, nullable=False, default=0, server_default="0")
    items_failed = Column(Integer, nullable=False, default=0, server_default="0")
    failure_details_json = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(24), nullable=False)
    triggered_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    triggered_by_user = relationship(
        "User", foreign_keys=[triggered_by_user_id],
    )


class WorkspaceTemplateLink(Base):
    """One row per provisioned workspace entity. The runtime never
    reads this — it's a side-table for the UI + the upgrade detector.

    `entity_type` is the workspace-side row kind. `source_template_kind`
    is the template-side kind. They may differ: Phase 8B materializes
    both `team` and `category` templates as Category workspace rows
    (the existing schema couples them; a future slice may split
    workspace-level teams into a separate table)."""
    __tablename__ = "workspace_template_links"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ("
            "'category','agent_profile','prompt_config','prompt_version'"
            ")",
            name="ck_workspace_template_links_entity_type",
        ),
        CheckConstraint(
            "source_template_kind IN ('team','category','agent')",
            name="ck_workspace_template_links_source_kind",
        ),
        CheckConstraint(
            "lineage_state IN ('pristine','modified','heavily_modified','forked')",
            name="ck_workspace_template_links_lineage_state",
        ),
        CheckConstraint(
            "(entity_id_uuid IS NOT NULL AND entity_id_int IS NULL) "
            "OR (entity_id_uuid IS NULL AND entity_id_int IS NOT NULL)",
            name="ck_workspace_template_links_entity_id_exclusive",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type = Column(String(32), nullable=False)
    entity_id_uuid = Column(UUID(as_uuid=True), nullable=True)
    entity_id_int = Column(BigInteger, nullable=True)
    source_template_kind = Column(String(16), nullable=False)
    source_template_slug = Column(String(64), nullable=False)
    source_template_version = Column(String(32), nullable=False)
    source_bundle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_bundles.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_bundle_version = Column(String(32), nullable=True)
    provisioning_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("template_provisioning_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )
    provisioned_at = Column(DateTime(timezone=True), nullable=False)
    lineage_state = Column(
        String(24), nullable=False, default="pristine",
        server_default="pristine",
    )
    diff_summary_json = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_diverged_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")


# ---------------------------------------------------------------------------
# Phase 8D — Upgrade proposals + publish events
#
# Two tables:
#
#   `template_publish_events` — append-only global audit; one row per
#   template version publish. Drives the Celery upgrade detector.
#
#   `template_upgrade_proposals` — per-(link, version-transition).
#   The admin's inbox of pending upgrades. Acceptance creates a new
#   prompt_version via Phase 7B; rejection leaves the workspace
#   on the current version. Supersession happens when a newer
#   version arrives before the admin decides.
# ---------------------------------------------------------------------------


class TemplatePublishEvent(Base):
    """Append-only global audit. The Celery detector scans this
    table for events whose proposals haven't been generated yet."""
    __tablename__ = "template_publish_events"
    __table_args__ = (
        CheckConstraint(
            "template_kind IN ('bundle','team','category','agent')",
            name="ck_template_publish_events_kind",
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    template_kind = Column(String(16), nullable=False)
    template_slug = Column(String(64), nullable=False)
    from_version = Column(String(32), nullable=True)
    to_version = Column(String(32), nullable=False)
    published_by = Column(UUID(as_uuid=True), nullable=True)
    manifest_hash_before = Column(String(64), nullable=True)
    manifest_hash_after = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )




class WorkspaceBehaviorOverride(Base):
    """Phase 8C — sparse override row for a scoped BehaviorProfile
    dimension.field. Zero rows for a scope means the workspace uses
    template defaults. The runtime resolver (8D) merges these on top
    of catalog defaults at query time.

    Natural key: (organization_id, scope_type, scope_id, dimension,
    field). Enforced by two partial unique indexes (one per scope_id
    shape — workspace scope has no id, category/team scopes use int).

    Cascade rules:
      - delete org      → wipe all overrides
      - delete link     → wipe link-scoped overrides (workspace-level
                          rows have NULL link_id and survive)
    """
    __tablename__ = "workspace_behavior_overrides"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('workspace','category','team')",
            name="behov_scope_type_chk",
        ),
        CheckConstraint(
            "dimension IN ("
            "'master_prompt','enabled_agents','retrieval_config',"
            "'memory_config','output_config','extraction_rules',"
            "'automation_rules','evaluation_rules',"
            "'tone_and_personality','compliance_and_guardrails',"
            "'tools_and_integrations','intent'"
            ")",
            name="behov_dimension_chk",
        ),
        CheckConstraint(
            "(scope_type = 'workspace' "
            "  AND scope_id_uuid IS NULL AND scope_id_int IS NULL) "
            "OR (scope_type IN ('category','team') "
            "    AND scope_id_int IS NOT NULL "
            "    AND scope_id_uuid IS NULL)",
            name="behov_scope_id_chk",
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_template_link_id = Column(
        BigInteger,
        ForeignKey("workspace_template_links.id", ondelete="CASCADE"),
        nullable=True,
    )
    scope_type = Column(String(16), nullable=False)
    scope_id_uuid = Column(UUID(as_uuid=True), nullable=True)
    scope_id_int = Column(Integer, nullable=True)
    dimension = Column(String(40), nullable=False)
    field = Column(String(80), nullable=False, default="", server_default="")
    value_json = Column(
        JSONB, nullable=False, default=lambda: None,
        server_default=text("'null'::jsonb"),
    )
    created_by_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )

    organization = relationship("Organization")
    link = relationship("WorkspaceTemplateLink")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


class TemplateBehaviorProfile(Base):
    """Phase 8A (revised) — the canonical AI cognition object.

    One table, three scope_kinds:
      - 'global'   — platform-wide default. Exactly one published row.
      - 'category' — installed by a workspace as a category template
      - 'team'     — installed by a workspace as a team template

    Each row carries 11 dimensions (master_prompt, enabled_agents,
    retrieval_config, memory_config, output_config, extraction_rules,
    automation_rules, evaluation_rules, tone_and_personality,
    compliance_and_guardrails, tools_and_integrations) as named JSONB
    columns. The resolver (8D) merges these top-down at runtime to
    produce a single `ResolvedBehaviorProfile`.

    Replaces: TemplateAgentDefinition + TemplateCategoryDefinition +
              TemplateTeamDefinition (those tables drop in 8F)."""
    __tablename__ = "template_behavior_profiles"
    __table_args__ = (
        CheckConstraint(
            "scope_kind IN ('global','category','team')",
            name="bp_scope_kind_chk",
        ),
        CheckConstraint(
            "state IN ('draft','published','deprecated')",
            name="bp_state_chk",
        ),
        CheckConstraint(
            "version ~ '^\\d+\\.\\d+\\.\\d+$'",
            name="bp_version_fmt_chk",
        ),
        UniqueConstraint(
            "scope_kind", "slug", "version",
            name="ux_bp_scope_slug_version"
        ),
        Index(
            "ux_bp_global_published",
            "scope_kind", "slug",
            unique=True,
            postgresql_where="(scope_kind = 'global' AND state = 'published')",
        ),
        Index(
            "ix_bp_lookup",
            "scope_kind", "slug", "state"
        ),
        Index(
            "ix_bp_parent_category_slug",
            "parent_category_slug",
            postgresql_where="parent_category_slug IS NOT NULL"
        ),
    )

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    scope_kind = Column(String(16), nullable=False)
    slug = Column(String(64), nullable=False)
    version = Column(String(32), nullable=False)
    display_name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    state = Column(
        String(16), nullable=False, default="published",
        server_default="published",
    )

    # The 11 BehaviorProfile dimensions.
    master_prompt = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    enabled_agents = Column(
        JSONB, nullable=False, default=list,
        server_default=text("'[]'::jsonb"),
    )
    retrieval_config = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    memory_config = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    output_config = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    extraction_rules = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    automation_rules = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    evaluation_rules = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    tone_and_personality = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    compliance_and_guardrails = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    tools_and_integrations = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    intent = Column(
        JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )

    # Phase 8G — set for scope_kind='team' profiles; references the
    # category profile's slug they nest under. NULL for category/global.
    parent_category_slug = Column(String(64), nullable=True)

    manifest_hash = Column(String(64), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
    )