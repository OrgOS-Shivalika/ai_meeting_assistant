"""Phase 9.2 — derive transcript-analyzer behavior context from the
resolved BehaviorProfile for a meeting.

The meeting pipeline calls `build_meeting_behavior_context(meeting)` to
produce a string preamble that the transcript analyzer injects into
its prompt. The preamble distills the merged BehaviorProfile into
plain English guidance the LLM can consume.

What we map from the profile:

  - master_prompt.system    → "Role + ownership context"
  - master_prompt.behavior  → "Behavior rules"
  - master_prompt.output    → "Output structure norms"
  - master_prompt.guardrails→ "Refusal + safety rules"
  - tone_and_personality    → "Tone"
  - extraction_rules        → "Entities to surface"
  - output_config           → "Section structure + max length"
  - compliance_and_guardrails → "Compliance directives"

The function is defensive: a missing meeting / missing category_id /
absent resolver returns an empty string, in which case the analyzer
runs with its filesystem default behavior (zero regression).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db.models import Meeting

logger = logging.getLogger(__name__)


def _bullet_list(items: list, indent: str = "  - ") -> str:
    if not items:
        return ""
    return "\n".join(f"{indent}{item}" for item in items)


def _section(label: str, body: str) -> str:
    body = (body or "").strip()
    if not body:
        return ""
    return f"## {label}\n{body}\n"


def _format_dimensions(dims: dict[str, Any]) -> str:
    """Translate a merged BehaviorProfile dict into a plain-English
    preamble. Returns "" if nothing meaningful surfaces."""
    sections: list[str] = []

    mp = dims.get("master_prompt") or {}
    if mp.get("system"):
        sections.append(_section("Role", mp["system"]))
    if mp.get("behavior"):
        sections.append(_section("Behavior Rules", mp["behavior"]))
    if mp.get("output"):
        sections.append(_section("Output Norms", mp["output"]))
    if mp.get("guardrails"):
        sections.append(_section("Guardrails", mp["guardrails"]))

    tone = dims.get("tone_and_personality") or {}
    if tone:
        bits = []
        for k, v in tone.items():
            if v:
                bits.append(f"{k.replace('_', ' ')}: {v}")
        if bits:
            sections.append(_section("Tone", "; ".join(bits)))

    extract = dims.get("extraction_rules") or {}
    entities = extract.get("entities") or []
    if entities:
        sections.append(_section(
            "Entities to Surface",
            "Pay extra attention to these in the summary + decisions:\n"
            + _bullet_list(entities),
        ))
    flags = [
        ("extract_action_items", "Action items"),
        ("extract_decisions", "Decisions"),
        ("extract_timeline", "Timeline events"),
        ("extract_crm_fields", "CRM-relevant fields (budget, authority, need, timeline)"),
    ]
    enabled_flags = [label for key, label in flags if extract.get(key)]
    if enabled_flags:
        sections.append(_section(
            "Always Extract", _bullet_list(enabled_flags),
        ))

    out = dims.get("output_config") or {}
    if out.get("sections"):
        sections.append(_section(
            "Summary Section Order",
            _bullet_list(out["sections"]),
        ))
    if out.get("max_length_tokens"):
        sections.append(_section(
            "Length Norm",
            f"Aim for summaries within ~{out['max_length_tokens']} tokens.",
        ))

    compliance = dims.get("compliance_and_guardrails") or {}
    cbits = []
    if compliance.get("redact_pii"):
        cbits.append("Redact PII (emails, phone numbers, IDs) in the summary.")
    if compliance.get("bias_check_enabled"):
        cbits.append("Avoid bias indicators; do NOT infer protected-class attributes.")
    if compliance.get("audit_trail_required"):
        cbits.append("Keep claims traceable to verbatim transcript quotes where possible.")
    refused = compliance.get("refused_topics") or []
    if refused:
        cbits.append(
            f"Refuse to engage with these topics: {', '.join(refused)}."
        )
    if cbits:
        sections.append(_section(
            "Compliance Directives", _bullet_list(cbits),
        ))

    body = "".join(s for s in sections if s).strip()
    if not body:
        return ""

    return (
        "## Workspace AI Behavior Context\n"
        "The following organizational behavior settings apply to this "
        "meeting. Use them to shape your output. They take precedence "
        "over any conflicting default style guidance below.\n\n"
        + body
    )


def build_meeting_behavior_context(
    db: Session, *, meeting: Meeting,
) -> str:
    """Resolve the meeting's BehaviorProfile and return a plaintext
    preamble suitable for prepending to the transcript analyzer's
    prompt. Empty string on any resolution failure → analyzer falls
    back to its hardcoded behavior."""
    try:
        from app.services.behavior.resolver import resolve_behavior_profile
        prof = resolve_behavior_profile(
            db,
            organization_id=meeting.organization_id,
            category_id=meeting.category_id,
            team_id=meeting.team_id,
        )
        # to_dict returns flat dict by dimension; pluck what we need.
        dims = {
            "master_prompt": prof.master_prompt,
            "tone_and_personality": prof.tone_and_personality,
            "extraction_rules": prof.extraction_rules,
            "output_config": prof.output_config,
            "compliance_and_guardrails": prof.compliance_and_guardrails,
        }
        return _format_dimensions(dims)
    except Exception as exc:
        logger.warning(
            "build_meeting_behavior_context failed for meeting=%s: %s",
            meeting.id, exc,
        )
        return ""
