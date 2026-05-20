"""Phase 8C+ — AI behavior orchestration.

Two responsibilities live in this package:

  - `overrides.py` — CRUD on workspace_behavior_overrides rows.
                     Sparse storage for "this scope deviates from
                     template defaults on these fields."

  - `resolver.py` (8D, future) — merges global → category template
                     → team template → category overrides
                     → team overrides → workspace overrides
                     into a final BehaviorProfile. Used by every
                     runtime service that needs to know how AI
                     should behave for a given (org, category, team)
                     context.

Templates are imported via `app.services.templates.*` — they live
in their own package because they're the distribution mechanism,
not the runtime engine.
"""
