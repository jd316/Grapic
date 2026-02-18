"""Server-Sent Events (SSE) endpoint for real-time upload/processing progress."""

import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.database import get_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["progress"])

# In-memory progress tracking (for production, use Redis)
# Structure: {event_id: {uploaded: int, processing: int, completed: int, failed: int, total: int}}
_progress_store: Dict[str, dict] = defaultdict(lambda: {
    "uploaded": 0,
    "processing": 0,
    "completed": 0,
    "failed": 0,
    "total": 0,
})

# Event queues for SSE clients
# Structure: {event_id: [queue1, queue2, ...]}
_client_queues: Dict[str, list] = defaultdict(list)


def update_progress(event_id: str, status: str, count: int = 1):
    """
    Update progress counters for an event.
    Status: 'uploaded', 'processing', 'completed', 'failed'

    This function is called by the upload and worker processes.
    """
    _progress_store[event_id][status] += count

    # Notify all connected clients
    for queue in _client_queues.get(event_id, []):
        try:
            queue.put_nowait({
                "event_id": event_id,
                "status": status,
                **_progress_store[event_id],
            })
        except asyncio.QueueFull:
            logger.warning(f"Progress queue full for event {event_id}")


def get_progress(event_id: str) -> dict:
    """Get current progress state for an event."""
    return _progress_store.get(event_id, {
        "uploaded": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "total": 0,
    })


def reset_progress(event_id: str):
    """Reset progress counters for an event (called on new upload)."""
    _progress_store[event_id] = {
        "uploaded": 0,
        "processing": 0,
        "completed": 0,
        "failed": 0,
        "total": 0,
    }


@router.get("/events/{event_id}/progress")
async def event_progress_stream(event_id: str):
    """
    Server-Sent Events stream for real-time upload/processing progress.

    Client-side usage:
    ```javascript
    const eventSource = new EventSource('/api/events/{event_id}/progress');
    eventSource.onmessage = (e) => {
        const data = JSON.parse(e.data);
        console.log('Progress:', data);
        // {uploaded: 10, processing: 5, completed: 3, failed: 0, total: 10}
    };
    ```
    """
    # Verify event exists
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    async def event_generator():
        try:
            # Create a queue for this client
            queue = asyncio.Queue(maxsize=100)
            _client_queues[event_id].append(queue)

            # Send initial state
            yield {
                "event": "progress",
                "data": json.dumps(get_progress(event_id)),
            }

            # Stream updates
            while True:
                try:
                    # Wait for new progress updates (with timeout)
                    progress = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": "progress",
                        "data": json.dumps(progress),
                    }

                    # Check if all photos are processed
                    total = progress.get("total", 0)
                    completed = progress.get("completed", 0)
                    failed = progress.get("failed", 0)

                    if total > 0 and (completed + failed) >= total:
                        # Send final complete event
                        yield {
                            "event": "complete",
                            "data": json.dumps(progress),
                        }
                        break

                except asyncio.TimeoutError:
                    # Send heartbeat every 30 seconds
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps(get_progress(event_id)),
                    }

        except asyncio.CancelledError:
            logger.info(f"Client disconnected from progress stream for event {event_id}")
        finally:
            # Clean up client queue
            if queue in _client_queues.get(event_id, []):
                _client_queues[event_id].remove(queue)
                if not _client_queues[event_id]:
                    del _client_queues[event_id]

    return EventSourceResponse(event_generator())


@router.get("/events/{event_id}/progress/status")
async def get_event_progress(event_id: str):
    """
    Get current progress status for an event (polling endpoint).

    Alternative to SSE if client doesn't support Server-Sent Events.
    Returns current progress state.
    """
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    progress = get_progress(event_id)
    progress["event_id"] = event_id

    # Calculate percentage
    total = progress.get("total", 0)
    if total > 0:
        progress["percent_complete"] = int((progress.get("completed", 0) / total) * 100)
    else:
        progress["percent_complete"] = 0

    return progress
