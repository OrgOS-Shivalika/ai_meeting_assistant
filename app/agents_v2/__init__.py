"""Agents v2 — per-team agent runtime.

See AGENTS_V2_PLAN.md at the project root for the full design.

This package is the NEW path for meeting analysis; it lives alongside the
legacy `app/services/agents/` while we migrate. Route decision happens
per-meeting via the presence of an `agents_v2` DB row for the meeting's
scope — no meeting is broken during the transition.
"""
