"""
Tests for the /health endpoint (and the /metrics guard).

The health endpoint is public (no auth) so uptime checks work out of the
box; /metrics is internal-only and must never be world-readable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


def _client() -> TestClient:
    return TestClient(api.app)


def test_health_returns_200():
    with _client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_expected_json_shape():
    with _client() as client:
        response = client.get("/api/v1/health")
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]
    assert "service" in body


def test_health_also_served_at_root_health_path():
    """Uptime checkers commonly probe /health without the version prefix."""
    with _client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_requires_no_auth():
    with _client() as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_metrics_rejects_public_access_without_token():
    with _client() as client:
        # Simulate a non-loopback caller so the private-range guard blocks it.
        response = client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.9"})
    assert response.status_code in (403, 404)


def test_metrics_accepts_bearer_token_when_configured(monkeypatch):
    # METRICS_TOKEN is read per-request, so no module re-import is needed —
    # re-importing `api` here would replace sys.modules['api'] and break the
    # patch-through wrappers used by every other test module.
    monkeypatch.setenv("METRICS_TOKEN", "s3cr3t-metrics-token")
    with _client() as client:
        response = client.get(
            "/metrics",
            headers={"Authorization": "Bearer s3cr3t-metrics-token"},
        )
        assert response.status_code == 200
        assert "http_requests_total" in response.text
        bad = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
        assert bad.status_code == 403
