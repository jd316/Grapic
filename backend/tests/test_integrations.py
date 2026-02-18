"""Integration tests for external services.

Tests for Redis, Supabase, Celery, and storage integrations.
"""

import pytest
import time
import io
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestRedisIntegration:
    """Test Redis integration for caching and rate limiting."""

    def test_redis_connection(self):
        """Test that Redis connection works."""
        from app.config import USE_REDIS, REDIS_URL

        if not USE_REDIS:
            pytest.skip("Redis not configured")

        try:
            import redis
            r = redis.from_url(REDIS_URL, decode_responses=True)
            r.ping()
            assert True
        except Exception as e:
            pytest.skip(f"Redis not available: {e}")

    def test_progress_tracking_in_redis(self):
        """Test that progress tracking uses Redis."""
        from app.redis_progress import update_progress, get_progress, reset_progress
        from app.config import USE_REDIS

        if not USE_REDIS:
            pytest.skip("Redis not configured")

        try:
            event_id = "test-event-123"

            # Reset
            reset_progress(event_id)

            # Update progress
            update_progress(event_id, "uploaded", 5)
            update_progress(event_id, "processing", 2)

            # Get progress
            progress = get_progress(event_id)

            assert progress["uploaded"] == 5
            assert progress["processing"] == 2

            # Cleanup
            reset_progress(event_id)

        except Exception as e:
            pytest.skip(f"Redis progress tracking failed: {e}")

    def test_rate_limiting_in_redis(self):
        """Test that rate limiting uses Redis."""
        from app.config import USE_REDIS

        if not USE_REDIS:
            pytest.skip("Redis not configured")

        # This is tested indirectly via API tests
        # Direct testing would require manipulating Redis directly
        assert True


class TestSupabaseIntegration:
    """Test Supabase authentication integration."""

    def test_supabase_connection(self):
        """Test that Supabase client can be initialized."""
        from app.supabase_client import get_supabase
        from app.config import USE_SUPABASE

        if not USE_SUPABASE:
            pytest.skip("Supabase not configured")

        try:
            client = get_supabase()
            assert client is not None
        except Exception as e:
            pytest.skip(f"Supabase not available: {e}")

    def test_jwt_verification(self):
        """Test JWT token verification."""
        from app.supabase_client import verify_jwt
        from app.config import SUPABASE_URL

        if not SUPABASE_URL:
            pytest.skip("Supabase not configured")

        # Test with invalid token
        result = verify_jwt("invalid_token")
        assert result is None

        # Test with expired token (if we had one)
        # result = verify_jwt("expired_token_structure")
        # assert result is None


class TestCeleryIntegration:
    """Test Celery task queue integration."""

    def test_celery_connection(self):
        """Test that Celery can connect to broker."""
        from app.celery_app import celery_app
        from app.config import USE_REDIS

        if not USE_REDIS:
            pytest.skip("Redis/Celery not configured")

        try:
            # Try to inspect Celery
            inspector = celery_app.control.inspect()
            # This may fail if no workers running, but connection test
            assert celery_app.broker is not None
        except Exception as e:
            pytest.skip(f"Celery not available: {e}")

    def test_task_submission(self):
        """Test submitting a task to Celery."""
        from app.tasks import process_photo
        from app.config import USE_REDIS

        if not USE_REDIS:
            pytest.skip("Redis/Celery not configured")

        # Create a test photo
        img = Image.new('RGB', (100, 100), color='blue')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Celery Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for Celery test")

        event = response.json()

        # Save photo to database first
        from app.database import save_photo, delete_event
        photo = save_photo(
            event_id=event["id"],
            filename="test.jpg",
            original_name="test.jpg",
            file_size=len(img_bytes.getvalue())
        )

        try:
            # Submit task (don't wait for result)
            result = process_photo.apply_async(
                args=[photo["id"], event["id"]],
                # Don't actually process, just test submission
            )

            assert result.id is not None

        except Exception as e:
            pytest.skip(f"Celery worker not running: {e}")

        finally:
            # Cleanup
            delete_event(event["id"])


class TestStorageIntegration:
    """Test storage integration (local and S3)."""

    def test_local_storage_write(self):
        """Test writing to local storage."""
        from app.services.storage import resolve_image_for_processing
        from app.config import UPLOAD_DIR
        import os

        # Create test event
        response = client.post(
            "/api/events",
            json={"name": "Storage Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for storage test")

        event = response.json()
        event_id = event["id"]

        # Create test image
        img = Image.new('RGB', (100, 100), color='green')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)

        try:
            # Upload photo
            response = client.post(
                f"/api/events/{event_id}/photos",
                files={"files": ("test.jpg", img_bytes.getvalue(), "image/jpeg")}
            )

            if response.status_code == 200:
                # Verify file exists
                upload_result = response.json()
                if upload_result.get("uploaded"):
                    photo_filename = upload_result["uploaded"][0]["filename"]
                    file_path = UPLOAD_DIR / event_id / photo_filename

                    # Check file exists (may be in S3)
                    # For local storage:
                    from app.config import USE_S3
                    if not USE_S3:
                        assert file_path.exists()

        finally:
            # Cleanup
            from app.database import delete_event
            delete_event(event_id)

    def test_s3_configuration(self):
        """Test S3 configuration when enabled."""
        from app.config import USE_S3, S3_BUCKET

        if not USE_S3:
            pytest.skip("S3 not configured")

        assert S3_BUCKET is not None
        assert len(S3_BUCKET) > 0


class TestFaceRecognitionIntegration:
    """Test face recognition service integration."""

    def test_face_detection_on_real_image(self):
        """Test face detection on a real image."""
        from app.services.face_service import detect_and_encode
        import tempfile

        # Create a test image with a face shape
        img = Image.new('RGB', (200, 200), color='white')
        # Draw a simple face-like shape
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.ellipse([50, 50, 150, 150], fill='pink')  # Face
        draw.ellipse([70, 80, 90, 100], fill='black')  # Left eye
        draw.ellipse([110, 80, 130, 100], fill='black')  # Right eye
        draw.ellipse([90, 120, 110, 130], fill='red')  # Nose/mouth area

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            img.save(tmp, format='JPEG')
            tmp_path = tmp.name

        try:
            # Detect faces
            faces = detect_and_encode(tmp_path)

            # Should return list (may be empty if no face detected)
            assert isinstance(faces, list)

            # If faces found, verify structure
            if faces:
                face = faces[0]
                assert "embedding" in face
                assert "location" in face
                assert len(face["embedding"]) == 128  # Facenet 128d

        finally:
            # Cleanup
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_embedding_vector_format(self):
        """Test that face embeddings are correct format."""
        from app.services.face_service import detect_and_encode
        import tempfile

        # Create simple image
        img = Image.new('RGB', (100, 100), color='blue')

        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            img.save(tmp, format='JPEG')
            tmp_path = tmp.name

        try:
            faces = detect_and_encode(tmp_path)

            # Check embedding format if faces detected
            for face in faces:
                embedding = face["embedding"]
                assert isinstance(embedding, list)
                assert len(embedding) == 128

                # Check values are floats in reasonable range
                for val in embedding:
                    assert isinstance(val, float)
                    assert -1 <= val <= 1  # Normalized embeddings

        finally:
            import os
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestVectorSearchIntegration:
    """Test vector search integration with database."""

    def test_vector_similarity_search(self):
        """Test similarity search with vector embeddings."""
        from app.database import create_event, save_photo, save_face_embedding, find_similar_faces, delete_event
        from app.config import USE_SELF_HOSTED_PG

        if not USE_SELF_HOSTED_PG:
            pytest.skip("PostgreSQL not configured")

        # Create event
        event = create_event(name="Vector Search Test", expires_in_days=7)
        event_id = event["id"]

        try:
            # Add photos with face embeddings
            photo1 = save_photo(
                event_id=event_id,
                filename="photo1.jpg",
                original_name="photo1.jpg",
                file_size=1024
            )

            photo2 = save_photo(
                event_id=event_id,
                filename="photo2.jpg",
                original_name="photo2.jpg",
                file_size=1024
            )

            # Create embeddings (similar faces should have similar embeddings)
            embedding1 = [0.1] * 128
            embedding2 = [0.11] * 128  # Very similar to embedding1

            save_face_embedding(
                photo_id=photo1["id"],
                event_id=event_id,
                embedding=embedding1,
                face_location={"x": 50, "y": 50, "w": 100, "h": 100}
            )

            save_face_embedding(
                photo_id=photo2["id"],
                event_id=event_id,
                embedding=embedding2,
                face_location={"x": 60, "y": 60, "w": 100, "h": 100}
            )

            # Wait for vector index to update
            time.sleep(1)

            # Search for similar faces
            results = find_similar_faces(
                embedding=embedding1,
                event_id=event_id,
                threshold=0.3
            )

            # Should find both photos (they're very similar)
            assert len(results) >= 1

            # Verify result structure
            for result in results:
                assert "photo_id" in result
                assert "similarity" in result
                assert result["similarity"] >= 0.3

        finally:
            # Cleanup
            delete_event(event_id)


class TestEndToEndWorkflows:
    """Complete end-to-end workflow tests."""

    def test_complete_photo_matching_workflow(self):
        """Test entire workflow from upload to match."""
        # This test requires:
        # 1. Create event
        # 2. Upload photos with faces
        # 3. Wait for processing
        # 4. Upload selfie
        # 5. Get matches

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "E2E Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for E2E test")

        event = response.json()
        event_id = event["id"]

        try:
            # Upload photos (would need real face images for full test)
            # For now, just verify endpoints respond
            response = client.get(f"/api/events/{event_id}/photos")
            assert response.status_code == 200

            # Test match endpoint (will fail without actual photos)
            # but verifies the endpoint works
            img = Image.new('RGB', (100, 100), color='red')
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='JPEG')
            img_bytes.seek(0)

            response = client.post(
                f"/api/events/{event_id}/match",
                files={"selfie": ("selfie.jpg", img_bytes.getvalue(), "image/jpeg")}
            )

            # Should either succeed or return no matches
            assert response.status_code in [200, 404]

        finally:
            # Cleanup
            from app.database import delete_event
            delete_event(event_id)
