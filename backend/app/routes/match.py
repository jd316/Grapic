"""Selfie matching routes."""

import io
import os
import zipfile
import tempfile
import logging
import time
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse, JSONResponse

from app.models import MatchResponse
from app.database import (
    get_event, get_embeddings_for_event, get_photo, increment_attendee_count,
    record_match, get_match_analytics
)
from app.services.face_service import encode_selfie, find_matches, find_matches_vector
from app.services.storage import get_image_path, get_image_bytes_for_zip
from app.config import USE_S3, USE_SUPABASE, USE_SELF_HOSTED_PG, SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["match"])


@router.post("/events/{event_id}/match", response_model=MatchResponse)
async def api_match_selfie(event_id: str, selfie: UploadFile = File(...)):
    """
    Upload a selfie to find matching photos in an event.
    Returns photos where the attendee's face was detected.
    PRD 5.1: Target latency under 3 seconds.
    """
    t0 = time.perf_counter()
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    # Save selfie to temp file
    selfie_data = await selfie.read()
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(selfie_data)
        tmp_path = tmp.name

    try:
        # Encode the selfie
        selfie_embedding = encode_selfie(tmp_path)
        if selfie_embedding is None:
            raise HTTPException(
                status_code=400,
                detail="No face detected in selfie. Please ensure your face is clearly visible and well-lit."
            )

        # Find matches using vector search (Supabase or self-hosted PostgreSQL) or sequential search (SQLite)
        if USE_SUPABASE or USE_SELF_HOSTED_PG:
            # Use indexed vector search for O(log n) performance
            if USE_SELF_HOSTED_PG:
                from app.database import find_similar_faces_vector
                matches = find_similar_faces_vector(event_id, selfie_embedding)
            else:
                matches = find_matches_vector(event_id, selfie_embedding)
        else:
            # Fallback to sequential search for SQLite mode
            stored = get_embeddings_for_event(event_id)
            if not stored:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                return JSONResponse(
                    content={"matched_count": 0, "results": []},
                    headers={"X-Processing-Ms": str(elapsed_ms)},
                )
            matches = find_matches(selfie_embedding, stored)

        # Build response with photo details
        results = []
        for match in matches:
            photo = get_photo(match["photo_id"])
            if photo:
                results.append({
                    "photo_id": photo["id"],
                    "filename": photo["filename"],
                    "original_name": photo["original_name"],
                    "similarity": match["similarity"],
                    "thumbnail_url": f"/api/photos/{photo['id']}/image?thumbnail=true",
                    "download_url": f"/api/photos/{photo['id']}/download",
                })

                # Record match for analytics (PostgreSQL modes only)
                if USE_SELF_HOSTED_PG or USE_SUPABASE:
                    try:
                        # Import user_id from auth middleware if available
                        from app.auth_middleware import get_user_id
                        user_id = None
                        # user_id would be available if the request had auth header
                        # For public matches, we record without user_id
                        record_match(
                            event_id=event_id,
                            photo_id=photo["id"],
                            similarity=match["similarity"],
                            threshold=SIMILARITY_THRESHOLD,
                            user_id=user_id
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record match history: {e}")

        # Track attendee usage
        if results:
            increment_attendee_count(event_id)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if elapsed_ms > 3000:
            logger.warning(f"Match exceeded 3s SLA: {elapsed_ms}ms for event {event_id}")

        return JSONResponse(
            content={"matched_count": len(results), "results": results},
            headers={"X-Processing-Ms": str(elapsed_ms)},
        )

    finally:
        # Clean up temp file
        os.unlink(tmp_path)


@router.get("/events/{event_id}/match/zip")
def api_bulk_download_zip(event_id: str, photo_ids: str = Query(..., description="Comma-separated photo IDs")):
    """
    Download multiple photos as a ZIP archive.
    Validates that all photo_ids belong to the event.
    """
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    ids = [p.strip() for p in photo_ids.split(",") if p.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="No photo IDs provided")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, photo_id in enumerate(ids):
            photo = get_photo(photo_id)
            if not photo or photo["event_id"] != event_id:
                continue
            if USE_S3:
                data = get_image_bytes_for_zip(event_id, photo["filename"])
                if data is None:
                    continue
                arcname = f"{i + 1:03d}_{photo['original_name']}"
                zf.writestr(arcname, data)
            else:
                path = get_image_path(event_id, photo["filename"])
                if not path.exists():
                    continue
                arcname = f"{i + 1:03d}_{photo['original_name']}"
                zf.write(str(path), arcname)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=grapic-photos.zip"},
    )
