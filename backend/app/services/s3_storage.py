"""Optional S3 storage for images. Used when GRAPIC_S3_BUCKET is set."""

from app.config import S3_BUCKET

try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def _client():
    if not HAS_BOTO3:
        raise RuntimeError("boto3 not installed. Pip install boto3 for S3 support.")
    return boto3.client("s3")


def save_image(file_data: bytes, filename: str, thumb_data: bytes, event_id: str) -> None:
    """Upload image and thumbnail to S3."""
    client = _client()
    key_img = f"{event_id}/{filename}"
    key_thumb = f"{event_id}/thumb_{filename}"
    client.put_object(Bucket=S3_BUCKET, Key=key_img, Body=file_data, ContentType="image/jpeg")
    client.put_object(Bucket=S3_BUCKET, Key=key_thumb, Body=thumb_data, ContentType="image/jpeg")


def get_image_bytes(event_id: str, filename: str, thumbnail: bool = False) -> bytes:
    """Fetch image or thumbnail bytes from S3."""
    client = _client()
    key = f"{event_id}/thumb_{filename}" if thumbnail else f"{event_id}/{filename}"
    resp = client.get_object(Bucket=S3_BUCKET, Key=key)
    return resp["Body"].read()


def get_presigned_url(event_id: str, filename: str, thumbnail: bool = False, expires_in: int = 3600) -> str:
    """Generate presigned URL for image download."""
    client = _client()
    key = f"{event_id}/thumb_{filename}" if thumbnail else f"{event_id}/{filename}"
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=expires_in
    )


def delete_photo_file(event_id: str, filename: str) -> None:
    """Delete a single photo and its thumbnail from S3."""
    client = _client()
    for key in [f"{event_id}/{filename}", f"{event_id}/thumb_{filename}"]:
        try:
            client.delete_object(Bucket=S3_BUCKET, Key=key)
        except Exception:
            pass


def delete_event_files(event_id: str) -> None:
    """Delete all objects for an event from S3."""
    client = _client()
    paginator = client.get_paginator("list_objects_v2")
    prefix = f"{event_id}/"
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        objects = page.get("Contents", [])
        if objects:
            client.delete_objects(
                Bucket=S3_BUCKET,
                Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
            )
