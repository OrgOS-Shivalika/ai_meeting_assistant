"""Versioned RAG prompts (planner + synthesizer).

Same convention as `app/ai_agents/prompts/graph/`:

  - Each file is `<version>.txt`.
  - Prompts have two subfolders here: `planner/` and `synth/`.
  - The version string travels with every `rag_query_runs` row, so 5F
    eval can re-run a stored query against the original prompt.

Resolve the active prompt with:

    planner_text = load_planner_prompt(settings.RAG_PLANNER_PROMPT_VERSION)
    synth_text   = load_synth_prompt(settings.RAG_SYNTH_PROMPT_VERSION)

Adding a version means dropping a new file (`v2.txt`, `v1-strict.txt`)
and bumping the env var / setting.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent

_planner_cache: dict[str, str] = {}
_synth_cache: dict[str, str] = {}


def _load(subdir: str, version: str, cache: dict[str, str]) -> str:
    if version in cache:
        return cache[version]
    path = _PROMPTS_DIR / subdir / f"{version}.txt"
    if not path.is_file():
        available = sorted(p.stem for p in (_PROMPTS_DIR / subdir).glob("*.txt"))
        raise FileNotFoundError(
            f"RAG {subdir} prompt version '{version}' not found at {path}. "
            f"Available versions: {available or '(none)'}"
        )
    text = path.read_text(encoding="utf-8")
    cache[version] = text
    return text


def load_planner_prompt(version: str) -> str:
    return _load("planner", version, _planner_cache)


def load_synth_prompt(version: str) -> str:
    return _load("synth", version, _synth_cache)


def available_planner_versions() -> list[str]:
    return sorted(p.stem for p in (_PROMPTS_DIR / "planner").glob("*.txt"))


def available_synth_versions() -> list[str]:
    return sorted(p.stem for p in (_PROMPTS_DIR / "synth").glob("*.txt"))
