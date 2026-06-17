"""Phase 14 — Kanban Boards.

Module layout:

  - defaults.py   — default board/column lookup; falls back to creating
                    the org default board if it's somehow missing
                    (defensive — the K1 migration backfills, but a new
                    org created post-migration also needs this).
  - positions.py  — Trello-style float position helpers. Midpoint
                    insertion; rebalance the column when gaps shrink
                    past a threshold.
  - activity.py   — single helper for writing rows into `task_activity`
                    consistently across API + background-task writers
                    (added in K2).

Public exports kept tight — callers should import the function they
need by name, not `from .kanban import *`.
"""
