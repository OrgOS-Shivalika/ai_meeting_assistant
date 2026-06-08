"""Phase 12C+ — Closing briefing services.

- `briefing_composer.py` (12C) — reads MeetingState, returns BriefingScript
- `tts_service.py` (12D) — text -> audio
- `audio_player.py` (12D) — uploads + plays via Recall.ai
- `closing_briefing_orchestrator.py` (12E) — wires the lifecycle events
  from 12A to the composer + TTS + Recall calls
"""
