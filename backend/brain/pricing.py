"""Backhaul pricing: buy lines and price previews."""

from .. import meridian

BACKHAUL_RATE_PER_MILE = 1.20
OUTBOUND_SHARE = 0.60
DEFAULT_MARGIN_PCT = 18

_fsc_cache = {}


def tl_fsc_per_mile():
    """Return the current TL fuel surcharge per mile from GET /fsc, cached for the process."""
    if "tl_per_mile" not in _fsc_cache:
        _fsc_cache["tl_per_mile"] = float(meridian.get("/fsc")["tl_per_mile"])
    return _fsc_cache["tl_per_mile"]


def _cents(value):
    return round(value + 1e-9, 2)


def backhaul_buy_lines(miles, avg_outbound_buy_frt=None):
    """Return rate-engine-shaped buy lines (FRT + FSC) for a backhaul of this many miles."""
    frt = miles * BACKHAUL_RATE_PER_MILE
    if avg_outbound_buy_frt:
        frt = max(frt, avg_outbound_buy_frt * OUTBOUND_SHARE)
    frt = _cents(frt)
    fsc_rate = tl_fsc_per_mile()
    return [
        {"charge_code": "FRT", "rate_basis": "FLAT", "quantity": 1, "rate": frt,
         "amount": frt, "description": "Backhaul linehaul"},
        {"charge_code": "FSC", "rate_basis": "PER_MILE", "quantity": miles, "rate": fsc_rate,
         "amount": _cents(miles * fsc_rate), "description": f"Fuel surcharge @ {fsc_rate}/mi"},
    ]


def margin_for(customer):
    """Return the customer's margin floor percent, or the default when it has none."""
    return (customer or {}).get("margin_floor_pct") or DEFAULT_MARGIN_PCT


def estimate(buy_lines, margin_pct):
    """Estimate buy, sell and GP locally, matching how /quotes/price-preview prices FRT and FSC."""
    buy = sum(line["amount"] for line in buy_lines)
    sell = 0.0
    for line in buy_lines:
        if line["charge_code"] == "FSC":
            sell += line["amount"]
        else:
            sell += _cents(line["amount"] / (1 - margin_pct / 100))
    sell = _cents(sell)
    gp = _cents(sell - buy)
    return {
        "buy_total": _cents(buy),
        "sell_total": sell,
        "gp_amount": gp,
        "gp_pct": round(gp / sell * 100, 1) if sell else None,
    }


def preview(buy_lines, margin_pct):
    """Price buy lines with Meridian's POST /quotes/price-preview and return its result."""
    return meridian.post(
        "/quotes/price-preview", {"buy_lines": buy_lines, "target_margin_pct": margin_pct}
    )
