"""
app.py — EgerBot Flask application entry point.
Creates the Flask app, registers all blueprints, starts the server.
"""

import logging
import os
from flask import Flask, jsonify, request
from flask_cors import CORS

from config.settings import FLASK_ENV, PORT, ALLOWED_ORIGINS
from routes.health import health_bp
from routes.chat import chat_bp
from routes.admin import admin_bp

# ── Rate limiting ─────────────────────────────────────────────────────────────
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "flask-limiter not installed — rate limiting disabled. "
        "Run: pip install flask-limiter"
    )


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if FLASK_ENV == "development" else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    if LIMITER_AVAILABLE:
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=["200 per day", "50 per hour"],
            headers_enabled=True,
            storage_uri="memory://",
        )
        app.extensions["limiter"] = limiter
        logger.info("Rate limiting enabled (200/day, 50/hour per IP)")
    else:
        app.extensions["limiter"] = None

    # ── Input Sanitization ────────────────────────────────────────────────────
    _BLOCKED_PATTERNS = [
        "ignore previous instructions",
        "ignore all instructions",
        "disregard your instructions",
        "reveal your system prompt",
        "show me your prompt",
        "what are your instructions",
        "act as a different ai",
        "pretend you are not",
        "jailbreak",
        "dan mode",
        "developer mode",
    ]

    @app.before_request
    def sanitize_input():
        """Block oversized bodies and obvious prompt-injection strings."""
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.content_length
            if content_length and content_length > 10_240:
                return jsonify({"error": "Request body too large"}), 413

            data = request.get_json(silent=True)
            if data:
                message = (data.get("message") or "").lower()
                for pattern in _BLOCKED_PATTERNS:
                    if pattern in message:
                        logger.warning(
                            f"Blocked prompt injection attempt: {message[:80]}"
                        )
                        return jsonify({
                            "error": "Message contains disallowed content"
                        }), 400

    # ── CORS ──────────────────────────────────────────────────────────────────
    if ALLOWED_ORIGINS.strip() == "*":
        CORS(
            app,
            resources={r"/*": {"origins": "*"}},
            allow_headers=["Content-Type",
                           "Authorization", "X-Requested-With"],
            expose_headers=["Content-Type"],
            methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            supports_credentials=False,
            max_age=86400,
        )
    else:
        origins_list = [o.strip()
                        for o in ALLOWED_ORIGINS.split(",") if o.strip()]
        CORS(
            app,
            origins=origins_list,
            allow_headers=["Content-Type",
                           "Authorization", "X-Requested-With"],
            expose_headers=["Content-Type"],
            methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            supports_credentials=False,
            max_age=86400,
        )
        logger.info(f"CORS restricted to: {origins_list}")

    # ── Manual CORS headers on every response ─────────────────────────────────
    @app.after_request
    def add_cors_headers(response):
        origin = "*"
        if ALLOWED_ORIGINS.strip() != "*":
            from flask import request as req
            req_origin = req.headers.get("Origin", "")
            allowed = [o.strip() for o in ALLOWED_ORIGINS.split(",")]
            if req_origin in allowed:
                origin = req_origin

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-Requested-With"
        )
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PATCH, PUT, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Max-Age"] = "86400"
        return response

    # ── Explicit OPTIONS handler for all routes ───────────────────────────────
    @app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
    @app.route("/<path:path>", methods=["OPTIONS"])
    def handle_options(path):
        return jsonify({}), 200

    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "status": "online",
            "message": "EgerBot Backend is running",
            "version": "1.0.0"
        }), 200

    # ── UptimeRobot Heartbeat Monitor ─────────────────────────────────────────
    # This endpoint is called by UptimeRobot's standard HTTP monitor.
    # When the server is alive, it forwards a ping to the Heartbeat monitor URL,
    # confirming the server is not just responding but fully operational.
    UPTIME_HEARTBEAT_URL = os.environ.get("UPTIME_HEARTBEAT_URL", "")

    @app.route("/api/heartbeat", methods=["GET", "POST"])
    def uptime_heartbeat():
        """
        Receives a ping from UptimeRobot's standard monitor and forwards
        a success signal to the Heartbeat monitor URL.

        This ensures that if the server is completely down (not just slow),
        the Heartbeat monitor will not receive its expected ping and will
        trigger an alert.

        Environment Variable Required:
            UPTIME_HEARTBEAT_URL — The unique Heartbeat URL from UptimeRobot
        """
        if not UPTIME_HEARTBEAT_URL:
            logger.warning("Heartbeat URL not configured — skipping ping")
            return jsonify({
                "status": "ok",
                "heartbeat": "not_configured"
            }), 200

        try:
            import requests
            response = requests.get(UPTIME_HEARTBEAT_URL, timeout=10)
            logger.debug(f"Heartbeat sent — status: {response.status_code}")
            return jsonify({
                "status": "ok",
                "heartbeat": "sent"
            }), 200
        except requests.exceptions.Timeout:
            logger.error("Heartbeat ping timed out")
            return jsonify({
                "status": "error",
                "heartbeat": "timeout"
            }), 500
        except requests.exceptions.RequestException as e:
            logger.error(f"Heartbeat ping failed: {e}")
            return jsonify({
                "status": "error",
                "heartbeat": "failed"
            }), 500

    # ── Register blueprints ───────────────────────────────────────────────────
    app.register_blueprint(health_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)

    # ── Error handlers ────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Route not found"}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal server error: {e}")
        return jsonify({"error": "Internal server error"}), 500

    logger.info(
        f"EgerBot app created — env={FLASK_ENV}, "
        f"port={PORT}, CORS origins={ALLOWED_ORIGINS!r}"
    )
    return app


# ── Entry point ───────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=(FLASK_ENV == "development"),
    )
