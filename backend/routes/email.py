"""Routes: /api/email/..., a thin wrapper around Asher's email_pipeline."""

import importlib
import importlib.util

from flask import Blueprint

bp = Blueprint("email", __name__, url_prefix="/api/email")

# Asher's email_pipeline.routes.bp (a Blueprint with no url_prefix) is mounted under /api/email.
if importlib.util.find_spec("email_pipeline") and importlib.util.find_spec("email_pipeline.routes"):
    bp.register_blueprint(importlib.import_module("email_pipeline.routes").bp)
