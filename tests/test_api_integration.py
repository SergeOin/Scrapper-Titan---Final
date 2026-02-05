"""Integration tests for critical API endpoints.

Tests all main API endpoints to ensure stability after P1/P2 changes.
Uses synchronous TestClient to avoid pytest-asyncio dependency.
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from server.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_endpoint_ok(client):
    """Test /health returns 200 with expected structure."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "redis_connected" in data


def test_healthz_alias(client):
    """Test /healthz is an alias for /health (Kubernetes probe)."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"


def test_api_stats(client):
    """Test /api/stats returns expected metrics."""
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    # Should have core fields
    assert "total_posts" in data or "posts_count" in data or "scraping_enabled" in data


def test_api_legal_stats(client):
    """Test /api/legal_stats returns legal-specific metrics."""
    resp = client.get("/api/legal_stats")
    assert resp.status_code == 200
    data = resp.json()
    # Should be a valid JSON response (structure may vary)
    assert isinstance(data, dict)


def test_api_posts_pagination(client):
    """Test /api/posts with pagination parameters."""
    resp = client.get("/api/posts", params={"page": 1, "per_page": 10})
    assert resp.status_code == 200
    data = resp.json()
    # Should return items/posts array (API uses 'items' key)
    assert "items" in data or "posts" in data
    items = data.get("items", data.get("posts", []))
    assert isinstance(items, list)


def test_metrics_endpoint(client):
    """Test /metrics returns Prometheus format."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus metrics are plain text
    assert "scrape_" in resp.text or "HELP" in resp.text


def test_dashboard_renders(client):
    """Test main dashboard (/) renders without error."""
    resp = client.get("/")
    # Should be 200 or redirect (302)
    assert resp.status_code in (200, 302, 307)
