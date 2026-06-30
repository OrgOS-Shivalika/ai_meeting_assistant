import requests

from app.services.recall_ai_service import RecallService
from app.processors.transcript_processor import TranscriptProcessor
from app.ai_agents.transcript_analyzer import TranscriptAnalyzer
from app.services.kanban.defaults import resolve_landing_for_meeting
from app.services.kanban.positions import position_for_end
from app.utils.logger import setup_logger
import json
from app.db.models import Meeting, Task, Participant
from sqlalchemy.orm import Session
from datetime import datetime

logger = setup_logger(__name__)

class MeetingPipeline:

    def __init__(self):
        self.recall = RecallService()

    def parse_iso_date(self, date_str):
        if not date_str:
            return None
        try:
            # Handle YYYY-MM-DD or full ISO
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse date string: {date_str}")
            return None

    def save_participants(self, db, meeting, transcript_json, bot_data=None):
        # Unique participants from transcript using their Recall ID
        unique_participants = {} # recall_id -> name

        # 1. First, populate from Recall bot's meeting_participants list (if available)
        # This list includes everyone who joined the meeting, even if they didn't speak.
        if bot_data and "meeting_participants" in bot_data:
            logger.info(f"Using bot metadata for {len(bot_data['meeting_participants'])} participants")
            for p in bot_data["meeting_participants"]:
                p_id = p.get("id")
                name = p.get("name")
                if p_id and name:
                    unique_participants[p_id] = name

        # 2. Fallback/Supplement from transcript (just in case).
        # transcript_json may be None when Recall's compiled transcript
        # failed and we fell back to the live transcript — in that case
        # we rely entirely on bot_data["meeting_participants"] above.
        for block in (transcript_json or []):
            p_info = block.get("participant", {})
            p_id = p_info.get("id")
            name = p_info.get("name")
            if p_id and name and p_id not in unique_participants:
                unique_participants[p_id] = name
        
        # Get attendee map from Google Calendar data if available
        attendee_map = {}
        
        # If google_event_data is missing, try to fetch it if we have a user with google tokens
        if not meeting.google_event_data and meeting.user and meeting.user.google_access_token:
            try:
                from app.services.google_calendar_service import get_calendar_events
                from sqlalchemy.exc import IntegrityError
                events = get_calendar_events(meeting.user)
                for event in events:
                    if event.get("hangoutLink") == meeting.meeting_url:
                        try:
                            meeting.google_event_id = event.get("id")
                            meeting.google_event_data = event
                            db.commit()
                            logger.info(f"Dynamically found matching Google event for meeting {meeting.id}")
                            break
                        except IntegrityError:
                            db.rollback()
                            logger.warning(f"Google event {event.get('id')} already linked to another meeting. Skipping dynamic fetch for meeting {meeting.id}.")
                            meeting.google_event_id = None
                            meeting.google_event_data = None
                            break
            except Exception as e:
                logger.error(f"Failed to dynamically fetch calendar data: {str(e)}")

        if meeting.google_event_data and "attendees" in meeting.google_event_data:
            logger.info(f"Processing {len(meeting.google_event_data['attendees'])} attendees from Google data")
            for attendee in meeting.google_event_data["attendees"]:
                a_email = attendee.get("email")
                if not a_email:
                    continue
                
                # Store by exact email (Recall often uses email if display name is missing)
                attendee_map[a_email.lower()] = a_email

                # Store by full name
                a_name = attendee.get("displayName")
                if a_name:
                    attendee_map[a_name.lower()] = a_email
                
                # Store by email prefix (common in Recall AI)
                prefix = a_email.split("@")[0].lower()
                attendee_map[prefix] = a_email
                
                # Store by parts of name
                if a_name:
                    for part in a_name.lower().split():
                        if len(part) > 2: # ignore short names
                            attendee_map[part] = a_email

        logger.info(f"Cross-referencing {len(unique_participants)} participants with {len(attendee_map)} unique calendar mapping keys")
        logger.info(f"Mapping keys available: {list(attendee_map.keys())}")

        # Track name occurrences for database display names
        name_counts = {}
        for p_id, name in unique_participants.items():
            if name not in name_counts:
                name_counts[name] = 0
            name_counts[name] += 1

        current_counts = {}

        for p_id, name in unique_participants.items():
            display_name = name
            if name_counts[name] > 1:
                if name not in current_counts:
                    current_counts[name] = 0
                current_counts[name] += 1
                display_name = f"{name} ({current_counts[name]})"

            # Try to find email using multiple strategies
            email = attendee_map.get(name.lower())
            is_organizer = False
            
            if not email:
                # Try matching by first name or last name
                for part in name.lower().split():
                    if part in attendee_map:
                        email = attendee_map[part]
                        break
            
            # Check if this person is the organizer
            if email and meeting.google_event_data and meeting.google_event_data.get("organizer", {}).get("email") == email:
                is_organizer = True
            
            logger.debug(f"Matching participant: '{name}' -> Email: {email or 'NOT FOUND'}, Organizer: {is_organizer}")
            
            participant = Participant(
                meeting_id=meeting.id,
                name=display_name,
                recall_id=p_id,
                email=email,
                is_organizer=str(is_organizer) # Maintaining string compatibility for now
            )
            db.add(participant)
        
        db.commit()

    def save_tasks(self, db, meeting_id, tasks):
        # Harness-aware short-circuit: if the action_items skill ran
        # through the tool-calling harness, it ALREADY created tasks
        # for this meeting via `create_task`. The master analyzer's
        # `action_items` list (passed here) would then duplicate them
        # — phrased slightly differently, so the per-text dedup below
        # wouldn't always catch them. Skip when we see harness rows.
        #
        # Local import to keep models out of the pipeline's hot path
        # for legacy callers that never touch the harness.
        from app.db.models import AgentToolInvocation
        harness_created = (
            db.query(AgentToolInvocation.id)
            .filter(
                AgentToolInvocation.meeting_id == meeting_id,
                AgentToolInvocation.tool_name == "create_task",
                AgentToolInvocation.success.is_(True),
            )
            .first()
        )
        if harness_created is not None:
            logger.info(
                "save_tasks: skipping %d analyzer task(s) for meeting %s — "
                "harness already created tasks via create_task.",
                len(tasks), meeting_id,
            )
            return

        for t in tasks:
            task_text = t.get("task")
            if not task_text:
                continue

            # Check if this task was already captured (e.g. by the Live Engine)
            existing = db.query(Task).filter(
                Task.meeting_id == meeting_id,
                Task.task == task_text
            ).first()

            if existing:
                # Update existing record with final analysis details.
                # status + is_completed stay untouched — the live engine
                # owns those during the meeting; the analyzer just
                # refines metadata fields.
                existing.owner_name = t.get("owner")
                existing.priority = t.get("priority", "medium")
                existing.due_date = self.parse_iso_date(t.get("due_date"))
                logger.debug(f"Harmonized final task {existing.id} with live version")
            else:
                # Phase 14 — new analyzer-extracted tasks (which happen
                # when the live engine missed something) also need to
                # land on the org default board's "To Do" column.
                # Meeting is already in scope here; fetch its
                # organization_id lazily through the relationship.
                meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
                board_id, column_id = (None, None)
                position = None
                if meeting is not None:
                    board_id, column_id = resolve_landing_for_meeting(
                        db, meeting.organization_id, status="todo",
                    )
                    if column_id is not None:
                        position = position_for_end(db, column_id)

                task = Task(
                    meeting_id=meeting_id,
                    task=task_text,
                    owner_name=t.get("owner"),
                    priority=t.get("priority", "medium"),
                    due_date=self.parse_iso_date(t.get("due_date")),
                    status="todo",
                    board_id=board_id,
                    column_id=column_id,
                    position=position,
                )
                db.add(task)
                logger.debug(
                    "Saved new final task for meeting %s (board=%s, column=%s)",
                    meeting_id, board_id, column_id,
                )

        db.commit()


    def run(self, db, meeting):
        try:
            meeting_url = meeting.meeting_url

            logger.info(f"🤖 Creating bot for URL: {meeting_url}")
            bot = self.recall.create_bot(meeting_url, meeting.id)

            bot_id = bot["id"]

            meeting.bot_id = bot_id
            db.commit()

            logger.info(f"⏳ Waiting for transcript for bot_id: {bot_id}")
            # Phase 12E — pass meeting_id so the polling loop can
            # self-deliver bot.status_change=call_ended webhooks when
            # Recall fails to deliver them via the per-bot webhook_url.
            #
            # Resilience: when Recall's underlying transcription provider
            # (AssemblyAI) fails mid-meeting with `provider_connection_failed`
            # or similar, wait_for_transcript raises. In that case we fall
            # back to the LIVE transcript captured via WebSocket during
            # the meeting (Phase 11) — the text is already in
            # `meeting.transcript` and is sufficient for AI analysis,
            # embedding, and graph extraction. We just lose the typed
            # JSON shape that gives us speaker-perfect attribution.
            transcript_json = None
            formatted = None
            try:
                transcript_url = self.recall.wait_for_transcript(
                    bot_id, meeting_id=meeting.id,
                )
                logger.info("📥 Fetching transcript...")
                transcript_json = requests.get(transcript_url).json()
                meeting.transcript_raw = transcript_json
                db.commit()

                logger.info("🧾 Formatting transcript...")
                formatted = TranscriptProcessor.format(transcript_json)
            except Exception as transcript_exc:
                # Compiled-transcript path failed. Try the live fallback.
                live_text = meeting.transcript or ""
                if len(live_text.strip()) < 100:
                    # No usable live data either — propagate the failure.
                    logger.error(
                        f"❌ Recall transcript failed AND no live fallback "
                        f"available (live_len={len(live_text)}): {transcript_exc}"
                    )
                    raise
                logger.warning(
                    f"⚠️  Recall compiled transcript failed ({transcript_exc}); "
                    f"falling back to live transcript ({len(live_text)} chars)"
                )
                # Live transcript is already in "Speaker: text\n" format
                # (per the Phase 12E persistence helper) — that's exactly
                # what TranscriptProcessor.format() would produce, so we
                # can feed it directly into the analyzer.
                formatted = live_text
                # transcript_raw stays NULL — downstream consumers should
                # check transcript_text / transcript before transcript_raw.

            meeting.transcript_text = formatted
            db.commit()

            # ✅ Save Participants
            logger.info("👥 Saving participants...")
            try:
                bot_data = self.recall.get_bot(bot_id)
            except Exception:
                bot_data = None
            self.save_participants(db, meeting, transcript_json, bot_data=bot_data)

            # Phase 9.6 — Agent Graph Orchestration.
            # Use the orchestrator to run capability-based analysis.
            # The orchestrator handles BehaviorProfile resolution internally
            # or we can pass it in if we already have it. 
            logger.info("🕸️  Running Orchestrated AI analysis (Phase 9.6)...")
            from app.services.agents.graph_orchestrator import AgentGraphOrchestrator
            from app.services.behavior.resolver import resolve_behavior_profile
            
            # 1. Resolve the profile once for the entire runtime execution
            prof = resolve_behavior_profile(
                db,
                organization_id=meeting.organization_id,
                category_id=meeting.category_id,
                team_id=meeting.team_id
            )

            # 2. Execute the Agent Graph
            # meeting_id MUST be passed — the harness threads it through
            # ToolContext to every tool. Without it, create_task can't
            # resolve which meeting to attach the new task to and fails
            # every call.
            result_obj = AgentGraphOrchestrator.run_meeting_analysis(
                db,
                formatted,
                prof,
                meeting_id=meeting.id,
            )

            # result_obj is a typed ExtractionSummary instance
            result_json = result_obj.model_dump()

            # save title
            title = result_obj.title or f"Meeting {meeting.id}"
            meeting.title = title

            # Save summary
            summary = result_obj.summary
            meeting.summary = summary
            logger.info(f"Summary generated: {summary[:50]}...")

            meeting.status = "completed"
            db.commit()

            # Save tasks BEFORE broadcasting so the frontend refetch sees the
            # complete picture (transcript_raw, summary, tasks) on the first
            # round-trip instead of needing a manual page refresh.
            self.save_tasks(db, meeting.id, result_json.get("action_items", []))

            # Memory Phase 1 — distill durable facts from this meeting.
            # Best-effort, wrapped non-fatal: a distiller failure must NEVER
            # fail a completed meeting. Cost ≈ $0.001/meeting (one
            # gpt-4o-mini call + N embeddings). Idempotent: a retry skips
            # if any active facts already exist for this meeting.
            try:
                from app.services.memory.engine import MeetingMemoryEngine
                distill_report = MeetingMemoryEngine.distill_for_meeting(db, meeting.id)
                logger.info(
                    "💭 MemoryEngine meeting=%s report=%s",
                    meeting.id, distill_report,
                )
            except Exception as mem_err:
                logger.error(
                    "MeetingMemoryEngine failed for meeting=%s (non-fatal): %s",
                    meeting.id, mem_err,
                )

            # Phase 9.3 — Compliance Runtime Gating & 9.5 Automation.
            try:
                from app.services.compliance.runtime import ComplianceRuntime
                from app.services.automation.bus import AutomationBus, AutomationEvent
                
                # Apply redaction gated by the same ResolvedBehaviorProfile
                ComplianceRuntime.apply_to_meeting(db, meeting, prof)
                db.commit() # Save the redacted version
                logger.info("🛡️ Compliance policies applied (redaction gated).")

                # Emit normalized events for authorized subscribers.
                AutomationBus.emit(
                    db, 
                    AutomationEvent(
                        "meeting.summary.completed", 
                        meeting.organization_id, 
                        meeting.id, 
                        {"title": meeting.title, "summary": meeting.summary}
                    ),
                    prof
                )
                if result_json.get("action_items"):
                    AutomationBus.emit(
                        db,
                        AutomationEvent(
                            "meeting.tasks.extracted",
                            meeting.organization_id,
                            meeting.id,
                            result_json["action_items"]
                        ),
                        prof
                    )

            except Exception as comp_err:
                logger.error("Compliance or Automation gating failed: %s", comp_err)

            # Broadcast status update via WebSocket
            try:
                from app.api.ws_router import manager
                import asyncio
                # Since this is a synchronous method running in a thread, we use asyncio.run
                asyncio.run(manager.broadcast(meeting.id, {"type": "status_update", "status": "completed"}))
            except Exception as ws_err:
                logger.error(f"Failed to broadcast status update: {ws_err}")

            # --- NEW: Session Cleanup ---
            try:
                from app.services.live_stream.stream_manager import stream_manager
                from app.services.meeting_memory.meeting_state_store import state_store
                stream_manager.end_session(str(meeting.id))
                state_store.remove_state(str(meeting.id))
                logger.info(f"🧹 Cleaned up live session and state for meeting {meeting.id}")
            except Exception as clean_err:
                logger.error(f"Failed to cleanup meeting session {meeting.id}: {clean_err}")

            # Phase 2: fan out to the embedding pipeline. Best-effort —
            # `dispatch_embed_meeting` swallows its own errors so a broken
            # embedding setup never poisons the main meeting flow.
            try:
                from app.celery_tasks.embedding_tasks import dispatch_embed_meeting
                dispatch_embed_meeting(meeting.id)
            except Exception as embed_err:
                logger.error(
                    "Failed to dispatch embedding for meeting %s: %s",
                    meeting.id, embed_err,
                )

            return result_json

        except Exception as e:
            import traceback as _tb
            tb = _tb.format_exc()
            logger.error(f"Pipeline failed: {str(e)}\n{tb}")

            meeting.status = "failed"
            # Persist the failure reason so post-mortem doesn't need
            # the celery scrollback. Trim to keep the row sane.
            meeting.error_message = (f"{type(e).__name__}: {e}\n\n{tb}")[:8000]
            db.commit()
            
            # Broadcast status update via WebSocket
            try:
                from app.api.ws_router import manager
                import asyncio
                asyncio.run(manager.broadcast(meeting.id, {"type": "status_update", "status": "failed"}))
            except Exception as ws_err:
                logger.error(f"Failed to broadcast failure status update: {ws_err}")

            raise
    

