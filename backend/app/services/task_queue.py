"""Unified task queue interface - supports both Celery+Redis and ThreadPool fallback."""

import logging
from typing import Optional

from app.config import USE_REDIS

logger = logging.getLogger(__name__)

# Lazy load Celery
_celery_tasks = None
_threadpool_worker = None


def submit_photo(photo_id: str, event_id: str) -> Optional[str]:
    """
    Submit a photo for background processing.
    Uses Celery if Redis is available, otherwise falls back to ThreadPool.

    Args:
        photo_id: UUID of the photo to process
        event_id: UUID of the event

    Returns:
        Task ID if using Celery, None if using ThreadPool
    """
    global _celery_tasks, _threadpool_worker

    if USE_REDIS:
        # Use Celery for distributed processing
        try:
            from app.tasks import process_photo
            result = process_photo.apply_async(args=[photo_id, event_id])
            logger.info(f"Submitted photo {photo_id} for Celery processing (task: {result.id})")
            return result.id
        except Exception as e:
            logger.error(f"Celery submission failed, falling back to ThreadPool: {e}")
            # Fall through to ThreadPool

    # Fallback to ThreadPool (in-memory)
    from app.services.worker import submit_photo as threadpool_submit
    threadpool_submit(photo_id, event_id)
    logger.info(f"Submitted photo {photo_id} for ThreadPool processing")
    return None


def get_task_status(task_id: str) -> Optional[dict]:
    """
    Get status of a Celery task by ID.
    Returns None if task not found or using ThreadPool.

    Args:
        task_id: Celery task ID

    Returns:
        Task status dict with keys: state, result, etc.
    """
    if not USE_REDIS:
        return None

    try:
        from celery.result import AsyncResult
        from app.celery_app import celery_app

        result = AsyncResult(task_id, app=celery_app)
        return {
            "task_id": task_id,
            "state": result.state,
            "result": result.result if result.ready() else None,
            "info": result.info,
        }
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        return None


def retry_failed_photos(event_id: str, limit: int = 10) -> Optional[str]:
    """
    Retry processing failed photos for an event.

    Args:
        event_id: UUID of the event
        limit: Maximum number of photos to retry

    Returns:
        Task ID if using Celery, None if using ThreadPool
    """
    if not USE_REDIS:
        # ThreadPool fallback: just log a message
        logger.warning("Retry not supported in ThreadPool mode")
        return None

    try:
        from app.tasks import retry_failed_photos
        result = retry_failed_photos.apply_async(args=[event_id, limit])
        logger.info(f"Submitted retry task for event {event_id} (task: {result.id})")
        return result.id
    except Exception as e:
        logger.error(f"Retry task submission failed: {e}")
        return None
