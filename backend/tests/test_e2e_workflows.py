"""End-to-end workflow tests for Grapic.

These tests simulate complete user workflows from event creation
through photo upload, processing, and matching.
"""

import pytest
import time
import io
from fastapi.testclient import TestClient
from PIL import Image
from app.main import app


client = TestClient(app)


@pytest.fixture
def test_image_bytes():
    """Create a test image as bytes."""
    img = Image.new('RGB', (800, 600), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes.read()


@pytest.fixture
def test_zip_file(test_image_bytes):
    """Create a test ZIP file with multiple images."""
    import zipfile
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("photo1.jpg", test_image_bytes)
        zip_file.writestr("photo2.jpg", test_image_bytes)
        zip_file.writestr("photo3.jpg", test_image_bytes)
    zip_buffer.seek(0)
    return zip_buffer


class TestEventWorkflow:
    """Test complete event workflow."""

    def test_create_event_lifecycle(self):
        """Test creating, updating, and deleting an event."""
        # Create event
        response = client.post(
            "/api/events",
            json={
                "name": "Test Wedding",
                "description": "Test Description",
                "expires_in_days": 7
            }
        )
        assert response.status_code == 200
        event = response.json()
        event_id = event["id"]

        # Verify event was created
        assert event["name"] == "Test Wedding"
        assert "access_code" in event
        assert "organizer_code" in event
        assert event["expires_at"] is not None

        # Get event details
        response = client.get(f"/api/events/{event_id}")
        assert response.status_code == 200
        assert response.json()["id"] == event_id

        # Update event
        response = client.patch(
            f"/api/events/{event_id}",
            json={"name": "Updated Wedding Name"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Wedding Name"

        # Delete event
        response = client.delete(f"/api/events/{event_id}")
        assert response.status_code == 200

        # Verify deletion
        response = client.get(f"/api/events/{event_id}")
        assert response.status_code == 404

    def test_event_join_with_access_code(self):
        """Test joining an event with access code."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        access_code = event["access_code"]

        # Join as attendee
        response = client.post(
            "/api/events/join",
            json={"access_code": access_code}
        )
        assert response.status_code == 200
        joined_event = response.json()

        # Should not expose organizer details
        assert "organizer_code" not in joined_event
        assert "user_id" not in joined_event
        assert joined_event["id"] == event["id"]

    def test_organizer_join(self):
        """Test organizer login with organizer code."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        organizer_code = event["organizer_code"]

        # Login as organizer
        response = client.post(
            "/api/events/organizer-join",
            json={"organizer_code": organizer_code}
        )
        assert response.status_code == 200
        organizer_event = response.json()

        # Should expose all details to organizer
        assert "organizer_code" in organizer_event
        assert organizer_event["id"] == event["id"]

    def test_qr_code_generation(self):
        """Test QR code generation for event."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()

        # Get QR code
        response = client.get(f"/api/events/{event['id']}/qr")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

        # Verify it's a valid image
        qr_data = response.content
        assert len(qr_data) > 0


class TestPhotoWorkflow:
    """Test complete photo upload and processing workflow."""

    def test_single_photo_upload(self, test_image_bytes):
        """Test uploading a single photo."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        # Upload photo
        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"files": ("test.jpg", test_image_bytes, "image/jpeg")}
        )
        assert response.status_code == 200
        result = response.json()

        # Should return uploaded photos
        assert "uploaded" in result
        assert len(result["uploaded"]) == 1

        # Verify photo appears in list
        response = client.get(f"/api/events/{event_id}/photos")
        assert response.status_code == 200
        photos = response.json()

        assert len(photos) >= 1
        assert photos[0]["original_name"] == "test.jpg"

    def test_bulk_photo_upload(self, test_zip_file):
        """Test bulk upload via ZIP file."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        # Upload ZIP
        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"zip": ("photos.zip", test_zip_file, "application/zip")}
        )
        assert response.status_code == 200
        result = response.json()

        # Should extract and upload all photos
        assert "uploaded" in result
        assert len(result["uploaded"]) == 3

        # Verify all photos in list
        response = client.get(f"/api/events/{event_id}/photos")
        assert response.status_code == 200
        photos = response.json()

        assert len(photos) == 3

    def test_photo_download(self, test_image_bytes):
        """Test downloading individual photos."""
        # Create event and upload photo
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"files": ("test.jpg", test_image_bytes, "image/jpeg")}
        )
        upload_result = response.json()
        photo_id = upload_result["uploaded"][0]["id"]

        # Download photo
        response = client.get(f"/api/photos/{photo_id}/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

        # Verify content
        downloaded_bytes = response.content
        assert len(downloaded_bytes) > 0

    def test_photo_deletion(self, test_image_bytes):
        """Test deleting photos."""
        # Create event and upload photo
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"files": ("test.jpg", test_image_bytes, "image/jpeg")}
        )
        upload_result = response.json()
        photo_id = upload_result["uploaded"][0]["id"]

        # Delete photo
        response = client.delete(f"/api/photos/{photo_id}")
        assert response.status_code == 200

        # Verify deletion
        response = client.get(f"/api/events/{event_id}/photos")
        photos = response.json()
        photo_ids = [p["id"] for p in photos]
        assert photo_id not in photo_ids


class TestProgressTracking:
    """Test real-time progress tracking."""

    def test_progress_after_upload(self, test_zip_file):
        """Test progress tracking during upload."""
        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        # Upload photos
        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"zip": ("photos.zip", test_zip_file, "application/zip")}
        )
        assert response.status_code == 200

        # Check progress
        response = client.get(f"/api/events/{event_id}/progress/status")
        assert response.status_code == 200
        progress = response.json()

        # Should have uploaded count
        assert "uploaded" in progress
        assert "total" in progress
        assert progress["uploaded"] == 3
        assert progress["total"] == 3


class TestAnalytics:
    """Test analytics and monitoring endpoints."""

    def test_event_analytics(self, test_zip_file):
        """Test event statistics."""
        # Create event and upload photos
        response = client.post(
            "/api/events",
            json={"name": "Test Event", "expires_in_days": 7}
        )
        event = response.json()
        event_id = event["id"]

        client.post(
            f"/api/events/{event_id}/photos",
            files={"zip": ("photos.zip", test_zip_file, "application/zip")}
        )

        # Get analytics
        response = client.get(f"/api/analytics/events/{event_id}/stats")
        assert response.status_code == 200
        stats = response.json()

        # Should have basic stats
        assert "photos" in stats
        assert stats["photos"]["total"] == 3
        assert "event_id" in stats

    def test_system_health(self):
        """Test system health endpoint."""
        response = client.get("/api/health")
        assert response.status_code == 200
        health = response.json()

        # Should have service status
        assert "status" in health
        assert "service" in health
        assert health["service"] == "grapic"

        # Should have database info
        assert "database_type" in health


class TestMetrics:
    """Test Prometheus metrics export."""

    def test_metrics_endpoint(self):
        """Test that metrics endpoint returns valid Prometheus format."""
        response = client.get("/metrics")
        assert response.status_code == 200

        metrics_text = response.text

        # Should have HTTP request metrics
        assert "grapic_http_requests_total" in metrics_text

        # Should have HTTP duration metrics
        assert "grapic_http_request_duration_seconds" in metrics_text


@pytest.mark.parametrize("endpoint,method,expected_status", [
    ("/api/events", "GET", 200),
    ("/api/health", "GET", 200),
    ("/metrics", "GET", 200),
])
def test_core_endpoints_respond(endpoint, method, expected_status):
    """Test that core endpoints respond."""
    if method == "GET":
        response = client.get(endpoint)
    assert response.status_code == expected_status
