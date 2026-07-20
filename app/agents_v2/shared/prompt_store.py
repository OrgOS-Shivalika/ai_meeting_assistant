"""Versioned prompt storage — DB first, file fallback.

Provides the pure functions used by:
  - agent execution (`load_active_prompt` at meeting time)
  - the admin API (`create_version`, `rollback_to`, `list_versions`)

Rules:
  - One active version per (agent_id, prompt_key). New edit inserts a
    new row and flips the previous active off — atomic under a
    transaction.
  - History is never mutated. Rollback CREATES A NEW ROW with the
    older text (version = max+1). The old version stays untouched.
  - When no DB row exists for an agent+key, we fall back to reading
    the file on disk from the agent's folder. This is how the app
    behaves out of the box before any user edits.
  - Content-hash dedup: submitting the same text twice = no new
    version. Cheap protection against a UI double-submit.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AgentPrompt, AgentV2

logger = logging.getLogger(__name__)


# Max prompt size at the API boundary. 30 KB ≈ ~7500 tokens, more than
# enough for any reasonable prompt and cheap protection against runaway.
MAX_PROMPT_CHARS = 30_000

# Prompts must reference the transcript. Without this placeholder the
# LLM sees only instructions, no data.
REQUIRED_PLACEHOLDERS = ["{{transcript}}"]


@dataclass
class LoadedPrompt:
    """Result of load_active_prompt — text + provenance metadata."""
    text: str
    source: str            # "db" or "file"
    version: int           # 0 for file, ≥1 for db
    hash: str              # sha256 of text
    prompt_key: str        # e.g. "master.md"
    row_id: Optional[int] = None       # DB row id when source=="db"
    edited_by: Optional[str] = None    # UUID str of user when source=="db"
    edited_at_iso: Optional[str] = None
    notes: Optional[str] = None

    def as_metadata(self) -> dict:
        """Shape suitable for attaching to a Langfuse Generation."""
        return {
            "prompt_source": self.source,
            "prompt_version": self.version,
            "prompt_hash": self.hash,
            "prompt_key": self.prompt_key,
            "prompt_row_id": self.row_id,
            "prompt_edited_by": self.edited_by,
            "prompt_edited_at": self.edited_at_iso,
            "prompt_notes": self.notes,
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_file_prompt(agent_folder: Path, prompt_key: str) -> Optional[str]:
    """Read a prompt file from the agent's folder. Returns None if the
    file doesn't exist (agent has no filesystem default for that key)."""
    path = agent_folder / "prompts" / prompt_key
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Read path — used at meeting time
# ---------------------------------------------------------------------------

def load_active_prompt(
    db: Session,
    *,
    agent_id: int,
    agent_folder: Path,
    prompt_key: str = "master.md",
) -> LoadedPrompt:
    """Look up the active DB version first, fall back to the file on disk.

    Args:
        db: session (caller-owned).
        agent_id: agents_v2 row id.
        agent_folder: pathlib Path to the agent's folder (used for the
            file fallback).
        prompt_key: which prompt to load (default master.md — supports
            per-skill prompts later).

    Returns:
        LoadedPrompt. Raises FileNotFoundError only if BOTH the DB and
        the folder have nothing for this key — that's an
        agent-configuration bug.
    """
    row = (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_key == prompt_key,
            AgentPrompt.is_active.is_(True),
        )
        .first()
    )
    if row:
        return LoadedPrompt(
            text=row.prompt_text,
            source="db",
            version=row.version,
            hash=row.prompt_hash,
            prompt_key=row.prompt_key,
            row_id=row.id,
            edited_by=str(row.created_by) if row.created_by else None,
            edited_at_iso=row.created_at.isoformat() if row.created_at else None,
            notes=row.notes,
        )

    file_text = _read_file_prompt(agent_folder, prompt_key)
    if file_text is None:
        raise FileNotFoundError(
            f"No prompt found for agent_id={agent_id} prompt_key={prompt_key!r} "
            f"— neither in agent_prompts table nor at {agent_folder}/prompts/"
        )
    return LoadedPrompt(
        text=file_text,
        source="file",
        version=0,
        hash=_sha256(file_text),
        prompt_key=prompt_key,
    )


# ---------------------------------------------------------------------------
# Write path — used by the admin API
# ---------------------------------------------------------------------------

class PromptValidationError(ValueError):
    """Raised when a submitted prompt fails validation."""


def _validate(text: str) -> None:
    """Raise PromptValidationError if the prompt is unusable."""
    if not text or not text.strip():
        raise PromptValidationError("Prompt is empty.")
    if len(text) > MAX_PROMPT_CHARS:
        raise PromptValidationError(
            f"Prompt exceeds {MAX_PROMPT_CHARS} chars (got {len(text)})."
        )
    missing = [p for p in REQUIRED_PLACEHOLDERS if p not in text]
    if missing:
        raise PromptValidationError(
            f"Prompt is missing required placeholder(s): {', '.join(missing)}"
        )


def create_version(
    db: Session,
    *,
    agent_id: int,
    text: str,
    created_by: Optional[UUID] = None,
    prompt_key: str = "master.md",
    notes: Optional[str] = None,
) -> AgentPrompt:
    """Create a new prompt version; deactivate the current active row.

    Idempotent by content — submitting the same text as the current
    active row returns the existing row without creating a new one.
    """
    _validate(text)
    new_hash = _sha256(text)

    # Lock the agent row briefly so two concurrent submits serialize
    agent = (
        db.query(AgentV2).filter(AgentV2.id == agent_id).with_for_update().first()
    )
    if agent is None:
        raise ValueError(f"Agent id={agent_id} not found")

    current = (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_key == prompt_key,
            AgentPrompt.is_active.is_(True),
        )
        .with_for_update()
        .first()
    )
    if current and current.prompt_hash == new_hash:
        logger.info(
            "prompt_store.create_version: no-op — same content as active v%d "
            "for agent_id=%d prompt_key=%r",
            current.version, agent_id, prompt_key,
        )
        return current

    next_version = _next_version(db, agent_id, prompt_key)
    if current is not None:
        current.is_active = False

    new_row = AgentPrompt(
        agent_id=agent_id,
        version=next_version,
        prompt_key=prompt_key,
        prompt_text=text,
        prompt_hash=new_hash,
        is_active=True,
        created_by=created_by,
        notes=notes,
    )
    db.add(new_row)
    db.flush()
    logger.info(
        "prompt_store.create_version: agent_id=%d prompt_key=%r v%d (rows=+1)",
        agent_id, prompt_key, next_version,
    )
    return new_row


def rollback_to(
    db: Session,
    *,
    agent_id: int,
    target_version_id: int,
    created_by: Optional[UUID] = None,
    prompt_key: str = "master.md",
    notes: Optional[str] = None,
) -> AgentPrompt:
    """Activate an older version by inserting a NEW row with its text.

    History is never mutated — the old version stays as-is, and a new
    row is created carrying the same text but a fresh version number.
    That way "rollback to v3" is recorded in the audit trail.
    """
    target = (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.id == target_version_id,
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_key == prompt_key,
        )
        .first()
    )
    if target is None:
        raise ValueError(
            f"Target version id={target_version_id} not found for "
            f"agent_id={agent_id} prompt_key={prompt_key!r}"
        )
    rollback_notes = notes or f"Rollback to v{target.version} (row id={target.id})"
    return create_version(
        db,
        agent_id=agent_id,
        text=target.prompt_text,
        created_by=created_by,
        prompt_key=prompt_key,
        notes=rollback_notes,
    )


def list_versions(
    db: Session,
    *,
    agent_id: int,
    prompt_key: str = "master.md",
    limit: int = 50,
) -> list[AgentPrompt]:
    """Newest first. Includes both active and inactive rows."""
    return (
        db.query(AgentPrompt)
        .filter(
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_key == prompt_key,
        )
        .order_by(AgentPrompt.version.desc())
        .limit(limit)
        .all()
    )


def _next_version(db: Session, agent_id: int, prompt_key: str) -> int:
    top = (
        db.query(AgentPrompt.version)
        .filter(
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_key == prompt_key,
        )
        .order_by(AgentPrompt.version.desc())
        .first()
    )
    return (top[0] + 1) if top else 1
