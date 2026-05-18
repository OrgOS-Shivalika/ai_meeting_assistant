"""Phase 7B — version-vs-version diff.

Produces a structured diff payload the dashboard renders into a
side-by-side view. Four pieces:

  1. Modular prompt diff — per section: a, b, unified_diff (line-level
     using stdlib `difflib.unified_diff`).
  2. Retrieval-config diff — per key: a, b. Plain key-level value diff
     (no recursive walk; the bundle is shallow).
  3. Model-config diff — same.
  4. Tool-permissions diff — added/removed for allowed + denied lists.

Variables-schema and label are reported as scalar changed/not-changed.

The diff is direction-aware: `from` is "a", `to` is "b". The dashboard
typically passes (old, new) so additions show as "+" in unified diff.
"""
from __future__ import annotations

import difflib
from typing import Any

from app.db.models import PromptVersion
from app.schemas.agent_schema import ModularPrompt


def _unified_diff(a: str, b: str) -> str:
    """Render a line-level unified diff between two strings. Empty
    when the inputs are identical."""
    if a == b:
        return ""
    a_lines = a.splitlines(keepends=False)
    b_lines = b.splitlines(keepends=False)
    diff_iter = difflib.unified_diff(
        a_lines, b_lines, fromfile="a", tofile="b", lineterm="",
    )
    return "\n".join(diff_iter)


def _diff_modular_prompts(
    a: dict, b: dict,
) -> dict[str, dict[str, str]]:
    """Per-section diff. Includes every section where either side has
    content — even if one side is empty (so admins can see what got
    added)."""
    out: dict[str, dict[str, str]] = {}
    sections = ModularPrompt.section_keys()
    for key in sections:
        a_text = (a or {}).get(key, "") or ""
        b_text = (b or {}).get(key, "") or ""
        if a_text == b_text and not a_text:
            continue  # both empty → skip
        if a_text == b_text:
            continue  # identical → skip
        out[key] = {
            "a": a_text,
            "b": b_text,
            "unified_diff": _unified_diff(a_text, b_text),
        }
    return out


def _diff_flat_dict(a: dict, b: dict) -> dict[str, dict[str, Any]]:
    """Shallow key-by-key diff. Returns only keys where a != b. The
    importance_weight_overrides nested dict is treated as one value;
    the UI can dive in if needed."""
    a = a or {}
    b = b or {}
    keys = sorted(set(a.keys()) | set(b.keys()))
    out: dict[str, dict[str, Any]] = {}
    for k in keys:
        av = a.get(k)
        bv = b.get(k)
        if av != bv:
            out[k] = {"a": av, "b": bv}
    return out


def _diff_tool_permissions(a: dict, b: dict) -> dict[str, list[str]]:
    """Compute added/removed sets for allowed + denied independently."""
    a_allowed = set((a or {}).get("allowed") or [])
    b_allowed = set((b or {}).get("allowed") or [])
    a_denied  = set((a or {}).get("denied")  or [])
    b_denied  = set((b or {}).get("denied")  or [])
    return {
        "added_allowed":   sorted(b_allowed - a_allowed),
        "removed_allowed": sorted(a_allowed - b_allowed),
        "added_denied":    sorted(b_denied  - a_denied),
        "removed_denied":  sorted(a_denied  - b_denied),
    }


def diff_versions(a: PromptVersion, b: PromptVersion) -> dict:
    """Public entry point. Returns the dict that maps directly to
    `VersionDiffResponse`. Callers populate the from/to ids — keeping
    them out of the function lets the caller decide direction."""
    return {
        "modular_prompt_diff": _diff_modular_prompts(
            a.modular_prompt_json, b.modular_prompt_json,
        ),
        "retrieval_config_diff": _diff_flat_dict(
            a.retrieval_config_json, b.retrieval_config_json,
        ),
        "model_config_diff": _diff_flat_dict(
            a.model_config_json, b.model_config_json,
        ),
        "tool_permissions_diff": _diff_tool_permissions(
            a.tool_permissions_json, b.tool_permissions_json,
        ),
        "variables_schema_changed": (
            (a.variables_schema_json or []) != (b.variables_schema_json or [])
        ),
        "label_changed": (a.label or None) != (b.label or None),
    }
