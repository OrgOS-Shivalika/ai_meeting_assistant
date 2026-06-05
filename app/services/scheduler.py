import logging

logger = logging.getLogger(__name__)

def start_scheduler():
    """
    Deprecated: APScheduler has been removed to prevent blocking the FastAPI event loop.
    Calendar sync is now handled exclusively by Celery Beat (app.celery_tasks.calendar_tasks).
    """
    logger.info("APScheduler disabled. Using Celery Beat for background tasks.")