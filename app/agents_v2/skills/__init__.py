"""Skills registry — boot-time discovery of every skill.py under this folder.

Any code that wants to check what's registered imports from
`app.agents_v2.skills.base`. `bootstrap()` is idempotent; the main
agents_v2 registry calls it once at startup.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

_BOOTSTRAPPED = False


def bootstrap() -> None:
    """Import every `<skill_id>/skill.py` under this package so the
    `register(...)` calls at module load time populate the registry.

    Skills declare themselves via `register(Skill(...))` at import time —
    that side effect is the whole point of importing them here.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    pkg_path = Path(__file__).parent
    for entry in pkg_path.iterdir():
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        skill_module = f"app.agents_v2.skills.{entry.name}.skill"
        try:
            importlib.import_module(skill_module)
        except Exception as exc:
            # A broken skill folder must not take down the app.
            logger.warning("Failed to load skill '%s': %s", entry.name, exc, exc_info=True)

    from app.agents_v2.skills.base import all_skills
    logger.info("Skills registry: %d skill(s) loaded: %s",
                len(all_skills()),
                ", ".join(s.id for s in all_skills()))
    _BOOTSTRAPPED = True
