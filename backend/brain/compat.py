"""Deterministic backhaul compatibility rules: equipment, FSMA, hazmat, size, carrier."""

import sqlite3
from datetime import date

from .. import db

FOOD_CATEGORIES = {"FOOD", "BEVERAGE"}
CONTAMINANT_CATEGORIES = {"CHEMICAL", "HAZMAT", "WASTE"}
FLATBED_CATEGORIES = {"STEEL", "WOOD", "MACHINERY", "SCRAP"}

DRY_EQUIPMENT = {"V", "SB", "SV"}
FLATBED_EQUIPMENT = {"F", "SD", "HS"}

# Which truck equipment can serve a requested equipment type (same table as email_pipeline.match).
EQUIPMENT_FITS = {"V": {"V", "R", "VC"}, "R": {"R"}, "F": {"F", "SD"}, "SD": {"SD"}, "VC": {"VC", "V"}}

# (max weight lb, max pallet positions). V is the spec's 53' dry van limit.
SIZE_LIMITS = {
    "V": (45000, 26),
    "R": (45000, 26),
    "SB": (10000, 12),
    "SV": (3000, 4),
}


def washout_on_file(trailer_number):
    """Return True if Asher's washouts table holds a certificate for this trailer."""
    if not trailer_number:
        return False
    try:
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM washouts WHERE trailer_number = ? LIMIT 1", (trailer_number,)
            ).fetchone()
    except sqlite3.OperationalError:
        # The email pipeline has not created the washouts table yet.
        return False
    return row is not None


def _equipment_rule(equipment, candidate):
    category = candidate["category"]
    if equipment == "R":
        return True, f"Reefer ({equipment}) can haul {'temp-controlled' if candidate['temp_controlled'] else 'dry'} freight."
    if equipment in DRY_EQUIPMENT:
        if candidate["temp_controlled"]:
            return False, f"Blocked: {category} freight needs a reefer; this truck is a dry {equipment}."
        return True, f"Dry {equipment} matches dry {category} freight."
    if equipment in FLATBED_EQUIPMENT:
        if category not in FLATBED_CATEGORIES:
            return False, f"Blocked: flatbed ({equipment}) only hauls flatbed freight, not {category}."
        return True, f"Flatbed ({equipment}) fits {category} freight."
    return False, f"Blocked: unknown equipment type {equipment!r}."


def _fsma_rule(trailer_last_category, candidate, trailer_number, last_load_note):
    if candidate["category"] not in FOOD_CATEGORIES:
        return True, None
    if trailer_last_category not in CONTAMINANT_CATEGORIES:
        return True, f"Trailer last hauled {trailer_last_category or 'unknown freight'}; no FSMA restriction."
    if washout_on_file(trailer_number):
        return True, f"Trailer last hauled {trailer_last_category}, but a washout certificate is on file."
    note = f" ({last_load_note})" if last_load_note else ""
    return False, (
        f"Blocked: trailer last hauled {trailer_last_category}{note}; "
        f"FSMA requires a washout before food."
    )


def carrier_has_equipment(carrier, equipment_type):
    """Return True if any of the carrier's equipment types can serve the requested equipment type."""
    fits = EQUIPMENT_FITS.get(equipment_type, {equipment_type})
    return bool(fits & set(carrier.get("equipment_types") or []))


def carrier_rule(carrier, today=None):
    """Meridian's /cover gate: return (ok, reason) for an ACTIVE status and an unexpired CARGO policy."""
    today = today or date.today().isoformat()
    name = carrier.get("vendor_id", "carrier")
    if carrier.get("status") != "ACTIVE":
        return False, f"Blocked: carrier {name} is {carrier.get('status')}, not ACTIVE."
    for policy in carrier.get("insurance") or []:
        expires = policy.get("expiration_date")
        if policy.get("policy_type") == "CARGO" and expires and expires >= today:
            return True, f"Carrier {name} is ACTIVE with an unexpired CARGO policy."
    return False, f"Blocked: carrier {name} has no unexpired CARGO policy."


def check_compat(trailer_last_category, equipment, candidate, carrier,
                 trailer_number=None, last_load_note=None, today=None):
    """Run every rule for one truck and one candidate load and return (ok, reasons).

    candidate needs category, temp_controlled, hazmat, weight_lb and pallet_positions.
    """
    today = today or date.today().isoformat()
    blocked, passed = [], []

    def record(result):
        ok, reason = result
        if reason:
            (passed if ok else blocked).append(reason)

    record(_equipment_rule(equipment, candidate))
    record(_fsma_rule(trailer_last_category, candidate, trailer_number, last_load_note))

    if candidate["hazmat"]:
        if carrier.get("hazmat_certified"):
            record((True, f"Carrier {carrier.get('vendor_id')} is hazmat certified."))
        else:
            record((False, f"Blocked: hazmat freight needs a hazmat-certified carrier; {carrier.get('vendor_id')} is not certified."))

    limit = SIZE_LIMITS.get(equipment)
    if limit:
        max_lb, max_pallets = limit
        weight, pallets = candidate.get("weight_lb") or 0, candidate.get("pallet_positions") or 0
        if weight > max_lb or pallets > max_pallets:
            record((False, f"Blocked: {weight:,.0f} lb / {pallets} pallets exceeds the {equipment} limit of {max_lb:,} lb / {max_pallets} pallets."))
        else:
            record((True, f"{weight:,.0f} lb / {pallets} pallets fits the {equipment}."))

    record(carrier_rule(carrier, today))
    return not blocked, blocked + passed
