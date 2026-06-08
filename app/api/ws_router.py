from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import Meeting
from app.services.transcript_persistence import schedule_transcript_save

logger = logging.getLogger(__name__)

ws_router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, meeting_id: int):
        await websocket.accept()
        if meeting_id not in self.active_connections:
            self.active_connections[meeting_id] = []
        self.active_connections[meeting_id].append(websocket)
        logger.info(f"Frontend WebSocket connected for meeting {meeting_id}")

    def disconnect(self, websocket: WebSocket, meeting_id: int):
        if meeting_id in self.active_connections:
            if websocket in self.active_connections[meeting_id]:
                self.active_connections[meeting_id].remove(websocket)
            if not self.active_connections[meeting_id]:
                del self.active_connections[meeting_id]
        logger.info(f"Frontend WebSocket disconnected for meeting {meeting_id}")

    async def broadcast(self, meeting_id: int, message: dict):
        n = len(self.active_connections.get(meeting_id, []))
        logger.info(f"[WS BROADCAST] meeting={meeting_id} subscribers={n} type={message.get('type')} active_keys={list(self.active_connections.keys())}")
        if meeting_id not in self.active_connections:
            return
        dead: List[WebSocket] = []
        payload = json.dumps(message)
        for connection in self.active_connections[meeting_id]:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.error(f"Error sending message to websocket: {e}")
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn, meeting_id)

manager = ConnectionManager()

# --- Shared Parsing Logic ---
def extract_transcript_fields(payload: dict, event: str) -> tuple:
    """Extract speaker, text, is_final from Recall.ai payload."""
    data_block = payload.get("data", {})
    
    # 1. Handle the deep WebSocket format: payload['data']['data']['transcript' or 'words']
    inner_data = data_block.get("data")
    if inner_data and isinstance(inner_data, dict):
        source = inner_data.get("transcript") or inner_data
    else:
        source = data_block.get("transcript") or data_block

    # 2. Extract Speaker
    # In some WS versions, speaker is in participant['name']
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

# --- Existing Frontend Endpoint ---
@ws_router.websocket("/ws/{meeting_id}")
async def websocket_endpoint(websocket: WebSocket, meeting_id: int):
    await manager.connect(websocket, meeting_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, meeting_id)
    except Exception:
        manager.disconnect(websocket, meeting_id)

# --- NEW Recall.ai Receiver Endpoint ---
@ws_router.websocket("/ws/recall/{meeting_id}")
async def recall_websocket_receiver(websocket: WebSocket, meeting_id: int):
    """
    Recall.ai connects to this endpoint to push live transcript data.
    We receive it, parse it, and broadcast it to the frontend viewers.
    """
    await websocket.accept()
    logger.info(f"✅ Recall.ai connected via WebSocket for meeting {meeting_id}")
    
    try:
        while True:
            message_text = await websocket.receive_text()
            print(f"\n>>> WS RAW MESSAGE: {message_text[:300]}") # Debug raw payload
            try:
                payload = json.loads(message_text)
                event = payload.get("event")
                
                # We only care about transcript events
                if event not in ["transcript.data", "transcript.partial_data"]:
                    continue

                speaker, text, is_final = extract_transcript_fields(payload, event)

                if not text:
                    continue

                formatted_line = f"{speaker}: {text}"
                logger.info(f"[LIVE WS] Meeting {meeting_id} | {event} | Final: {is_final} | {formatted_line}")

                ws_message = {
                    "type": "transcript_update",
                    "speaker": speaker,
                    "text": text,
                    "is_final": is_final
                }

                # Push to all frontend viewers
                await manager.broadcast(meeting_id, ws_message)

                # --- NEW: Pipe to Live Cognitive Engine ---
                if is_final:
                    from app.services.live_stream.stream_manager import stream_manager
                    from app.services.live_stream.live_chunk_models import LiveTranscriptChunk
                    import asyncio

                    # 1. Ensure Session exists
                    stream_manager.start_session(str(meeting_id))

                    # 2. Ingest Chunk (Offload to thread to avoid blocking WS loop)
                    # We use a simple sequence counter or timestamp
                    chunk = LiveTranscriptChunk(
                        speaker_id="recall_auto",
                        speaker_name=speaker,
                        text=text,
                        is_final=True,
                        sequence_number=int(datetime.now().timestamp())
                    )
                    
                    # We use to_thread because ingest_chunk is currently synchronous and calls OpenAI
                    asyncio.create_task(asyncio.to_thread(stream_manager.ingest_chunk, str(meeting_id), chunk))

                # Save final chunks to DB so late joiners see history.
                # Fire-and-forget on a worker thread — see
                # app/services/transcript_persistence.py for why
                # the previous inline read-modify-write was an
                # O(n^2) event-loop blocker.
                if is_final:
                    schedule_transcript_save(meeting_id, formatted_line)

            except json.JSONDecodeError:
                logger.error("Failed to decode JSON from Recall.ai WebSocket")
                
    except WebSocketDisconnect:
        logger.warning(f"❌ Recall.ai disconnected WebSocket for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Error in Recall.ai WebSocket receiver: {e}")
