"""Detailed task descriptions, written from the full transcript.

The extraction call produces a `context` per task, but it is one field among
title/summary/decisions/risks/cleaned transcript in a single response, and the
model compresses it to a sentence. This is a second, focused pass: the whole
transcript plus this meeting's tasks in, one detailed markdown brief per task
out. It covers every task on the meeting — analyzer, live-detected and
harness-created alike — because it runs on the saved rows.

A description a person edited (a `description_changed` activity row) is never
touched. If this pass fails, the shorter extraction `context` stays in place.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import select

from app.db.models import Task, TaskActivity

logger = logging.getLogger(__name__)

MODEL = "gpt-4o"   # mini compressed briefs and skipped tasks in a side-by-side on meeting 4929; ~$0.02-0.05/meeting
BATCH = 15                 # tasks per call — keeps the JSON well inside the output budget
MAX_TRANSCRIPT_CHARS = 300_000   # ponytail: hard cut, ~75k tokens; chunked retrieval if meetings outgrow it

SYSTEM = """You write task descriptions for a team's task board, from a meeting transcript.

For EACH task you are given, write a detailed markdown brief so that someone who
missed the meeting can do the task without asking anyone. Include everything the
transcript says that bears on that task:
- why it is needed — the problem or goal, and who raised it
- every specific point made: requirements, fields, numbers, dates, names,
  systems, files, examples, objections, agreements (keep terms as said)
- constraints, dependencies, deadlines and the reasons given
- what "done" looks like and open questions — ONLY if the transcript states them

Method: for each task, first scan the WHOLE transcript for every line that
touches it — including lines far from where the task was agreed, and lines in
Hindi/Hinglish — and turn each relevant point into its own bullet. Be
exhaustive: a reader should not need the transcript afterwards.

Rules:
- Use only what the transcript says. Never invent, never pad.
- Length follows the discussion: many bullets for a task discussed at length,
  two or three lines for a passing mention.
- Write in English even if the transcript is Hindi/Hinglish.
- Start with a one-line summary sentence, then bullets. No headings for empty sections.

Return JSON: {"briefs": {"<task id>": "<markdown brief>", ...}} with every id given."""


def _human_edited(db, task_ids):
    rows = db.execute(
        select(TaskActivity.task_id).where(
            TaskActivity.task_id.in_(task_ids),
            TaskActivity.event_type == "description_changed",
        )
    ).scalars()
    return set(rows)


def _briefs_for(client, transcript, tasks):
    items = [
        {"id": str(t.id), "task": t.task, "owner": t.owner_name, "notes_so_far": t.description}
        for t in tasks
    ]
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"TRANSCRIPT:\n{transcript}\n\nTASKS:\n{json.dumps(items, ensure_ascii=False)}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(resp.choices[0].message.content).get("briefs") or {}


def enrich_meeting_task_descriptions(db, meeting_id, transcript, client=None) -> int:
    """Rewrite the description of every machine-described task on this meeting
    with a detailed brief. Returns how many rows were updated."""
    if not transcript:
        return 0
    tasks = db.query(Task).filter(Task.meeting_id == meeting_id).all()
    if not tasks:
        return 0
    edited = _human_edited(db, [t.id for t in tasks])
    tasks = [t for t in tasks if t.id not in edited]
    if not tasks:
        return 0

    if client is None:
        from app.ai_agents.openAI_transcript_analyzer import _get_client
        client = _get_client()
    transcript = transcript[:MAX_TRANSCRIPT_CHARS]

    updated = 0
    for i in range(0, len(tasks), BATCH):
        batch = tasks[i:i + BATCH]
        briefs = _briefs_for(client, transcript, batch)
        for t in batch:
            brief = (briefs.get(str(t.id)) or "").strip()
            if brief:
                t.description = brief
                updated += 1
        db.commit()
    return updated
