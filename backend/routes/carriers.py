"""Routes: /api/carriers, /api/carriers/<vendor_id> and /api/carriers/rank."""

from flask import Blueprint, request

from ..brain import carrier_score
from ..errors import BadRequest, NotFound

bp = Blueprint("carriers", __name__, url_prefix="/api")

RANK_FIELDS = ("shipment_id", "origin", "destination", "equipment_type", "hazmat", "mode")


@bp.get("/carriers")
def list_carriers():
    """Return every carrier's scorecard, best base score first."""
    return {"items": carrier_score.all_scorecards()}


@bp.get("/carriers/<vendor_id>")
def get_carrier(vendor_id):
    """Return one carrier's scorecard with its per-load breakdown."""
    card = carrier_score.carrier_detail(vendor_id.upper())
    if card is None:
        raise NotFound(f"Carrier {vendor_id} not found.")
    return card


@bp.post("/carriers/rank")
def rank():
    """Rank carriers for {shipment_id} or {origin, destination, equipment_type, hazmat, mode}."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    return carrier_score.rank_request(**{k: body[k] for k in RANK_FIELDS if k in body})
