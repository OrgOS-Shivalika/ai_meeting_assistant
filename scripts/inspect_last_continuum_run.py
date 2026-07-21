"""Inspect the last Continuum Core run(s) — quick correctness check.

Reads the most recent rows from cc_runs and prints the audit-relevant
fields side-by-side so we can eyeball whether the pipeline ran
correctly (stage stayed pinned, playbook_delta present, board_version
incremented, no error_message).
"""
from __future__ import annotations

import json
import sys

from app.db.database import SessionLocal
from app.db.models import ContinuumClient, ContinuumRun

_LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def truncate(s, n=200):
    if not s:
        return "—"
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def main() -> None:
    db = SessionLocal()
    try:
        total = db.query(ContinuumRun).count()
        print(f"Total cc_runs rows: {total}")
        if total == 0:
            print("No runs to inspect — the smoke script cleans up after itself.")
            return

        rows = (
            db.query(ContinuumRun, ContinuumClient)
            .join(ContinuumClient, ContinuumRun.client_id == ContinuumClient.id)
            .order_by(ContinuumRun.id.desc())
            .limit(_LIMIT)
            .all()
        )

        for run, client in rows:
            print("─" * 76)
            print(f"cc_runs.id={run.id}  |  client={client.name} (id={client.id})")
            print(f"  mode={run.mode}  status={run.status}  model={run.model}")
            print(f"  meeting_id={run.meeting_id}  duration_ms={run.duration_ms}")
            print(f"  board_version_after={run.board_version_after}")
            print(f"  stage_recommendation={run.stage_recommendation}")
            if run.error_message:
                print(f"  ⚠ error_message: {truncate(run.error_message, 400)}")

            # Board sanity — did the LLM try to change the stage?
            if run.board_after and isinstance(run.board_after, dict):
                pipe = run.board_after.get("pipeline") or {}
                board_stage = pipe.get("stage")
                # Compare with the client's current stage (already pinned).
                current_stage = None
                if client.board and isinstance(client.board, dict):
                    current_stage = (client.board.get("pipeline") or {}).get("stage")
                print(f"  board_after.pipeline.stage = {board_stage}  "
                      f"(client current: {current_stage})")

            # Envelope sanity — playbook null? mode field present?
            env = run.input_envelope or {}
            print(f"  envelope: mode={env.get('mode')}  "
                  f"meeting_number={env.get('meeting_number')}  "
                  f"stage_playbook={'null' if env.get('stage_playbook') is None else 'present'}")

            # Playbook delta capture — is it being produced?
            pd = run.playbook_delta
            if pd is None:
                pd_info = "not produced"
            elif isinstance(pd, list):
                pd_info = f"{len(pd)} candidate(s)"
            elif isinstance(pd, dict):
                pd_info = "dict shape"
            else:
                pd_info = f"unexpected type {type(pd).__name__}"
            print(f"  playbook_delta: {pd_info}")

            # Package (human output) preview
            pkg = run.package_markdown or ""
            print(f"  package_markdown ({len(pkg)} chars):")
            print("    " + truncate(pkg, 400).replace("\n", "\n    "))
    finally:
        db.close()


if __name__ == "__main__":
    main()
