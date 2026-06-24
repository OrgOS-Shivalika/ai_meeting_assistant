"""send_email — STUB. Send an email.

To wire:
  1. Pick a provider (SendGrid / Postmark / SES) + per-org config
  2. Implement handler with the provider's SDK
  3. Expand parameters with `to`, `cc`, `subject`, `body_html`, `body_text`
  4. Add compliance check: deny if `compliance_and_guardrails.restrict_external_sharing=true`
  5. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="send_email",
    description="Send an email (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("send_email"),
    implemented=False,
    tags=["stub", "email"],
))
