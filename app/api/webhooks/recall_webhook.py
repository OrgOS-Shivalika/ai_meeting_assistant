from fastapi import APIRouter, Request, HTTPException
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.api.ws_router import manager
from app.utils.logger import setup_logger
import json

logger = setup_logger(__name__)

recall_webhook_router = APIRouter()


def extract_transcript_fields(payload: dict, event: str) -> tuple:
    """Extract speaker, text, is_final from Recall.ai payload.
    Handles various nested formats from Recall.ai webhooks and WebSockets.
    """
    data_block = payload.get("data", {})
    
    # 1. Handle the deep format: payload['data']['data']['transcript' or 'words']
    inner_data = data_block.get("data", {})
    if isinstance(inner_data, dict):
        source = inner_data.get("transcript") or inner_data
    else:
        source = data_block.get("transcript") or data_block

    # 2. Extract Speaker
    participant = source.get("participant", {})
    if isinstance(participant, dict):
        speaker = participant.get("name", "Unknown Speaker")
    else:
        speaker = source.get("speaker", "Unknown Speaker")

    # 3. Determine if Final
    is_final = source.get("is_final", event == "transcript.data")

    # 4. Extract Text
    text = source.get("text", "")
    if not text:
        # Check for 'words' list and join them
        words = source.get("words", [])
        if words:
            text = " ".join([w.get("text", "") for w in words]).strip()
    
    return speaker, text, is_final


async def process_transcript_event(meeting_id: int, payload: dict):
    event = payload.get("event")

    if event not in ["transcript.data", "transcript.partial_data"]:
        return

    speaker, text, is_final = extract_transcript_fields(payload, event)

    if not text:
        logger.warning(f"[LIVE TRANSCRIPT] Empty text for meeting {meeting_id} | payload: {json.dumps(payload)}")
        return

    formatted_line = f"{speaker}: {text}"
    logger.info(f"[LIVE TRANSCRIPT] Meeting {meeting_id} | {event} | Final: {is_final} | {formatted_line}")

    ws_message = {
        "type": "transcript_update",
        "speaker": speaker,
        "text": text,
        "is_final": is_final
    }

    await manager.broadcast(meeting_id, ws_message)

    # --- NEW: Pipe to Live Cognitive Engine ---
    if is_final:
        from app.services.live_stream.stream_manager import stream_manager
        from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
        import asyncio
        from datetime import datetime

        # 1. Ensure Session exists
        stream_manager.start_session(str(meeting_id))

        # 2. Ingest Chunk (Offload to thread to avoid blocking webhook)
        chunk = LiveTranscriptChunk(
            speaker_id="recall_auto",
            speaker_name=speaker,
            text=text,
            is_final=True,
            sequence_number=int(datetime.now().timestamp())
        )
        
        # Trigger background task for detection & stabilization
        asyncio.create_task(asyncio.to_thread(stream_manager.ingest_chunk, str(meeting_id), chunk))

    if is_final:
        db = SessionLocal()
        try:
            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            if meeting:
                current_transcript = meeting.transcript or ""
                meeting.transcript = current_transcript + ("\n" if current_transcript else "") + formatted_line
                db.commit()
            else:
                logger.warning(f"Meeting {meeting_id} not found for transcript save")
        except Exception as e:
            db.rollback()
            logger.error(f"DB error saving transcript for meeting {meeting_id}: {e}")
        finally:
            db.close()


@recall_webhook_router.post("/webhook/recall/{meeting_id}")
async def handle_recall_webhook(meeting_id: int, request: Request):
    try:
        payload = await request.json()
        event = payload.get("event", "unknown")
        
        # Super loud logging for debugging
        print(f"\n>>> WEBHOOK RECEIVED: event={event}, meeting_id={meeting_id}")
        logger.info(f"Webhook from Recall | event={event} | meeting_id={meeting_id}")
        
        # Check if it's a transcript event
        if "transcript" in event:
            await process_transcript_event(meeting_id, payload)
        else:
            logger.info(f"Ignoring non-transcript event: {event}")

        return {"status": "ok"}
    except Exception as e:
        print(f"!!! ERROR IN WEBHOOK: {e}")
        logger.error(f"Error handling recall webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")


@recall_webhook_router.get("/webhook/debug/{meeting_id}")
async def debug_bot(meeting_id: int):
    """Check the Recall.ai bot config for a meeting to verify webhook URLs are set."""
    from app.services.recall_ai_service import RecallService
    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting or not meeting.bot_id:
            return {"error": f"Meeting {meeting_id} not found or has no bot_id"}

        recall = RecallService()
        bot_data = recall.get_bot(meeting.bot_id)
        return {
            "meeting_id": meeting_id,
            "bot_id": meeting.bot_id,
            "bot_status": bot_data.get("status_changes", [])[-1] if bot_data.get("status_changes") else None,
            "webhook_url": bot_data.get("webhook_url"),
            "realtime_endpoints": bot_data.get("recording_config", {}).get("realtime_endpoints"),
            "transcript_provider": bot_data.get("recording_config", {}).get("transcript", {}).get("provider"),
            "recordings_count": len(bot_data.get("recordings", [])),
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@recall_webhook_router.post("/webhook/test/{meeting_id}")
async def test_webhook(meeting_id: int):
    """Simulate a Recall.ai transcript webhook to verify the full pipeline."""
    active = {k: len(v) for k, v in manager.active_connections.items()}
    has_ws = meeting_id in manager.active_connections
    ws_count = len(manager.active_connections.get(meeting_id, []))

    test_payload = {
        "event": "transcript.data",
        "data": {
            "speaker": "Test Speaker",
            "speaker_id": 1,
            "words": [
                {"text": "This", "start_time": 0.0, "end_time": 0.2},
                {"text": "is", "start_time": 0.2, "end_time": 0.3},
                {"text": "a", "start_time": 0.3, "end_time": 0.4},
                {"text": "live", "start_time": 0.4, "end_time": 0.6},
                {"text": "transcript", "start_time": 0.6, "end_time": 0.9},
                {"text": "test.", "start_time": 0.9, "end_time": 1.1},
            ],
            "is_final": True,
            "language": "en"
        }
    }
    await process_transcript_event(meeting_id, test_payload)
    return {
        "status": "ok",
        "meeting_id": meeting_id,
        "ws_connected": has_ws,
        "ws_clients": ws_count,
        "all_active": active,
    }
