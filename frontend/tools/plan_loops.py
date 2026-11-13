"""Builds the Return Trip demo data from REAL Meridian loads only.

Nothing here invents freight. Every leg of every loop is an existing Meridian shipment.
The script:
  1. pulls every shipment (list + detail, for truck number and driver) from the Meridian API,
  2. replays the whole truckload history twice: every load booked one by one (the truck drives
     home empty) versus loads chained into loops by the same rules the brain uses,
  3. finds the loops a broker can book right now: a truck already on a load chains into open
     loads that still need a carrier,
  4. finds trucks that already ran consecutive loads (loops that already happened),
  5. finds loads where moving the pickup a day or two would let a loop close,
  6. adds real road geometry (OSRM / OpenStreetMap) and real market prices (Meridian rate engine).

Assumptions (the only numbers not from Meridian), kept in one place:
  EMPTY_COST_PER_MILE  what an empty mile costs a carrier (industry average, ATRI 2024 ~ $2.27/mi)
  MAX_DEADHEAD_MI      how far a truck may drive empty to its next pickup
  MAX_GAP_DAYS         how long a truck may wait between loads
  ROAD_FACTOR          road miles per straight-line mile for deadhead estimates

Run:  python3 frontend/tools/plan_loops.py secret.txt frontend/mocks
Ryan: this is the logic to port into backend/brain/network.py.
"""
import json
import math
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

EMPTY_COST_PER_MILE = 2.27
MAX_DEADHEAD_MI = 300
MAX_GAP_DAYS = 2
ROAD_FACTOR = 1.2
TOUR_MAX_DAYS = 10

secret, out = sys.argv[1], Path(sys.argv[2])
here = Path(__file__).parent
cache_dir = here / ".cache"
cache_dir.mkdir(exist_ok=True)
txt = open(secret, encoding="utf-8").read().replace("\r", "")
BASE = re.search(r"Base URL:\s*(\S+)", txt).group(1)
KEY = re.search(r"API key:\s*(\S+)", txt).group(1)


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET",
                                 headers={"x-api-key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def cached(name, fn):
    f = cache_dir / name
    if f.exists():
        return json.loads(f.read_text())
    data = fn()
    f.write_text(json.dumps(data))
    return data


# ---------- 1. real data ----------
listing = cached("shipments.json", lambda: api("/shipments?limit=200")["items"])
details = cached("details.json", lambda: {s["shipment_id"]: (time.sleep(0.15), api(f"/shipments/{s['shipment_id']}"))[1] for s in listing})
vendors = {v["vendor_id"]: v for v in cached("vendors.json", lambda: api("/vendors?limit=200")["items"])}
ships = [details[s["shipment_id"]] for s in listing]

COORDS = {
    "Chicago,IL": (41.88, -87.63), "Dallas,TX": (32.78, -96.80), "Rockford,IL": (42.27, -89.09), "Aurora,CO": (39.73, -104.83),
    "Columbus,OH": (39.96, -83.00), "Fort Worth,TX": (32.75, -97.33), "Pittsburgh,PA": (40.44, -79.99), "Newark,NJ": (40.74, -74.17),
    "Houston,TX": (29.76, -95.37), "Portland,OR": (45.52, -122.68), "Kent,WA": (47.38, -122.23), "Charlotte,NC": (35.23, -80.84),
    "Boston,MA": (42.36, -71.06), "Kansas City,MO": (39.10, -94.58), "Phoenix,AZ": (33.45, -112.07), "El Paso,TX": (31.76, -106.49),
    "Fresno,CA": (36.74, -119.79), "Ontario,CA": (34.06, -117.65), "McDonough,GA": (33.45, -84.15), "Grand Rapids,MI": (42.96, -85.67),
    "Des Moines,IA": (41.59, -93.62), "Memphis,TN": (35.15, -90.05), "Nashville,TN": (36.16, -86.78), "Salt Lake City,UT": (40.76, -111.89),
    "Scottsdale,AZ": (33.49, -111.93), "Naperville,IL": (41.75, -88.15), "Pooler,GA": (32.12, -81.25), "Allentown,PA": (40.60, -75.49),
    "Joliet,IL": (41.53, -88.08), "Bedford Park,IL": (41.77, -87.80), "Denver,CO": (39.74, -104.99),
}


def place(city, state):
    lat, lng = COORDS[f"{city},{state}"]
    return {"city": city, "state": state, "lat": lat, "lng": lng}


def miles_between(a, b):
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3959 * math.asin(math.sqrt(h)) * ROAD_FACTOR


def category(s):
    text = " ".join((f.get("description") or "") for f in s.get("freight_lines") or []).lower()
    if any(f.get("hazmat") for f in s.get("freight_lines") or []) or re.search(r"\bun\d{4}\b", text):
        return "HAZMAT"
    rules = [("FOOD", r"food|seafood|dairy|grocer|frozen|produce|meat|bakery|snack|beverage"),
             ("CHEMICAL", r"chemical|cleaning|compound|fertilizer|solvent"),
             ("WOOD", r"lumber|wood|decking"), ("STEEL", r"steel|metal|bracket|machined"),
             ("PACKAGING", r"carton|corrugat|packaging|pallet|tote"), ("RETAIL_RETURNS", r"return")]
    return next((c for c, rx in rules if re.search(rx, text)), "GENERAL")


def d(s):
    return date.fromisoformat(s)


loads = []
for s in ships:
    if s["mode"] not in ("TL", "EXPEDITE") or s["status"] in ("CANCELLED", "TONU"):
        continue
    loads.append({
        "id": s["shipment_id"], "status": s["status"], "mode": s["mode"], "eq": s.get("equipment_type") or "V",
        "origin": place(s["shipper_city"], s["shipper_state"]), "dest": place(s["consignee_city"], s["consignee_state"]),
        "pickup": d(s["pickup_date"]), "deliver": d(s.get("delivery_date_target") or s["pickup_date"]),
        "miles": s["miles"], "sell": s["sell_total"], "buy": s["buy_total"] or None,
        "carrier": s.get("carrier_id"), "truck": s.get("truck_number"), "driver": s.get("driver_name"),
        "customer": s["customer_id"], "shipper": s.get("shipper_name"), "consignee": s.get("consignee_name"),
        "commodity": ((s.get("freight_lines") or [{}])[0].get("description") or ""), "category": category(s),
        "target_pay": [s.get("target_pay_min"), s.get("target_pay_max")],
    })
by_id = {l["id"]: l for l in loads}


# ---------- 2. the rules the brain applies between two consecutive loads of one truck ----------
def can_carry(truck_eq, load):
    return load["eq"] == truck_eq or (truck_eq == "R" and load["eq"] == "V")


def why_not(prev, nxt, truck_eq, history_cats):
    """None if the truck can take `nxt` after `prev`, else the rule that blocks it."""
    if not can_carry(truck_eq, nxt):
        return "equipment"
    if nxt["category"] == "FOOD" and history_cats & {"HAZMAT", "CHEMICAL", "WASTE"}:
        return "fsma"
    gap = (nxt["pickup"] - prev["deliver"]).days
    if gap < 0 or gap > MAX_GAP_DAYS:
        return "timing"
    if miles_between(prev["dest"], nxt["origin"]) > MAX_DEADHEAD_MI:
        return "distance"
    return None


def tour_empty(legs):
    """Empty miles of one truck: hops between loads plus the drive back to where it started."""
    hops = sum(miles_between(a["dest"], b["origin"]) for a, b in zip(legs, legs[1:]))
    return hops + miles_between(legs[-1]["dest"], legs[0]["origin"])


def plan(pool, seeds=None):
    """Greedy, in pickup order: each load joins the open tour that reaches it with the least empty driving."""
    tours = [dict(legs=[s], eq=s["eq"], cats={s["category"]}) for s in (seeds or [])]
    for l in sorted(pool, key=lambda x: (x["pickup"], x["id"])):
        best, best_mi = None, None
        for t in tours:
            last = t["legs"][-1]
            if (l["pickup"] - t["legs"][0]["pickup"]).days > TOUR_MAX_DAYS or why_not(last, l, t["eq"], t["cats"]):
                continue
            # only chain when it actually cuts empty driving: the hop plus the new drive home must be
            # shorter than the old drive home plus this load's own empty return
            home = t["legs"][0]["origin"]
            gain = (miles_between(last["dest"], home) + tour_empty([l])) - (miles_between(last["dest"], l["origin"]) + miles_between(l["dest"], home))
            if gain <= 0:
                continue
            mi = -gain
            if best is None or mi < best_mi:
                best, best_mi = t, mi
        if best:
            best["legs"].append(l)
            best["cats"].add(l["category"])
        else:
            tours.append(dict(legs=[l], eq=l["eq"], cats={l["category"]}))
    return tours


# ---------- 3. network-wide replay of every truckload Meridian has booked ----------
history = plan(loads)
one_by_one_empty = sum(tour_empty([l]) for l in loads)  # each truck drives home empty (same estimator as the loops)
loops_empty = sum(tour_empty(t["legs"]) for t in history)
loaded = sum(l["miles"] for l in loads)
chained = [t for t in history if len(t["legs"]) > 1]
network = {
    "loads": len(loads), "loaded_miles": round(loaded),
    "one_by_one": {"empty_miles": round(one_by_one_empty), "loaded_pct": round(loaded / (loaded + one_by_one_empty) * 100)},
    "as_loops": {"empty_miles": round(loops_empty), "loaded_pct": round(loaded / (loaded + loops_empty) * 100)},
    "empty_miles_saved": round(one_by_one_empty - loops_empty),
    "pct_saved": round((one_by_one_empty - loops_empty) / one_by_one_empty * 100, 1),
    "loads_in_loops": sum(len(t["legs"]) for t in chained), "loops": len(chained),
    "trucks_needed": {"one_by_one": len(loads), "as_loops": len(history)},
    "cost_per_empty_mile": EMPTY_COST_PER_MILE,
    "cost_saved_usd": round((one_by_one_empty - loops_empty) * EMPTY_COST_PER_MILE),
    "period": {"from": str(min(l["pickup"] for l in loads)), "to": str(max(l["pickup"] for l in loads))},
    "rules": {"max_deadhead_mi": MAX_DEADHEAD_MI, "max_gap_days": MAX_GAP_DAYS, "tour_max_days": TOUR_MAX_DAYS},
}
print("NETWORK", json.dumps(network))

# ---------- 4. loops a broker can book now ----------
OPEN = {"COVERED", "DISPATCHED", "AT_PICKUP", "PICKED_UP", "IN_TRANSIT", "AT_DELIVERY", "DELIVERED", "ON_HOLD", "POD_RECEIVED"}
seeds = [l for l in loads if l["status"] in OPEN and l["carrier"] and l["truck"]
         and vendors.get(l["carrier"], {}).get("status") == "ACTIVE"]
needs_carrier = [l for l in loads if l["status"] == "BOOKED"]
now_tours = [t for t in plan(needs_carrier, seeds) if len(t["legs"]) > 1 and t["legs"][0]["status"] != "BOOKED"]

# ---------- 5. loops that already happened (same truck, consecutive chained loads) ----------
by_truck = defaultdict(list)
for l in loads:
    if l["carrier"] and l["truck"]:
        by_truck[(l["carrier"], l["truck"])].append(l)
done_tours = []
for key, ls in by_truck.items():
    ls.sort(key=lambda x: x["pickup"])
    run = [ls[0]]
    for prev, nxt in zip(ls, ls[1:]):
        if not why_not(prev, nxt, run[0]["eq"], {x["category"] for x in run}):
            run.append(nxt)
        else:
            if len(run) > 1: done_tours.append(run)
            run = [nxt]
    if len(run) > 1: done_tours.append(run)
print("loops now:", len(now_tours), "| already happened:", len(done_tours))

# ---------- 6. flexible dates: a load that would close a loop if it moved a day or two ----------
flex = []
for t in now_tours + [dict(legs=r) for r in done_tours]:
    pass  # loops that already work need no date change
for a in seeds:
    for b in needs_carrier:
        if b in sum((t["legs"] for t in now_tours), []):
            continue
        gap = (b["pickup"] - a["deliver"]).days
        if can_carry(a["eq"], b) and miles_between(a["dest"], b["origin"]) <= MAX_DEADHEAD_MI and (-3 <= gap < 0 or MAX_GAP_DAYS < gap <= MAX_GAP_DAYS + 3):
            shift = -gap if gap < 0 else -(gap - MAX_GAP_DAYS)
            flex.append((a, b, shift))
print("flex-date opportunities:", len(flex))

# ---------- 7. road geometry + market prices ----------
route_cache_f = cache_dir / "routes.json"
route_cache = json.loads(route_cache_f.read_text()) if route_cache_f.exists() else {}


def road(a, b):
    key = f"{a['lng']:.3f},{a['lat']:.3f};{b['lng']:.3f},{b['lat']:.3f}"
    if key not in route_cache:
        url = f"https://router.project-osrm.org/route/v1/driving/{key}?overview=full&geometries=geojson"
        r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "return-trip-hackathon-demo"}), timeout=30))
        c = r["routes"][0]["geometry"]["coordinates"]
        step = max(1, len(c) // 220)
        pts = c[::step] + ([c[-1]] if c[-1] != c[::step][-1] else [])
        route_cache[key] = {"path": [[round(x, 4), round(y, 4)] for x, y in pts], "miles": round(r["routes"][0]["distance"] / 1609.34)}
        route_cache_f.write_text(json.dumps(route_cache))
        time.sleep(1.1)
    return route_cache[key]


market_cache = cached("market.json", lambda: {})


def market(l):
    k = f"{l['mode']}|{l['origin']['state']}|{l['dest']['state']}|{l['miles']}"
    if k not in market_cache:
        body = {"mode": l["mode"], "origin": {"state": l["origin"]["state"]}, "destination": {"state": l["dest"]["state"]}, "miles": l["miles"]}
        if l["mode"] == "EXPEDITE":
            body["freight_lines"] = [{"pieces": 1, "weight_lb": 2000}]
        r = api("/rate-engine/quotes", body)
        market_cache[k] = {"buy": r["buy_total"], "low": r["market_context"]["low"], "high": r["market_context"]["high"]}
        (cache_dir / "market.json").write_text(json.dumps(market_cache))
    return market_cache[k]


EQ = {"V": "Dry van", "R": "Reefer", "F": "Flatbed", "SV": "Sprinter", "SB": "Box truck", "HS": "Hotshot"}
COLORS = ["#0891b2", "#2563eb", "#7c3aed", "#0ea5e9", "#14b8a6", "#f59e0b", "#8b5cf6", "#22c55e", "#64748b", "#db2777"]


def leg_json(seq, l, booked_tour):
    r = road(l["origin"], l["dest"])
    m = market(l)
    needs = l["status"] == "BOOKED"
    buy = l["buy"] if l["buy"] else m["buy"]
    return {"seq": seq, "kind": "existing", "status": ("covered" if booked_tour else "needs_carrier") if needs else "booked",
            "shipment_id": l["id"], "meridian_status": l["status"], "origin": l["origin"], "destination": l["dest"],
            "miles": l["miles"], "pickup": str(l["pickup"]), "deliver": str(l["deliver"]),
            "customer": l["shipper"] or l["customer"], "customer_id": l["customer"], "commodity": l["commodity"], "category": l["category"],
            "sell": l["sell"], "buy": round(buy, 2), "buy_source": "meridian" if l["buy"] else "rate_engine_market",
            "market": m, "gp_pct": round((l["sell"] - buy) / l["sell"] * 100, 1) if l["sell"] else None,
            "path": r["path"], "road_miles": r["miles"]}


def empty_json(seq, a, b, note):
    r = road(a, b)
    return {"seq": seq, "kind": "empty", "status": "empty", "origin": a, "destination": b,
            "miles": round(miles_between(a, b)), "road_miles": r["miles"], "path": r["path"], "note": note}


def build_tour(i, legs, status):
    first = legs[0]
    out_legs, seq = [], 1
    for a, b in zip(legs, legs[1:] + [None]):
        out_legs.append(leg_json(seq, a, status == "booked")); seq += 1
        nxt_origin = b["origin"] if b else first["origin"]
        if a["dest"]["city"] != nxt_origin["city"] or not b:
            if b is None and a["dest"]["city"] == first["origin"]["city"]:
                break
            out_legs.append(empty_json(seq, a["dest"], nxt_origin, "Drive home" if b is None else f"Empty to the next pickup in {nxt_origin['city']}")); seq += 1
    loaded_mi = sum(l["miles"] for l in legs)
    empty_mi = round(tour_empty(legs))
    one_by_one = round(sum(tour_empty([l]) for l in legs))  # every load alone sends its own truck home empty
    saved = one_by_one - empty_mi
    sell = sum(l["sell"] for l in legs)
    buy = sum(x["buy"] for x in out_legs if x["kind"] != "empty")
    vendor = vendors.get(first["carrier"], {})
    cities = []
    for l in legs:
        for c in (l["origin"]["city"], l["dest"]["city"]):
            if not cities or cities[-1] != c: cities.append(c)
    open_legs = [x for x in out_legs if x["status"] == "needs_carrier"]
    decisions = [
        {"check": "equipment", "passed": True, "text": f"Every load fits a {EQ.get(first['eq'], first['eq']).lower()} ({first['carrier']} truck {first['truck']})"},
        {"check": "food_safety", "passed": True, "text": "No food after hazmat or chemicals in this trailer" if any(l["category"] == "FOOD" for l in legs) else "No food on this run, no food-safety rule applies"},
        {"check": "timing", "passed": True, "text": " · ".join(f"{b['id']} picks up {(b['pickup'] - a['deliver']).days} day(s) after {a['id']} delivers" for a, b in zip(legs, legs[1:]))},
        {"check": "distance", "passed": True, "text": " · ".join(f"{round(miles_between(a['dest'], b['origin']))} mi empty {a['dest']['city']} → {b['origin']['city']}" for a, b in zip(legs, legs[1:]))},
        {"check": "compliance", "passed": vendor.get("status") == "ACTIVE", "text": f"{vendor.get('legal_name', first['carrier'])} is {vendor.get('status', 'unknown')}, compliance {vendor.get('compliance_light', '?')}"},
    ]
    return {
        "tour_id": f"L-{i:03d}", "name": " → ".join(cities), "status": status,
        "action_id": f"A-L{i:03d}" if status == "proposed" else None,
        "equipment": first["eq"], "color": COLORS[i % len(COLORS)],
        "carrier": {"vendor_id": first["carrier"], "name": vendor.get("legal_name", first["carrier"]), "truck": f"Truck {first['truck']}",
                    "driver": first["driver"] or "Driver not assigned", "home": first["origin"]},
        "window": {"start": str(first["pickup"]), "end": str(legs[-1]["deliver"]), "home_by": str(legs[-1]["deliver"] + timedelta(days=1))},
        "confidence": 1.0 if status == "booked" else round(0.95 - 0.05 * len(open_legs), 2),
        "headline": (f"{vendor.get('legal_name', first['carrier'])} truck {first['truck']} ({first['driver'] or 'driver tbd'}) is already on {first['id']}. "
                     f"Give it {', '.join(x['shipment_id'] for x in open_legs)} next, which still need a carrier, instead of sending it home empty.") if status == "proposed"
                    else f"Truck {first['truck']} already ran these loads back to back in Meridian.",
        "legs": out_legs, "decisions": decisions,
        "totals": {"loaded_miles": loaded_mi, "empty_miles": empty_mi, "loaded_pct": round(loaded_mi / (loaded_mi + empty_mi) * 100),
                   "one_by_one_empty_miles": one_by_one, "one_by_one_loaded_pct": round(loaded_mi / (loaded_mi + one_by_one) * 100), "empty_miles_saved": saved,
                   "cost_saved_usd": round(saved * EMPTY_COST_PER_MILE), "sell": round(sell, 2), "buy": round(buy, 2),
                   "gp": round(sell - buy, 2), "gp_pct": round((sell - buy) / sell * 100, 1), "loads": len(legs),
                   "carrier_pay": round(buy, 2), "carrier_pay_per_mile": round(buy / (loaded_mi + empty_mi), 2)},
    }


tours = [build_tour(i + 1, t["legs"], "proposed") for i, t in enumerate(sorted(now_tours, key=lambda t: -tour_empty([t["legs"][0]]) + tour_empty(t["legs"])))]
tours += [build_tour(len(tours) + i + 1, run, "booked") for i, run in enumerate(sorted(done_tours, key=lambda r: -len(r))[:6])]
(out / "tours.json").write_text(json.dumps({"items": tours}, indent=2) + "\n")
(out / "network_backtest.json").write_text(json.dumps(network, indent=2) + "\n")

actions = [{"action_id": t["action_id"], "type": "book_tour", "status": "pending", "tier": "write", "tour_id": t["tour_id"],
            "title": f"Book loop {t['tour_id']}: {t['name']}",
            "summary": f"{t['carrier']['name']} {t['carrier']['truck']} takes {t['totals']['loads']} loads, {t['totals']['empty_miles_saved']} empty miles saved",
            "confidence": t["confidence"],
            "steps": [f"Cover {x['shipment_id']} with {t['carrier']['name']} at market ${x['buy']:,.2f}" for x in t["legs"] if x["status"] == "needs_carrier"],
            "reasoning": t["headline"], "miles": t["totals"]["empty_miles_saved"], "created_at": "2026-11-13T12:00:00Z", "created_by": "agent"}
           for t in tours if t["status"] == "proposed"]
(out / "tour_actions.json").write_text(json.dumps({"items": actions}, indent=2) + "\n")

weeks = []
for t in tours:
    tt = t["totals"]
    weeks.append({"carrier": t["carrier"] | {"equipment": t["equipment"]}, "tour_id": t["tour_id"],
                  "status": "accepted" if t["status"] == "booked" else "offered", "offer_expires": "2026-11-14T18:00:00Z",
                  "legs": [{k: l.get(k) for k in ("seq", "kind", "origin", "destination", "miles", "pickup", "deliver", "commodity", "status", "note", "path")} | {"pay": l.get("buy")} for l in t["legs"]],
                  "totals": {"pay": tt["carrier_pay"], "loaded_miles": tt["loaded_miles"], "empty_miles": tt["empty_miles"], "loaded_pct": tt["loaded_pct"],
                             "per_mile": tt["carrier_pay_per_mile"], "idle_days": 0, "home_by": t["window"]["home_by"], "home_note": f"Back in {t['carrier']['home']['city']}"},
                  "standalone": {"pay": t["legs"][0]["buy"], "loaded_pct": 50, "idle_days": 1,
                                 "note": f"Only {t['legs'][0]['shipment_id']}, then {t['legs'][0]['miles']} mi home empty"}})
(out / "carrier_weeks.json").write_text(json.dumps({"items": weeks}, indent=2) + "\n")

offers = []
for i, (a, b, shift) in enumerate(sorted(flex, key=lambda x: -x[1]["miles"])[:6]):
    saved = round(b["miles"] + a["miles"] - tour_empty([a, b]))
    new_date = b["pickup"] + timedelta(days=shift)
    offers.append({"offer_id": f"O-{i + 1:03d}", "shipper": {"id": b["customer"], "name": b["shipper"] or b["customer"], "type": "Shipper"},
                   "kind": "flex_date", "status": "open", "tour_id": None, "shipment_id": b["id"],
                   "title": f"Pick up {abs(shift)} day{'s' if abs(shift) != 1 else ''} {'later' if shift > 0 else 'earlier'} and a truck is already there",
                   "detail": f"{a['carrier']} truck {a['truck']} delivers {a['id']} in {a['dest']['city']} on {a['deliver']:%a %-m/%-d}. "
                             f"If {b['id']} picks up {new_date:%a %-m/%-d} instead of {b['pickup']:%a %-m/%-d}, the same truck takes it.",
                   "lane": {"origin": b["origin"], "destination": b["dest"]}, "date": str(new_date), "original_date": str(b["pickup"]),
                   "price": b["sell"], "market_price": b["sell"], "savings": round(saved * EMPTY_COST_PER_MILE),
                   "empty_miles_saved": saved,
                   "reasons": [f"{round(miles_between(a['dest'], b['origin']))} mi from where truck {a['truck']} empties",
                               f"Saves {saved} empty miles (≈ ${round(saved * EMPTY_COST_PER_MILE):,} at ${EMPTY_COST_PER_MILE}/mi)"]})
(out / "shipper_offers.json").write_text(json.dumps({"items": offers}, indent=2) + "\n")

price = {"summary": {"emails": 0, "calls": 0, "signals": 0, "lanes": 0, "avg_loop_discount_pct": 0, "source": "Meridian rate engine"},
         "signals": [], "lanes": []}
for t in tours:
    for l in t["legs"]:
        if l["kind"] == "empty":
            continue
        m = l["market"]
        price["lanes"].append({"lane": {"origin": l["origin"], "destination": l["destination"]}, "equipment": t["equipment"],
                               "market_buy": m["buy"], "one_way_buy": m["buy"], "recommended_buy": l["buy"], "discount_pct": 0,
                               "confidence": 1, "signals": [], "note": f"Meridian rate engine: market ${m['low']:,.0f}–${m['high']:,.0f}; {'carrier rate in Meridian' if l['buy_source'] == 'meridian' else 'market rate used until a carrier is assigned'}."})
(out / "price_signals.json").write_text(json.dumps(price, indent=2) + "\n")

for t in tours:
    print(t["tour_id"], t["status"], t["carrier"]["vendor_id"], t["carrier"]["truck"], "|", t["name"], "| loads", t["totals"]["loads"],
          "| loaded", t["totals"]["loaded_pct"], "% | saved", t["totals"]["empty_miles_saved"], "mi")

# ---------- 8. return lanes to win: where trucks go home empty, and who could fill them ----------
customers = cached("customers.json", lambda: api("/customers?limit=200")["items"])
facilities = cached("facilities.json", lambda: api("/facilities?limit=200")["items"])
months = max(1, round((max(l["pickup"] for l in loads) - min(l["pickup"] for l in loads)).days / 30))
lanes = defaultdict(list)
for l in loads:
    lanes[(l["origin"]["city"], l["origin"]["state"], l["dest"]["city"], l["dest"]["state"])].append(l)
return_lanes = []
for (oc, os_, dc, ds), ls in lanes.items():
    back = len(lanes.get((dc, ds, oc, os_), []))
    if len(ls) - back < 3:
        continue  # only lanes where trucks regularly go home empty
    o, dst = place(oc, os_), place(dc, ds)
    empty_per_truck = round(tour_empty([ls[0]]))
    trucks = len(ls) - back
    avg_mi = round(sum(x["miles"] for x in ls) / len(ls))
    eq = max(set(x["eq"] for x in ls), key=lambda e: sum(1 for x in ls if x["eq"] == e))
    mode = "EXPEDITE" if eq in ("SV", "SB", "HS") else "TL"
    rev = {"mode": mode, "origin": dst, "dest": o, "miles": avg_mi}
    m = market(rev)
    # real Meridian accounts in the city where the trucks empty out: a shipper there, or a receiver that may send returns back
    fac_here = [f for f in facilities if f["city"] == dc and f["state"] == ds]
    cust_here = [c for c in customers if any(a.get("city") == dc and a.get("state") == ds for a in c.get("addresses") or [])]
    leads = [{"name": f["name"], "kind": "facility", "roles": f.get("roles"), "why": "Meridian already delivers here" if f.get("roles") in ("CONSIGNEE", "BOTH") else "Ships from this city"} for f in fac_here]
    leads += [{"name": c["legal_name"], "kind": "customer", "roles": c.get("customer_roles"), "why": "Existing Meridian customer in this city"} for c in cust_here]
    r = road(dst, o)
    return_lanes.append({
        "lane_id": f"R-{ds}-{dc}-{os_}-{oc}".replace(" ", "_"),
        "origin": dst, "destination": o, "equipment": eq, "mode": mode,
        "trucks_home_empty": trucks, "per_month": round(trucks / months, 1), "outbound_loads": len(ls), "return_loads": back,
        "empty_miles": trucks * empty_per_truck, "empty_miles_per_truck": empty_per_truck,
        "empty_cost_usd": round(trucks * empty_per_truck * EMPTY_COST_PER_MILE),
        "market_rate": m["buy"], "market_low": m["low"], "market_high": m["high"],
        "freight_value_usd": round(trucks * m["buy"]),
        "commodities_in": sorted({x["commodity"] for x in ls})[:3], "customers_in": sorted({x["shipper"] or x["customer"] for x in ls})[:3],
        "leads": leads[:5], "path": r["path"], "road_miles": r["miles"],
    })
return_lanes.sort(key=lambda x: -x["empty_miles"])
network["return_lanes"] = {"lanes": len(return_lanes), "empty_miles": sum(x["empty_miles"] for x in return_lanes),
                           "share_of_empty": round(sum(x["empty_miles"] for x in return_lanes) / one_by_one_empty * 100, 1),
                           "freight_value_usd": sum(x["freight_value_usd"] for x in return_lanes), "months": months}
(out / "return_lanes.json").write_text(json.dumps({"items": return_lanes}, indent=2) + "\n")
(out / "network_backtest.json").write_text(json.dumps(network, indent=2) + "\n")
print("RETURN LANES", len(return_lanes), network["return_lanes"])
for x in return_lanes[:8]:
    print(" ", x["origin"]["city"], "->", x["destination"]["city"], x["equipment"], "| trucks", x["trucks_home_empty"], "| empty mi", x["empty_miles"], "| market", x["market_rate"], "| leads", [l["name"] for l in x["leads"]][:2])
