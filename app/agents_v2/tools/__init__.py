"""Tools registry — boot-time discovery.

Each tool lives in `agents_v2/tools/<tool_id>/tool.py` and calls
`register(Tool(...))` at import time. `bootstrap()` walks the folder
and imports each so those side effects fire.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_BOOTSTRAPPED = False


def bootstrap() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    pkg_path = Path(__file__).parent
    for entry in pkg_path.iterdir():
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        module_name = f"app.agents_v2.tools.{entry.name}.tool"
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Failed to load tool '%s': %s", entry.name, exc, exc_info=True)

    from app.agents_v2.tools.base import all_tools
    logger.info(
        "Tools registry: %d tool(s) loaded: %s",
        len(all_tools()),
        ", ".join(t.id for t in all_tools()),
    )
    _BOOTSTRAPPED = True
