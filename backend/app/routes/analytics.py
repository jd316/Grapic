"""Analytics routes for event statistics and accuracy monitoring."""

import logging
from fastapi import APIRouter, HTTPException, Query

from app.database import get_event, get_photos_for_event, get_embeddings_for_event
from app.routes.progress import get_progress
from app.config import USE_SUPABASE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/events/{event_id}/stats")
def get_event_analytics(event_id: str):
    """
    Get detailed analytics for an event.
    Includes processing stats, face detection rates, and accuracy metrics.
    """
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    photos = get_photos_for_event(event_id)
    embeddings = get_embeddings_for_event(event_id)

    # Basic stats
    total_photos = len(photos)
    total_faces = len(embeddings)
    photos_with_faces = len(set(e["photo_id"] for e in embeddings))

    # Processing stats
    processed = [p for p in photos if p.get("status") == "done"]
    pending = [p for p in photos if p.get("status") == "pending"]
    failed = [p for p in photos if p.get("status") == "error"]

    # Processing time stats
    processing_times = [
        p.get("processing_time_ms")
        for p in processed
        if p.get("processing_time_ms") is not None
    ]

    if processing_times:
        avg_processing = sum(processing_times) / len(processing_times)
        min_processing = min(processing_times)
        max_processing = max(processing_times)
        median_processing = sorted(processing_times)[len(processing_times) // 2]
    else:
        avg_processing = min_processing = max_processing = median_processing = None

    # Face detection rate
    face_detection_rate = (photos_with_faces / total_photos * 100) if total_photos > 0 else 0

    # Faces per photo distribution
    faces_per_photo = {}
    for e in embeddings:
        photo_id = e["photo_id"]
        faces_per_photo[photo_id] = faces_per_photo.get(photo_id, 0) + 1

    face_counts = list(faces_per_photo.values())
    if face_counts:
        avg_faces_per_photo = sum(face_counts) / len(face_counts)
        max_faces_in_photo = max(face_counts)
    else:
        avg_faces_per_photo = max_faces_in_photo = 0

    return {
        "event_id": event_id,
        "event_name": event.get("name"),
        "photos": {
            "total": total_photos,
            "processed": len(processed),
            "pending": len(pending),
            "failed": len(failed),
            "with_faces": photos_with_faces,
            "face_detection_rate": round(face_detection_rate, 2),
        },
        "faces": {
            "total_faces": total_faces,
            "avg_faces_per_photo": round(avg_faces_per_photo, 2),
            "max_faces_in_photo": max_faces_in_photo,
        },
        "processing_time_ms": {
            "avg": round(avg_processing, 2) if avg_processing else None,
            "min": round(min_processing, 2) if min_processing else None,
            "max": round(max_processing, 2) if max_processing else None,
            "median": round(median_processing, 2) if median_processing else None,
        },
        "progress": get_progress(event_id),
    }


@router.get("/events/{event_id}/similarity-distribution")
def get_similarity_distribution(event_id: str):
    """
    Get similarity score distribution for matched photos.
    This helps monitor accuracy and tune threshold.
    """
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Get comprehensive match analytics
    from app.database import get_match_analytics

    # Check if match analytics is available (PostgreSQL modes)
    try:
        analytics = get_match_analytics(event_id)
        return {
            "event_id": event_id,
            "similarity_distribution": analytics["similarity_distribution"],
            "similarity_stats": analytics["similarity_stats"],
            "false_positive_estimate": analytics["false_positive_estimate"]
        }
    except Exception as e:
        # Fallback for SQLite or when match history not available
        logger.warning(f"Match analytics not available for event {event_id}: {e}")
        return {
            "event_id": event_id,
            "note": "Similarity tracking requires PostgreSQL with match history table (not available in SQLite mode)",
            "structure": {
                "similarity_ranges": {
                    "0.90-1.00": 0,
                    "0.70-0.89": 0,
                    "0.50-0.69": 0,
                    "0.40-0.49": 0,
                    "0.00-0.39": 0,
                },
                "avg_similarity": 0,
                "median_similarity": 0,
                "false_positive_estimate": 0,
            }
        }


@router.get("/system/health")
def get_system_health():
    """
    Get system health metrics for monitoring.
    """
    from app.services.worker import _executor
    from app.config import USE_REDIS, MAX_WORKERS

    health = {
        "status": "healthy",
        "components": {},
    }

    # Check ThreadPool
    if _executor:
        health["components"]["threadpool"] = {
            "status": "active",
            "max_workers": MAX_WORKERS,
        }
    else:
        health["components"]["threadpool"] = {"status": "inactive"}

    # Check Celery/Redis
    if USE_REDIS:
        try:
            from app.celery_app import celery_app
            inspector = celery_app.control.inspect()
            workers = inspector.active()
            if workers:
                health["components"]["celery"] = {
                    "status": "active",
                    "workers": list(workers.keys()),
                }
            else:
                health["components"]["celery"] = {"status": "configured_no_workers"}
        except Exception as e:
            health["components"]["celery"] = {"status": "error", "message": str(e)}
    else:
        health["components"]["celery"] = {"status": "not_configured"}

    # Check Supabase (for authentication only, not database)
    if USE_SUPABASE:
        try:
            from app.supabase_client import get_supabase
            supabase = get_supabase()
            # Only test auth connection, not database tables
            supabase.auth.get_user("test")
        except Exception:
            # Auth may not be accessible without real token, that's ok
            health["components"]["supabase_auth"] = {"status": "configured", "note": "Authentication configured"}
        health["components"]["supabase_auth"] = {"status": "configured"}
    else:
        health["components"]["supabase_auth"] = {"status": "not_configured"}

    # Check Self-Hosted PostgreSQL (primary database)
    from app.config import USE_SELF_HOSTED_PG
    if USE_SELF_HOSTED_PG:
        try:
            from app.database_postgres import get_pool
            pool = get_pool()
            conn = pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            conn.close()
            health["components"]["postgresql"] = {"status": "connected"}
        except Exception as e:
            health["components"]["postgresql"] = {"status": "error", "message": str(e)}
            health["status"] = "degraded"
    else:
        health["components"]["postgresql"] = {"status": "not_configured"}

    return health


@router.post("/events/{event_id}/retry-failed")
def retry_failed_photos_endpoint(event_id: str, limit: int = Query(10, ge=1, le=100)):
    """
    Retry processing failed photos for an event.
    Only works when using Celery (Redis enabled).
    """
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    from app.services.task_queue import retry_failed_photos

    task_id = retry_failed_photos(event_id, limit)

    if task_id:
        return {
            "status": "retry_submitted",
            "event_id": event_id,
            "task_id": task_id,
            "limit": limit,
            "message": f"Submitted retry task for up to {limit} failed photos",
        }
    else:
        return {
            "status": "retry_not_available",
            "event_id": event_id,
            "message": "Retry not available (requires Celery/Redis)",
        }
