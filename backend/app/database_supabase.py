"""Supabase database access layer (both auth + database mode)."""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from app.supabase_client import get_supabase, get_supabase_service

logger = logging.getLogger(__name__)


def init_db():
    """Initialize database (no-op for Supabase - schema is managed via migrations)."""
    logger.info("Using Supabase database - schema managed via migrations")
    pass


# ─── Event Operations ───────────────────────────────────────────────────────

def create_event(name: str, description: str = "", expires_in_days: Optional[int] = 7, user_id: Optional[str] = None) -> dict:
    """Create a new event and return its data."""
    event_id = str(uuid.uuid4())
    access_code = uuid.uuid4().hex[:8].upper()
    organizer_code = uuid.uuid4().hex[:8].upper()
    now = datetime.now(timezone.utc).isoformat()
    expires_at = None
    if expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

    supabase = get_supabase()
    event_data = {
        "id": event_id,
        "user_id": user_id,
        "name": name,
        "description": description,
        "created_at": now,
        "expires_at": expires_at,
        "access_code": access_code,
        "organizer_code": organizer_code,
        "photo_count": 0,
        "processed_count": 0,
        "attendee_count": 0,
    }

    result = supabase.table("events").insert(event_data).execute()

    if result.data:
        return result.data[0]
    return event_data


def get_event(event_id: str) -> Optional[dict]:
    """Get event by ID with computed metrics."""
    supabase = get_supabase()
    result = supabase.table("events").select("*").eq("id", event_id).execute()

    if not result.data:
        return None

    ev = result.data[0]

    # Get stats from photos table
    stats_result = supabase.table("photos").select("processing_time_ms").eq("event_id", event_id).eq("status", "done").not_("processing_time_ms", "is", None).execute()

    if stats_result.data:
        total_ms = sum(p.get("processing_time_ms", 0) for p in stats_result.data)
        ev["avg_processing_sec"] = round(total_ms / len(stats_result.data) / 1000, 2) if stats_result.data else None
    else:
        ev["avg_processing_sec"] = None

    ev["engagement_pct"] = round((ev["attendee_count"] / max(1, ev["photo_count"])) * 100, 1) if ev.get("photo_count", 0) else 0

    return ev


def get_event_by_code(access_code: str) -> Optional[dict]:
    """Get event by attendee access code."""
    supabase = get_supabase()
    result = supabase.table("events").select("*").eq("access_code", access_code.upper()).execute()

    if result.data:
        return result.data[0]
    return None


def get_event_by_organizer_code(organizer_code: str) -> Optional[dict]:
    """Get event by organizer code."""
    supabase = get_supabase()
    result = supabase.table("events").select("*").eq("organizer_code", organizer_code.upper()).execute()

    if result.data:
        return result.data[0]
    return None


def get_events_by_user(user_id: str) -> List[dict]:
    """Get all events for a specific user."""
    supabase = get_supabase()
    result = supabase.table("events").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()

    return result.data if result.data else []


def update_event(event_id: str, name: Optional[str] = None, description: Optional[str] = None, expires_in_days: Optional[int] = None) -> Optional[dict]:
    """Update event fields."""
    update_data = {}
    if name is not None:
        update_data["name"] = name
    if description is not None:
        update_data["description"] = description
    if expires_in_days is not None:
        update_data["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

    if not update_data:
        return get_event(event_id)

    supabase = get_supabase()
    result = supabase.table("events").update(update_data).eq("id", event_id).execute()

    if result.data:
        return result.data[0]
    return None


def delete_event(event_id: str) -> bool:
    """Delete an event and all related data."""
    supabase = get_supabase_service()
    result = supabase.table("events").delete().eq("id", event_id).execute()
    return len(result.data) > 0


def cleanup_expired_events() -> List[dict]:
    """Delete events that have passed their expiration date."""
    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase_service()

    # Get expired events
    result = supabase.table("events").select("*").not_("expires_at", "is", None).lt("expires_at", now).execute()

    expired_events = result.data if result.data else []
    deleted = []

    for event in expired_events:
        logger.info(f"Auto-deleting expired event: {event['name']} ({event['id']})")
        delete_event_result = supabase.table("events").delete().eq("id", event['id']).execute()
        if delete_event_result.data:
            deleted.append(event)

    if deleted:
        logger.info(f"Cleaned up {len(deleted)} expired event(s)")

    return deleted


def increment_attendee_count(event_id: str):
    """Increment the attendee usage counter."""
    supabase = get_supabase()
    # Get current count
    result = supabase.table("events").select("attendee_count").eq("id", event_id).single().execute()
    if result.data:
        current = result.data.get("attendee_count", 0)
        supabase.table("events").update({"attendee_count": current + 1}).eq("id", event_id).execute()


# ─── Photo Operations ───────────────────────────────────────────────────────

def create_photo(event_id: str, filename: str, original_name: str, file_size: int, width: int, height: int) -> dict:
    """Create a photo record."""
    photo_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    supabase = get_supabase()
    photo_data = {
        "id": photo_id,
        "event_id": event_id,
        "filename": filename,
        "original_name": original_name,
        "file_size": file_size,
        "width": width,
        "height": height,
        "face_count": 0,
        "status": "pending",
        "uploaded_at": now,
    }

    result = supabase.table("photos").insert(photo_data).execute()

    # Increment event photo count
    supabase.rpc("increment_event_photo_count", {"event_id": event_id}).execute()

    if result.data:
        return result.data[0]
    return photo_data


def update_photo_status(photo_id: str, status: str, face_count: int = 0, processing_time_ms: Optional[int] = None):
    """Update photo processing status."""
    now = datetime.now(timezone.utc).isoformat()
    update_data = {
        "status": status,
        "face_count": face_count,
        "processed_at": now,
    }
    if processing_time_ms is not None:
        update_data["processing_time_ms"] = processing_time_ms

    supabase = get_supabase()
    supabase.table("photos").update(update_data).eq("id", photo_id).execute()

    # If status is done, increment event processed count
    if status == "done":
        photo = get_photo(photo_id)
        if photo:
            supabase.rpc("increment_event_processed_count", {"event_id": photo["event_id"]}).execute()


def get_photos_for_event(event_id: str) -> List[dict]:
    """Get all photos for an event."""
    supabase = get_supabase()
    result = supabase.table("photos").select("*").eq("event_id", event_id).order("uploaded_at", desc=True).execute()

    return result.data if result.data else []


def get_photo(photo_id: str) -> Optional[dict]:
    """Get a single photo by ID."""
    supabase = get_supabase()
    result = supabase.table("photos").select("*").eq("id", photo_id).execute()

    if result.data:
        return result.data[0]
    return None


def delete_photo(photo_id: str) -> bool:
    """Delete a single photo, its files, and face embeddings."""
    photo = get_photo(photo_id)
    if not photo:
        return False

    event_id = photo["event_id"]
    filename = photo["filename"]
    was_processed = photo.get("status") == "done"

    from app.services.storage import delete_photo_file
    delete_photo_file(event_id, filename)

    supabase = get_supabase_service()
    result = supabase.table("photos").delete().eq("id", photo_id).execute()

    # Update event counts
    event_result = supabase.table("events").select("photo_count", "processed_count").eq("id", event_id).single().execute()
    if event_result.data:
        update_data = {"photo_count": max(0, event_result.data["photo_count"] - 1)}
        if was_processed:
            update_data["processed_count"] = max(0, event_result.data["processed_count"] - 1)
        supabase.table("events").update(update_data).eq("id", event_id).execute()

    return len(result.data) > 0


# ─── Face Embedding Operations ───────────────────────────────────────────────

def save_face_embedding(photo_id: str, event_id: str, embedding: List[float], face_location: tuple):
    """Save a face embedding."""
    emb_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    supabase = get_supabase()
    emb_data = {
        "id": emb_id,
        "photo_id": photo_id,
        "event_id": event_id,
        "embedding": embedding,
        "face_location": list(face_location),
        "created_at": now,
    }

    result = supabase.table("face_embeddings").insert(emb_data).execute()
    return result.data[0] if result.data else emb_data


def get_embeddings_for_event(event_id: str) -> List[dict]:
    """Get all face embeddings for an event."""
    supabase = get_supabase()
    result = supabase.table("face_embeddings").select("id", "photo_id", "embedding", "face_location").eq("event_id", event_id).execute()

    return result.data if result.data else []


# ─── Match History Operations (Supabase) ─────────────────────────────────

def record_match(event_id: str, photo_id: str, similarity: float, threshold: float = 0.4, user_id: Optional[str] = None) -> dict:
    """Record a match attempt for analytics (Supabase version)."""
    now = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase()
    
    match_data = {
        "event_id": event_id,
        "photo_id": photo_id,
        "similarity": similarity,
        "threshold_used": threshold,
        "match_timestamp": now,
        "user_id": user_id,
        "metadata": {}
    }
    
    result = supabase.table("match_history").insert(match_data).execute()
    return result.data[0] if result.data else match_data


def get_similarity_distribution(event_id: str) -> List[dict]:
    """Get similarity score distribution for an event (Supabase version)."""
    supabase = get_supabase()
    
    # Call the SQL function via RPC
    result = supabase.rpc(
        "get_similarity_distribution",
        {"evt_id": event_id}
    ).execute()
    
    return result.data if result.data else []


def get_similarity_stats(event_id: str) -> dict:
    """Get aggregate similarity statistics for an event (Supabase version)."""
    supabase = get_supabase()
    
    result = supabase.rpc(
        "get_similarity_stats",
        {"evt_id": event_id}
    ).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    return {}


def estimate_false_positive_rate(event_id: str, low_confidence_threshold: float = 0.50) -> dict:
    """Estimate false positive rate for an event (Supabase version)."""
    supabase = get_supabase()
    
    result = supabase.rpc(
        "estimate_false_positive_rate",
        {"evt_id": event_id, "low_confidence_threshold": low_confidence_threshold}
    ).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    
    return {
        "false_positive_estimate": 0.0,
        "total_matches": 0,
        "low_confidence_matches": 0
    }


def get_match_analytics(event_id: str) -> dict:
    """Get comprehensive match analytics for an event (Supabase version)."""
    distribution = get_similarity_distribution(event_id)
    stats = get_similarity_stats(event_id)
    fp_rate = estimate_false_positive_rate(event_id)
    
    # Calculate percentages by range
    total = stats.get("total_matches", 0)
    distribution_dict = {}
    for item in distribution:
        range_key = item["similarity_range"]
        count = item.get("count", 0)
        distribution_dict[range_key] = {
            "count": count,
            "percentage": round((count / total * 100), 2) if total > 0 else 0
        }
    
    return {
        "event_id": event_id,
        "similarity_distribution": distribution_dict,
        "similarity_stats": {
            "avg": round(stats.get("avg_similarity", 0), 4),
            "median": round(stats.get("median_similarity", 0), 4),
            "min": round(stats.get("min_similarity", 0), 4),
            "max": round(stats.get("max_similarity", 0), 4),
            "total": stats.get("total_matches", 0)
        },
        "false_positive_estimate": fp_rate
    }


# ─── User Profile Operations ──────────────────────────────────────────────────

def get_user_profile(user_id: str) -> Optional[dict]:
    """Get user profile by ID."""
    supabase = get_supabase()
    result = supabase.table("user_profiles").select("*").eq("id", user_id).single().execute()

    if result.data:
        return result.data
    return None


def update_user_profile(user_id: str, full_name: Optional[str] = None, avatar_url: Optional[str] = None) -> Optional[dict]:
    """Update user profile."""
    update_data = {}
    if full_name is not None:
        update_data["full_name"] = full_name
    if avatar_url is not None:
        update_data["avatar_url"] = avatar_url

    if not update_data:
        return get_user_profile(user_id)

    supabase = get_supabase()
    result = supabase.table("user_profiles").update(update_data).eq("id", user_id).execute()

    if result.data:
        return result.data[0]
    return None
