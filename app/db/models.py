from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timezone
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

    category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)
    category = relationship("Category", back_populates="meetings")
    team = relationship("Team", back_populates="meetings")

    tasks = relationship("Task", back_populates="meeting", cascade="all, delete-orphan")
    participants = relationship("Participant", back_populates="meeting", cascade="all, delete-orphan")

    google_event_id = Column(String, unique=True)
    google_event_data = Column(JSON)      # Full event details including attendees

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


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    
    google_access_token = Column(String)
    google_refresh_token = Column(String)
    google_token_expires_at = Column(DateTime(timezone=True))
    google_profile_name = Column(String)
    google_profile_picture = Column(String)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    meetings = relationship("Meeting", back_populates="user")
    categories = relationship("Category", back_populates="user", cascade="all, delete-orphan")


class Category(Base):
    """Meeting type / category (per meeting-types-architecture.md, this is `meeting_types`)."""
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_category_user_name"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String, nullable=True)
    icon = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="categories")
    teams = relationship("Team", back_populates="category", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="category")


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