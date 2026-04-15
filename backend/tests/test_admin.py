"""
tests/test_admin.py
Tests for admin routes.
Run with: pytest tests/test_admin.py -v
"""

import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── /api/admin/login ──────────────────────────────────────────────────────────

def test_login_missing_fields(client):
    res = client.post("/api/admin/login", json={"email": "test@test.com"})
    assert res.status_code == 400


def test_login_wrong_credentials(client):
    res = client.post("/api/admin/login", json={
        "email":    "wrong@egerton.ac.ke",
        "password": "wrongpassword"
    })
    assert res.status_code == 401


def test_login_no_body(client):
    res = client.post("/api/admin/login")
    assert res.status_code == 400


# ── Protected routes without token ───────────────────────────────────────────

def test_analytics_requires_auth(client):
    res = client.get("/api/admin/analytics")
    assert res.status_code == 401


def test_unanswered_requires_auth(client):
    res = client.get("/api/admin/unanswered")
    assert res.status_code == 401


def test_config_requires_auth(client):
    res = client.get("/api/admin/config")
    assert res.status_code == 401


def test_faqs_list_requires_auth(client):
    res = client.get("/api/admin/faqs")
    assert res.status_code == 401


def test_faqs_create_requires_auth(client):
    res = client.post("/api/admin/faqs", json={
        "question_en": "Test?",
        "answer_en":   "Test answer.",
        "category":    "Test",
    })
    assert res.status_code == 401


def test_logs_requires_auth(client):
    res = client.get("/api/admin/logs")
    assert res.status_code == 401


def test_invalid_token_rejected(client):
    res = client.get("/api/admin/analytics", headers={
        "Authorization": "Bearer thisisnotavalidtoken"
    })
    assert res.status_code == 401
