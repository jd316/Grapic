"""Automatic retry logic for failed photo processing with exponential backoff."""

import logging
import time
from celery import Celery
from app.celery_app import celery_app
from app.database import get_photos_for_event
from app.tasks import process_photo

logger = logging.getLogger(__name__)

# Max retry attempts
MAX_RETRIES = 3

# Backoff intervals in seconds: 5min, 15min, 1hour
RETRY_DELAYS = [300, 900, 3600]


@celery_app.task(name="app.tasks.auto_retry_failed_photos")
def auto_retry_failed_photos(event_id: str):
    """
    Automatically retry failed photos for an event with exponential backoff.

    This task should be scheduled to run periodically (e.g., every 5 minutes).
    It will check for photos with status "error" and retry them up to MAX_RETRIES times.

    Args:
        event_id: UUID of the event

    Returns:
        dict with retry results
    """
    photos = get_photos_for_event(event_id)
    failed_photos = [p for p in photos if p.get("status") == "error"]

    if not failed_photos:
        return {"status": "no_failures", "event_id": event_id}

    retried = []
    skipped = []

    for photo in failed_photos:
        retry_count = photo.get("retry_count", 0)

        if retry_count >= MAX_RETRIES:
            logger.warning(f"Photo {photo['id']} exceeded max retries ({MAX_RETRIES})")
            skipped.append(photo["id"])
            continue

        # Calculate delay based on retry count
        delay = RETRY_DELAYS[min(retry_count, len(RETRY_DELAYS) - 1)]

        # Schedule retry with countdown
        try:
            task = process_photo.apply_async(
                args=[photo["id"], event_id],
                countdown=delay,
                retry=False  # We handle retries manually
            )
            retried.append({
                "photo_id": photo["id"],
                "task_id": task.id,
                "retry_count": retry_count + 1,
                "delay_seconds": delay,
            })

            # Update retry_count in database
            from app.database import _get_pool
            pool = _get_pool()
            conn = pool.getconn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE photos SET retry_count = %s WHERE id = %s",
                (retry_count + 1, photo["id"])
            )
            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            logger.error(f"Failed to schedule retry for photo {photo['id']}: {e}")

    logger.info(f"Auto-retry for event {event_id}: {len(retried)} retried, {len(skipped)} skipped")

    return {
        "status": "retry_scheduled",
        "event_id": event_id,
        "retried_count": len(retried),
        "skipped_count": len(skipped),
        "tasks": retried,
    }


@celery_app.task(name="app.tasks.scan_and_retry_all_events")
def scan_and_retry_all_events():
    """
    Scan all active events and automatically retry failed photos.

    This task should be scheduled to run periodically (e.g., every 10 minutes).
    It will find all events with failed photos and trigger auto-retry for each.

    Returns:
        dict with scan results
    """
    from app.database import get_all_active_events

    events = get_all_active_events()
    results = []

    for event in events:
        event_id = event["id"]
        result = auto_retry_failed_photos.apply_async(args=[event_id])
        results.append({
            "event_id": event_id,
            "task_id": result.id,
        })

    return {
        "status": "scan_complete",
        "events_scanned": len(events),
        "retry_tasks": results,
    }


def get_all_active_events():
    """Get all active (non-expired) events."""
    from app.database import _get_pool
    pool = _get_pool()
    conn = pool.getconn()
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, expires_at FROM events WHERE expires_at > NOW() OR expires_at IS NULL ORDER BY created_at DESC"
    )
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": row[0],
            "name": row[1],
            "expires_at": row[2].isoformat() if row[2] else None,
        }
        for row in rows
    ]


@celery_app.task(name="app.tasks.cleanup_expired_events_task")
def cleanup_expired_events_task():
    """
    Celery task to clean up expired events.
    This is called by Celery Beat on a schedule.
    """
    from app.database import cleanup_expired_events
    try:
        result = cleanup_expired_events()
        return {"status": "success", "cleaned": result}
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")
        return {"status": "error", "message": str(e)}


@celery_app.task(name="app.tasks.backup_reminder")
def backup_reminder():
    """
    Daily reminder to run database backups.
    In production, this should trigger actual backup or alert if backup hasn't run.
    """
    logger.info("Daily backup reminder: Database backup should be run via cron")
    return {"status": "reminder", "message": "Run database backup via cron job"}
