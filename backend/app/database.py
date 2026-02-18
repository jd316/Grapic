"""Database access layer with multiple backend support."""

import logging

from app.config import USE_SUPABASE, USE_SELF_HOSTED_PG

logger = logging.getLogger(__name__)

# Determine which database backend to use
if USE_SELF_HOSTED_PG:
    # Self-hosted PostgreSQL with pgvector (data only, auth from Supabase)
    logger.info("Using self-hosted PostgreSQL with pgvector")
    from app.database_postgres import (
        init_db, create_event, get_event, get_event_by_code, get_event_by_organizer_code,
        update_event, delete_event, cleanup_expired_events, increment_attendee_count,
        create_photo, update_photo_status, get_photos_for_event, get_photo, delete_photo,
        save_face_embedding, get_embeddings_for_event, find_similar_faces_vector,
        get_user_profile, create_user_profile, update_user_profile, get_events_by_user,
        record_match, get_similarity_distribution, get_similarity_stats,
        estimate_false_positive_rate, get_match_analytics
    )

elif USE_SUPABASE:
    # Supabase (both auth + database)
    logger.info("Using Supabase PostgreSQL")
    from app.database_supabase import (
        init_db, create_event, get_event, get_event_by_code, get_event_by_organizer_code,
        update_event, delete_event, cleanup_expired_events, increment_attendee_count,
        create_photo, update_photo_status, get_photos_for_event, get_photo, delete_photo,
        save_face_embedding, get_embeddings_for_event, get_user_profile, update_user_profile,
        get_events_by_user,
        record_match, get_similarity_distribution, get_similarity_stats,
        estimate_false_positive_rate, get_match_analytics
    )

else:
    # SQLite fallback (development mode)
    logger.info("Using SQLite database")
    from app.database_sqlite import (
        init_db, create_event, get_event, get_event_by_code, get_event_by_organizer_code,
        update_event, delete_event, cleanup_expired_events, increment_attendee_count,
        create_photo, update_photo_status, get_photos_for_event, get_photo, delete_photo,
        save_face_embedding, get_embeddings_for_event
    )

# Re-export for compatibility
__all__ = [
    "init_db",
    "create_event",
    "get_event",
    "get_event_by_code",
    "get_event_by_organizer_code",
    "update_event",
    "delete_event",
    "cleanup_expired_events",
    "increment_attendee_count",
    "create_photo",
    "update_photo_status",
    "get_photos_for_event",
    "get_photo",
    "delete_photo",
    "save_face_embedding",
    "get_embeddings_for_event",
    # Additional exports (available in PostgreSQL modes)
    "get_events_by_user",
    "get_user_profile",
    "create_user_profile",
    "update_user_profile",
    "find_similar_faces_vector",
    # Match history and analytics exports
    "record_match",
    "get_similarity_distribution",
    "get_similarity_stats",
    "estimate_false_positive_rate",
    "get_match_analytics",
]
