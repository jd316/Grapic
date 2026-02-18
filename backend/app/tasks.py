"""Celery tasks for background photo processing."""

import logging
import time
from celery import Task
from pathlib import Path

from app.celery_app import celery_app
from app.database import save_face_embedding, update_photo_status, get_photo
from app.services.storage import resolve_image_for_processing
from app.services.face_service import detect_and_encode
from app.routes.progress import update_progress

logger = logging.getLogger(__name__)


class CallbackTask(Task):
    """Base task class that handles callbacks and progress updates."""

    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        event_id = kwargs.get("event_id") or (args[1] if len(args) > 1 else None)
        if event_id:
            update_progress(event_id, "completed")

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        event_id = kwargs.get("event_id") or (args[1] if len(args) > 1 else None)
        photo_id = kwargs.get("photo_id") or (args[0] if len(args) > 0 else None)

        if photo_id:
            update_photo_status(photo_id, "error")

        if event_id:
            update_progress(event_id, "failed")

        logger.error(f"Task {task_id} failed: {exc}")


@celery_app.task(base=CallbackTask, bind=True, name="app.tasks.process_photo")
def process_photo(self, photo_id: str, event_id: str):
    """
    Process a single photo: detect faces and store embeddings.
    This is a Celery task that runs on a worker process.

    Args:
        photo_id: UUID of the photo to process
        event_id: UUID of the event

    Returns:
        dict with processing results
    """
    try:
        photo = get_photo(photo_id)
        if not photo:
            logger.error(f"Photo {photo_id} not found")
            return {"status": "error", "message": "Photo not found"}

        # Update progress: processing
        update_progress(event_id, "processing")

        image_path, should_cleanup = resolve_image_for_processing(event_id, photo["filename"])
        try:
            if not Path(image_path).exists():
                logger.error(f"Image file not found: {image_path}")
                update_photo_status(photo_id, "error")
                update_progress(event_id, "failed")
                return {"status": "error", "message": "Image file not found"}

            logger.info(f"Processing photo {photo_id} ({photo['original_name']})")
            t0 = time.perf_counter()
            faces = detect_and_encode(image_path)

            for face in faces:
                save_face_embedding(
                    photo_id=photo_id,
                    event_id=event_id,
                    embedding=face["embedding"],
                    face_location=face["location"],
                )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            update_photo_status(photo_id, "done", face_count=len(faces), processing_time_ms=elapsed_ms)
            logger.info(f"Photo {photo_id}: found {len(faces)} face(s)")

            return {
                "status": "success",
                "photo_id": photo_id,
                "face_count": len(faces),
                "processing_time_ms": elapsed_ms,
            }

        finally:
            if should_cleanup:
                import os
                try:
                    os.unlink(image_path)
                except OSError:
                    pass

    except Exception as e:
        logger.error(f"Error processing photo {photo_id}: {e}")
        update_photo_status(photo_id, "error")
        update_progress(event_id, "failed")
        return {"status": "error", "message": str(e)}


@celery_app.task(name="app.tasks.batch_process")
def batch_process(photo_ids: list, event_id: str):
    """
    Process multiple photos in batch.
    This task chains individual photo processing tasks.

    Args:
        photo_ids: List of photo UUIDs to process
        event_id: UUID of the event

    Returns:
        dict with batch processing results
    """
    results = []
    for photo_id in photo_ids:
        result = process_photo.apply_async(args=[photo_id, event_id])
        results.append({
            "photo_id": photo_id,
            "task_id": result.id,
        })

    return {
        "status": "batch_started",
        "total_tasks": len(results),
        "tasks": results,
    }


@celery_app.task(name="app.tasks.retry_failed_photos")
def retry_failed_photos(event_id: str, limit: int = 10):
    """
    Retry processing failed photos for an event.

    Args:
        event_id: UUID of the event
        limit: Maximum number of photos to retry

    Returns:
        dict with retry results
    """
    from app.database import get_photos_for_event

    photos = get_photos_for_event(event_id)
    failed_photos = [p for p in photos if p.get("status") == "error"][:limit]

    retried = []
    for photo in failed_photos:
        task = process_photo.apply_async(args=[photo["id"], event_id])
        retried.append({
            "photo_id": photo["id"],
            "task_id": task.id,
        })

    return {
        "status": "retry_started",
        "retried_count": len(retried),
        "tasks": retried,
    }
