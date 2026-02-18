"""Celery configuration for distributed task processing."""

from celery import Celery
from app.config import USE_REDIS, REDIS_URL

# Default Redis URL if not configured
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

# Create Celery app
celery_app = Celery(
    "grapic",
    broker=REDIS_URL if USE_REDIS else DEFAULT_REDIS_URL,
    backend=REDIS_URL if USE_REDIS else DEFAULT_REDIS_URL,
    include=["app.tasks"],  # Tasks will be defined in app/tasks.py
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (prevents memory leaks)
)

# Optional: Configure result expiration
celery_app.conf.result_expires = 3600  # Results expire after 1 hour

# Optional: Configure task routing
celery_app.conf.task_routes = {
    "app.tasks.process_photo": {"queue": "face_processing"},
    "app.tasks.batch_process": {"queue": "batch_processing"},
}

# Optional: Configure rate limits
celery_app.conf.task_annotations = {
    "app.tasks.process_photo": {"rate_limit": "10/m"},
}
