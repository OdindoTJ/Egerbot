"""
tests/test_chat.py
Tests for public chat routes.
Run with: pytest tests/test_chat.py -v
"""

import pytest
from app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── /api/greeting ─────────────────────────────────────────────────────────────

def test_greeting_returns_200(client):
    res = client.get("/api/greeting")
    assert res.status_code == 200


def test_greeting_has_both_languages(client):
    res  = client.get("/api/greeting")
    data = res.get_json()
    assert "greeting_en" in data
    assert "greeting_sw" in data
    assert len(data["greeting_en"]) > 0
    assert len(data["greeting_sw"]) > 0


# ── /api/session/start ────────────────────────────────────────────────────────

def test_start_session_returns_session_id(client):
    res  = client.post("/api/session/start", json={"user_type": "prospective"})
    assert res.status_code == 201
    data = res.get_json()
    assert "session_id" in data
    assert len(data["session_id"]) > 0


def test_start_session_no_body(client):
    """Session start should work even with no body — defaults apply."""
    res = client.post("/api/session/start")
    assert res.status_code == 201


# ── /api/chat ─────────────────────────────────────────────────────────────────

def test_chat_requires_session_id(client):
    res = client.post("/api/chat", json={"message": "What courses are offered?"})
    assert res.status_code == 400
    assert "session_id" in res.get_json()["error"].lower()


def test_chat_requires_message(client):
    # Start a real session first
    session = client.post("/api/session/start", json={}).get_json()
    res = client.post("/api/chat", json={"session_id": session["session_id"], "message": ""})
    assert res.status_code == 400


def test_chat_no_body_returns_400(client):
    res = client.post("/api/chat")
    assert res.status_code == 400


def test_chat_full_flow(client):
    """
    Integration test: start session → send message → check response shape.
    Requires real Supabase + Anthropic credentials in .env.
    """
    # Start session
    session_res = client.post("/api/session/start", json={"user_type": "prospective"})
    assert session_res.status_code == 201
    session_id = session_res.get_json()["session_id"]

    # Send message
    chat_res = client.post("/api/chat", json={
        "session_id": session_id,
        "message":    "What is Egerton University?",
    })
    assert chat_res.status_code == 200
    data = chat_res.get_json()

    assert "response"      in data
    assert "session_id"    in data
    assert "language"      in data
    assert "escalated"     in data
    assert "quick_replies" in data
    assert len(data["response"]) > 0


def test_chat_swahili_detected(client):
    """Swahili input should return language='sw'."""
    session_id = client.post("/api/session/start", json={}).get_json()["session_id"]
    res = client.post("/api/chat", json={
        "session_id": session_id,
        "message":    "Ninahitaji kujua kuhusu masomo ya uhandisi",
    })
    assert res.status_code == 200
    assert res.get_json()["language"] == "sw"


# ── /api/feedback ─────────────────────────────────────────────────────────────

def test_feedback_requires_rating(client):
    res = client.post("/api/feedback", json={"chat_log_id": "some-uuid"})
    assert res.status_code == 400


def test_feedback_rating_out_of_range(client):
    res = client.post("/api/feedback", json={"chat_log_id": "some-uuid", "rating": 10})
    assert res.status_code == 400


# ── /api/session/end ──────────────────────────────────────────────────────────

def test_end_session_requires_session_id(client):
    res = client.post("/api/session/end", json={})
    assert res.status_code == 400
