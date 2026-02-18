"""Photo upload and retrieval routes."""

import io
import logging
import zipfile
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, RedirectResponse
from typing import List
from pathlib import Path

from app.models import PhotoResponse, UploadResponse
from app.database import get_event, create_photo, get_photos_for_event, get_photo, delete_photo
from app.services.storage import validate_image, save_image, get_image_path, get_thumbnail_path, get_image_url
from app.config import USE_S3
from app.services.task_queue import submit_photo
from app.config import ALLOWED_EXTENSIONS, FREE_TIER_PHOTO_LIMIT
from app.routes.progress import reset_progress, update_progress

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["photos"])


def _process_image_upload(file_data: bytes, original_name: str, event_id: str) -> dict | None:
    """Process a single image file: validate, save, create DB record, submit for face processing."""
    file_size = len(file_data)

    valid, error_msg = validate_image(original_name, file_size)
    if not valid:
        logger.warning(f"Skipping invalid file {original_name}: {error_msg}")
        return None

    file_info = save_image(file_data, original_name, event_id)

    photo = create_photo(
        event_id=event_id,
        filename=file_info["filename"],
        original_name=original_name,
        file_size=file_info["file_size"],
        width=file_info["width"],
        height=file_info["height"],
    )

    # Submit for background processing (Celery or ThreadPool)
    submit_photo(photo["id"], event_id)

    return photo


@router.post("/events/{event_id}/photos", response_model=UploadResponse)
async def api_upload_photos(event_id: str, files: List[UploadFile] = File(...)):
    """Upload one or more photos (or ZIP archives) to an event. Processing happens in background."""
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event["photo_count"] >= FREE_TIER_PHOTO_LIMIT:
        raise HTTPException(
            status_code=402,
            detail=f"Event exceeds free tier limit ({FREE_TIER_PHOTO_LIMIT} photos). Upgrade for more.",
        )

    # Reset progress for this event (new upload batch)
    reset_progress(event_id)

    uploaded_photos = []
    limit_reached = False

    def _would_exceed_limit():
        return event["photo_count"] + len(uploaded_photos) >= FREE_TIER_PHOTO_LIMIT

    for upload_file in files:
        file_data = await upload_file.read()
        filename = upload_file.filename or "unknown.jpg"

        # Handle ZIP files: extract and process each image inside
        if filename.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                    for zip_entry in zf.namelist():
                        if _would_exceed_limit():
                            limit_reached = True
                            break
                        # Skip directories and hidden files
                        if zip_entry.endswith("/") or zip_entry.startswith("__MACOSX"):
                            continue
                        ext = Path(zip_entry).suffix.lower()
                        if ext not in ALLOWED_EXTENSIONS:
                            continue

                        entry_data = zf.read(zip_entry)
                        entry_name = Path(zip_entry).name  # Use basename only

                        photo = _process_image_upload(entry_data, entry_name, event_id)
                        if photo:
                            uploaded_photos.append(photo)
                            update_progress(event_id, "uploaded")
            except zipfile.BadZipFile:
                logger.warning(f"Invalid ZIP file: {filename}")
                continue
        else:
            # Regular image upload
            if _would_exceed_limit():
                limit_reached = True
            else:
                photo = _process_image_upload(file_data, filename, event_id)
                if photo:
                    uploaded_photos.append(photo)
                    update_progress(event_id, "uploaded")

    # Update total count for progress tracking
    if uploaded_photos:
        from app.routes.progress import _progress_store
        _progress_store[event_id]["total"] = len(uploaded_photos)

    if limit_reached and not uploaded_photos:
        raise HTTPException(
            status_code=402,
            detail=f"Event exceeds free tier limit ({FREE_TIER_PHOTO_LIMIT} photos). Upgrade for more.",
        )

    return {"uploaded": len(uploaded_photos), "photos": uploaded_photos}


@router.delete("/photos/{photo_id}")
def api_delete_photo(photo_id: str):
    """Delete a single photo from an event."""
    deleted = delete_photo(photo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Photo not found")
    return {"status": "ok", "message": "Photo deleted"}


@router.get("/events/{event_id}/photos", response_model=list[PhotoResponse])
def api_list_photos(event_id: str):
    """List all photos in an event."""
    event = get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return get_photos_for_event(event_id)


@router.get("/photos/{photo_id}/image")
def api_get_photo_image(photo_id: str, thumbnail: bool = False):
    """Serve a photo image (original or thumbnail)."""
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    if USE_S3:
        url = get_image_url(photo["event_id"], photo["filename"], thumbnail=thumbnail)
        if url:
            return RedirectResponse(url=url)
    path = get_thumbnail_path(photo["event_id"], photo["filename"]) if thumbnail else get_image_path(photo["event_id"], photo["filename"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(str(path))


@router.get("/photos/{photo_id}/download")
def api_download_photo(photo_id: str):
    """Download a photo with its original filename."""
    photo = get_photo(photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    if USE_S3:
        url = get_image_url(photo["event_id"], photo["filename"])
        if url:
            return RedirectResponse(url=url)
    path = get_image_path(photo["event_id"], photo["filename"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(
        str(path),
        filename=photo["original_name"],
        media_type="application/octet-stream",
    )
