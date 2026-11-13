"""Lane flows, one-way cities, backhaul finder and prospect scoring."""

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .. import db
from . import classify, compat, hos, pricing

EMPTY_COST_PER_MILE = 2.00
NEAR_MILES = 100
ROAD_FACTOR = 1.2
TRUCK_MODES = {"TL", "EXPEDITE"}
INACTIVE_STATUSES = {"CANCELLED", "TONU"}

# Reverse-logistics patterns: what comes back from a consignee after this inbound category.
REVERSE_BY_CATEGORY = {"STEEL": "SCRAP", "WOOD": "WOOD", "PACKAGING": "PACKAGING"}
# General merchandise delivered to these facility types comes back as retail returns.
RETAIL_FACILITY_TYPES = {"DC", "STORE", "WAREHOUSE"}
FULL_SCORE_MILES = 1000
REVERSE_DESCRIPTIONS = {
    "SCRAP": "steel scrap and offcuts",
    "WOOD": "wood pallets and dunnage",
    "PACKAGING": "baled cartons and empty totes",
    "RETAIL_RETURNS": "retail returns",
}

# Assumed freight profile for a prospect customer with no loads yet.
COLD_LEAD_PROFILE = {"category": "GENERAL", "temp_controlled": False, "hazmat": False,
                     "weight_lb": 20000, "pallet_positions": 12, "equipment": None}

# Facilities in Meridian have no latitude/longitude, so map cities by hand.
CITY_COORDS = {
    ("Allentown", "PA"): (40.6023, -75.4714),
    ("Aurora", "CO"): (39.7294, -104.8319),
    ("Bedford Park", "IL"): (41.7681, -87.8131),
    ("Boston", "MA"): (42.3601, -71.0589),
    ("Charlotte", "NC"): (35.2271, -80.8431),
    ("Chicago", "IL"): (41.8781, -87.6298),
    ("Columbus", "OH"): (39.9612, -82.9988),
    ("Dallas", "TX"): (32.7767, -96.7970),
    ("Denver", "CO"): (39.7392, -104.9903),
    ("Des Moines", "IA"): (41.5868, -93.6250),
    ("El Paso", "TX"): (31.7619, -106.4850),
    ("Fort Worth", "TX"): (32.7555, -97.3308),
    ("Fresno", "CA"): (36.7378, -119.7871),
    ("Grand Rapids", "MI"): (42.9634, -85.6681),
    ("Houston", "TX"): (29.7604, -95.3698),
    ("Joliet", "IL"): (41.5250, -88.0817),
    ("Kansas City", "MO"): (39.0997, -94.5786),
    ("Kent", "WA"): (47.3809, -122.2348),
    ("McDonough", "GA"): (33.4473, -84.1469),
    ("Memphis", "TN"): (35.1495, -90.0490),
    ("Naperville", "IL"): (41.7508, -88.1535),
    ("Nashville", "TN"): (36.1627, -86.7816),
    ("Newark", "NJ"): (40.7357, -74.1724),
    ("Ontario", "CA"): (34.0633, -117.6509),
    ("Phoenix", "AZ"): (33.4484, -112.0740),
    ("Pittsburgh", "PA"): (40.4406, -79.9959),
    ("Pooler", "GA"): (32.1155, -81.2471),
    ("Portland", "OR"): (45.5152, -122.6784),
    ("Rockford", "IL"): (42.2711, -89.0940),
    ("Salt Lake City", "UT"): (40.7608, -111.8910),
    ("Scottsdale", "AZ"): (33.4942, -111.9261),
}


# ---------- data loading ----------

def _load():
    """Return (active shipments with their classification attached, vendors, facilities, customers)."""
    labels = classify.get_classifications()
    shipments = []
    for s in db.load_records("shipments"):
        if s.get("status") in INACTIVE_STATUSES:
            continue
        label = labels.get(s["shipment_id"])
        if label is None:
            # Not classified yet: trust Meridian's hazmat flag so FSMA and hazmat rules still apply.
            hazmat = any(line.get("hazmat") for line in s.get("freight_lines") or [])
            label = {"category": "HAZMAT" if hazmat else "GENERAL", "temp_controlled": False,
                     "hazmat": hazmat}
        s["_category"] = label["category"]
        s["_temp_controlled"] = bool(label["temp_controlled"])
        s["_hazmat"] = bool(label["hazmat"])
        shipments.append(s)
    vendors = {v["vendor_id"]: v for v in db.load_records("vendors")}
    facilities = {f["facility_id"]: f for f in db.load_records("facilities")}
    customers = {c["customer_id"]: c for c in db.load_records("customers")}
    return shipments, vendors, facilities, customers


def _origin(s):
    return (s["shipper_city"], s["shipper_state"])


def _dest(s):
    return (s["consignee_city"], s["consignee_state"])


def _place(key):
    return {"city": key[0], "state": key[1]}


def coords(key, facilities=None):
    """Return (lat, lng) for a (city, state), preferring facility coordinates, else the city table."""
    for f in (facilities or {}).values():
        if (f.get("city"), f.get("state")) == key and f.get("latitude") is not None:
            return f["latitude"], f["longitude"]
    return CITY_COORDS.get(key, (None, None))


def distance_miles(a, b):
    """Estimate road miles between two (city, state) keys: great-circle distance times ROAD_FACTOR."""
    if a == b:
        return 0
    (lat1, lng1), (lat2, lng2) = CITY_COORDS.get(a, (None, None)), CITY_COORDS.get(b, (None, None))
    if lat1 is None or lat2 is None:
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(3958.8 * 2 * math.asin(math.sqrt(h)) * ROAD_FACTOR)


def _known_lane_miles(shipments):
    miles = defaultdict(list)
    for s in shipments:
        if s.get("miles"):
            miles[(_origin(s), _dest(s))].append(s["miles"])
            miles[(_dest(s), _origin(s))].append(s["miles"])
    return {lane: round(sum(m) / len(m)) for lane, m in miles.items()}


def _lane_miles(a, b, known):
    return known.get((a, b)) or distance_miles(a, b)


def _buy_frt(s):
    return sum(c.get("amount") or 0 for c in s.get("vendor_costs") or []
               if c.get("charge_code") == "FRT" and c.get("status") != "CANCELLED")


# ---------- network ----------

def lane_flows(shipments=None):
    """Aggregate active shipments by origin -> destination; return lanes with loads, equipment mix and avg miles."""
    if shipments is None:
        shipments = _load()[0]
    lanes = {}
    for s in shipments:
        key = (_origin(s), _dest(s))
        lane = lanes.setdefault(key, {"origin": key[0], "destination": key[1], "loads": 0,
                                      "truck_loads": 0, "equipment": Counter(), "miles": []})
        lane["loads"] += 1
        lane["truck_loads"] += s.get("mode") in TRUCK_MODES
        lane["equipment"][s.get("equipment_type") or "?"] += 1
        if s.get("miles"):
            lane["miles"].append(s["miles"])
    for lane in lanes.values():
        lane["miles"] = round(sum(lane["miles"]) / len(lane["miles"])) if lane["miles"] else None
        lane["one_way"] = (lane["destination"], lane["origin"]) not in lanes
    return sorted(lanes.values(), key=lambda lane: -lane["loads"])


def one_way_cities(shipments=None):
    """Return {(city, state): {"inbound": n, "outbound": n}} for every city in the network."""
    if shipments is None:
        shipments = _load()[0]
    counts = defaultdict(lambda: {"inbound": 0, "outbound": 0})
    for s in shipments:
        counts[_origin(s)]["outbound"] += 1
        counts[_dest(s)]["inbound"] += 1
    return dict(counts)


def network_summary():
    """Build the /api/network payload: totals, cities with flow counts, and lane arcs."""
    shipments, _, facilities, _ = _load()
    lanes = lane_flows(shipments)
    cities = one_way_cities(shipments)

    def point(key):
        lat, lng = coords(key, facilities)
        return {"city": key[0], "state": key[1], "lat": lat, "lng": lng}

    one_way = [lane for lane in lanes if lane["one_way"]]
    # Only dedicated trucks (TL, expedite) drive home empty; LTL trucks run on networks.
    empty_miles = sum(lane["truck_loads"] * (lane["miles"] or 0) for lane in one_way)
    return {
        "totals": {
            "empty_miles": empty_miles,
            "empty_cost_usd": round(empty_miles * EMPTY_COST_PER_MILE, 2),
            "one_way_lanes": len(one_way),
            "loads": len(shipments),
        },
        "cities": [dict(point(key), **counts) for key, counts in sorted(cities.items())],
        "arcs": [
            {"from": point(lane["origin"]), "to": point(lane["destination"]),
             "loads": lane["loads"], "miles": lane["miles"], "equipment": dict(lane["equipment"])}
            for lane in lanes
        ],
    }


# ---------- trucks and candidate freight ----------

def trailer_history(shipments):
    """Return the last shipment per (carrier_id, trailer_number), ordered by pickup date then file."""
    last = {}
    for s in sorted(shipments, key=lambda s: (s.get("pickup_date") or "", s["shipment_id"])):
        if s.get("carrier_id") and s.get("trailer_number"):
            last[(s["carrier_id"], s["trailer_number"])] = s
    return last


def _hazmat_note(s):
    for line in s.get("freight_lines") or []:
        match = re.search(r"UN\d{4}", line.get("description") or "")
        if match:
            return match.group(0)
    return None


def _trucks_arriving(key, shipments, known_miles):
    history = trailer_history(shipments)
    lane_buys = defaultdict(list)
    for s in shipments:
        if _buy_frt(s):
            lane_buys[(_origin(s), _dest(s))].append(_buy_frt(s))
    trucks = []
    for s in shipments:
        if _dest(s) != key or s.get("mode") not in TRUCK_MODES or not s.get("carrier_id"):
            continue
        last = history.get((s["carrier_id"], s.get("trailer_number")), s)
        buys = lane_buys.get((_origin(s), key))
        trucks.append({
            "outbound_file": s["shipment_id"],
            "shipment": s,
            "delivery_facility_id": (s.get("stops") or [{}])[-1].get("facility_id"),
            "home": _origin(s),
            "home_miles": s.get("miles") or _lane_miles(key, _origin(s), known_miles),
            "equipment": s.get("equipment_type"),
            "carrier_id": s["carrier_id"],
            "trailer_number": s.get("trailer_number"),
            "last_category": last["_category"],
            "last_note": _hazmat_note(last),
            "avg_outbound_buy_frt": sum(buys) / len(buys) if buys else None,
        })
    return trucks


def _profile(loads):
    """Summarize a group of shipments as a candidate freight profile."""
    n = len(loads)
    return {
        "category": Counter(s["_category"] for s in loads).most_common(1)[0][0],
        "temp_controlled": sum(s["_temp_controlled"] for s in loads) * 2 > n,
        "hazmat": any(s["_hazmat"] for s in loads),
        "weight_lb": round(sum((s.get("freight_totals") or {}).get("actual_lb") or 0 for s in loads) / n),
        "pallet_positions": round(sum((s.get("freight_totals") or {}).get("pallet_positions") or 0 for s in loads) / n),
        "equipment": Counter(s.get("equipment_type") for s in loads).most_common(1)[0][0],
    }


def _candidates_near(key, shipments, facilities, customers, known_miles):
    """Return candidate return freight that can be picked up within NEAR_MILES of a city."""

    def near(other):
        d = _lane_miles(key, other, known_miles)
        return d is not None and d <= NEAR_MILES

    candidates = []

    # 1. Customers that already ship from somewhere near this city.
    by_shipper = defaultdict(list)
    for s in shipments:
        if near(_origin(s)):
            by_shipper[(s["customer_id"], _origin(s))].append(s)
    for (customer_id, pickup), loads in by_shipper.items():
        pickup_facilities = Counter((s.get("stops") or [{}])[0].get("facility_id") for s in loads)
        candidates.append(dict(_profile(loads), customer_id=customer_id, pickup=pickup,
                               pickup_facility_id=pickup_facilities.most_common(1)[0][0],
                               destination=None, loads=len(loads),
                               source=f"already ships from {pickup[0]}, {pickup[1]} ({len(loads)} loads)"))

    # 2. Reverse logistics at consignees near this city, going back to the shipper's origin.
    by_consignee = defaultdict(list)
    for s in shipments:
        if near(_dest(s)):
            by_consignee[(s["customer_id"], s["stops"][-1].get("facility_id"), _dest(s), _origin(s))].append(s)
    for (customer_id, facility_id, pickup, origin), loads in by_consignee.items():
        inbound = _profile(loads)
        facility = facilities.get(facility_id) or {}
        patterns = []
        if inbound["category"] in REVERSE_BY_CATEGORY:
            patterns.append(REVERSE_BY_CATEGORY[inbound["category"]])
        if inbound["category"] == "GENERAL" and facility.get("facility_type") in RETAIL_FACILITY_TYPES:
            patterns.append("RETAIL_RETURNS")
        for category in patterns:
            candidates.append(dict(
                inbound, category=category, temp_controlled=False, hazmat=False,
                customer_id=customer_id, pickup=pickup, pickup_facility_id=facility_id,
                destination=origin, loads=len(loads),
                source=f"reverse logistics: {REVERSE_DESCRIPTIONS[category]} from "
                       f"{facility.get('name') or pickup[0]} back to {origin[0]}, {origin[1]}",
            ))

    # 3. Prospect customers with no loads yet whose main address is near this city.
    shipping = {s["customer_id"] for s in shipments}
    for customer in customers.values():
        if customer["customer_id"] in shipping:
            continue
        for address in customer.get("addresses") or []:
            pickup = (address.get("city"), address.get("state"))
            if near(pickup):
                candidates.append(dict(COLD_LEAD_PROFILE, customer_id=customer["customer_id"],
                                       pickup=pickup, pickup_facility_id=None, destination=None, loads=0,
                                       source=f"prospect with no loads yet; freight profile assumed GENERAL"))
                break
    return candidates


# ---------- scoring ----------

def score_prospect(ok, truck, candidate, customer, miles_saved):
    """Score a truck + candidate pairing 0-100 and return (score, reasons). Compat is a hard gate."""
    if not ok:
        return 0, []
    score, reasons = 30, []
    if candidate["loads"] and customer.get("status") == "ACTIVE":
        score += 25
        reasons.append(f"Warm lead: {customer.get('legal_name', candidate['customer_id'])} "
                       f"already ships with us ({candidate['loads']} loads on this pattern).")
    else:
        reasons.append("Cold lead: no loads with us yet.")
    score += round(30 * min(1.0, miles_saved / FULL_SCORE_MILES))
    share = miles_saved / truck["home_miles"] if truck["home_miles"] else 0
    reasons.append(f"Saves {miles_saved:,} empty miles ({share:.0%} of the trip home).")
    if candidate.get("equipment") == truck["equipment"]:
        score += 15
        reasons.append(f"Equipment match: this freight usually moves on {truck['equipment']}.")
    return min(score, 100), reasons


def _pair(key, truck, candidate, vendors, customers, known_miles, facilities=None, driver=None):
    destination = candidate["destination"] or truck["home"]
    deadhead = _lane_miles(key, candidate["pickup"], known_miles)
    loaded = _lane_miles(candidate["pickup"], destination, known_miles)
    to_home = _lane_miles(destination, truck["home"], known_miles)
    # Skip pairings with an unknown distance (a city missing from CITY_COORDS) or no loaded leg.
    if deadhead is None or to_home is None or not loaded or not truck["home_miles"]:
        return None
    miles_saved = round(truck["home_miles"] - deadhead - to_home)
    if miles_saved <= 0:
        return None

    carrier = vendors.get(truck["carrier_id"], {"vendor_id": truck["carrier_id"]})
    customer = customers.get(candidate["customer_id"], {})
    ok, compat_reasons = compat.check_compat(
        truck["last_category"], truck["equipment"], candidate, carrier,
        trailer_number=truck["trailer_number"], last_load_note=truck["last_note"],
    )
    # Hours of Service: the earliest day this driver can legally pick the freight up and deliver it.
    timing = {}
    if driver is not None:
        same_dock = candidate.get("pickup_facility_id") and candidate["pickup_facility_id"] == truck["delivery_facility_id"]
        timing = hos.earliest_backhaul(driver, (facilities or {}).get(candidate.get("pickup_facility_id")), loaded,
                                       0 if same_dock else max(deadhead, hos.LOCAL_DEADHEAD_MILES))
        ok = ok and timing["ok"]
        reasons = compat_reasons + timing["reasons"]
        # The contract promises the first reason says what blocked it.
        compat_reasons = [r for r in reasons if r.startswith("Blocked")] + [r for r in reasons if not r.startswith("Blocked")]
    score, score_reasons = score_prospect(ok, truck, candidate, customer, miles_saved)

    buy_lines = pricing.backhaul_buy_lines(loaded, truck["avg_outbound_buy_frt"])
    margin = pricing.margin_for(customer)
    money = pricing.estimate(buy_lines, margin)
    prospect_id = ":".join([key[1], key[0], candidate["customer_id"], candidate["category"],
                            candidate["pickup"][0], destination[0], truck["outbound_file"]])
    return {
        "prospect_id": prospect_id,
        "customer_id": candidate["customer_id"],
        "customer_name": customer.get("legal_name", candidate["customer_id"]),
        "origin": _place(candidate["pickup"]),
        "destination": _place(destination),
        "equipment": truck["equipment"],
        "category": candidate["category"],
        "score": score,
        "est_buy": money["buy_total"],
        "est_sell": money["sell_total"],
        "gp_pct": money["gp_pct"],
        "miles": loaded,
        "outbound_file": truck["outbound_file"],
        "ok": ok,
        "reasons": compat_reasons + score_reasons + [f"Source: {candidate['source']}."],
        "carrier_id": truck["carrier_id"],
        "miles_saved": miles_saved,
        "pickup_date": timing.get("pickup_date"),
        "delivery_date_target": timing.get("delivery_date"),
        "est_pickup": timing.get("pickup_at"),
        "est_delivery": timing.get("arrive_at"),
        "target_margin_pct": margin,
        "buy_lines": buy_lines,
    }


def _resolve_city(city, state, cities):
    for key in cities:
        if key[0].lower() == city.lower() and key[1].lower() == state.lower():
            return key
    return (city, state.upper())


def find_backhauls(city, state):
    """Return ranked backhaul prospects for trucks arriving in a city: best truck per candidate load."""
    shipments, vendors, facilities, customers = _load()
    key = _resolve_city(city, state, one_way_cities(shipments))
    known_miles = _known_lane_miles(shipments)
    trucks = _trucks_arriving(key, shipments, known_miles)
    # Each truck's driver clock once; a truck that emptied in the past is available now (it has rested).
    now = datetime.now(timezone.utc)
    drivers = {t["outbound_file"]: hos.off_duty(hos.driver_after_outbound(t["shipment"], facilities), now,
                                                "already empty: available now")
               for t in trucks}
    prospects = []
    for candidate in _candidates_near(key, shipments, facilities, customers, known_miles):
        pairs = [p for p in (_pair(key, t, candidate, vendors, customers, known_miles, facilities,
                                   drivers[t["outbound_file"]]) for t in trucks) if p]
        if not pairs:
            continue
        compatible = [p for p in pairs if p["ok"]]
        if compatible:
            prospects.append(max(compatible, key=lambda p: (p["score"], p["miles_saved"])))
        else:
            prospects.append(max(pairs, key=lambda p: p["miles_saved"]))
    return sorted(prospects, key=lambda p: (-p["score"], -p["miles_saved"]))


def city_detail(city, state):
    """Build the /api/city payload: the city's inbound/outbound counts and its backhaul prospects."""
    shipments = _load()[0]
    cities = one_way_cities(shipments)
    key = _resolve_city(city, state, cities)
    counts = cities.get(key, {"inbound": 0, "outbound": 0})
    return {"city": key[0], "state": key[1], **counts, "prospects": find_backhauls(*key)}


def find_prospect(prospect_id):
    """Recompute the prospects for the prospect's city and return the one with this id, or None."""
    parts = prospect_id.split(":")
    if len(parts) != 7:
        return None
    state, city = parts[0], parts[1]
    return next((p for p in find_backhauls(city, state) if p["prospect_id"] == prospect_id), None)
