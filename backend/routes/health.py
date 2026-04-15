"""
routes/health.py
Health check endpoints.
GET /health        — quick liveness check (no DB call)
GET /health/full   — deep check including Supabase connection
"""

from flask import Blueprint, jsonify
from config.supabase import test_connection
from config.settings  import LLM_MODEL

health_bp = Blueprint("health", __name__)


@health_bp.route("/health", methods=["GET"])
def liveness():
    """
    Liveness check — used by deployment platforms (Render, Railway)
    to know the server is up. Does NOT call Supabase.
    """
    return jsonify({
        "status":  "ok",
        "bot":     "EgerBot",
        "model":   LLM_MODEL,
    }), 200


@health_bp.route("/health/full", methods=["GET"])
def readiness():
    """
    Full readiness check — verifies the Supabase connection is working.
    Use this when you want to confirm the whole system is operational.
    """
    db_status = test_connection()

    overall = "ok" if db_status["status"] == "connected" else "degraded"

    return jsonify({
        "status":   overall,
        "bot":      "EgerBot",
        "model":    LLM_MODEL,
        "database": db_status,
    }), 200 if overall == "ok" else 503
