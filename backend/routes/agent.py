"""Routes: /api/agent/chat and /api/audit."""

from flask import Blueprint

bp = Blueprint("agent", __name__, url_prefix="/api")
