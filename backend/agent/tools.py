"""Registers the brain and Meridian tools with the agent."""

import importlib.util

from .. import meridian
from ..brain import carrier_score, network, pricing
from ..errors import Conflict, NotFound
from .registry import tool


@tool(
    name="network_overview",
    description="Summarize the freight network: totals for empty miles and cost, and the cities "
                "with the most one-way inbound freight. Use this first to find where trucks run empty.",
    schema={"type": "object", "properties": {}, "additionalProperties": False},
)
def network_overview():
    """Return network totals and the top cities ranked by inbound minus outbound loads."""
    summary = network.network_summary()
    cities = sorted(summary["cities"], key=lambda c: c["outbound"] - c["inbound"])
    return {
        "totals": summary["totals"],
        "most_one_way_cities": [
            {"city": c["city"], "state": c["state"], "inbound": c["inbound"], "outbound": c["outbound"]}
            for c in cities[:8]
        ],
    }


@tool(
    name="find_backhauls",
    description="Find ranked backhaul prospects for trucks arriving empty in a city. Each prospect "
                "has a prospect_id, score, compatibility result (ok) and human-readable reasons.",
    schema={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name, e.g. Dallas"},
            "state": {"type": "string", "description": "2-letter state code, e.g. TX"},
        },
        "required": ["city", "state"],
        "additionalProperties": False,
    },
)
def find_backhauls(city, state):
    """Return the city's prospects without their internal pricing lines."""
    prospects = network.find_backhauls(city, state)
    return [{k: v for k, v in p.items() if k != "buy_lines"} for p in prospects]


@tool(
    name="create_return_quote",
    description="Propose a real backhaul quote in Meridian for one compatible prospect. "
                "A human must approve it before anything is written.",
    schema={
        "type": "object",
        "properties": {"prospect_id": {"type": "string"}},
        "required": ["prospect_id"],
        "additionalProperties": False,
    },
    tier="approve",
)
def create_return_quote(prospect_id):
    """Look up a prospect, preview its price in Meridian and return the proposal for the approval queue."""
    prospect = network.find_prospect(prospect_id)
    if prospect is None:
        raise NotFound(f"Prospect {prospect_id} not found. Call find_backhauls again for fresh ids.")
    if not prospect["ok"]:
        raise Conflict(f"Prospect {prospect_id} is blocked: {prospect['reasons'][0]}")
    price = pricing.preview(prospect["buy_lines"], prospect["target_margin_pct"])
    origin, destination = prospect["origin"], prospect["destination"]
    return {
        "title": f"Return quote: {origin['city']}, {origin['state']} -> "
                 f"{destination['city']}, {destination['state']} for {prospect['customer_id']}",
        "summary": f"Backhaul for outbound file {prospect['outbound_file']}. {prospect['miles']} mi "
                   f"{prospect['equipment']}, {prospect['category']}, buy ${price['buy_total']:,.2f} / "
                   f"sell ${price['sell_total']:,.2f} / GP {price['gp_pct']}%.",
        "payload": {
            "prospect_id": prospect_id,
            "customer_id": prospect["customer_id"],
            "equipment_type": prospect["equipment"],
            "category": prospect["category"],
            "origin": origin,
            "destination": destination,
            "miles": prospect["miles"],
            "outbound_file": prospect["outbound_file"],
            "target_margin_pct": prospect["target_margin_pct"],
            "buy_lines": prospect["buy_lines"],
            "pickup_date": prospect.get("pickup_date"),
            "delivery_date_target": prospect.get("delivery_date_target"),
        },
        "confidence": round(prospect["score"] / 100, 2),
        "reasoning": " ".join(prospect["reasons"]),
    }


@tool(
    name="get_shipment",
    description="Get one Meridian shipment by its 7-digit file number.",
    schema={
        "type": "object",
        "properties": {"shipment_id": {"type": "string"}},
        "required": ["shipment_id"],
        "additionalProperties": False,
    },
)
def get_shipment(shipment_id):
    """Return the shipment from Meridian."""
    return meridian.get(f"/shipments/{shipment_id}")


@tool(
    name="search",
    description="Search Meridian by any reference number (file, PO, PRO, BOL, MC) or by name.",
    schema={
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
        "additionalProperties": False,
    },
)
def search(q):
    """Return Meridian's grouped search results."""
    return meridian.get("/search", q=q)


@tool(
    name="price_preview",
    description="Preview customer pricing for buy lines at a target margin (percent of sell) "
                "without creating anything.",
    schema={
        "type": "object",
        "properties": {
            "buy_lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "charge_code": {"type": "string"},
                        "rate_basis": {"type": "string"},
                        "quantity": {"type": "number"},
                        "rate": {"type": "number"},
                        "amount": {"type": "number"},
                        "description": {"type": "string"},
                    },
                    "required": ["charge_code", "amount"],
                },
            },
            "target_margin_pct": {"type": "number"},
        },
        "required": ["buy_lines", "target_margin_pct"],
        "additionalProperties": False,
    },
)
def price_preview(buy_lines, target_margin_pct):
    """Return Meridian's price preview."""
    return pricing.preview(buy_lines, target_margin_pct)


@tool(
    name="add_shipment_note",
    description="Add a note to a Meridian shipment's activity log.",
    schema={
        "type": "object",
        "properties": {"shipment_id": {"type": "string"}, "text": {"type": "string"}},
        "required": ["shipment_id", "text"],
        "additionalProperties": False,
    },
)
def add_shipment_note(shipment_id, text):
    """Append the note in Meridian and return the created event."""
    return meridian.post(f"/shipments/{shipment_id}/notes", {"note": text})


@tool(
    name="rank_carriers",
    description="Rank carriers for a load by how they actually performed on our loads (on-time, "
                "late causes, damage, bounces, cost) plus lane and truck-location fit. Pass "
                "shipment_id for an existing file, or origin, destination and equipment_type. "
                "Returns the top 5 eligible carriers with reasons and every excluded carrier with why.",
    schema={
        "type": "object",
        "properties": {
            "shipment_id": {"type": "string", "description": "7-digit file number"},
            "origin": {"type": "object", "properties": {"city": {"type": "string"},
                                                        "state": {"type": "string"}}},
            "destination": {"type": "object", "properties": {"city": {"type": "string"},
                                                             "state": {"type": "string"}}},
            "equipment_type": {"type": "string", "description": "e.g. V, R, F"},
            "mode": {"type": "string", "enum": ["TL", "LTL", "EXPEDITE"]},
            "hazmat": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
)
def rank_carriers(**request):
    """Return the ranked carriers, trimmed to what the model needs."""
    result = carrier_score.rank_request(**request)
    keep = ("vendor_id", "legal_name", "score", "base_score", "fit", "on_time_actual_pct",
            "loads", "compliance_light", "reasons")
    result["eligible"] = [{k: card[k] for k in keep} for card in result["eligible"]]
    return result


# Asher's email tools register themselves on import once email_pipeline is in the repo.
if importlib.util.find_spec("email_pipeline") and importlib.util.find_spec("email_pipeline.tools"):
    importlib.import_module("email_pipeline.tools")
