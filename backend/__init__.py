"""Return Trip backend: Flask app factory."""

import openai
from flask import Flask

from . import config, db
from .errors import ApiError
from .meridian import MeridianError
from .routes import actions as actions_routes
from .routes import agent as agent_routes
from .routes import email as email_routes
from .routes import network as network_routes

FRONTEND_ORIGIN = "http://localhost:5173"


def _error(status, code, detail):
    return {"error": code, "detail": detail}, status


def create_app():
    """Build the Flask app, create the database tables, register the API blueprints and return it."""
    app = Flask(__name__)
    app.config["DB_PATH"] = config.DB_PATH
    db.init_db()

    for module in (network_routes, actions_routes, agent_routes, email_routes):
        app.register_blueprint(module.bp)

    @app.get("/api/health")
    def health():
        """Report that the server is up and whether Meridian and OpenAI credentials were found."""
        return {
            "ok": True,
            "meridian_configured": bool(config.TMS_API_BASE and config.TMS_API_KEY),
            "openai_configured": bool(config.OPENAI_API_KEY),
        }

    @app.errorhandler(ApiError)
    def api_error(exc):
        return _error(exc.status, exc.code, str(exc))

    @app.errorhandler(MeridianError)
    def meridian_error(exc):
        # Meridian's detail sentence says what to do next, so pass it through unchanged.
        return _error(exc.status if exc.status < 500 else 502, exc.error, exc.detail)

    @app.errorhandler(openai.OpenAIError)
    def openai_error(exc):
        return _error(502, "openai_error", f"The language model call failed: {type(exc).__name__}.")

    @app.errorhandler(404)
    def route_not_found(exc):
        return _error(404, "not_found", "Unknown route.")

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return _error(405, "method_not_allowed", "Known route, wrong HTTP method.")

    @app.errorhandler(500)
    def internal_error(exc):
        return _error(500, "internal_error", "Unexpected server error.")

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = FRONTEND_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
        return response

    return app
