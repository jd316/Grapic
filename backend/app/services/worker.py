"""Background worker for processing uploaded photos."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import MAX_WORKERS
from app.database import save_face_embedding, update_photo_status, get_photo
from app.services.storage import resolve_image_for_processing
from app.services.face_service import detect_and_encode

logger = logging.getLogger(__name__)

# Global thread pool
_executor: ThreadPoolExecutor | None = None


def start_worker():
    """Initialize the background worker pool."""
    global _executor
    _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="face-worker")
    logger.info(f"Face processing worker started with {MAX_WORKERS} threads")


def stop_worker():
    """Shut down the worker pool."""
    global _executor
    if _executor:
        _executor.shutdown(wait=False)
        _executor = None
        logger.info("Face processing worker stopped")


def process_photo(photo_id: str, event_id: str):
    """Process a single photo: detect faces and store embeddings."""
    try:
        # Import progress tracking
        from app.routes.progress import update_progress

        photo = get_photo(photo_id)
        if not photo:
            logger.error(f"Photo {photo_id} not found")
            return

        # Update progress: processing
        update_progress(event_id, "processing")

        image_path, should_cleanup = resolve_image_for_processing(event_id, photo["filename"])
        try:
            from pathlib import Path
            if not Path(image_path).exists():
                logger.error(f"Image file not found: {image_path}")
                update_photo_status(photo_id, "error")
                update_progress(event_id, "failed")
                return

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

            # Update progress: completed
            update_progress(event_id, "completed")

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
        # Update progress: failed
        try:
            from app.routes.progress import update_progress
            update_progress(event_id, "failed")
        except Exception:
            pass


def submit_photo(photo_id: str, event_id: str):
    """Submit a photo for background processing."""
    if _executor is None:
        raise RuntimeError("Worker not initialized. Call start_worker() first.")
    _executor.submit(process_photo, photo_id, event_id)
    logger.info(f"Submitted photo {photo_id} for processing")
