"""Carrier scorecards from how carriers actually performed on our loads, with plain-English reasons."""

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .. import db, meridian
from ..errors import BadRequest
from . import classify, compat

WEIGHTS = {
    "K": 5,                  # shrinkage strength: pseudo-loads at the fleet rate
    "reliability": 0.4,
    "quality": 0.2,
    "cost": 0.2,
    "fit": 0.2,
    "late_delivery": 0.7,    # share of reliability
    "late_pickup": 0.3,
    "late_unknown": 0.5,     # a late delivery with no usable reason counts as half
    "missed_appt": 0.5,      # share of quality
    "fit_lane": 0.4,         # carrier lists this origin -> destination state lane
    "fit_here": 0.6,         # truck's last delivery is in the pickup city
    "fit_state": 0.3,        # ... or in the pickup state
    "cost_no_data": 0.5,     # same as paying the fleet average
    "cost_band": 0.10,       # pay/target_min this far below the fleet average scores a full 1.0
}

CARRIER_FAULT = {"AI", "T3", "D1", "MECHANICAL"}
EXCUSED = {"AO", "WEATHER", "B1"}
LATE_CODE_TEXT = {
    "AI": "mechanical breakdown", "MECHANICAL": "mechanical", "T3": "tractor or trailer not available",
    "D1": "carrier dispatch error", "AO": "weather", "WEATHER": "weather", "B1": "consignee closed",
    "NS": "no reason given", "LATE": "no reason given",
}
FINISHED = {"DELIVERED", "POD_RECEIVED", "CLOSED"}
CARRIER_TYPES = {"TRUCKLOAD_CARRIER", "LTL_CARRIER", "CARTAGE_AGENT", "EXPEDITE_CARRIER"}
# Which vendor types haul each mode (matches every carrier assignment in the sandbox).
MODE_VENDOR_TYPES = {
    "TL": {"TRUCKLOAD_CARRIER"},
    "LTL": {"LTL_CARRIER"},
    "EXPEDITE": {"EXPEDITE_CARRIER", "TRUCKLOAD_CARRIER", "CARTAGE_AGENT"},
}
PICKUP_TIMED_MODES = {"TL", "EXPEDITE"}
DAMAGE_CONDITIONS = {"SHORTAGE", "DAMAGE", "REFUSED"}
EXTRA_CHARGES = {"DET", "LAY"}
# A TONU cancelled for these reasons is the customer's doing, not the carrier's.
TONU_NOT_CARRIER = {"CUSTOMER_CANCELLED", "DUPLICATE"}
NOT_MOVING = {"BOOKED", "CANCELLED", "TONU"}
PROFILE_GAP_POINTS = 10
RANK_LIMIT = 5


# ---------- per-load rules ----------

def _parse_utc(value, zone=None):
    """Parse an ISO time to aware UTC; a naive value is read in the given IANA zone."""
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        if not zone:
            return None
        moment = moment.replace(tzinfo=ZoneInfo(zone))
    return moment.astimezone(timezone.utc)


def late_delivery(s):
    """Return (cause, code) for a late delivery with a POD, cause in carrier/excused/unknown, else None."""
    pod = s.get("pod") or {}
    if not pod.get("received") or (pod.get("on_time") is not False and not s.get("service_failure")):
        return None
    code = (pod.get("late_reason_code") or s.get("service_failure_reason") or "LATE").upper()
    if code in CARRIER_FAULT:
        return "carrier", code
    if code in EXCUSED:
        return "excused", code
    return "unknown", code


def late_pickup(s):
    """Return True/False for whether the truck reached the shipper after stop 1's window, or None if unknown."""
    if s.get("mode") not in PICKUP_TIMED_MODES or not s.get("stops"):
        return None
    milestones = {m["milestone_code"]: m for m in s.get("milestones") or [] if m.get("complete")}
    arrived, loaded = milestones.get("AT_SHIPPER"), milestones.get("LOADED")
    if not arrived:
        return None
    # A status jump completes skipped milestones with one shared time, so the arrival is unknown.
    if loaded and loaded.get("event_at") == arrived.get("event_at"):
        return None
    window = s["stops"][0].get("scheduled_window") or {}
    arrived_at = _parse_utc(arrived.get("event_at"), arrived.get("event_timezone"))
    latest = _parse_utc(window.get("latest_local"), window.get("timezone"))
    if arrived_at is None or latest is None:
        return None
    return arrived_at > latest


def damaged(s):
    """Return True when the POD records a shortage, damage or refusal."""
    pod = s.get("pod") or {}
    return bool(pod.get("received")) and pod.get("condition") in DAMAGE_CONDITIONS


def missed_appointment(s):
    """Return True when any stop's appointment was missed."""
    return any((stop.get("appointment") or {}).get("status") == "MISSED" for stop in s.get("stops") or [])


def extra_charges(s, carrier_id):
    """Count the carrier's non-cancelled detention and layover cost lines on a load."""
    return sum(1 for c in s.get("vendor_costs") or []
               if c.get("charge_code") in EXTRA_CHARGES and c.get("status") != "CANCELLED"
               and c.get("vendor_id") == carrier_id)


def cost_ratio(s, carrier_id):
    """Return the carrier's FRT pay divided by target_pay_min (1.0 = paid exactly the minimum), or None."""
    low = s.get("target_pay_min")
    paid = sum(c.get("amount") or 0 for c in s.get("vendor_costs") or []
               if c.get("charge_code") == "FRT" and c.get("status") != "CANCELLED"
               and c.get("vendor_id") == carrier_id)
    if not low or not paid:
        return None
    return paid / low


def carrier_tonu(s):
    """Return True when a TONU load counts against its carrier (not a customer cancellation)."""
    return s.get("status") == "TONU" and s.get("cancel_reason") not in TONU_NOT_CARRIER


def bounces(events, vendor_ids):
    """Return [(vendor_id, reason_code, shipment_id)] for every uncover event naming a known carrier."""
    found = []
    for e in events:
        note = e.get("note") or ""
        if e.get("event_type") != "SYSTEM" or not note.startswith("Uncovered"):
            continue
        match = re.search(r"was carrier ([A-Z0-9_-]+)", note)
        vendor_id = match.group(1) if match and match.group(1) in vendor_ids else next(
            (v for v in vendor_ids if re.search(rf"\b{re.escape(v)}\b", note)), None)
        if vendor_id:
            found.append((vendor_id, e.get("reason_code") or "OTHER", e.get("shipment_id")))
    return found


# ---------- per-carrier stats ----------

def _empty_stats():
    return {"loads": 0, "pod_loads": 0, "late": Counter(), "late_codes": defaultdict(Counter),
            "pickups_checked": 0, "late_pickups": 0, "damage": 0, "missed_appts": 0, "extras": 0,
            "tonu": 0, "tonu_excused": 0, "bounces": [], "cost_ratios": [], "last_load": None,
            "per_load": []}


def _position_key(s):
    return (s.get("delivery_date_target") or s.get("pickup_date") or "", s["shipment_id"])


def carrier_stats(shipments=None, events=None, vendors=None):
    """Build {carrier_id: stats} from cached shipments and events, for every carrier vendor."""
    shipments = db.load_records("shipments") if shipments is None else shipments
    events = db.load_events() if events is None else events
    vendors = db.load_records("vendors") if vendors is None else vendors
    carrier_ids = {v["vendor_id"] for v in vendors if v.get("vendor_type") in CARRIER_TYPES}
    stats = {vendor_id: _empty_stats() for vendor_id in carrier_ids}

    for s in shipments:
        carrier_id = s.get("carrier_id")
        if carrier_id not in stats:
            continue
        st = stats[carrier_id]
        if s.get("status") == "TONU":
            if carrier_tonu(s):
                st["tonu"] += 1
            else:
                st["tonu_excused"] += 1
        if s.get("status") not in NOT_MOVING and (
                st["last_load"] is None or _position_key(s) > _position_key(st["last_load"])):
            st["last_load"] = s
        if s.get("status") not in FINISHED:
            continue

        st["loads"] += 1
        late = late_delivery(s)
        pickup_late = late_pickup(s)
        ratio = cost_ratio(s, carrier_id)
        if (s.get("pod") or {}).get("received"):
            st["pod_loads"] += 1
        if late:
            st["late"][late[0]] += 1
            st["late_codes"][late[0]][late[1]] += 1
        if pickup_late is not None:
            st["pickups_checked"] += 1
            st["late_pickups"] += pickup_late
        st["damage"] += damaged(s)
        st["missed_appts"] += missed_appointment(s)
        st["extras"] += extra_charges(s, carrier_id)
        if ratio is not None:
            st["cost_ratios"].append(ratio)
        st["per_load"].append({
            "shipment_id": s["shipment_id"], "status": s.get("status"),
            "lane": f"{s.get('shipper_city')}, {s.get('shipper_state')} -> "
                    f"{s.get('consignee_city')}, {s.get('consignee_state')}",
            "pickup_date": s.get("pickup_date"),
            "late_delivery": {"cause": late[0], "code": late[1]} if late else None,
            "late_pickup": pickup_late,
            "condition": (s.get("pod") or {}).get("condition"),
            "cost_ratio": None if ratio is None else round(ratio, 2),
            "extra_charges": extra_charges(s, carrier_id),
        })

    for vendor_id, reason, shipment_id in bounces(events, carrier_ids):
        stats[vendor_id]["bounces"].append({"shipment_id": shipment_id, "reason": reason})
    return stats


# ---------- scoring ----------

def shrunk(events, n, fleet_rate):
    """Shrink a carrier's rate toward the fleet rate: (events + K x fleet) / (n + K)."""
    return (events + WEIGHTS["K"] * fleet_rate) / (n + WEIGHTS["K"])


def _late_weighted(st):
    return st["late"]["carrier"] + WEIGHTS["late_unknown"] * st["late"]["unknown"]


def _rates(st):
    """Return {rate name: (events, n)} for one carrier's stats."""
    attempts = st["loads"] + len(st["bounces"]) + st["tonu"]
    return {
        "late_delivery": (_late_weighted(st), st["pod_loads"]),
        "late_pickup": (st["late_pickups"], st["pickups_checked"]),
        "damage": (st["damage"], st["pod_loads"]),
        "bounce": (len(st["bounces"]), attempts),
        "tonu": (st["tonu"], attempts),
        "missed_appt": (st["missed_appts"], st["loads"]),
    }


def shrunk_pay_ratio(st, fleet):
    """The carrier's average pay / target_pay_min, shrunk toward the fleet average; None without data."""
    ratios = st["cost_ratios"]
    if not ratios:
        return None
    return shrunk(sum(ratios), len(ratios), fleet["pay_ratio"])


def fleet_rates(stats):
    """Return each rate pooled across every carrier (0 when there is no data), plus the pay-ratio spread."""
    totals = defaultdict(lambda: [0.0, 0])
    for st in stats.values():
        for name, (events, n) in _rates(st).items():
            totals[name][0] += events
            totals[name][1] += n
        totals["pay_ratio"][0] += sum(st["cost_ratios"])
        totals["pay_ratio"][1] += len(st["cost_ratios"])
    fleet = {name: (events / n if n else 0.0) for name, (events, n) in totals.items()}
    if not totals["pay_ratio"][1]:
        fleet["pay_ratio"] = None
    return fleet


def components(st, fleet):
    """Return the reliability, quality and cost components (each 0-1) for one carrier."""
    rate = {name: shrunk(events, n, fleet[name]) for name, (events, n) in _rates(st).items()}
    reliability = 1 - (WEIGHTS["late_delivery"] * rate["late_delivery"]
                       + WEIGHTS["late_pickup"] * rate["late_pickup"])
    quality = 1 - min(1.0, rate["damage"] + rate["bounce"] + rate["tonu"]
                      + WEIGHTS["missed_appt"] * rate["missed_appt"])
    # Every sandbox load pays under target_pay_min, so cost is scored against the fleet average:
    # average pay = 0.5, and cost_band cheaper (or dearer) than average = 1 (or 0).
    pay = shrunk_pay_ratio(st, fleet)
    if pay is None:
        cost = WEIGHTS["cost_no_data"]
    else:
        cost = min(1.0, max(0.0, 0.5 + (fleet["pay_ratio"] - pay) / (2 * WEIGHTS["cost_band"])))
    return {"reliability": reliability, "quality": quality, "cost": cost}


def base_score(parts):
    """Score 0-100 from reliability, quality and cost only (fit excluded, rescaled to 100)."""
    total = WEIGHTS["reliability"] + WEIGHTS["quality"] + WEIGHTS["cost"]
    return round(100 * (WEIGHTS["reliability"] * parts["reliability"] + WEIGHTS["quality"] * parts["quality"]
                        + WEIGHTS["cost"] * parts["cost"]) / total)


def load_score(parts, fit_value):
    """Score 0-100 for one load: the weighted sum of all four components."""
    return round(100 * (WEIGHTS["reliability"] * parts["reliability"] + WEIGHTS["quality"] * parts["quality"]
                        + WEIGHTS["cost"] * parts["cost"] + WEIGHTS["fit"] * fit_value))


def on_time_actual_pct(st):
    """Percent of POD loads delivered on time; excused lates count as on time, unknown as half late."""
    if not st["pod_loads"]:
        return None
    return round(100 * (1 - _late_weighted(st) / st["pod_loads"]))


def _plural(n, word):
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else f"{n} {word}s"


def _causes(codes):
    return ", ".join(sorted({LATE_CODE_TEXT.get(code, code.lower()) for code in codes}))


def reasons_for(vendor, st):
    """Return 3-5 short plain-English reasons for a carrier's base score."""
    reasons = []
    actual = on_time_actual_pct(st)
    if actual is None:
        reasons.append("No delivered loads with a POD yet; scored at the fleet average")
    else:
        reasons.append(f"{actual}% on time across {_plural(st['pod_loads'], 'load')}")

    late = st["late"]
    if late["carrier"]:
        reasons.append(f"{_plural(late['carrier'], 'late delivery')}, "
                       f"{_causes(st['late_codes']['carrier'])} (carrier fault)")
    if late["excused"]:
        reasons.append(f"{_plural(late['excused'], 'late delivery')} excused: "
                       f"{_causes(st['late_codes']['excused'])}")
    if late["unknown"]:
        reasons.append(f"{_plural(late['unknown'], 'late delivery')} with no usable reason (counted as half)")
    if st["bounces"]:
        why = ", ".join(sorted({b["reason"] for b in st["bounces"]}))
        reasons.append(f"Bounced {_plural(len(st['bounces']), 'load')} ({why})")
    if st["damage"]:
        reasons.append(f"{_plural(st['damage'], 'damage or shortage claim')} at delivery")
    if st["late_pickups"]:
        reasons.append(f"Late to pickup on {st['late_pickups']} of {st['pickups_checked']} timed pickups")
    if st["tonu"]:
        reasons.append(f"{_plural(st['tonu'], 'truck-ordered-not-used load')}")
    if not (late["carrier"] or st["bounces"] or st["damage"]) and st["loads"]:
        reasons.append("No carrier-fault lates, bounces or damage")

    stored = vendor.get("on_time_delivery_pct")
    if actual is not None and stored is not None and abs(stored - actual) >= PROFILE_GAP_POINTS:
        reasons.append(f"Profile says {stored}% on time; actual loads say {actual}%")
    if st["cost_ratios"]:
        avg = sum(st["cost_ratios"]) / len(st["cost_ratios"])
        side = "under" if avg <= 1 else "over"
        reasons.append(f"Paid {abs(1 - avg):.0%} {side} target minimum on average "
                       f"({_plural(len(st['cost_ratios']), 'load')})")
    else:
        reasons.append("No target pay on file; cost scored neutral")
    if st["extras"]:
        reasons.append(f"{_plural(st['extras'], 'detention/layover charge')}")
    return reasons[:5]


def _city(load):
    if not load:
        return None
    return {"city": load.get("consignee_city"), "state": load.get("consignee_state"),
            "shipment_id": load["shipment_id"], "date": load.get("delivery_date_target")}


def scorecard(vendor, st, parts):
    """Build the public Scorecard dict for one carrier from its stats and components."""
    return {
        "vendor_id": vendor["vendor_id"],
        "legal_name": vendor.get("legal_name"),
        "compliance_light": vendor.get("compliance_light"),
        "loads": st["loads"],
        "on_time_actual_pct": on_time_actual_pct(st),
        "on_time_stored_pct": vendor.get("on_time_delivery_pct"),
        "late_by_cause": {cause: st["late"][cause] for cause in ("carrier", "excused", "unknown")},
        "damage": st["damage"],
        "bounces": len(st["bounces"]),
        "tonu": st["tonu"],
        "cost_score": round(parts["cost"], 2),
        "reliability": round(parts["reliability"], 3),
        "quality": round(parts["quality"], 3),
        "base_score": base_score(parts),
        "last_city": _city(st["last_load"]),
        "reasons": reasons_for(vendor, st),
    }


def _carrier_vendors():
    return {v["vendor_id"]: v for v in db.load_records("vendors") if v.get("vendor_type") in CARRIER_TYPES}


def all_scorecards():
    """Return a Scorecard for every carrier, best base score first."""
    vendors = _carrier_vendors()
    stats = carrier_stats(vendors=list(vendors.values()))
    fleet = fleet_rates(stats)
    cards = [scorecard(vendors[vendor_id], st, components(st, fleet)) for vendor_id, st in stats.items()]
    return sorted(cards, key=lambda c: (-c["base_score"], -c["loads"], c["vendor_id"]))


def carrier_detail(vendor_id):
    """Return one carrier's Scorecard plus its per-load breakdown and bounces, or None if unknown."""
    vendors = _carrier_vendors()
    if vendor_id not in vendors:
        return None
    stats = carrier_stats(vendors=list(vendors.values()))
    card = scorecard(vendors[vendor_id], stats[vendor_id], components(stats[vendor_id], fleet_rates(stats)))
    card["per_load"] = sorted(stats[vendor_id]["per_load"], key=lambda r: r["pickup_date"] or "", reverse=True)
    card["bounced_loads"] = stats[vendor_id]["bounces"]
    return card


# ---------- ranking for one load ----------

def fit(vendor, st, origin, destination):
    """Return (fit 0-1, reasons) for a carrier on a lane: lane match plus where its truck is."""
    value, reasons = 0.0, []
    if any(lane.get("origin") == origin["state"] and lane.get("destination") == destination["state"]
           for lane in vendor.get("lanes") or []):
        value += WEIGHTS["fit_lane"]
        reasons.append(f"Runs this lane ({origin['state']} -> {destination['state']})")
    last = _city(st["last_load"])
    if last and last["state"] == origin["state"]:
        here = (last["city"] or "").lower() == (origin.get("city") or "").lower()
        value += WEIGHTS["fit_here"] if here else WEIGHTS["fit_state"]
        reasons.append(f"Truck last delivered in {last['city']}, {last['state']}"
                       + (" — already at pickup" if here else " — same state as pickup"))
    return min(value, 1.0), reasons


def gate(vendor, equipment_type, hazmat, mode=None, today=None):
    """Return None if the carrier may haul the load, else the reason it is excluded."""
    ok, reason = compat.carrier_rule(vendor, today)
    if not ok:
        return reason.removeprefix("Blocked: ")
    if mode in MODE_VENDOR_TYPES and vendor.get("vendor_type") not in MODE_VENDOR_TYPES[mode]:
        return f"Does not haul {mode} ({vendor.get('vendor_type')})"
    if equipment_type and not compat.carrier_has_equipment(vendor, equipment_type):
        return f"No equipment for {equipment_type} (has {', '.join(vendor.get('equipment_types') or []) or 'none'})"
    if hazmat and not vendor.get("hazmat_certified"):
        return "Not hazmat certified"
    return None


def load_from_shipment(shipment):
    """Turn a shipment into a rank request: origin, destination, equipment and hazmat."""
    label = classify.get_classifications().get(shipment["shipment_id"]) or {}
    hazmat = bool(label.get("hazmat")) or any(l.get("hazmat") for l in shipment.get("freight_lines") or [])
    return {
        "origin": {"city": shipment.get("shipper_city"), "state": shipment.get("shipper_state")},
        "destination": {"city": shipment.get("consignee_city"), "state": shipment.get("consignee_state")},
        "equipment_type": shipment.get("equipment_type"),
        "mode": shipment.get("mode"),
        "hazmat": hazmat,
    }


def rank_carriers(origin, destination, equipment_type=None, hazmat=False, mode=None, shipment_id=None,
                  today=None):
    """Rank carriers for one load: {eligible: top scorecards with fit and score, excluded: [...]}."""
    vendors = _carrier_vendors()
    stats = carrier_stats(vendors=list(vendors.values()))
    fleet = fleet_rates(stats)
    bounced_here = {}
    for vendor_id, st in stats.items():
        for bounce in st["bounces"]:
            if shipment_id and bounce["shipment_id"] == shipment_id:
                bounced_here[vendor_id] = bounce["reason"]

    eligible, excluded = [], []
    for vendor_id, vendor in sorted(vendors.items()):
        reason = gate(vendor, equipment_type, hazmat, mode, today)
        if reason is None and vendor_id in bounced_here:
            reason = f"Already bounced this load ({bounced_here[vendor_id]})"
        if reason:
            excluded.append({"vendor_id": vendor_id, "legal_name": vendor.get("legal_name"), "reason": reason})
            continue
        parts = components(stats[vendor_id], fleet)
        card = scorecard(vendor, stats[vendor_id], parts)
        fit_value, fit_reasons = fit(vendor, stats[vendor_id], origin, destination)
        card.update(fit=round(fit_value, 2), score=load_score(parts, fit_value),
                    reasons=(fit_reasons + card["reasons"])[:5])
        eligible.append(card)
    eligible.sort(key=lambda c: (-c["score"], -c["base_score"], c["vendor_id"]))
    return {"eligible": eligible[:RANK_LIMIT], "excluded": excluded}


def _place(value, name):
    if not isinstance(value, dict) or not value.get("city") or not value.get("state"):
        raise BadRequest(f"{name} must be an object with city and state.")
    return {"city": value["city"], "state": value["state"].upper()}


def rank_request(shipment_id=None, origin=None, destination=None, equipment_type=None, hazmat=False,
                 mode=None):
    """Rank carriers for a shipment id, or for an explicit lane; the shared entry for the route and tool."""
    if shipment_id:
        shipment_id = str(shipment_id)
        cached = {s["shipment_id"]: s for s in db.load_records("shipments")}
        shipment = cached.get(shipment_id) or meridian.get(f"/shipments/{shipment_id}")
        result = rank_carriers(shipment_id=shipment_id, **load_from_shipment(shipment))
        return {"shipment_id": shipment_id, **result}
    return rank_carriers(_place(origin, "origin"), _place(destination, "destination"),
                         equipment_type=equipment_type, hazmat=bool(hazmat), mode=mode)
