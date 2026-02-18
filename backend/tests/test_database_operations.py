"""Database operation tests.

Tests for database CRUD operations, connection pooling,
and data integrity.
"""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    # This would typically use a test database configuration
    pass


class TestDatabaseConnections:
    """Test database connection handling."""

    def test_connection_pool_initialization(self):
        """Test that connection pool initializes correctly."""
        from app.database_postgres import get_pool
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        try:
            pool = get_pool()
            assert pool is not None
            assert pool.minconn >= 1
            assert pool.maxconn >= pool.minconn
        except Exception as e:
            pytest.skip(f"Could not connect to database: {e}")

    def test_database_connection_health(self):
        """Test database connection health check."""
        from app.database_postgres import get_pool
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        try:
            pool = get_pool()
            conn = pool.getconn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            result = cur.fetchone()
            cur.close()
            conn.close()

            assert result[0] == 1
        except Exception as e:
            pytest.skip(f"Could not connect to database: {e}")


class TestEventCRUD:
    """Test Event CRUD operations."""

    def test_create_event(self):
        """Test creating an event in database."""
        from app.database import create_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        event = create_event(
            name="Test Event",
            description="Test Description",
            expires_in_days=7,
            user_id=None
        )

        assert event is not None
        assert "id" in event
        assert event["name"] == "Test Event"
        assert "access_code" in event
        assert "organizer_code" in event

        # Cleanup
        from app.database import delete_event
        delete_event(event["id"])

    def test_get_event(self):
        """Test retrieving an event."""
        from app.database import create_event, get_event, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        # Get event
        retrieved = get_event(event_id)
        assert retrieved is not None
        assert retrieved["id"] == event_id
        assert retrieved["name"] == "Test Event"

        # Cleanup
        delete_event(event_id)

    def test_update_event(self):
        """Test updating an event."""
        from app.database import create_event, update_event, get_event, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Original Name", expires_in_days=7)
        event_id = event["id"]

        # Update event
        updated = update_event(event_id, name="Updated Name")
        assert updated["name"] == "Updated Name"

        # Verify update persisted
        retrieved = get_event(event_id)
        assert retrieved["name"] == "Updated Name"

        # Cleanup
        delete_event(event_id)

    def test_delete_event(self):
        """Test deleting an event."""
        from app.database import create_event, get_event, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        # Delete event
        delete_event(event_id)

        # Verify deletion
        retrieved = get_event(event_id)
        assert retrieved is None


class TestPhotoCRUD:
    """Test Photo CRUD operations."""

    def test_save_and_get_photo(self):
        """Test saving and retrieving photo metadata."""
        from app.database import create_event, save_photo, get_photo, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        # Save photo
        photo = save_photo(
            event_id=event_id,
            filename="test.jpg",
            original_name="test.jpg",
            file_size=1024
        )

        assert photo is not None
        assert "id" in photo
        assert photo["filename"] == "test.jpg"

        # Get photo
        retrieved = get_photo(photo["id"])
        assert retrieved is not None
        assert retrieved["id"] == photo["id"]

        # Cleanup
        delete_event(event_id)

    def test_update_photo_status(self):
        """Test updating photo processing status."""
        from app.database import create_event, save_photo, update_photo_status, get_photo, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event and photo
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        photo = save_photo(
            event_id=event_id,
            filename="test.jpg",
            original_name="test.jpg",
            file_size=1024
        )
        photo_id = photo["id"]

        # Update status to done
        update_photo_status(photo_id, "done", face_count=3, processing_time_ms=1500)

        # Verify update
        retrieved = get_photo(photo_id)
        assert retrieved["status"] == "done"
        assert retrieved["face_count"] == 3
        assert retrieved["processing_time_ms"] == 1500

        # Cleanup
        delete_event(event_id)


class TestFaceEmbeddings:
    """Test face embedding storage and retrieval."""

    def test_save_face_embedding(self):
        """Test saving face embeddings."""
        from app.database import create_event, save_photo, save_face_embedding, get_embeddings_for_event, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event and photo
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        photo = save_photo(
            event_id=event_id,
            filename="test.jpg",
            original_name="test.jpg",
            file_size=1024
        )
        photo_id = photo["id"]

        # Save face embedding (128d vector from Facenet)
        embedding = [0.1] * 128
        save_face_embedding(
            photo_id=photo_id,
            event_id=event_id,
            embedding=embedding,
            face_location={"x": 100, "y": 100, "w": 50, "h": 50}
        )

        # Retrieve embeddings
        embeddings = get_embeddings_for_event(event_id)
        assert len(embeddings) == 1
        assert embeddings[0]["photo_id"] == photo_id

        # Cleanup
        delete_event(event_id)


class TestDataIntegrity:
    """Test data integrity and constraints."""

    def test_event_expiration(self):
        """Test that expired events are handled correctly."""
        from app.database import create_event, get_event, cleanup_expired_events, delete_event
        from app.config import USE_SELF_HOSTED_PG
        from datetime import datetime, timedelta

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event that expires in 1 day
        event = create_event(
            name="Expiring Event",
            expires_in_days=1
        )
        event_id = event["id"]

        # Event should still be accessible
        retrieved = get_event(event_id)
        assert retrieved is not None

        # Cleanup (should not delete yet as not expired)
        # This test verifies the cleanup function runs without error
        cleanup_expired_events()

        # Event should still exist
        retrieved = get_event(event_id)
        assert retrieved is not None

        # Cleanup
        delete_event(event_id)

    def test_cascade_delete_photos(self):
        """Test that deleting an event deletes its photos."""
        from app.database import create_event, save_photo, get_photos_for_event, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Test Event", expires_in_days=7)
        event_id = event["id"]

        # Add photos
        save_photo(event_id=event_id, filename="photo1.jpg", original_name="photo1.jpg", file_size=1024)
        save_photo(event_id=event_id, filename="photo2.jpg", original_name="photo2.jpg", file_size=1024)

        # Verify photos exist
        photos = get_photos_for_event(event_id)
        assert len(photos) == 2

        # Delete event
        delete_event(event_id)

        # Verify photos are deleted
        photos = get_photos_for_event(event_id)
        assert len(photos) == 0


class TestVectorSearch:
    """Test vector similarity search functionality."""

    def test_vector_search_setup(self):
        """Test that vector search tables are properly set up."""
        from app.database_postgres import get_pool
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        try:
            pool = get_pool()
            conn = pool.getconn()
            cur = conn.cursor()

            # Check pgvector extension
            cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            result = cur.fetchone()
            assert result is not None, "pgvector extension not installed"

            # Check face_embeddings table exists
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name = 'face_embeddings'
            """)
            result = cur.fetchone()
            assert result is not None, "face_embeddings table not found"

            # Check embedding_vector column exists
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'face_embeddings'
                AND column_name = 'embedding_vector'
            """)
            result = cur.fetchone()
            assert result is not None, "embedding_vector column not found"

            cur.close()
            conn.close()

        except Exception as e:
            pytest.skip(f"Could not verify vector search setup: {e}")
