"""Proxy to the Size Set inspection service.

The `sizeset` project is a separate FastAPI process that turns a garment
size-set inspection recording into a filled inspection report. This module adds
the two things it deliberately does not have — authentication and a same-origin
mount point — and forwards everything else untouched.

Why proxy instead of letting the browser call it directly:

  * sizeset has NO auth. No login, no user, nothing. Exposing :8100 to a
    browser exposes every client report to anyone who can reach the port.
  * sizeset registers no CORS middleware, so a page served from :8000 could not
    call :8100 anyway.

Proxying solves both and costs one small module. Errors from sizeset are passed
through with their own status and detail rather than collapsed into a 500 — the
useful ones ("unsupported file type", "no style set for style 1234", "job is
running, not ready") are exactly what the operator needs to see.

State lives entirely in sizeset: jobs are in its memory, outputs on its disk.
Nothing here touches the database, and restarting sizeset loses job history.
That is a deliberate demo-scope choice, not an oversight.
"""
from __future__ import annotations

import re
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.database import get_db
from app.db.models import Category
from app.dependencies.auth import get_current_user
from app.services import permissions
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter(prefix="/sizeset", tags=["sizeset"])

# Uploads are whole inspection recordings — the reference ones run 18-46 MB —
# and sizeset re-encodes anything over 25 MB before sending it on. The POST
# itself returns 202 as soon as the file is on its disk, so this ceiling covers
# the transfer only, not the transcription.
_UPLOAD_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

# Polls and downloads. Generated reports are tens of kilobytes.
_READ_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# Mirrors sizeset's own DOWNLOADS keys. Checked here so a junk value never
# reaches the forwarded URL.
_DOWNLOAD_KINDS = frozenset({"report", "form", "measurements", "data"})

_SERVICE_DOWN = (
    "The Size Set service is not reachable at {url}. Start it with: "
    "python src\\main.py serve --port 8100"
)


def _safe_job_id(job_id: str) -> str:
    """Job ids are 12 hex chars from `uuid4().hex[:12]`.

    Validated before it is interpolated into a URL, so a crafted id cannot
    reach for another path on the sizeset service.
    """
    if not job_id.isalnum() or len(job_id) > 64:
        raise HTTPException(status_code=404, detail="no such job")
    return job_id


async def _forward(
    method: str, path: str, *, timeout: httpx.Timeout, **kwargs
) -> httpx.Response:
    """One request to sizeset. Raises 503 when the service is not running."""
    url = f"{settings.SIZESET_API_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            return await client.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        logger.error("sizeset unreachable at %s: %s", url, exc)
        raise HTTPException(
            status_code=503,
            detail=_SERVICE_DOWN.format(url=settings.SIZESET_API_URL),
        ) from exc


def _checked(response: httpx.Response) -> httpx.Response:
    """Re-raise sizeset's own error, preserving status and detail.

    Collapsing these into a 500 would hide the messages that matter most:
    sizeset tells the operator when a file type is unsupported, when a
    recording is too large to re-encode, and when a chosen style has no spec
    sheet on disk.
    """
    if response.status_code < 400:
        return response

    detail = f"Size Set service returned {response.status_code}"
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("detail"):
            detail = body["detail"]
    except ValueError:
        if response.text:
            detail = response.text[:500]
    raise HTTPException(status_code=response.status_code, detail=detail)


@router.get("/config")
async def read_config(user=Depends(get_current_user)) -> dict:
    """Which category may produce Size Set reports.

    Exists so the SPA can show the "Generate Size Set" action only on meetings
    that qualify, instead of offering it everywhere and letting most attempts
    come back as a 400. The name is server-side configuration, so the client
    cannot be the one holding it.
    """
    return {"category_name": (settings.SIZESET_CATEGORY_NAME or "").strip()}


@router.get("/styles")
async def list_styles(user=Depends(get_current_user)) -> list:
    """Style numbers that have a spec sheet on disk — the upload dropdown."""
    response = _checked(await _forward("GET", "/api/style-sets", timeout=_READ_TIMEOUT))
    return response.json()


@router.get("/jobs")
async def list_jobs(user=Depends(get_current_user)) -> list:
    """Every job sizeset is holding, newest first.

    NOT scoped to the caller — sizeset has no concept of users, so this returns
    all jobs on the service. Acceptable for a single-operator demo; it is the
    first thing that needs fixing before real multi-tenant use.
    """
    response = _checked(await _forward("GET", "/api/jobs", timeout=_READ_TIMEOUT))
    return response.json()


@router.get("/jobs/{job_id}")
async def read_job(job_id: str, user=Depends(get_current_user)) -> dict:
    response = _checked(
        await _forward(
            "GET", f"/api/jobs/{_safe_job_id(job_id)}", timeout=_READ_TIMEOUT
        )
    )
    return response.json()


@router.post("/jobs", status_code=202)
async def create_job(
    recording: Annotated[UploadFile, File()],
    style_no: Annotated[str, Form()] = "",
    user=Depends(get_current_user),
) -> dict:
    """Hand a recording to sizeset and return the job to poll.

    `style_no` picks the spec sheet to grade against; empty falls back to the
    style number the inspector announces at the start of the recording.
    """
    # `UploadFile.file` is a SpooledTemporaryFile, so httpx streams it from
    # there rather than us materialising 46 MB as bytes. Seek first: FastAPI
    # may already have read it while parsing the multipart body.
    recording.file.seek(0)
    files = {
        "recording": (
            recording.filename or "recording",
            recording.file,
            recording.content_type or "application/octet-stream",
        )
    }
    response = _checked(
        await _forward(
            "POST",
            "/api/jobs",
            timeout=_UPLOAD_TIMEOUT,
            files=files,
            data={"style_no": style_no},
        )
    )
    job = response.json()
    logger.info(
        "sizeset job %s queued for %s (style %s) by %s",
        job.get("id"), recording.filename, style_no or "as announced",
        getattr(user, "email", "?"),
    )
    return job


_SPEAKER_PREFIX = re.compile(r"^[^:\n]{1,60}:\s*")

# Below this, extraction returns noise and costs an API call for nothing.
# Mirrors the guard in `continuum_tasks._process_continuum_meeting_sync`.
_MIN_TRANSCRIPT_WORDS = 10


def strip_speaker_prefixes(transcript: str) -> str:
    """Drop the "Speaker: " prefix from every line.

    A size-set report records measurements, not who said them, so speaker
    labels are pure overhead here — and the sizeset extractor was tuned on raw
    transcription output, which has none.

    Measured 2026-08-25 on a real inspection transcript, extracting the same
    text with and without synthetic prefixes: identical row count (55/55), the
    same style number detected, comparable flagged counts (7 vs 6), and 42/55
    rows byte-identical. The remainder differed only in point-of-measure
    phrasing, which the model varies between runs anyway. So prefixes cost
    **+26% input tokens** (8666 vs 6891 chars) and buy nothing.

    Caveat on that measurement: the same input was not run twice, so
    run-to-run variance was not separated out. The conclusion holds either way
    — there is no evidence prefixes HELP, and they demonstrably cost tokens.

    The pattern is bounded to 60 characters and stops at the first colon so a
    transcript line that merely contains a colon ("chest: thirty eight" spoken
    mid-sentence) keeps its content.
    """
    lines = (transcript or "").split("\n")
    return "\n".join(_SPEAKER_PREFIX.sub("", line, count=1) for line in lines)


class FromMeetingRequest(BaseModel):
    """Which style to grade a meeting's transcript against."""

    style_no: str = ""


@router.post("/from-meeting/{meeting_id}", status_code=202)
async def create_job_from_meeting(
    meeting_id: int,
    payload: FromMeetingRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Turn a completed meeting's transcript into a Size Set report.

    Option A from the client's spec: one action, during or after the meeting,
    that formats the live transcript into the standard report — as opposed to
    Option B, which uploads a recording.

    Three guards, in order:

      1. The caller must be able to VIEW the meeting. Read access is the right
         bar: the report is derived from a transcript they can already read, so
         nothing new is exposed. `get_viewable_meeting` also handles the
         cross-tenant 404 vs in-tenant 403 distinction.
      2. The meeting's category must match `SIZESET_CATEGORY_NAME`. This is the
         "Triburg org, Quality Team section" placement, done with a category
         name rather than a schema change.
      3. The transcript must have enough words to be worth an API call.
    """
    meeting = permissions.get_viewable_meeting(db, user, meeting_id)

    wanted_category = (settings.SIZESET_CATEGORY_NAME or "").strip()
    if wanted_category:
        category = (
            db.query(Category).filter(Category.id == meeting.category_id).first()
            if meeting.category_id
            else None
        )
        if category is None or category.name.strip() != wanted_category:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Size Set reports are only generated for meetings in the "
                    f"{wanted_category!r} category. This meeting is in "
                    f"{(category.name if category else 'no category')!r}."
                ),
            )

    # `transcript_text` is the compiled transcript; `transcript` is the live
    # one, which is all that exists when Recall's compiled version failed.
    raw = (meeting.transcript_text or meeting.transcript or "").strip()
    if len(raw.split()) < _MIN_TRANSCRIPT_WORDS:
        raise HTTPException(
            status_code=400,
            detail="This meeting has no usable transcript yet.",
        )

    response = _checked(
        await _forward(
            "POST",
            "/api/transcript-jobs",
            timeout=_READ_TIMEOUT,
            json={
                "transcript": strip_speaker_prefixes(raw),
                "style_no": payload.style_no,
                # The meeting id, not the title: this names the saved
                # transcript and all four output files, and titles carry
                # slashes, quotes and emoji.
                "name": f"meeting-{meeting.id}",
            },
        )
    )
    job = response.json()
    logger.info(
        "sizeset job %s queued from meeting %s (style %s) by %s",
        job.get("id"), meeting.id, payload.style_no or "as announced",
        getattr(user, "email", "?"),
    )
    return job


@router.get("/jobs/{job_id}/download/{kind}")
async def download(job_id: str, kind: str, user=Depends(get_current_user)) -> Response:
    """Stream one generated output back to the browser.

    Returned as bytes rather than a streaming passthrough because these files
    are tens of kilobytes — a CSV is ~4-15 KB and the PDF ~20 KB. If reports
    ever carry embedded artwork, revisit.
    """
    if kind not in _DOWNLOAD_KINDS:
        raise HTTPException(
            status_code=404,
            detail=f"unknown output {kind!r}. "
            f"Expected one of: {', '.join(sorted(_DOWNLOAD_KINDS))}",
        )

    response = _checked(
        await _forward(
            "GET",
            f"/api/jobs/{_safe_job_id(job_id)}/download/{kind}",
            timeout=_READ_TIMEOUT,
        )
    )
    # Carry sizeset's filename through so the browser saves it under the
    # report's own name rather than the endpoint's last path segment.
    headers = {}
    disposition = response.headers.get("content-disposition")
    if disposition:
        headers["Content-Disposition"] = disposition
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "application/octet-stream"),
        headers=headers,
    )
