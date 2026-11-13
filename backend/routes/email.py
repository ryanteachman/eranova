"""Routes: /api/email/..., a thin wrapper around Asher's email_pipeline."""

from flask import Blueprint

bp = Blueprint("email", __name__, url_prefix="/api/email")
