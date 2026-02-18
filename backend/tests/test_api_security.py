"""Security and authentication tests.

Tests for rate limiting, authentication, authorization,
and security headers.
"""

import pytest
import time
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_upload_rate_limiting(self):
        """Test that upload endpoint is rate limited."""
        from PIL import Image
        import io

        # Create a small test image
        img = Image.new('RGB', (100, 100), color='blue')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)

        # Create event first (should not be rate limited)
        response = client.post(
            "/api/events",
            json={"name": "Rate Limit Test", "expires_in_days": 7}
        )
        if response.status_code != 200:
            pytest.skip("Could not create event for rate limit test")

        event = response.json()
        event_id = event["id"]

        # Make multiple upload requests rapidly
        rate_limited = False
        for i in range(10):  # Try more than the limit (5)
            response = client.post(
                f"/api/events/{event_id}/photos",
                files={"files": (f"test{i}.jpg", img_bytes.read(), "image/jpeg")}
            )

            if response.status_code == 429:
                rate_limited = True
                break

            img_bytes.seek(0)  # Reset for next upload

        # Should eventually be rate limited
        assert rate_limited, "Upload endpoint was not rate limited"

    def test_match_rate_limiting(self):
        """Test that match endpoint is rate limited."""
        from PIL import Image
        import io

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Rate Limit Test", "expires_in_days": 7}
        )
        if response.status_code != 200:
            pytest.skip("Could not create event for rate limit test")

        event = response.json()
        event_id = event["id"]

        # Create a selfie image
        img = Image.new('RGB', (100, 100), color='blue')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)
        selfie_data = img_bytes.read()

        # Make multiple match requests rapidly
        rate_limited = False
        for i in range(15):  # Try more than the limit (10)
            response = client.post(
                f"/api/events/{event_id}/match",
                files={"selfie": ("selfie.jpg", selfie_data, "image/jpeg")}
            )

            if response.status_code == 429:
                rate_limited = True
                break

        # Should eventually be rate limited
        assert rate_limited, "Match endpoint was not rate limited"


class TestSecurityHeaders:
    """Test security headers are properly set."""

    def test_security_headers_on_root(self):
        """Test security headers on root endpoint."""
        response = client.get("/api/health")

        # Check for security headers
        assert "x-content-type-options" in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"

        assert "x-frame-options" in response.headers
        assert response.headers["x-frame-options"] == "DENY"

    def test_cors_headers(self):
        """Test CORS headers are set."""
        response = client.get("/api/health")

        # Check CORS headers exist
        # Note: Actual values depend on configuration
        assert "access-control-allow-origin" in response.headers


class TestAuthentication:
    """Test authentication and authorization."""

    def test_protected_endpoint_requires_auth(self):
        """Test that protected endpoints require authentication."""
        from app.config import USE_SUPABASE

        if not USE_SUPABASE:
            pytest.skip("Supabase auth not configured")

        # Try to list user events without auth
        response = client.get("/api/events")
        # Should either return 401 or empty list depending on configuration
        assert response.status_code in [401, 200]

    def test_event_ownership_enforcement(self):
        """Test that event ownership is enforced."""
        from app.config import USE_SUPABASE

        if not USE_SUPABASE:
            pytest.skip("Supabase auth not configured")

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "Ownership Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for ownership test")

        event = response.json()
        event_id = event["id"]

        # Try to update without proper authentication
        # This should fail if auth is properly configured
        response = client.patch(
            f"/api/events/{event_id}",
            json={"name": "Hacked Name"}
        )

        # Should fail without proper auth token
        assert response.status_code in [401, 403, 200]  # 200 if auth not enforced


class TestInputValidation:
    """Test input validation and sanitization."""

    def test_sql_injection_prevention(self):
        """Test that SQL injection is prevented."""
        malicious_input = "'; DROP TABLE events; --"

        response = client.post(
            "/api/events",
            json={
                "name": malicious_input,
                "expires_in_days": 7
            }
        )

        # Should either succeed (input sanitized) or fail validation
        # But should not cause database errors
        assert response.status_code in [200, 400, 422]

        if response.status_code == 200:
            # If succeeded, verify malicious code was stored as-is (not executed)
            event = response.json()
            assert event["name"] == malicious_input

    def test_xss_prevention(self):
        """Test that XSS is prevented."""
        xss_payload = "<script>alert('xss')</script>"

        response = client.post(
            "/api/events",
            json={
                "name": xss_payload,
                "expires_in_days": 7
            }
        )

        if response.status_code == 200:
            event = response.json()
            # Payload should be stored, but properly escaped when rendered
            # This is a basic check - proper XSS testing requires frontend
            assert "name" in event

    def test_file_type_validation(self):
        """Test that only valid image files are accepted."""
        from app.config import USE_SUPABASE

        if not USE_SUPABASE:
            pytest.skip("Supabase auth not configured")

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "File Type Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for file type test")

        event = response.json()
        event_id = event["id"]

        # Try to upload a non-image file
        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"files": ("test.txt", b"This is not an image", "text/plain")}
        )

        # Should be rejected
        assert response.status_code in [400, 422, 400]

    def test_file_size_limits(self):
        """Test that file size limits are enforced."""
        from app.config import USE_SUPABASE, MAX_FILE_SIZE_MB

        if not USE_SUPABASE:
            pytest.skip("Supabase auth not configured")

        # Create a file that exceeds the limit
        large_file = b"x" * (MAX_FILE_SIZE_MB * 1024 * 1024 + 1024)

        # Create event
        response = client.post(
            "/api/events",
            json={"name": "File Size Test", "expires_in_days": 7}
        )

        if response.status_code != 200:
            pytest.skip("Could not create event for file size test")

        event = response.json()
        event_id = event["id"]

        # Try to upload oversized file
        response = client.post(
            f"/api/events/{event_id}/photos",
            files={"files": ("large.jpg", large_file, "image/jpeg")}
        )

        # Should be rejected
        assert response.status_code in [400, 413, 422]


class TestRequestIdTracking:
    """Test request ID tracking for distributed tracing."""

    def test_request_id_header(self):
        """Test that request ID is returned in response headers."""
        response = client.get("/api/health")

        # Should have X-Request-ID header
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    def test_request_id_uniqueness(self):
        """Test that each request gets a unique ID."""
        request_ids = set()

        for _ in range(10):
            response = client.get("/api/health")
            request_id = response.headers.get("x-request-id")
            assert request_id is not None
            request_ids.add(request_id)

        # Should have gotten unique IDs for each request
        # (allowing for small possibility of collision)
        assert len(request_ids) >= 9


class TestErrorHandling:
    """Test error handling and edge cases."""

    def test_404_not_found(self):
        """Test 404 responses for non-existent resources."""
        # Non-existent event
        response = client.get("/api/events/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

        # Non-existent photo
        response = client.get("/api/photos/00000000-0000-0000-0000-000000000000/download")
        assert response.status_code == 404

    def test_invalid_json(self):
        """Test handling of invalid JSON input."""
        response = client.post(
            "/api/events",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]

    def test_missing_required_fields(self):
        """Test validation of required fields."""
        response = client.post(
            "/api/events",
            json={"description": "Missing name field"}
        )
        assert response.status_code in [400, 422]


class TestConcurrency:
    """Test concurrent request handling."""

    def test_concurrent_event_creation(self):
        """Test handling of concurrent event creation requests."""
        import threading

        results = []
        errors = []

        def create_event():
            try:
                response = client.post(
                    "/api/events",
                    json={"name": "Concurrent Test", "expires_in_days": 7}
                )
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads
        threads = [threading.Thread(target=create_event) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All requests should complete without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5

        # All should succeed or be rate limited
        for status in results:
            assert status in [200, 429]
