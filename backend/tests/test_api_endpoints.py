"""Tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_health_check():
    """Test health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data


def test_create_event():
    """Test event creation endpoint."""
    response = client.post(
        "/api/events",
        json={
            "name": "Test Event",
            "description": "Test Description",
            "expires_in_days": 7
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["name"] == "Test Event"
    assert "access_code" in data


def test_get_event():
    """Test getting event details."""
    # First create an event
    create_response = client.post(
        "/api/events",
        json={"name": "Test Event", "expires_in_days": 7}
    )
    event_id = create_response.json()["id"]

    # Then get it
    response = client.get(f"/api/events/{event_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == event_id


def test_metrics_endpoint():
    """Test Prometheus metrics endpoint."""
    response = client.get("/metrics")
    assert response.status_code == 200
    # Prometheus text format
    assert "grapic_http_requests_total" in response.text


@pytest.mark.parametrize("endpoint,method", [
    ("/api/events", "GET"),
    ("/api/events", "POST"),
    ("/api/health", "GET"),
])
def test_cors_headers(endpoint, method):
    """Test CORS headers are properly set."""
    if method == "GET":
        response = client.get(endpoint)
    else:
        response = client.post(endpoint, json={})

    # Check CORS headers exist
    assert "access-control-allow-origin" in response.headers
