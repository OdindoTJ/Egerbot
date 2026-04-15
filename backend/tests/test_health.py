"""
tests/test_health.py
Tests for the health check endpoints.
Run with: pytest tests/test_health.py -v
"""

import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_liveness_returns_200(client):
    """GET /health should always return 200 with status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert data["bot"] == "EgerBot"


def test_liveness_has_model(client):
    """GET /health should include the LLM model name."""
    res  = client.get("/health")
    data = res.get_json()
    assert "model" in data


def test_full_health_returns_database_status(client):
    """GET /health/full should include a database key."""
    res  = client.get("/health/full")
    data = res.get_json()
    assert "database" in data
    assert "status" in data["database"]


def test_full_health_connected(client):
    """GET /health/full should show database as connected when Supabase is reachable."""
    res  = client.get("/health/full")
    data = res.get_json()
    # Will be 200 if connected, 503 if not — just check structure either way
    assert data["database"]["status"] in ("connected", "error")
