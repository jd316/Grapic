"""Storage service for images. Supports local filesystem or S3 when GRAPIC_S3_BUCKET is set."""

import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from app.config import (
    UPLOAD_DIR,
    THUMBNAIL_DIR,
    THUMBNAIL_SIZE,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    MAX_IMAGE_DIMENSION,
    STORAGE_JPEG_QUALITY,
    USE_S3,
)


def validate_image(filename: str, file_size: int) -> tuple[bool, str]:
    """Validate an uploaded image file."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        return False, f"File too large. Maximum size: {MAX_FILE_SIZE_MB}MB"
    return True, ""


def _process_image(file_data: bytes) -> tuple[object, object, int, int, int]:
    """Pre-process image: resize, compress. Returns (img, thumb_img, width, height, file_size_bytes)."""
    img = Image.open(io.BytesIO(file_data))
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    width, height = img.size
    if max(width, height) > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max(width, height)
        new_w = int(width * ratio)
        new_h = int(height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        width, height = new_w, new_h

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=STORAGE_JPEG_QUALITY, optimize=True)
    file_size = buf.tell()
    buf.seek(0)

    thumb = img.copy()
    thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, "JPEG", quality=85)
    thumb_buf.seek(0)

    return buf, thumb_buf, width, height, file_size


def save_image(file_data: bytes, original_name: str, event_id: str) -> dict:
    """Save an uploaded image with pre-processing (resize/compress) and create a thumbnail.
    PRD 4.2: Resize/compress for optimal storage and processing speed."""
    stem = uuid.uuid4().hex
    unique_name = f"{stem}.jpg"

    buf, thumb_buf, width, height, file_size = _process_image(file_data)

    if USE_S3:
        from app.services.s3_storage import save_image as s3_save
        s3_save(buf.read(), unique_name, thumb_buf.read(), event_id)
        return {"filename": unique_name, "file_size": file_size, "width": width, "height": height}

    event_upload_dir = UPLOAD_DIR / event_id
    event_thumb_dir = THUMBNAIL_DIR / event_id
    event_upload_dir.mkdir(parents=True, exist_ok=True)
    event_thumb_dir.mkdir(parents=True, exist_ok=True)

    filepath = event_upload_dir / unique_name
    filepath.write_bytes(buf.getvalue())
    thumb_path = event_thumb_dir / unique_name
    thumb_path.write_bytes(thumb_buf.getvalue())

    return {"filename": unique_name, "file_size": file_size, "width": width, "height": height}


def get_image_path(event_id: str, filename: str) -> Path:
    """Get the full path to an original image (local only)."""
    return UPLOAD_DIR / event_id / filename


def resolve_image_for_processing(event_id: str, filename: str) -> tuple[str, bool]:
    """Return a path to the image for processing. When S3, downloads to temp.
    Returns (path, should_cleanup). Caller must os.unlink(path) when should_cleanup."""
    if not USE_S3:
        p = get_image_path(event_id, filename)
        return str(p), False
    from app.services.s3_storage import get_image_bytes
    data = get_image_bytes(event_id, filename, thumbnail=False)
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="grapic_")
    os.close(fd)
    Path(path).write_bytes(data)
    return path, True


def get_image_bytes_for_zip(event_id: str, filename: str) -> bytes | None:
    """Get image bytes for zip creation. Returns None if not found."""
    if not USE_S3:
        p = get_image_path(event_id, filename)
        if not p.exists():
            return None
        return p.read_bytes()
    try:
        from app.services.s3_storage import get_image_bytes
        return get_image_bytes(event_id, filename, thumbnail=False)
    except Exception:
        return None


def get_image_url(event_id: str, filename: str, thumbnail: bool = False) -> str | None:
    """Get presigned S3 URL when USE_S3. Returns None for local."""
    if not USE_S3:
        return None
    from app.services.s3_storage import get_presigned_url
    return get_presigned_url(event_id, filename, thumbnail=thumbnail)


def get_thumbnail_path(event_id: str, filename: str) -> Path:
    """Get the full path to a thumbnail."""
    # Thumbnail is always JPEG
    thumb_name = Path(filename).stem + Path(filename).suffix
    return THUMBNAIL_DIR / event_id / thumb_name


def delete_photo_file(event_id: str, filename: str):
    """Delete a single photo's files (original + thumbnail)."""
    if USE_S3:
        from app.services.s3_storage import delete_photo_file as s3_delete
        s3_delete(event_id, filename)
        return
    img_path = get_image_path(event_id, filename)
    thumb_path = get_thumbnail_path(event_id, filename)
    if img_path.exists():
        img_path.unlink()
    if thumb_path.exists():
        thumb_path.unlink()


def delete_event_files(event_id: str):
    """Delete all files associated with an event."""
    if USE_S3:
        from app.services.s3_storage import delete_event_files as s3_delete
        s3_delete(event_id)
        return
    upload_dir = UPLOAD_DIR / event_id
    thumb_dir = THUMBNAIL_DIR / event_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    if thumb_dir.exists():
        shutil.rmtree(thumb_dir)
