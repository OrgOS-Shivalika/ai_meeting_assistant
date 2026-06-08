"""Phase 12B — live rolling summary.

A single string ('summary') updated every N semantic batches.
Lives in `MeetingState.summary`; read by the Phase 12C briefing composer.

Different shape from `live_tasks` / `live_decisions` because a summary
is not a collection of discrete items — it's one piece of evolving prose.
"""
