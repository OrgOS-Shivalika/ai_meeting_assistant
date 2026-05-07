import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.api.auth_router import router as auth_router
from app.api.google_auth_router import router as google_auth_router 
from app.api.routes import router
from app.api.category_router import router as category_router, team_router
from app.api.transcription_router import router as transcription_router
from app.api.ws_router import ws_router
from app.api.webhooks.recall_webhook import recall_webhook_router
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
app.include_router(team_router)
app.include_router(transcription_router)
app.include_router(google_auth_router)
app.include_router(ws_router)
app.include_router(recall_webhook_router)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Agentic Meeting Assistant...")
    start_scheduler()
    logger.info("Scheduler started successfully.")

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Serve Frontend (MUST be last to not interfere with API routes)
frontend_path = os.path.join(os.getcwd(), "meeting_ai_frontend", "dist")

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
