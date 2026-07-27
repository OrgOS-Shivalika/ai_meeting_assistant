import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.api.auth_router import router as auth_router, public_router as auth_public_router
from app.api.admin_router import router as admin_router
from app.api.google_auth_router import router as google_auth_router
from app.api.routes import router
from app.api.category_router import router as category_router, team_router, meeting_types_router
from app.api.document_router import router as document_router
from app.api.team_document_router import router as team_document_router
from app.api.transcription_router import router as transcription_router
from app.api.ws_router import ws_router, recall_ws_router
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
from app.api.closing_briefing_router import closing_briefing_router
from app.api.kanban_router import kanban_router
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
    allow_methods=["*"], 
    allow_headers=["*"],
)
_API = settings.API_PREFIX
_PUBLIC = settings.PUBLIC_PREFIX
app.include_router(auth_public_router, prefix=_PUBLIC)
app.include_router(auth_router, prefix=_API)
app.include_router(admin_router, prefix=_API)
app.include_router(router, prefix=_API)
app.include_router(category_router, prefix=_API)
app.include_router(meeting_types_router, prefix=_API)
app.include_router(team_router, prefix=_API)
app.include_router(document_router, prefix=_API)
app.include_router(team_document_router, prefix=_API)
app.include_router(transcription_router, prefix=_API)
app.include_router(google_auth_router, prefix=_API)
app.include_router(search_router, prefix=_API)
app.include_router(graph_router, prefix=_API)
app.include_router(rag_router, prefix=_API)
app.include_router(consolidation_router, prefix=_API)
app.include_router(observability_router, prefix=_API)
app.include_router(harness_observability_router, prefix=_API)
app.include_router(agents_router, prefix=_API)
app.include_router(prompt_configs_router, prefix=_API)
app.include_router(playground_router, prefix=_API)
app.include_router(templates_router, prefix=_API)
app.include_router(behavior_router, prefix=_API)
app.include_router(ws_router, prefix=_API)
app.include_router(closing_briefing_router, prefix=_API)
app.include_router(kanban_router,prefix=_API)
app.include_router(continuum_router,prefix=_API)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Agentic Meeting Assistant...")
    start_scheduler()
    logger.info("Scheduler started successfully.")

    try:
        logger.info("Initializing closing-briefing orchestrator...")
        orch = get_orchestrator()
        orch.start()
        from app.services.live_events.event_bus import live_event_bus
        logger.info(
            "Closing-briefing orchestrator: started=%s, bus_subscribers=%d",
            orch._started, len(live_event_bus._subscribers),
        )
    except Exception as exc:
        logger.error("Closing-briefing orchestrator failed to start: %s", exc, exc_info=True)
        from app.services.storage_service import storage
        if storage.is_configured:
            storage.ensure_bucket()
            logger.info("Storage bucket ready.")
        else:
            logger.warning("Storage not configured (S3 credentials missing) — document uploads disabled.")
    except Exception as exc:
        logger.error("Storage bucket bootstrap failed: %s", exc)

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

frontend_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meeting_ai_frontend", "dist")

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
        candidate = os.path.join(frontend_path, request.url.path.lstrip("/"))
        if os.path.isfile(candidate):
            return FileResponse(candidate)
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
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
        file_path = os.path.join(frontend_path, catchall)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_file = os.path.join(frontend_path, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(
                index_file,
                headers={"Cache-Control": "no-store", "Vary": "Accept"},
            )

        return {"error": "Frontend not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
