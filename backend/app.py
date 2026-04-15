"""
app.py — EgerBot Flask application entry point.
Creates the Flask app, registers all blueprints, starts the server.
"""

import logging
from flask import Flask
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

    # CORS — allow all origins so both chat (8080) and admin (8081) can reach backend.
    # In production set ALLOWED_ORIGINS to your real domain(s) in .env
    CORS(app,
         resources={r"/*": {"origins": "*"}},
         allow_headers=["Content-Type", "Authorization"],
         methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
         supports_credentials=False)

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)

    # ── Error handlers ────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return {"error": "Route not found"}, 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return {"error": "Method not allowed"}, 405

    @app.errorhandler(500)
    def server_error(e):
        logger.error(f"Unhandled exception: {e}")
        return {"error": "Internal server error"}, 500

    logger.info(f"EgerBot backend started — env={FLASK_ENV}")
    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=FLASK_ENV == "development",
    )
