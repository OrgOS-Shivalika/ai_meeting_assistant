"""Agent registry — boot-time discovery + DB seeding.

At app startup we scan `app/agents_v2/` for subdirectories (skipping
`shared/`), import each as an agent module, and:

  1. Read its MANIFEST to know what it declares.
  2. Cache the imported module so orchestrator.route() can `.run()` it.
  3. If a matching agents_v2 DB row doesn't exist yet, INSERT one seeded
     from the manifest.

If an existing row is found, we DON'T overwrite it — the DB row is the
authoritative source of overrides. Manifest changes only affect new
scopes, not existing ones.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import AgentV2

logger = logging.getLogger(__name__)


# Cache of imported agent modules, keyed by slug. Populated by bootstrap().
_AGENT_MODULES: dict[str, ModuleType] = {}
_BOOTSTRAPPED = False


def _ensure_bootstrapped() -> None:
    """Lazy self-bootstrap so any Python process that touches the registry
    (FastAPI web, Celery worker, celery beat, standalone scripts) gets the
    agent folders imported and DB rows seeded — regardless of whether the
    process's entry point remembered to call bootstrap() at startup.

    Idempotent: first call runs the full scan, subsequent calls are cheap.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    bootstrap()


def get_agent_module(slug: str) -> ModuleType | None:
    """Return the imported agent module for a slug, or None if unknown."""
    _ensure_bootstrapped()
    return _AGENT_MODULES.get(slug)


def list_agents() -> list[str]:
    """Return all registered agent slugs."""
    _ensure_bootstrapped()
    return list(_AGENT_MODULES.keys())


def bootstrap() -> None:
    """Discover agent folders, import their manifests, seed DB rows.

    Idempotent — safe to call multiple times. Called at FastAPI startup
    via main.py, and lazily by _ensure_bootstrapped() from any other
    process (Celery worker, beat, scripts).
    """
    global _BOOTSTRAPPED
    _BOOTSTRAPPED = True   # mark FIRST so a re-entrant call from imports
                            # doesn't loop.
    logger.info("agents_v2.bootstrap: scanning agent folders...")

    # Discover subpackages of app.agents_v2 (skip shared/ and this file)
    import app.agents_v2 as ns
    for _, name, is_pkg in pkgutil.iter_modules(ns.__path__):
        if not is_pkg:
            continue
        if name in ("shared", "skills", "tools"):
            continue
        try:
            module = importlib.import_module(f"app.agents_v2.{name}.agent")
        except Exception as exc:
            logger.error(
                "agents_v2.bootstrap: failed to import %s: %s",
                name, exc, exc_info=True,
            )
            continue

        manifest = getattr(module, "MANIFEST", None)
        if not manifest:
            logger.warning("agents_v2.bootstrap: %s has no MANIFEST — skipping", name)
            continue

        slug = manifest.get("slug") or name
        _AGENT_MODULES[slug] = module
        logger.info("agents_v2.bootstrap: registered agent %r", slug)

        _seed_db_rows(slug, manifest)

    # Skills registry — populates `agents_v2.skills.base._REGISTRY` by
    # importing every `<skill_id>/skill.py`. Done AFTER agent import so
    # agent manifests can safely reference skill ids by string.
    try:
        from app.agents_v2 import skills as skills_pkg
        skills_pkg.bootstrap()
    except Exception as exc:
        logger.error("agents_v2.bootstrap: skills bootstrap failed: %s", exc, exc_info=True)

    # Tools registry — same shape as skills.
    try:
        from app.agents_v2 import tools as tools_pkg
        tools_pkg.bootstrap()
    except Exception as exc:
        logger.error("agents_v2.bootstrap: tools bootstrap failed: %s", exc, exc_info=True)


def _seed_db_rows(slug: str, manifest: dict[str, Any]) -> None:
    """Insert an agents_v2 row for the manifest's declared seed_scopes
    if a row for that scope doesn't already exist.

    Manifest can declare zero or more `seed_scopes`, each is a dict:
        {"organization_id": UUID, "category_id": int|None, "team_id": int|None}

    Zero seed_scopes = the agent code exists but isn't bound to any
    scope until an admin creates the row manually (e.g. via SQL).
    """
    seed_scopes = manifest.get("seed_scopes") or []
    if not seed_scopes:
        return

    db: Session = SessionLocal()
    try:
        for scope in seed_scopes:
            org_id = scope.get("organization_id")
            cat_id = scope.get("category_id")
            team_id = scope.get("team_id")
            if not org_id:
                logger.warning(
                    "agents_v2.bootstrap: skipping seed_scope without "
                    "organization_id for %s", slug,
                )
                continue

            q = db.query(AgentV2).filter(
                AgentV2.slug == slug,
                AgentV2.organization_id == org_id,
                AgentV2.category_id.is_(cat_id) if cat_id is None
                else AgentV2.category_id == cat_id,
                AgentV2.team_id.is_(team_id) if team_id is None
                else AgentV2.team_id == team_id,
                AgentV2.status == "active",
            )
            if q.first():
                continue

            row = AgentV2(
                slug=slug,
                organization_id=org_id,
                category_id=cat_id,
                team_id=team_id,
                name=manifest.get("name", slug),
                model=manifest.get("model", "gpt-4o-mini"),
                max_tokens=manifest.get("max_tokens", 4000),
                harness_enabled=bool(manifest.get("harness_enabled", False)),
                system_prompt_key=manifest.get(
                    "master_prompt", "prompts/master.md"
                ).split("/")[-1],
            )
            db.add(row)
            logger.info(
                "agents_v2.bootstrap: seeded row for %s (org=%s, cat=%s, team=%s)",
                slug, org_id, cat_id, team_id,
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "agents_v2.bootstrap: seed failed for %s: %s",
            slug, exc, exc_info=True,
        )
    finally:
        db.close()
