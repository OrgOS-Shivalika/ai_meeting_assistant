import requests

from app.services.recall_ai_service import RecallService
from app.processors.transcript_processor import TranscriptProcessor
from app.ai_agents.transcript_analyzer import TranscriptAnalyzer
from app.services.kanban.defaults import resolve_landing_for_meeting
from app.services.kanban.positions import position_for_end
from app.services.kanban import assignees
from app.utils.logger import setup_logger
import json
from app.db.models import Meeting, Task, Participant, User
from app.utils.admin_enums import ParticipantMatchSource
from sqlalchemy import func
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
        # Unique participants keyed by their Recall ID. The value is the
        # display name, or None until a real one turns up.
        unique_participants: dict = {}

        def _remember(p_id, name) -> None:
            """Record one attendee.

            An id with no name is still an attendee. Recall routinely
            emits `{"id": 101, "name": null}` for dial-ins, guests, and
            anyone whose platform profile it can't read — and the old
            `if p_id and name` guard dropped every one of them, which is
            why meetings showed fewer attendees than their transcript
            contains (and zero when the only speaker was nameless). The
            live webhook path already synthesizes the same placeholder;
            this makes the batch path agree with it.

            `is not None` rather than truthiness because Recall numbers
            participants from 0 on some platforms.
            """
            if p_id is None:
                return
            real = (name or "").strip()
            # A real name always wins over a placeholder; a nameless
            # sighting never overwrites a name we already have.
            if real or p_id not in unique_participants:
                unique_participants[p_id] = real or None

        # 1. First, populate from Recall bot's meeting_participants list (if available)
        # This list includes everyone who joined the meeting, even if they didn't speak.
        if bot_data and "meeting_participants" in bot_data:
            logger.info(f"Using bot metadata for {len(bot_data['meeting_participants'])} participants")
            for p in bot_data["meeting_participants"]:
                _remember(p.get("id"), p.get("name"))

        # 2. Fallback/Supplement from transcript (just in case).
        # transcript_json may be None when Recall's compiled transcript
        # failed and we fell back to the live transcript — in that case
        # we rely entirely on bot_data["meeting_participants"] above.
        for block in (transcript_json or []):
            p_info = block.get("participant") or {}
            _remember(p_info.get("id"), p_info.get("name"))

        # Label whoever Recall never named, so the row is still saved and
        # renders as something a human can pick out of a list.
        unique_participants = {
            p_id: name or f"Participant {p_id}"
            for p_id, name in unique_participants.items()
        }

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

        # Two maps, not one, because they carry different levels of
        # trust and `participants.user_id` is now an authorization
        # input rather than just an avatar lookup.
        #
        #   exact_map — the Recall name IS the attendee's email, or IS
        #               their full calendar display name. Unambiguous.
        #   fuzzy_map — email local-part, or a single token of a display
        #               name. Good enough to render a face next to a
        #               transcript line; nowhere near good enough to
        #               decide who may read the meeting. Two colleagues
        #               named "Chris" resolve to the same token.
        #
        # A link made through fuzzy_map is stored with
        # match_source='heuristic' and grants nothing — see
        # `permissions.TRUSTED_MATCH_SOURCES`.
        exact_map: dict[str, str] = {}
        fuzzy_map: dict[str, str] = {}
        ambiguous_fuzzy_keys: set[str] = set()

        def _add_fuzzy(key: str, email: str) -> None:
            """Record a loose key, tracking collisions.

            When two attendees claim the same token the key is poisoned
            rather than won by whoever the iteration order happened to
            reach first — a silently wrong avatar is bad, and the same
            code path used to feed access decisions."""
            existing = fuzzy_map.get(key)
            if existing and existing.lower() != email.lower():
                ambiguous_fuzzy_keys.add(key)
            else:
                fuzzy_map[key] = email

        if meeting.google_event_data and "attendees" in meeting.google_event_data:
            logger.info(f"Processing {len(meeting.google_event_data['attendees'])} attendees from Google data")
            for attendee in meeting.google_event_data["attendees"]:
                a_email = attendee.get("email")
                if not a_email:
                    continue

                # Exact: the email itself (Recall often uses the email
                # when a display name is missing).
                exact_map[a_email.strip().lower()] = a_email

                # Exact: the complete display name.
                a_name = (attendee.get("displayName") or "").strip()
                if a_name:
                    exact_map[a_name.lower()] = a_email

                # Fuzzy: email local-part, common in Recall.ai output.
                _add_fuzzy(a_email.split("@")[0].strip().lower(), a_email)

                # Fuzzy: individual name tokens.
                if a_name:
                    for part in a_name.lower().split():
                        if len(part) > 2:  # ignore initials / particles
                            _add_fuzzy(part, a_email)

        for key in ambiguous_fuzzy_keys:
            fuzzy_map.pop(key, None)

        logger.info(
            "Cross-referencing %d participants with %d exact and %d unambiguous "
            "fuzzy calendar keys (%d keys dropped as ambiguous)",
            len(unique_participants), len(exact_map), len(fuzzy_map),
            len(ambiguous_fuzzy_keys),
        )

        # Idempotency. A re-run (scripts/rerun_analysis.py, a Celery
        # retry, a second dispatch for the same meeting) used to append a
        # whole extra copy of every attendee — hence meetings carrying
        # exactly 2× or 3× their real participant count.
        #
        # Skip ids already on the meeting rather than delete-and-reinsert:
        # a row may carry a hand-made `match_source='manual'` link, which
        # is the only recovery from a failed calendar match, and wiping it
        # silently revokes that person's access to the meeting.
        already_saved = {
            r[0]
            for r in db.query(Participant.recall_id)
            .filter(Participant.meeting_id == meeting.id)
            .all()
        }

        # Track name occurrences for database display names
        name_counts = {}
        for p_id, name in unique_participants.items():
            if name not in name_counts:
                name_counts[name] = 0
            name_counts[name] += 1

        current_counts = {}

        for p_id, name in unique_participants.items():
            if str(p_id) in already_saved:
                logger.debug(
                    "Participant %s already on meeting %s — not duplicating",
                    p_id, meeting.id,
                )
                continue

            display_name = name
            if name_counts[name] > 1:
                if name not in current_counts:
                    current_counts[name] = 0
                current_counts[name] += 1
                display_name = f"{name} ({current_counts[name]})"

            # Per participant, not per meeting. Without the reset the
            # first organizer match leaked onto everyone processed after
            # them — and before this line existed at all the reference
            # below raised NameError on the first non-organizer, which is
            # nearly every call, so no participant rows were written and
            # member access could never work.
            is_organizer = False

            # Exact first, and remember which path won — the answer
            # decides whether this person gets access to the meeting.
            lookup = name.strip().lower()
            email = exact_map.get(lookup)
            match_source = (
                ParticipantMatchSource.CALENDAR_EXACT.value if email else None
            )

            if not email:
                for part in lookup.split():
                    if part in fuzzy_map:
                        email = fuzzy_map[part]
                        match_source = ParticipantMatchSource.HEURISTIC.value
                        break

            # Check if this person is the organizer
            if email and meeting.google_event_data and meeting.google_event_data.get("organizer", {}).get("email") == email:
                is_organizer = True

            # Attendance is membership, so this is the row that grants a
            # member their access. Exact, case-normalized email equality
            # against a user in the SAME organization — never a name.
            linked_user_id = None
            if email:
                linked_user = (
                    db.query(User)
                    .filter(
                        func.lower(User.email) == email.strip().lower(),
                        User.organization_id == meeting.organization_id,
                    )
                    .first()
                )
                linked_user_id = linked_user.id if linked_user else None
            if linked_user_id is None:
                # No account behind this attendee (external guest,
                # dial-in, or someone who hasn't signed up yet).
                # Provenance describes a link, so with no link there's
                # nothing to describe.
                match_source = None

            logger.debug(
                "Matching participant: '%s' -> email=%s source=%s user=%s organizer=%s",
                name, email or "NOT FOUND", match_source or "-",
                linked_user_id or "-", is_organizer,
            )

            participant = Participant(
                meeting_id=meeting.id,
                name=display_name,
                # str() explicitly: the column is String, Recall sends an
                # int, and `already_saved` above compares against what
                # Postgres gives back. Leaving the coercion implicit meant
                # the in-memory row and the stored row differed by type.
                recall_id=str(p_id),
                email=email,
                user_id=linked_user_id,
                match_source=match_source,
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
                        category_id=meeting.category_id,
                        team_id=meeting.team_id,
                    )
                    if column_id is not None:
                        position = position_for_end(db, column_id)

                # Resolve the analyzer's owner LABEL to a real account where it
                # unambiguously names one. Doing it here is what stops this
                # being a backfill problem forever: a task that arrives
                # assigned needs no cleanup later.
                #
                # Deliberately NOT wrapped in try/except. The resolver is one
                # indexed query — if it can fail, the Task insert two lines
                # below has already failed. Swallowing here would be the
                # silent-failure pattern that hides dead features in this
                # codebase.
                # Guarded, like the board lookup above: `meeting` is a
                # .first() and the code five lines up already treats None as
                # reachable. Unguarded this would AttributeError and take down
                # task saving for the entire meeting.
                assignee = (
                    assignees.resolve_assignee(
                        db, meeting.organization_id, t.get("owner")
                    )
                    if meeting is not None
                    else None
                )

                task = Task(
                    meeting_id=meeting_id,
                    task=task_text,
                    owner_name=t.get("owner"),
                    assignee_user_id=assignee.id if assignee else None,
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

            # Idempotency guard — if a bot has already been dispatched for
            # this meeting, do NOT create a second one. Any duplicate call to
            # process_meeting (manual re-dispatch, calendar-sync re-trigger,
            # celery retry after a crashed worker) would otherwise send an
            # orphan bot into the same Meet — hence the "two bots joined"
            # bug in production.
            if meeting.bot_id:
                logger.warning(
                    f"⚠️  Meeting {meeting.id} already has bot_id={meeting.bot_id} — "
                    f"skipping duplicate bot creation. Reusing existing bot."
                )
                bot_id = meeting.bot_id
            else:
                # Cross-meeting dedup — protects against the "two rows
                # racing to dispatch a bot for the same Meet URL" case.
                # Happens when /inject-bot and the calendar-sync beat
                # tick fire concurrently against the same URL, or when
                # a user pastes a URL that already has an active bot
                # from another entry point.
                #
                # If ANOTHER active meeting for the same URL already has
                # a bot, don't send a second one — mark this meeting as
                # failed so it doesn't sit as "processing" forever.
                from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                cutoff = _dt.now(_tz.utc) - _td(minutes=15)
                other = (
                    db.query(Meeting)
                    .filter(
                        Meeting.id != meeting.id,
                        Meeting.meeting_url == meeting_url,
                        Meeting.bot_id.isnot(None),
                        Meeting.status.in_(("pending", "processing")),
                        Meeting.created_at >= cutoff,
                    )
                    .order_by(Meeting.created_at.desc())
                    .first()
                )
                if other:
                    logger.warning(
                        "⛔ Meeting %s aborted — another meeting %s already "
                        "dispatched bot %s for %s; not sending a duplicate.",
                        meeting.id, other.id, other.bot_id, meeting_url,
                    )
                    meeting.status = "failed"
                    meeting.error_message = (
                        f"Duplicate — bot already dispatched by meeting {other.id}."
                    )
                    db.commit()
                    return

                logger.info(f"🤖 Creating bot for URL: {meeting_url}")
                # capture_mode decides whether Recall asks the transcription
                # provider to separate voices. It has to be known BEFORE the
                # bot exists — audio that was not analysed for distinct
                # voices cannot be re-analysed from the transcript later.
                bot = self.recall.create_bot(
                    meeting_url, meeting.id,
                    capture_mode=meeting.capture_mode or "online",
                )
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
            # Bound before the try because the live-transcript fallback below
            # produces no attribution at all — there is no `transcript_raw` to
            # derive voices from, so nothing to persist.
            label_resolutions: dict = {}
            try:
                transcript_url = self.recall.wait_for_transcript(
                    bot_id, meeting_id=meeting.id,
                )
                logger.info("📥 Fetching transcript...")
                transcript_json = requests.get(transcript_url).json()
                meeting.transcript_raw = transcript_json
                db.commit()

                logger.info("🧾 Formatting transcript...")
                # capture_mode routes in-room meetings through voice-cluster
                # attribution; online meetings take the identical path they
                # always have. The calendar attendee list is what turns a
                # roll-call name from a guess into a corroborated match — see
                # `speaker_attribution._validate_candidate`.
                formatted, label_resolutions, _diag = (
                    TranscriptProcessor.format_detailed(
                        transcript_json,
                        capture_mode=meeting.capture_mode or "online",
                        calendar_attendees=(
                            (meeting.google_event_data or {}).get("attendees")
                        ),
                    )
                )
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

            # In-room attribution: persist "voice cluster N is Karthik" and
            # give each separated voice an attendee row.
            #
            # Empty for every online meeting, so this is a no-op on the path
            # that already works. Non-fatal because the names are ALREADY in
            # `transcript_text` by this point — losing these rows costs the
            # correction UI its data, not the meeting its notes. Logged at
            # ERROR rather than warning precisely because the degradation is
            # otherwise invisible.
            if label_resolutions:
                try:
                    from app.services import speaker_labels
                    speaker_labels.persist_resolutions(
                        db, meeting.id, label_resolutions,
                    )
                    speaker_labels.save_room_speakers(
                        db, meeting, label_resolutions,
                    )
                except Exception as label_err:
                    db.rollback()
                    logger.error(
                        "Speaker label persistence failed for meeting %s — "
                        "notes are correctly attributed but the correction UI "
                        "will have nothing to edit: %s",
                        meeting.id, label_err, exc_info=True,
                    )

            # Resolve the behaviour profile ONCE, before the routing branch.
            #
            # It must be bound on both paths: the legacy orchestrator takes it
            # as an argument, and the compliance + automation block further
            # down gates on it regardless of which path produced `result_obj`.
            # Resolving it inside the `else` left it unbound on every
            # agents_v2 meeting, and the resulting NameError was caught by
            # that block's `except Exception` — so PII redaction and every
            # automation event were silently skipped rather than erroring.
            from app.services.behavior.resolver import resolve_behavior_profile
            prof = resolve_behavior_profile(
                db,
                organization_id=meeting.organization_id,
                category_id=meeting.category_id,
                team_id=meeting.team_id
            )

            # Agents v2 feature flag — if there's an agents_v2 row for
            # this meeting's scope, route through the new orchestrator.
            # Otherwise fall through to the legacy Phase 9.6 path.
            # Presence of the DB row IS the feature flag — no env var.
            from app.agents_v2 import orchestrator as v2_orchestrator
            if v2_orchestrator.has_agent_for_scope(db, meeting):
                logger.info("🆕 Routing meeting %s through agents_v2 pipeline", meeting.id)
                result_obj = v2_orchestrator.run_meeting_analysis(db, formatted, meeting)
            else:
                # Phase 9.6 — Agent Graph Orchestration.
                # Use the orchestrator to run capability-based analysis.
                logger.info("🕸️  Running Orchestrated AI analysis (Phase 9.6)...")
                from app.services.agents.graph_orchestrator import AgentGraphOrchestrator

                # Execute the Agent Graph
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

            # Continuum Core: if this meeting belongs to a Continuum
            # client (team linked to a cc_clients row), feed the
            # transcript into the client's board. Best-effort — the
            # dispatcher swallows its own errors and skips non-Continuum
            # meetings cheaply.
            try:
                from app.celery_tasks.continuum_tasks import dispatch_continuum_process
                dispatch_continuum_process(meeting.id)
            except Exception as cc_err:
                logger.error(
                    "Failed to dispatch continuum processing for meeting %s: %s",
                    meeting.id, cc_err,
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
    

