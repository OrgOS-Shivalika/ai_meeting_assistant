from fastapi import APIRouter, BackgroundTasks, Depends, Query
from requests import Session
from typing import Optional
from app.db.database import get_db
from app.dependencies.auth import get_current_user
from app.pipelines.meeting_pipeline import MeetingPipeline
from app.schemas.meeting_schema import (
    MeetingRequest,
    MeetingAssignRequest,
    MeetingUpdateRequest,
    MeetingScheduleRequest,
    TaskUpdateRequest,
)
from app.utils.logger import setup_logger
import uuid
from app.config.settings import settings
from app.db.database import SessionLocal
from app.services import meeting_service
from app.store.job_store import jobs


logger = setup_logger(__name__)
router = APIRouter()
pipeline = MeetingPipeline()


@router.post("/inject-bot")
def create_meeting(
    request: MeetingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    meeting_service.validate_category_team(db, user, request.category_id, request.team_id)

    # Idempotency guard — return the in-flight row instead of creating a
    # duplicate bot when the same user re-fires /inject-bot for the same URL.
    if request.meeting_url:
        recent = meeting_service.find_recent_duplicate_meeting(db, user, request.meeting_url)
        if recent:
            logger.info(
                "🛑 /inject-bot dedup: user=%s already has meeting %s "
                "processing url=%s (created %s)",
                user.email, recent.id, request.meeting_url, recent.created_at,
            )
            return {"job_id": None, "meeting_id": recent.id, "deduped": True}

    job_id = str(uuid.uuid4())

    meeting = meeting_service.create_processing_meeting(db, user, request)

    jobs[job_id] = {
        "status": "processing",
        "meeting_id": meeting.id
    }

    if settings.USE_CELERY:
        # Production / Docker path: dispatch onto the Celery worker.
        from app.celery_tasks.meeting_tasks import process_meeting
        async_result = process_meeting.delay(meeting.id)
        jobs[job_id]["celery_task_id"] = async_result.id
        logger.info(
            "Dispatched meeting %s to Celery (task=%s)", meeting.id, async_result.id
        )
    else:
        # Local dev path without a broker: fall back to in-process work via
        # FastAPI BackgroundTasks. Same behaviour as before USE_CELERY existed.
        # NOTE: the background closure owns its own SessionLocal lifecycle, so
        # only the pure lookup is delegated to the service — the session
        # creation/teardown and pipeline invocation stay here on purpose.
        def run():
            local_db = SessionLocal()
            try:
                db_meeting = meeting_service.get_meeting(local_db, meeting.id)
                if not db_meeting:
                    logger.error(f"Meeting {meeting.id} not found in background task")
                    return

                result = pipeline.run(local_db, db_meeting)
                jobs[job_id]["status"] = "completed"
                jobs[job_id]["result"] = result

            except Exception as e:
                jobs[job_id]["status"] = "failed"
                jobs[job_id]["result"] = str(e)
                logger.error(f"Error in background task: {str(e)}")

            finally:
                local_db.close()

        background_tasks.add_task(run)

    return {
        "job_id": job_id,
        "meeting_id": meeting.id
    }


# @router.get("/meetings/{job_id}")
# def get_status(job_id: str):
#     job = jobs.get(job_id)

#     if not job:
#         return {"error": "Job not found"}

#     return {
#         "job_id": job_id,
#         "status": job["status"]
#     }



# @router.get("/meetings/{job_id}/result")
# def get_result(job_id: str):
#     job = jobs.get(job_id)

#     if not job:
#         return {"error": "Job not found"}

#     if job["status"] != "completed":
#         return {
#             "status": job["status"],
#             "message": "Result not ready yet"
#         }

#     return {
#         "status": "completed",
#         "result": job["result"]
#     }


@router.get("/allmeetings")
def get_meetings(
    category_id: Optional[int] = Query(None),
    team_id: Optional[int] = Query(None),
    uncategorized: Optional[bool] = Query(None),
    q: Optional[str] = Query(None, max_length=200),
    page: Optional[int] = Query(None, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=200),
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    return meeting_service.list_meetings(
        db, user, category_id, team_id, uncategorized, q, page, page_size
    )


@router.get("/meetings/grouped-latest")
def get_meetings_grouped_latest(
    per_category: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.get_meetings_grouped_latest(db, user, per_category)


# Spec: GET /meetings/uncategorized — meetings without a team assignment.
@router.get("/meetings/uncategorized")
def list_uncategorized_meetings(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.list_uncategorized_meetings(db, user)


# Spec: GET /teams/{team_id}/meetings — meetings inside a specific team.
@router.get("/teams/{team_id}/meetings")
def list_team_meetings(
    team_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.list_team_meetings(db, user, team_id)


# Spec: POST /teams/{team_id}/meetings/schedule — create a scheduled meeting
# (no bot dispatch yet — that happens at start time).
@router.post("/teams/{team_id}/meetings/schedule")
def schedule_team_meeting(
    team_id: int,
    payload: MeetingScheduleRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.create_scheduled_meeting(db, user, team_id, payload)


@router.delete("/meetings/{meeting_id}")
def delete_meeting(
    meeting_id: int,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    return meeting_service.delete_meeting(db, user, meeting_id)


# ---------------------------------------------------------------------------
# Manual retry endpoints for the AI Memory pipeline. The pipeline normally
# fans out automatically (process_meeting → embed_meeting → extract_graph),
# but when a stage fails the user needs a one-click way to retry it from
# the meeting detail page without dropping into a CLI.
# ---------------------------------------------------------------------------


@router.post("/meetings/{meeting_id}/retry-embedding")
def retry_embedding(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    meeting_service.mark_meeting_for_embedding_retry(db, user, meeting_id)
    from app.celery_tasks.embedding_tasks import dispatch_embed_meeting
    dispatch_embed_meeting(meeting_id)
    return {"status": "dispatched", "meeting_id": meeting_id, "stage": "embedding"}


@router.post("/meetings/{meeting_id}/retry-graph")
def retry_graph(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    meeting_service.mark_meeting_for_graph_retry(db, user, meeting_id)
    from app.celery_tasks.graph_tasks import dispatch_extract_graph
    dispatch_extract_graph(meeting_id)
    return {"status": "dispatched", "meeting_id": meeting_id, "stage": "graph"}


@router.patch("/meetings/{meeting_id}/category")
def assign_meeting_category(
    meeting_id: int,
    payload: MeetingAssignRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.assign_meeting_category(db, user, meeting_id, payload)


# Spec: PATCH /meetings/{id} — generic partial update.
@router.patch("/meetings/{meeting_id}")
def update_meeting(
    meeting_id: int,
    payload: MeetingUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.update_meeting(db, user, meeting_id, payload)


@router.get("/allmeetings/{meeting_id}")
def get_meeting_detail(
    meeting_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.get_meeting_detail(db, user, meeting_id)


@router.get("/tasks")
def get_tasks(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
    owner: Optional[str] = None,
    priority: Optional[str] = None,
    unassigned_only: bool = False,
    completed: Optional[bool] = None,
):
    return meeting_service.list_tasks(
        db, user, owner=owner, priority=priority,
        unassigned_only=unassigned_only, completed=completed,
    )


@router.get("/meetings/{meeting_id}/tasks")
def get_meeting_tasks(meeting_id: int, db: Session = Depends(get_db)):
    return meeting_service.get_meeting_tasks(db, meeting_id)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    return meeting_service.update_task(db, user, task_id, payload)
