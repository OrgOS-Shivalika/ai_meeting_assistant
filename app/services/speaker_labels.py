"""Persistence for in-room speaker attribution.

Splits the DB-touching half away from `app/processors/speaker_attribution.py`,
which is deliberately pure — no session, no network — because that purity is
what lets the whole of the risky attribution logic be replayed offline against
every stored transcript before any of it reaches a live meeting.

Two jobs, both called from the meeting pipeline after a transcript lands:

    persist_resolutions(db, meeting_id, resolutions)   the mapping rows
    save_room_speakers(db, meeting, resolutions)       attendee rows per voice

Stage 5 will add the correction path here too, which is why this is its own
module rather than another 100 lines in `meeting_service`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import Participant, SpeakerLabelMapping
from app.processors.speaker_attribution import (
    METHOD_UNRESOLVED, parse_key, serialize_key,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Prefix for the synthetic `participants.recall_id` of a room speaker.
# Recall's own ids are integers, so a prefixed string cannot collide with one,
# and the existing skip-not-replace logic in `save_participants` then gives us
# idempotency for free with no schema change.
ROOM_SPEAKER_PREFIX = "dia:"


def room_speaker_recall_id(diarization_label: int) -> str:
    return f"{ROOM_SPEAKER_PREFIX}{diarization_label}"


def persist_resolutions(
    db: Session, meeting_id: int, resolutions: dict,
) -> tuple[int, int]:
    """Upsert one `label_mappings` row per resolved speaker.

    Returns ``(inserted, updated)``.

    Idempotent, because a pipeline re-run (`scripts/rerun_analysis.py`, a
    Celery redelivery, a second dispatch) must not duplicate rows — the same
    failure mode that once left meetings carrying 2x their real participants.

    **A human correction is never overwritten.** A row with `corrected_by` set
    is left exactly as it is, even if the automatic pass now disagrees. Same
    reasoning as `save_participants` being skip-not-replace: the manual fix is
    the only recovery from a bad automatic match, and silently reverting it
    would be worse than never having offered the correction.
    """
    if not resolutions:
        return (0, 0)

    existing = {
        row.speaker_key: row
        for row in db.query(SpeakerLabelMapping).filter(
            SpeakerLabelMapping.meeting_id == meeting_id,
        )
    }

    inserted = updated = protected = 0
    for key, resolution in resolutions.items():
        serialized = serialize_key(key)
        participant_id = key[1] if len(key) > 1 else None
        row = existing.get(serialized)

        if row is None:
            db.add(SpeakerLabelMapping(
                meeting_id=meeting_id,
                speaker_key=serialized,
                # str() to match `participants.recall_id`, which is String
                # while Recall sends an int.
                participant_id=None if participant_id is None else str(participant_id),
                diarization_label=resolution.diarization_label,
                display_name=resolution.display_name,
                method=resolution.method,
                confidence=resolution.confidence,
                matched_email=resolution.matched_email,
                needs_review=resolution.needs_review,
            ))
            inserted += 1
            continue

        if row.corrected_by is not None:
            protected += 1
            continue

        row.display_name = resolution.display_name
        row.method = resolution.method
        row.confidence = resolution.confidence
        row.matched_email = resolution.matched_email
        row.needs_review = resolution.needs_review
        row.diarization_label = resolution.diarization_label
        updated += 1

    db.commit()
    logger.info(
        "label_mappings meeting=%s: %d inserted, %d updated, %d human-corrected "
        "rows left untouched", meeting_id, inserted, updated, protected,
    )
    return (inserted, updated)


def save_room_speakers(db: Session, meeting, resolutions: dict) -> int:
    """Give every separated voice a `participants` row. Returns rows added.

    Without this an in-room meeting's attendee list shows only the laptop's
    account while the notes name three people — an inconsistency a user reads
    as a bug.

    **These rows grant nothing.** `user_id` and `match_source` are both left
    NULL even when the roll-call name matched a calendar invite, because
    `permissions._attended_meeting_ids` gates meeting READ access on exactly
    those two fields. Anyone can say any name into a room mic; a spoken name is
    a display label, never authentication. `matched_email` is carried for
    display and assignee suggestions only, mirroring how `save_participants`
    already stores a `heuristic` email that confers nothing.

    Written as a separate pass rather than inside `save_participants`, which is
    guarded by three separate landmines (sticky `is_organizer`, truthiness on
    id 0, skip-not-replace) and is not worth destabilizing.
    """
    clusters = {
        key: resolution
        for key, resolution in (resolutions or {}).items()
        if key[0] == "d"
    }
    if not clusters:
        return 0

    already = {
        r[0]
        for r in db.query(Participant.recall_id).filter(
            Participant.meeting_id == meeting.id,
        ).all()
    }

    added = 0
    for key, resolution in clusters.items():
        recall_id = room_speaker_recall_id(key[2])
        if recall_id in already:
            continue
        db.add(Participant(
            meeting_id=meeting.id,
            name=resolution.display_name,
            recall_id=recall_id,
            email=resolution.matched_email,
            user_id=None,        # never — see the docstring
            match_source=None,   # never — see the docstring
            is_organizer="False",
        ))
        added += 1

    if added:
        db.commit()
        logger.info(
            "Added %d room-speaker participant row(s) for meeting %s "
            "(no access granted)", added, meeting.id,
        )
    return added


def mappings_for_meeting(db: Session, meeting_id: int) -> list:
    """All mapping rows for a meeting, unresolved ones first.

    Ordering puts what needs a human at the top of the correction UI.
    """
    rows = (
        db.query(SpeakerLabelMapping)
        .filter(SpeakerLabelMapping.meeting_id == meeting_id)
        .all()
    )
    return sorted(
        rows,
        key=lambda r: (
            r.method != METHOD_UNRESOLVED,
            not r.needs_review,
            r.diarization_label if r.diarization_label is not None else -1,
        ),
    )


def apply_correction(
    db: Session,
    meeting_id: int,
    speaker_key: str,
    display_name: str,
    *,
    corrected_by: Optional[UUID] = None,
) -> SpeakerLabelMapping:
    """Record a human fix for one speaker. Raises ValueError on a bad key.

    Marks the row `corrected_by`/`corrected_at` so `persist_resolutions` will
    never overwrite it. Does NOT re-render `meetings.transcript_text` — the
    caller decides, because regenerating notes costs LLM calls and may
    overwrite hand-edited summaries and tasks (Stage 5).
    """
    parse_key(speaker_key)  # validate; a corrupt key must not label a speaker

    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name must not be empty")

    row = (
        db.query(SpeakerLabelMapping)
        .filter(
            SpeakerLabelMapping.meeting_id == meeting_id,
            SpeakerLabelMapping.speaker_key == speaker_key,
        )
        .first()
    )
    if row is None:
        raise ValueError(
            f"no speaker {speaker_key!r} on meeting {meeting_id}"
        )

    row.display_name = name
    row.method = "manual"
    row.confidence = 1.0
    row.needs_review = False
    row.corrected_by = corrected_by
    row.corrected_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        "label_mapping corrected: meeting=%s key=%s -> %r",
        meeting_id, speaker_key, name,
    )
    return row
