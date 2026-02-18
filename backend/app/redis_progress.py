"""Redis-based progress tracking for horizontal scalability."""

import json
import logging
from typing import Dict

from app.config import USE_REDIS, REDIS_URL

logger = logging.getLogger(__name__)

_redis_client = None


def _get_redis():
    """Get Redis client (lazy initialization)."""
    global _redis_client
    if _redis_client is None:
        if not USE_REDIS:
            return None
        try:
            import redis
            _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return None
    return _redis_client


def update_progress(event_id: str, status: str, count: int = 1):
    """
    Update progress counters for an event in Redis.
    Status: 'uploaded', 'processing', 'completed', 'failed'

    This function is called by the upload and worker processes.
    Uses Redis HINCRBY for atomic updates.
    """
    client = _get_redis()
    if not client:
        # Fallback to in-memory if Redis not available
        from app.routes.progress import update_progress as mem_update_progress
        mem_update_progress(event_id, status, count)
        return

    try:
        key = f"progress:{event_id}"
        client.hincrby(key, status, count)

        # Also publish to Redis PubSub for real-time updates
        client.publish(f"progress_updates:{event_id}", json.dumps({
            "event_id": event_id,
            "status": status,
        }))
    except Exception as e:
        logger.error(f"Failed to update progress in Redis: {e}")


def get_progress(event_id: str) -> dict:
    """Get current progress state for an event from Redis."""
    client = _get_redis()
    if not client:
        # Fallback to in-memory if Redis not available
        from app.routes.progress import get_progress as mem_get_progress
        return mem_get_progress(event_id)

    try:
        key = f"progress:{event_id}"
        data = client.hgetall(key)

        if not data:
            return {
                "uploaded": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "total": 0,
            }

        return {
            "uploaded": int(data.get("uploaded", 0)),
            "processing": int(data.get("processing", 0)),
            "completed": int(data.get("completed", 0)),
            "failed": int(data.get("failed", 0)),
            "total": int(data.get("total", 0)),
        }
    except Exception as e:
        logger.error(f"Failed to get progress from Redis: {e}")
        return {
            "uploaded": 0,
            "processing": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        }


def reset_progress(event_id: str):
    """Reset progress counters for an event in Redis."""
    client = _get_redis()
    if not client:
        # Fallback to in-memory if Redis not available
        from app.routes.progress import reset_progress as mem_reset_progress
        mem_reset_progress(event_id)
        return

    try:
        key = f"progress:{event_id}"
        client.delete(key)
    except Exception as e:
        logger.error(f"Failed to reset progress in Redis: {e}")


def set_total(event_id: str, total: int):
    """Set the total number of photos for an event."""
    client = _get_redis()
    if not client:
        return

    try:
        key = f"progress:{event_id}"
        client.hset(key, "total", total)
    except Exception as e:
        logger.error(f"Failed to set total in Redis: {e}")
