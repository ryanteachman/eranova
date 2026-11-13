"""Return Trip backend: Flask app factory."""

from flask import Flask

from . import config
from .routes import actions, agent, email, network

FRONTEND_ORIGIN = "http://localhost:5173"


def create_app():
    """Build the Flask app, register the API blueprints and return it."""
    app = Flask(__name__)
    app.config["DB_PATH"] = config.DB_PATH

    for module in (network, actions, agent, email):
        app.register_blueprint(module.bp)

    @app.get("/api/health")
    def health():
        """Report that the server is up and whether Meridian credentials were found."""
        return {"ok": True, "meridian_configured": bool(config.TMS_API_BASE and config.TMS_API_KEY)}

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = FRONTEND_ORIGIN
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
        return response

    return app
