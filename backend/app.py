"""
app.py — EgerBot Flask application entry point.
Creates the Flask app, registers all blueprints, starts the server.
"""

import logging
from flask import Flask, jsonify
from flask_cors import CORS

from config.settings import FLASK_ENV, PORT, ALLOWED_ORIGINS
from routes.health import health_bp
from routes.chat import chat_bp
from routes.admin import admin_bp

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if FLASK_ENV == "development" else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)

    # ── CORS ──────────────────────────────────────────────────────────────────
    # The key fix: flask-cors must handle preflight OPTIONS requests explicitly.
    # CORS(app, origins="*") alone is NOT enough — Render's proxy strips headers.
    # We must set supports_credentials=False and explicitly expose all routes.
    #
    # For production: set ALLOWED_ORIGINS=https://egerbot.netlify.app in Render
    # env vars. Comma-separate multiple origins if needed.
    #
    # For development (ALLOWED_ORIGINS=*): allow everything.

    if ALLOWED_ORIGINS.strip() == "*":
        CORS(
            app,
            resources={r"/*": {"origins": "*"}},
            allow_headers=["Content-Type",
                           "Authorization", "X-Requested-With"],
            expose_headers=["Content-Type"],
            methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            supports_credentials=False,
            max_age=86400,          # cache preflight for 24h
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

    # ── Belt-and-suspenders: manual CORS headers on every response ────────────
    # Some reverse proxies (including Render's) strip flask-cors headers.
    # This after_request hook guarantees they are always present.
    @app.after_request
    def add_cors_headers(response):
        origin = "*"
        if ALLOWED_ORIGINS.strip() != "*":
            # Echo back the request origin if it's in our allowed list
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
    # Browsers send a preflight OPTIONS request before POST/PATCH.
    # Without this, Render returns 404 for OPTIONS → CORS fails.
    @app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
    @app.route("/<path:path>",            methods=["OPTIONS"])
    def handle_options(path):
        return jsonify({}), 200

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
        host="0.0.0.0",    # MUST be 0.0.0.0 for Render — not 127.0.0.1
        port=PORT,
        debug=(FLASK_ENV == "development"),
    )
