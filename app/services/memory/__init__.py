"""app.services.memory — Phase 1 of the memory layer.

Public surface:
  - MemoryAccess  : the only authorized reader/writer of org_memory_facts
                    (cross-meeting recall — answers "who owns X?" etc.)
  - MeetingMemoryEngine (next file) : the once-per-meeting distiller that
                    emits 0–10 facts from a completed meeting

See /memory_plan_second.md for the active plan.
"""
from app.services.memory.access import MemoryAccess  # noqa: F401
from app.services.memory.long_term import LongTermMemory  # noqa: F401
