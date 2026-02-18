"""PostgreSQL database access layer (self-hosted with pgvector)."""

import logging
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import json

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Connection pool for self-hosted PostgreSQL
_pool: Optional[SimpleConnectionPool] = None


def _serialize_datetime(obj: any) -> any:
    """Convert datetime objects to ISO format strings for JSON serialization."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _serialize_datetime(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_datetime(item) for item in obj]
    return obj


def get_pool():
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set for self-hosted PostgreSQL")
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=DATABASE_URL,
            cursor_factory=RealDictCursor
        )
    return _pool


class _AutoSerializeCursor:
    """Cursor wrapper that automatically serializes datetime objects."""
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        return self._cursor.execute(query, params)

    def fetchone(self):
        row = self._cursor.fetchone()
        return _serialize_datetime(row) if row else None

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [_serialize_datetime(row) for row in rows]

    def __getattr__(self, name):
        return getattr(self._cursor, name)


@contextmanager
def get_db_cursor():
    """Context manager for database queries with automatic commit/rollback and datetime serialization."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        raw_cursor = conn.cursor()
        cursor = _AutoSerializeCursor(raw_cursor)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def init_db():
    """Initialize database schema (for self-hosted PostgreSQL)."""
    logger.info("Initializing self-hosted PostgreSQL database with pgvector...")

    with get_db_cursor() as cur:
        # Enable pgvector extension
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

        # Create user_profiles table (links to Supabase auth.users via user_id)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id UUID PRIMARY KEY,
                full_name TEXT,
                avatar_url TEXT,
                subscription_tier TEXT DEFAULT 'free',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Create events table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                expires_at TIMESTAMPTZ,
                access_code TEXT UNIQUE NOT NULL,
                organizer_code TEXT UNIQUE NOT NULL,
                photo_count INTEGER DEFAULT 0,
                processed_count INTEGER DEFAULT 0,
                attendee_count INTEGER DEFAULT 0,
                branding_logo_url TEXT DEFAULT '',
                branding_company_name TEXT DEFAULT '',
                branding_custom_css TEXT DEFAULT ''
            );
        """)

        # Create photos table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS photos (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                event_id UUID NOT NULL,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                face_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed_at TIMESTAMPTZ,
                processing_time_ms INTEGER,
                CONSTRAINT fk_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );
        """)

        # Create face_embeddings table with pgvector
        cur.execute("""
            CREATE TABLE IF NOT EXISTS face_embeddings (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                photo_id UUID NOT NULL,
                event_id UUID NOT NULL,
                embedding JSONB NOT NULL,
                embedding_vector vector(128),
                face_location JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT fk_photo FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
                CONSTRAINT fk_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );
        """)

        # Create match_history table for analytics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS match_history (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                event_id UUID NOT NULL,
                photo_id UUID NOT NULL,
                similarity FLOAT NOT NULL,
                threshold_used FLOAT NOT NULL DEFAULT 0.4,
                match_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                user_id UUID,
                metadata JSONB DEFAULT '{}',
                CONSTRAINT fk_match_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE,
                CONSTRAINT fk_match_photo FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE
            );
        """)

        # Create indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_faces_event ON face_embeddings(event_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_faces_photo ON face_embeddings(photo_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_access ON events(access_code);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);")

        # Match history indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_match_history_event ON match_history(event_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_match_history_photo ON match_history(photo_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_match_history_similarity ON match_history(similarity);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_match_history_timestamp ON match_history(match_timestamp DESC);")

        # Create pgvector index for cosine similarity
        cur.execute("""
            CREATE INDEX IF NOT EXISTS face_embeddings_vector_idx
            ON face_embeddings
            USING ivfflat (embedding_vector vector_cosine_ops)
            WITH (lists = 100);
        """)

        # Create function to update updated_at timestamp
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create trigger for user_profiles
        cur.execute("""
            DROP TRIGGER IF EXISTS update_user_profiles_updated_at ON user_profiles;
            CREATE TRIGGER update_user_profiles_updated_at
                BEFORE UPDATE ON user_profiles
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at();
        """)

        # Create function to increment event photo count
        cur.execute("""
            CREATE OR REPLACE FUNCTION increment_event_photo_count(evt_id UUID)
            RETURNS VOID AS $$
            BEGIN
                UPDATE events
                SET photo_count = photo_count + 1
                WHERE id = evt_id;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create function to increment event processed count
        cur.execute("""
            CREATE OR REPLACE FUNCTION increment_event_processed_count(evt_id UUID)
            RETURNS VOID AS $$
            BEGIN
                UPDATE events
                SET processed_count = processed_count + 1
                WHERE id = evt_id;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create function to auto-update embedding_vector from JSONB
        cur.execute("""
            CREATE OR REPLACE FUNCTION update_embedding_vector()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.embedding_vector IS NULL AND NEW.embedding IS NOT NULL THEN
                    NEW.embedding_vector := NEW.embedding::vector;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)

        # Create trigger for face_embeddings
        cur.execute("""
            DROP TRIGGER IF EXISTS on_face_embeddings_insert_or_update ON face_embeddings;
            CREATE TRIGGER on_face_embeddings_insert_or_update
                BEFORE INSERT OR UPDATE ON face_embeddings
                FOR EACH ROW
                EXECUTE FUNCTION update_embedding_vector();
        """)

        # Create function for vector similarity search
        cur.execute("""
            CREATE OR REPLACE FUNCTION find_similar_faces(
                target_embedding vector(128),
                evt_id UUID,
                threshold FLOAT DEFAULT 0.4
            )
            RETURNS TABLE (
                photo_id UUID,
                similarity FLOAT
            ) AS $$
            BEGIN
                RETURN QUERY
                SELECT
                    fe.photo_id,
                    (1 - (fe.embedding_vector <=> target_embedding))::FLOAT as similarity
                FROM face_embeddings fe
                WHERE fe.event_id = evt_id
                    AND fe.embedding_vector IS NOT NULL
                    AND (1 - (fe.embedding_vector <=> target_embedding)) >= threshold
                ORDER BY fe.embedding_vector <=> target_embedding
                LIMIT 1000;
            END;
            $$ LANGUAGE plpgsql;
        """)

    logger.info("PostgreSQL database initialized successfully")


# ─── Event Operations ───────────────────────────────────────────────────────

def create_event(name: str, description: str = "", expires_in_days: Optional[int] = 7, user_id: Optional[str] = None, branding_logo_url: Optional[str] = None, branding_company_name: Optional[str] = None, branding_custom_css: Optional[str] = None) -> dict:
    """Create a new event and return its data."""
    import secrets
    access_code = secrets.token_hex(4).upper()
    organizer_code = secrets.token_hex(4).upper()

    # Calculate expires_at timestamp
    expires_at = None
    if expires_in_days:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO events (name, description, expires_at, user_id, access_code, organizer_code, branding_logo_url, branding_company_name, branding_custom_css)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, description, created_at, expires_at, access_code, organizer_code,
                     photo_count, processed_count, attendee_count, user_id,
                     branding_logo_url, branding_company_name, branding_custom_css
        """, (name, description, expires_at, user_id, access_code, organizer_code, branding_logo_url, branding_company_name, branding_custom_css))
        return dict(cur.fetchone())


def get_event(event_id: str) -> Optional[dict]:
    """Get event by ID with computed metrics."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT * FROM events WHERE id = %s
        """, (event_id,))
        row = cur.fetchone()
        if not row:
            return None

        ev = dict(row)

        # Get avg processing time
        cur.execute("""
            SELECT AVG(processing_time_ms) as avg_ms
            FROM photos
            WHERE event_id = %s AND status = 'done' AND processing_time_ms IS NOT NULL
        """, (event_id,))
        stats = cur.fetchone()
        ev["avg_processing_sec"] = round(stats["avg_ms"] / 1000, 2) if stats and stats["avg_ms"] else None

        ev["engagement_pct"] = round((ev["attendee_count"] / max(1, ev["photo_count"])) * 100, 1) if ev.get("photo_count", 0) else 0

        return ev


def get_event_by_code(access_code: str) -> Optional[dict]:
    """Get event by attendee access code."""
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM events WHERE access_code = %s", (access_code.upper(),))
        row = cur.fetchone()
        return dict(row) if row else None


def get_event_by_organizer_code(organizer_code: str) -> Optional[dict]:
    """Get event by organizer code."""
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM events WHERE organizer_code = %s", (organizer_code.upper(),))
        row = cur.fetchone()
        return dict(row) if row else None


def get_events_by_user(user_id: str) -> List[dict]:
    """Get all events for a specific user."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT * FROM events WHERE user_id = %s ORDER BY created_at DESC
        """, (user_id,))
        return [dict(row) for row in cur.fetchall()]


def update_event(event_id: str, name: Optional[str] = None, description: Optional[str] = None, expires_in_days: Optional[int] = None) -> Optional[dict]:
    """Update event fields."""
    updates = []
    params = []

    if name is not None:
        updates.append("name = %s")
        params.append(name)
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    if expires_in_days is not None:
        updates.append("expires_at = NOW() + INTERVAL '%s days'")
        params.append(expires_in_days)

    if updates:
        params.append(event_id)
        with get_db_cursor() as cur:
            cur.execute(f"""
                UPDATE events SET {', '.join(updates)}
                WHERE id = %s
                RETURNING *
            """, params)
            return dict(cur.fetchone())

    return get_event(event_id)


def delete_event(event_id: str) -> bool:
    """Delete an event and all related data."""
    with get_db_cursor() as cur:
        cur.execute("DELETE FROM events WHERE id = %s", (event_id,))
        return cur.rowcount > 0


def cleanup_expired_events() -> List[dict]:
    """Delete events that have passed their expiration date."""
    with get_db_cursor() as cur:
        cur.execute("""
            DELETE FROM events
            WHERE expires_at IS NOT NULL AND expires_at < NOW()
            RETURNING id, name
        """)
        deleted = [dict(row) for row in cur.fetchall()]

    if deleted:
        logger.info(f"Cleaned up {len(deleted)} expired event(s)")

    return deleted


def increment_attendee_count(event_id: str):
    """Increment the attendee usage counter."""
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE events SET attendee_count = attendee_count + 1 WHERE id = %s
        """, (event_id,))


# ─── Photo Operations ───────────────────────────────────────────────────────

def create_photo(event_id: str, filename: str, original_name: str, file_size: int, width: int, height: int) -> dict:
    """Create a photo record."""
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO photos (event_id, filename, original_name, file_size, width, height)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (event_id, filename, original_name, file_size, width, height))

        photo = dict(cur.fetchone())

        # Increment event photo count
        cur.execute("SELECT increment_event_photo_count(%s)", (event_id,))
        cur.fetchone()  # Consume the result

        return photo


def update_photo_status(photo_id: str, status: str, face_count: int = 0, processing_time_ms: Optional[int] = None):
    """Update photo processing status."""
    now = datetime.now(timezone.utc)
    with get_db_cursor() as cur:
        cur.execute("""
            UPDATE photos
            SET status = %s, face_count = %s, processed_at = %s, processing_time_ms = %s
            WHERE id = %s
            RETURNING event_id
        """, (status, face_count, now, processing_time_ms, photo_id))
        result = cur.fetchone()

        # If status is done, increment event processed count
        if status == "done" and result:
            cur.execute("SELECT increment_event_processed_count(%s)", (result["event_id"],))


def get_photos_for_event(event_id: str) -> List[dict]:
    """Get all photos for an event."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT * FROM photos WHERE event_id = %s ORDER BY uploaded_at DESC
        """, (event_id,))
        return [dict(row) for row in cur.fetchall()]


def get_photo(photo_id: str) -> Optional[dict]:
    """Get a single photo by ID."""
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM photos WHERE id = %s", (photo_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def delete_photo(photo_id: str) -> bool:
    """Delete a single photo."""
    photo = get_photo(photo_id)
    if not photo:
        return False

    event_id = photo["event_id"]
    filename = photo["filename"]
    was_processed = photo.get("status") == "done"

    from app.services.storage import delete_photo_file
    delete_photo_file(event_id, filename)

    with get_db_cursor() as cur:
        cur.execute("DELETE FROM photos WHERE id = %s", (photo_id,))

        # Update event counts
        cur.execute("""
            UPDATE events
            SET photo_count = photo_count - 1,
                processed_count = processed_count - %s
            WHERE id = %s
        """, (1 if was_processed else 0, event_id))

    return True


# ─── Face Embedding Operations ───────────────────────────────────────────────

def save_face_embedding(photo_id: str, event_id: str, embedding: List[float], face_location: tuple):
    """Save a face embedding."""
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO face_embeddings (photo_id, event_id, embedding, face_location)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (photo_id, event_id, json.dumps(embedding), json.dumps(list(face_location))))
        return dict(cur.fetchone())


def get_embeddings_for_event(event_id: str) -> List[dict]:
    """Get all face embeddings for an event."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, photo_id, embedding, face_location
            FROM face_embeddings
            WHERE event_id = %s
        """, (event_id,))
        results = []
        for row in cur.fetchall():
            d = dict(row)
            d["embedding"] = json.loads(d["embedding"])
            d["face_location"] = json.loads(d["face_location"])
            results.append(d)
        return results


def find_similar_faces_vector(event_id: str, selfie_embedding: List[float], threshold: float = 0.4) -> List[dict]:
    """Find similar faces using pgvector."""
    import numpy as np

    if isinstance(selfie_embedding, np.ndarray):
        selfie_embedding = selfie_embedding.tolist()

    vector_str = f"[{','.join(map(str, selfie_embedding))}]"

    with get_db_cursor() as cur:
        cur.execute("""
            SELECT * FROM find_similar_faces(%s::vector, %s, %s)
        """, (vector_str, event_id, threshold))

        return [dict(row) for row in cur.fetchall()]


# ─── Match History Operations ───────────────────────────────────────────────

def record_match(event_id: str, photo_id: str, similarity: float, threshold: float = 0.4, user_id: Optional[str] = None) -> dict:
    """Record a match attempt for analytics."""
    now = datetime.now(timezone.utc)
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO match_history (event_id, photo_id, similarity, threshold_used, match_timestamp, user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (event_id, photo_id, similarity, threshold, now, user_id))
        return dict(cur.fetchone())


def get_similarity_distribution(event_id: str) -> List[dict]:
    """Get similarity score distribution for an event."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT
                CASE
                    WHEN similarity >= 0.90 THEN '0.90-1.00'
                    WHEN similarity >= 0.70 THEN '0.70-0.89'
                    WHEN similarity >= 0.50 THEN '0.50-0.69'
                    WHEN similarity >= 0.40 THEN '0.40-0.49'
                    ELSE '0.00-0.39'
                END as similarity_range,
                COUNT(*) as count
            FROM match_history
            WHERE event_id = %s
            GROUP BY
                CASE
                    WHEN similarity >= 0.90 THEN '0.90-1.00'
                    WHEN similarity >= 0.70 THEN '0.70-0.89'
                    WHEN similarity >= 0.50 THEN '0.50-0.69'
                    WHEN similarity >= 0.40 THEN '0.40-0.49'
                    ELSE '0.00-0.39'
                END
            ORDER BY MIN(similarity) DESC
        """, (event_id,))
        return [dict(row) for row in cur.fetchall()]


def get_similarity_stats(event_id: str) -> dict:
    """Get aggregate similarity statistics for an event."""
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT
                AVG(similarity) as avg_similarity,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY similarity) as median_similarity,
                MIN(similarity) as min_similarity,
                MAX(similarity) as max_similarity,
                COUNT(*) as total_matches
            FROM match_history
            WHERE event_id = %s
        """, (event_id,))
        result = cur.fetchone()
        return dict(result) if result else {}


def estimate_false_positive_rate(event_id: str, low_confidence_threshold: float = 0.50) -> dict:
    """
    Estimate false positive rate based on low confidence matches.
    Returns percentage of matches below the low confidence threshold.
    """
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*) as total_matches,
                COUNT(*) FILTER (WHERE similarity < %s) as low_confidence_matches
            FROM match_history
            WHERE event_id = %s
        """, (low_confidence_threshold, event_id))
        result = cur.fetchone()

        if not result or result["total_matches"] == 0:
            return {
                "false_positive_estimate": 0.0,
                "total_matches": 0,
                "low_confidence_matches": 0
            }

        total = result["total_matches"]
        low_conf = result["low_confidence_matches"]
        fp_rate = round((low_conf / total) * 100, 2)

        return {
            "false_positive_estimate": fp_rate,
            "total_matches": total,
            "low_confidence_matches": low_conf
        }


def get_match_analytics(event_id: str) -> dict:
    """Get comprehensive match analytics for an event."""
    distribution = get_similarity_distribution(event_id)
    stats = get_similarity_stats(event_id)
    fp_rate = estimate_false_positive_rate(event_id)

    # Calculate percentages by range
    total = stats.get("total_matches", 0)
    distribution_dict = {}
    for item in distribution:
        range_key = item["similarity_range"]
        count = item["count"]
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
    with get_db_cursor() as cur:
        cur.execute("SELECT * FROM user_profiles WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def create_user_profile(user_id: str, full_name: Optional[str] = None, email: Optional[str] = None) -> dict:
    """Create a user profile (after Supabase signup)."""
    with get_db_cursor() as cur:
        cur.execute("""
            INSERT INTO user_profiles (id, full_name)
            VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET full_name = COALESCE(EXCLUDED.full_name, user_profiles.full_name)
            RETURNING *
        """, (user_id, full_name))
        return dict(cur.fetchone())


def update_user_profile(user_id: str, full_name: Optional[str] = None, avatar_url: Optional[str] = None) -> Optional[dict]:
    """Update user profile."""
    updates = []
    params = []

    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name)
    if avatar_url is not None:
        updates.append("avatar_url = %s")
        params.append(avatar_url)

    if updates:
        params.append(user_id)
        with get_db_cursor() as cur:
            cur.execute(f"""
                UPDATE user_profiles SET {', '.join(updates)}, updated_at = NOW()
                WHERE id = %s
                RETURNING *
            """, params)
            return dict(cur.fetchone())

    return get_user_profile(user_id)
