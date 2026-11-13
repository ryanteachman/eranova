"""Routes: /api/network and /api/city/<state>/<city>."""

from flask import Blueprint

bp = Blueprint("network", __name__, url_prefix="/api")
