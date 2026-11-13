"""Routes: /api/network and /api/city/<state>/<city>."""

from flask import Blueprint

from ..brain import network

bp = Blueprint("network", __name__, url_prefix="/api")

INTERNAL_FIELDS = ("buy_lines",)


@bp.get("/network")
def get_network():
    """Return network totals, cities and lane arcs."""
    return network.network_summary()


@bp.get("/city/<state>/<city>")
def get_city(state, city):
    """Return one city's flow counts and ranked backhaul prospects."""
    detail = network.city_detail(city, state)
    detail["prospects"] = [
        {k: v for k, v in p.items() if k not in INTERNAL_FIELDS} for p in detail["prospects"]
    ]
    return detail
