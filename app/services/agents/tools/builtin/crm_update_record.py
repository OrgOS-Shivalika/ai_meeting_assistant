"""crm_update_record — STUB. Update a CRM record (HubSpot / Salesforce).

To wire:
  1. Multi-provider CRM abstraction (HubSpot, Salesforce, etc.) +
     per-org auth tokens
  2. Implement handler that dispatches to the right provider client
  3. Expand parameters with `object_type` (contact/deal/account),
     `record_id`, `fields`
  4. Flip implemented=True
"""
from __future__ import annotations

from app.services.agents.tools.registry import Tool, register
from app.services.agents.tools.builtin._stub import make_handler


register(Tool(
    name="crm_update_record",
    description="Update a CRM record (NOT WIRED — placeholder).",
    parameters={"type": "object", "properties": {}},
    handler=make_handler("crm_update_record"),
    implemented=False,
    tags=["stub", "crm"],
))
