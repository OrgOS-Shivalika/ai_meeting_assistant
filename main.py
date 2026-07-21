import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.api.auth_router import router as auth_router
from app.api.google_auth_router import router as google_auth_router 
from app.api.routes import router
from app.api.category_router import router as category_router, team_router, meeting_types_router
from app.api.document_router import router as document_router
from app.api.team_document_router import router as team_document_router
from app.api.transcription_router import router as transcription_router
from app.api.ws_router import ws_router
from app.api.webhooks.recall_webhook import recall_webhook_router
from app.api.search_router import router as search_router
from app.api.graph_router import router as graph_router
from app.api.rag_router import router as rag_router
from app.api.consolidation_router import router as consolidation_router
from app.api.observability_router import router as observability_router
from app.api.harness_observability_router import router as harness_observability_router
from app.api.agents_router import router as agents_router
from app.api.agents_v2_router import router as agents_v2_router
from app.api.prompt_configs_router import router as prompt_configs_router
from app.api.playground_router import router as playground_router
from app.api.templates_router import router as templates_router
from app.api.behavior_router import router as behavior_router
# Phase 12E — closing-briefing endpoint + orchestrator startup hook.
from app.api.closing_briefing_router import closing_briefing_router
# Phase 14 K2 — Kanban Boards REST API.
from app.api.kanban_router import kanban_router
# Continuum Core — client boards + stage kanban + agent runs.
from app.api.continuum_router import router as continuum_router
from app.services.briefing.closing_briefing_orchestrator import get_orchestrator
from app.utils.logger import setup_logger
from app.config.settings import settings
from fastapi.middleware.cors import CORSMiddleware
from app.services.scheduler import start_scheduler



logger = setup_logger(__name__)

app = FastAPI(title="Agentic Meeting Assistant")


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],  # IMPORTANT → allows OPTIONS
    allow_headers=["*"],
)


app.include_router(auth_router)
app.include_router(router)
app.include_router(category_router)
app.include_router(meeting_types_router)
app.include_router(team_router)
app.include_router(document_router)
app.include_router(team_document_router)
app.include_router(transcription_router)
app.include_router(google_auth_router)
app.include_router(search_router)
app.include_router(graph_router)
app.include_router(rag_router)
app.include_router(consolidation_router)
app.include_router(observability_router)
app.include_router(harness_observability_router)
app.include_router(agents_router)
app.include_router(agents_v2_router)
app.include_router(prompt_configs_router)
app.include_router(playground_router)
app.include_router(templates_router)
app.include_router(behavior_router)
app.include_router(ws_router)
app.include_router(recall_webhook_router)
# Phase 12E — closing briefing endpoint (replaces the Phase 12C debug router).
app.include_router(closing_briefing_router)
# Phase 14 K2 — Kanban Boards (boards/columns/task moves).
app.include_router(kanban_router)
# Continuum Core meeting agent.
app.include_router(continuum_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Agentic Meeting Assistant...")
    start_scheduler()
    logger.info("Scheduler started successfully.")

    # Phase 12E — subscribe the closing-briefing orchestrator to the
    # LiveEventBus so it reacts to meeting.winding_down / meeting.ended
    # events emitted by the Phase 12A lifecycle detectors.
    try:
        logger.info("Initializing closing-briefing orchestrator...")
        orch = get_orchestrator()
        orch.start()
        # Belt-and-suspenders: log via setup_logger (always visible) so
        # the boot log unambiguously confirms subscription.
        from app.services.live_events.event_bus import live_event_bus
        logger.info(
            "Closing-briefing orchestrator: started=%s, bus_subscribers=%d",
            orch._started, len(live_event_bus._subscribers),
        )
    except Exception as exc:
        # Never let an orchestrator-init failure block app boot — the
        # rest of the system (transcripts, RAG, dashboard) stays usable
        # even when the closing-briefing pipeline is degraded.
        logger.error("Closing-briefing orchestrator failed to start: %s", exc, exc_info=True)

    # Ensure the document storage bucket exists. No-op when storage isn't
    # configured — the app stays usable for non-storage features.
    try:
        from app.services.storage_service import storage
        if storage.is_configured:
            storage.ensure_bucket()
            logger.info("Storage bucket ready.")
        else:
            logger.warning("Storage not configured (S3 credentials missing) — document uploads disabled.")
    except Exception as exc:
        logger.error("Storage bucket bootstrap failed: %s", exc)

    # Agents v2 bootstrap — scan agent folders, seed DB rows.
    # Wrapped non-fatal: a bad manifest can't take down the app.
    try:
        from app.agents_v2 import registry as agents_v2_registry
        agents_v2_registry.bootstrap()
        logger.info("agents_v2 registry ready (%d agent(s))",
                    len(agents_v2_registry.list_agents()))
    except Exception as exc:
        logger.error("agents_v2 bootstrap failed (non-fatal): %s", exc, exc_info=True)

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Serve Frontend (MUST be last to not interfere with API routes)
frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meeting_ai_frontend", "dist")


# Some SPA routes collide by name with API routes — the most painful is
# `/meeting-types`, which the SPA uses for its category management page
# AND the API uses for its categories CRUD endpoint. Without this
# middleware, hitting `http://localhost:8000/meeting-types` from a
# browser refresh resolves to the API route, FastAPI's
# OAuth2PasswordBearer sees no Authorization header (browsers don't ship
# localStorage on top-level GETs), and the user gets a raw
# `{"detail":"Not authenticated"}` JSON page.
#
# Fix: for clear HTML navigations (Accept: text/html on GET), if the
# path is one of the known SPA shells, short-circuit and return the
# SPA's index.html BEFORE the API router has a chance to 401. Real
# XHR / fetch calls (Accept: application/json or */*) pass through and
# hit the API exactly as before.
#
# Generalized: EVERY top-level HTML navigation gets the SPA shell (or a
# real file from dist), because a browser refresh never carries the
# Authorization header — any SPA route that shares a path with an API
# GET (/, /boards, /agents, /meeting-types, ...) would otherwise return
# a raw {"detail": "Not authenticated"}. Real XHR/fetch calls (Accept:
# application/json or */*) are untouched and hit the API as before.
# Only genuinely-HTML API surfaces are exempted.
_API_HTML_PASSTHROUGH: set[str] = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
}


@app.middleware("http")
async def spa_shell_on_html_navigation(request: Request, call_next):
    if (
        request.method == "GET"
        and "text/html" in (request.headers.get("accept") or "").lower()
        and request.url.path not in _API_HTML_PASSTHROUGH
        and os.path.exists(frontend_path)
    ):
        # Address-bar hit on a real built asset (e.g. an image) → serve it.
        candidate = os.path.join(frontend_path, request.url.path.lstrip("/"))
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            # no-store + Vary: the shell shares its URL with API GETs
            # (/boards, ...). Without these, the browser caches the HTML
            # navigation response and later serves it to the SPA's JSON
            # fetch of the same URL → "Unexpected token '<'".
            return FileResponse(
                index_file,
                headers={"Cache-Control": "no-store", "Vary": "Accept"},
            )
    return await call_next(request)


if os.path.exists(frontend_path):
    @app.get("/")
    async def serve_root():
        """Serve root path"""
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
        return {"error": "Frontend not found"}

    @app.get("/{catchall:path}")
    async def serve_frontend(catchall: str):
        # 1. Try to serve exact file from dist (assets, etc)
        file_path = os.path.join(frontend_path, catchall)
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # 2. Fallback to index.html for SPA routing (no-store: see the
        #    spa_shell_on_html_navigation middleware comment)
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(
                index_file,
                headers={"Cache-Control": "no-store", "Vary": "Accept"},
            )

        return {"error": "Frontend not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
