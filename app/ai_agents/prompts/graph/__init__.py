"""Versioned graph extraction prompts.

Each version of the graph extractor's prompt is a `.txt` file in this
directory named `<version>.txt`. The version string travels with every
`graph_extraction_runs` row so a backfill can target stale prompts.

Resolve the active prompt with:

    text = load_prompt(settings.GRAPH_PROMPT_VERSION)

Adding a new version means dropping a new file (`v2.txt`, `v1-strict.txt`)
and bumping `GRAPH_PROMPT_VERSION` in settings or env.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent

_cache: dict[str, str] = {}


def load_prompt(version: str) -> str:
    """Return the prompt template for `version`. Cached after first read.

    Raises FileNotFoundError with a clear message if the requested
    version doesn't exist — better than failing silently with a generic
    open() error mid-extraction.
    """
    if version in _cache:
        return _cache[version]
    path = _PROMPTS_DIR / f"{version}.txt"
    if not path.is_file():
        available = sorted(p.stem for p in _PROMPTS_DIR.glob("*.txt"))
        raise FileNotFoundError(
            f"Graph extractor prompt version '{version}' not found at {path}. "
            f"Available versions: {available or '(none)'}"
        )
    text = path.read_text(encoding="utf-8")
    _cache[version] = text
    return text


def available_versions() -> list[str]:
    """Discoverability helper — list every shipped prompt version."""
    return sorted(p.stem for p in _PROMPTS_DIR.glob("*.txt"))
