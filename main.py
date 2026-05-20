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
from app.api.agents_router import router as agents_router
from app.api.prompt_configs_router import router as prompt_configs_router
from app.api.playground_router import router as playground_router
from app.api.templates_router import router as templates_router
from app.api.behavior_router import router as behavior_router
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
app.include_router(agents_router)
app.include_router(prompt_configs_router)
app.include_router(playground_router)
app.include_router(templates_router)
app.include_router(behavior_router)
app.include_router(ws_router)
app.include_router(recall_webhook_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Agentic Meeting Assistant...")
    start_scheduler()
    logger.info("Scheduler started successfully.")

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

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Serve Frontend (MUST be last to not interfere with API routes)
frontend_path = os.path.join(os.getcwd(), "meeting_ai_frontend", "dist")


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
# Add a path here when a new SPA route would otherwise be shadowed by
# an API route. Paths NOT in this set fall through to the regular API
# routing + the existing catch-all at the bottom of this file.
_SPA_OVERLAY_PATHS: set[str] = {
    "/meeting-types",
    "/auth/google/callback",
}


@app.middleware("http")
async def spa_shell_on_html_navigation(request: Request, call_next):
    if (
        request.method == "GET"
        and "text/html" in (request.headers.get("accept") or "").lower()
        and request.url.path in _SPA_OVERLAY_PATHS
        and os.path.exists(frontend_path)
    ):
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)
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

        # 2. Fallback to index.html for SPA routing
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)

        return {"error": "Frontend not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
