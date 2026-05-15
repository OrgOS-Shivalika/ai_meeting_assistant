"""Phase 6D — memory consolidation.

Two pure-Python services + a Celery wrapper:

  - `archive.run_archive(org)` — flags cold chunks/entities/relationships
    as `archive_status='archived'`. Non-destructive: rows STAY in their
    table; retrieval queries add `WHERE archive_status='active'` to
    hide them. Rehydratable via the API endpoint.

  - `merges.run_merge_suggestions(org)` — finds candidate duplicate
    entity pairs within the same (org, scope, type), writes them to
    `entity_merge_suggestions` as `status='pending'`. NEVER auto-merges.
    Sticky-rejection: rejected pairs persist as `status='rejected'`
    so a re-run skips them.

Both functions are idempotent and org-scoped.
"""
from app.services.consolidation.archive import run_archive
from app.services.consolidation.merges import run_merge_suggestions

__all__ = ["run_archive", "run_merge_suggestions"]
