"""Phase 7C — modular prompt composition + safe variable interpolation.

Two public entry points:

  interpolate(text, variables) -> (rendered, warnings)
  compose_system_message(modular_prompts, variables) -> (assembled, warnings)

Syntax: `{{var_name}}`. Plain str.replace — no Jinja, no template
inheritance, no expression evaluation. Variables are HTML-escaped at
substitution time to prevent prompt-injection where a user-supplied
value contains literal section markers or instruction-shaped text.

Missing-variable handling: an unresolvable `{{var}}` becomes the
placeholder `[var unavailable]` and a warning is appended to the
returned list. The composer never raises on missing variables — same
defensive posture as `query_planner._default_plan`.

Composition order (locked, matches plan §4.2):

    {{system}}

    {{behavior}}

    {{team_rules}}

    {{meeting_type}}

    {{guardrails}}

    {{retrieval}}

    {{citation}}

    {{output}}

Empty sections are skipped (no leading/trailing blank lines, no empty
section markers — keeps token count clean).

Phase 7C does NOT wire this into the synthesizer or planner; that's
the 7D switch-flip. 7C ships the composer + tests so 7D can land as a
pure plumbing change.
"""
from __future__ import annotations

import html
import re
from typing import Any

from app.schemas.agent_schema import ModularPrompt

# Strict variable token: `{{ <name> }}` with optional whitespace inside
# the braces. Names are [a-z_][a-z0-9_]* — same as Python identifiers,
# lowercase. Anything outside this shape is left as-is (won't match).
_VAR_RE = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def _stringify(value: Any) -> str:
    """Render a variable's value as a string. None → empty string.
    Containers get a compact repr — the composer doesn't try to be
    smart; admins who want fancy rendering should pre-format."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_stringify(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}={_stringify(v)}" for k, v in value.items())
    return str(value)


def interpolate(text: str, variables: dict[str, Any]) -> tuple[str, list[str]]:
    """Replace every `{{var}}` token in `text` with the corresponding
    value from `variables`. Returns `(rendered, warnings)`.

    Missing keys (not in dict, or value is None+empty) yield the
    placeholder `[<var> unavailable]` and a warning string. We
    HTML-escape values at substitution so a value containing prompt
    structure like `=== SECTION ===` can't masquerade as the assembled
    template's own markers.

    The same variable name appearing multiple times pays the lookup
    once (case-insensitive map lookup via the regex).
    """
    if not text:
        return "", []
    warnings: list[str] = []
    seen_missing: set[str] = set()

    def _replace(m: re.Match) -> str:
        name = m.group(1).lower()
        if name in variables:
            v = variables[name]
            if v is None:
                if name not in seen_missing:
                    warnings.append(f"missing_variable:{name}")
                    seen_missing.add(name)
                return f"[{name} unavailable]"
            rendered = _stringify(v)
            return html.escape(rendered, quote=False)
        if name not in seen_missing:
            warnings.append(f"missing_variable:{name}")
            seen_missing.add(name)
        return f"[{name} unavailable]"

    return _VAR_RE.sub(_replace, text), warnings


# Composition order — locked in the plan. Adding a section means
# inserting it here AND adding the key to `ModularPrompt.section_keys()`.
_COMPOSITION_ORDER: tuple[str, ...] = (
    "system",
    "behavior",
    "team_rules",
    "meeting_type",
    "guardrails",
    "retrieval",
    "citation",
    "output",
)


def compose_system_message(
    modular_prompts: dict[str, str],
    variables: dict[str, Any],
) -> tuple[str, list[str]]:
    """Build the system-message string from the 8-section dict.

    Empty sections are skipped — no blank stanzas, no leading or
    trailing newlines. Each non-empty section is interpolated
    independently so a missing variable warning lists the section
    name implicitly (the section the variable lived in is the section
    where the warning originated, but we don't tag it explicitly to
    keep the warnings list a flat set of names; the dashboard can
    cross-reference).

    Returns `(assembled, warnings)`. `warnings` aggregates across
    every section.
    """
    modular_prompts = modular_prompts or {}
    pieces: list[str] = []
    warnings: list[str] = []
    for key in _COMPOSITION_ORDER:
        raw = modular_prompts.get(key) or ""
        if not raw.strip():
            continue
        rendered, w = interpolate(raw, variables)
        warnings.extend(w)
        if rendered.strip():
            pieces.append(rendered.strip())
    return "\n\n".join(pieces), warnings


# Re-export the canonical section order so callers can introspect
# without duplicating the constant.
def composition_order() -> tuple[str, ...]:
    return _COMPOSITION_ORDER


# Sanity check at import time: the composition order must match the
# canonical section keys. Drift = explicit failure.
_DECLARED = set(ModularPrompt.section_keys())
_ORDERED = set(_COMPOSITION_ORDER)
assert _DECLARED == _ORDERED, (
    f"composition order drift: declared={_DECLARED}, ordered={_ORDERED}"
)
