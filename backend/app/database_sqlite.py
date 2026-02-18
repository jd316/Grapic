"""SQLite database fallback (for backward compatibility during migration)."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for database transactions."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Initialize database schema."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                access_code TEXT UNIQUE NOT NULL,
                organizer_code TEXT UNIQUE,
                photo_count INTEGER DEFAULT 0,
                processed_count INTEGER DEFAULT 0,
                attendee_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                width INTEGER DEFAULT 0,
                height INTEGER DEFAULT 0,
                face_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                uploaded_at TEXT NOT NULL,
                processed_at TEXT,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS face_embeddings (
                id TEXT PRIMARY KEY,
                photo_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                embedding TEXT NOT NULL,
                face_location TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id);
            CREATE INDEX IF NOT EXISTS idx_photos_status ON photos(status);
            CREATE INDEX IF NOT EXISTS idx_faces_event ON face_embeddings(event_id);
            CREATE INDEX IF NOT EXISTS idx_faces_photo ON face_embeddings(photo_id);
            CREATE INDEX IF NOT EXISTS idx_events_access ON events(access_code);
        """)
        # Migration: add processing_time_ms for PRD 8
        try:
            conn.execute("ALTER TABLE photos ADD COLUMN processing_time_ms INTEGER")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise
        # Migration: add organizer_code for existing DBs (separate from attendee access_code)
        try:
            conn.execute("ALTER TABLE events ADD COLUMN organizer_code TEXT")
            conn.execute("UPDATE events SET organizer_code = access_code WHERE organizer_code IS NULL")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise


# ─── Event Operations ──────────────────────────────────────────────

def create_event(name: str, description: str = "", expires_in_days: Optional[int] = 7) -> dict:
    """Create a new event and return its data."""
    event_id = str(uuid.uuid4())
    access_code = uuid.uuid4().hex[:8].upper()  # For attendees to join
    organizer_code = uuid.uuid4().hex[:8].upper()  # For organizer dashboard only
    now = datetime.now(timezone.utc).isoformat()
    expires_at = None
    if expires_in_days:
        from datetime import timedelta
        expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (id, name, description, created_at, expires_at, access_code, organizer_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, name, description, now, expires_at, access_code, organizer_code),
        )

    return {
        "id": event_id,
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


def get_event(event_id: str) -> Optional[dict]:
    """Get event by ID with computed metrics (avg_processing_sec, engagement_pct)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        ev = dict(row)
        stats = conn.execute(
            "SELECT AVG(processing_time_ms) as avg_ms FROM photos WHERE event_id = ? AND status = 'done' AND processing_time_ms IS NOT NULL",
            (event_id,),
        ).fetchone()
        ev["avg_processing_sec"] = round(stats["avg_ms"] / 1000, 2) if stats and stats["avg_ms"] else None
        ev["engagement_pct"] = round((ev["attendee_count"] / max(1, ev["photo_count"])) * 100, 1) if ev["photo_count"] else 0
        return ev


def get_event_by_code(access_code: str) -> Optional[dict]:
    """Get event by attendee access code (for joining to find photos)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM events WHERE access_code = ?", (access_code.upper(),)).fetchone()
        return dict(row) if row else None


def get_event_by_organizer_code(organizer_code: str) -> Optional[dict]:
    """Get event by organizer code (for dashboard access)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE organizer_code = ?", (organizer_code.upper(),)
        ).fetchone()
        return dict(row) if row else None


def update_event(event_id: str, name: Optional[str] = None, description: Optional[str] = None, expires_in_days: Optional[int] = None) -> Optional[dict]:
    """Update event fields. Returns updated event or None."""
    event = get_event(event_id)
    if not event:
        return None
    if name is not None or description is not None or expires_in_days is not None:
        with get_db() as conn:
            if name is not None:
                conn.execute("UPDATE events SET name = ? WHERE id = ?", (name, event_id))
            if description is not None:
                conn.execute("UPDATE events SET description = ? WHERE id = ?", (description, event_id))
            if expires_in_days is not None:
                from datetime import timedelta
                new_expires = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
                conn.execute("UPDATE events SET expires_at = ? WHERE id = ?", (new_expires, event_id))
    return get_event(event_id)


def delete_event(event_id: str) -> bool:
    """Delete an event and all related data."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return cursor.rowcount > 0


def delete_photo(photo_id: str) -> bool:
    """Delete a single photo, its files, and face embeddings. Returns True if deleted."""
    photo = get_photo(photo_id)
    if not photo:
        return False
    event_id = photo["event_id"]
    filename = photo["filename"]
    was_processed = photo.get("status") == "done"

    from app.services.storage import delete_photo_file
    delete_photo_file(event_id, filename)

    with get_db() as conn:
        conn.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
        conn.execute("UPDATE events SET photo_count = photo_count - 1 WHERE id = ?", (event_id,))
        if was_processed:
            conn.execute("UPDATE events SET processed_count = processed_count - 1 WHERE id = ?", (event_id,))
    return True


def increment_attendee_count(event_id: str):
    """Increment the attendee usage counter."""
    with get_db() as conn:
        conn.execute("UPDATE events SET attendee_count = attendee_count + 1 WHERE id = ?", (event_id,))


# ─── Photo Operations ──────────────────────────────────────────────

def create_photo(event_id: str, filename: str, original_name: str, file_size: int, width: int, height: int) -> dict:
    """Create a photo record."""
    photo_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO photos (id, event_id, filename, original_name, file_size, width, height, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (photo_id, event_id, filename, original_name, file_size, width, height, now),
        )
        conn.execute("UPDATE events SET photo_count = photo_count + 1 WHERE id = ?", (event_id,))

    return {
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
        "processed_at": None,
    }


def update_photo_status(photo_id: str, status: str, face_count: int = 0, processing_time_ms: Optional[int] = None):
    """Update photo processing status."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE photos SET status = ?, face_count = ?, processed_at = ?, processing_time_ms = COALESCE(?, processing_time_ms) WHERE id = ?",
            (status, face_count, now, processing_time_ms, photo_id),
        )
        if status == "done":
            row = conn.execute("SELECT event_id FROM photos WHERE id = ?", (photo_id,)).fetchone()
            if row:
                conn.execute("UPDATE events SET processed_count = processed_count + 1 WHERE id = ?", (row["event_id"],))


def get_photos_for_event(event_id: str) -> list[dict]:
    """Get all photos for an event."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM photos WHERE event_id = ? ORDER BY uploaded_at DESC", (event_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_photo(photo_id: str) -> Optional[dict]:
    """Get a single photo by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return dict(row) if row else None


# ─── Face Embedding Operations ─────────────────────────────────────

def save_face_embedding(photo_id: str, event_id: str, embedding: list[float], face_location: tuple):
    """Save a face embedding."""
    emb_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        conn.execute(
            "INSERT INTO face_embeddings (id, photo_id, event_id, embedding, face_location, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (emb_id, photo_id, event_id, json.dumps(embedding), json.dumps(face_location), now),
        )


def get_embeddings_for_event(event_id: str) -> list[dict]:
    """Get all face embeddings for an event."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, photo_id, embedding, face_location FROM face_embeddings WHERE event_id = ?",
            (event_id,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["embedding"] = json.loads(d["embedding"])
            d["face_location"] = json.loads(d["face_location"])
            results.append(d)
        return results


def cleanup_expired_events() -> list[dict]:
    """Delete events that have passed their expiration date. Returns list of deleted events."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM events WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        ).fetchall()

    deleted = []
    for row in rows:
        from app.services.storage import delete_event_files
        logger = __import__("logging").getLogger(__name__)
        logger.info(f"Auto-deleting expired event: {row['name']} ({row['id']})")
        delete_event_files(row["id"])
        delete_event(row["id"])
        deleted.append(dict(row))

    if deleted:
        logger = __import__("logging").getLogger(__name__)
        logger.info(f"Cleaned up {len(deleted)} expired event(s)")

    return deleted


# ─── Match History Operations (SQLite) ────────────────────────────

def record_match(event_id: str, photo_id: str, similarity: float, threshold: float = 0.4, user_id: Optional[str] = None) -> dict:
    """Record a match attempt for analytics (SQLite version - simplified)."""
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO match_history (event_id, photo_id, similarity, threshold_used, match_timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (event_id, photo_id, similarity, threshold, now))
        return {"id": str(uuid.uuid4()), "event_id": event_id, "photo_id": photo_id}


def get_similarity_distribution(event_id: str) -> list[dict]:
    """Get similarity score distribution for an event (SQLite version - simplified)."""
    with get_db() as conn:
        rows = conn.execute("""
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
            WHERE event_id = ?
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
        return [dict(r) for r in rows.fetchall()]


def get_similarity_stats(event_id: str) -> dict:
    """Get aggregate similarity statistics for an event (SQLite version - simplified)."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                AVG(similarity) as avg_similarity,
                MIN(similarity) as min_similarity,
                MAX(similarity) as max_similarity,
                COUNT(*) as total_matches
            FROM match_history
            WHERE event_id = ?
        """, (event_id,)).fetchone()
        return dict(row) if row else {
            "avg_similarity": 0,
            "min_similarity": 0,
            "max_similarity": 0,
            "total_matches": 0
        }


def estimate_false_positive_rate(event_id: str, low_confidence_threshold: float = 0.50) -> dict:
    """Estimate false positive rate for an event (SQLite version - simplified)."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_matches,
                COUNT(*) FILTER (WHERE similarity < ?) as low_confidence_matches
            FROM match_history
            WHERE event_id = ?
        """, (low_confidence_threshold, event_id,)).fetchone()
        return dict(row) if row else {
            "false_positive_estimate": 0.0,
            "total_matches": 0,
            "low_confidence_matches": 0
        }


def get_match_analytics(event_id: str) -> dict:
    """Get comprehensive match analytics for an event (SQLite version)."""
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
            "median": round(stats.get("avg_similarity", 0), 4),  # SQLite: no median, use avg
            "min": round(stats.get("min_similarity", 0), 4),
            "max": round(stats.get("max_similarity", 0), 4),
            "total": stats.get("total_matches", 0)
        },
        "false_positive_estimate": fp_rate
    }
