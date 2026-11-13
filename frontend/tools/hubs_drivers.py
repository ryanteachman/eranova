"""Supply hubs (manufacturer view) and driver days (driver app) from REAL Meridian shipments.

Reads the cache written by plan_loops.py (run that first). Writes:
  mocks/shipper_hubs.json  each shipper's plants as hubs, spokes to everywhere they ship, with this
                           week's loads and their status, spend and on-time history
  mocks/drivers.json       each driver on an open load: today's load with stops, windows and facility
                           rules, plus the rest of their week

Run:  python3 frontend/tools/hubs_drivers.py frontend/mocks
"""
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

out = Path(sys.argv[1])
cache = Path(__file__).parent / ".cache"
details = json.loads((cache / "details.json").read_text())
facilities = {f["facility_id"]: f for f in json.loads((cache / "facilities.json").read_text())}
customers = {c["customer_id"]: c for c in json.loads((cache / "customers.json").read_text())}
vendors = {v["vendor_id"]: v for v in json.loads((cache / "vendors.json").read_text())}
routes = json.loads((cache / "routes.json").read_text())
reports = json.loads((out / "reports.json").read_text())
WEEK = date.fromisoformat(reports["week"])  # latest full week in Meridian's data
WEEK_END = WEEK + timedelta(days=13)  # this week and next, so open loads show up

exec((Path(__file__).parent / "plan_loops.py").read_text().split("# ---------- 1. real data")[0].split("secret, out = ")[0])
COORDS = {}
src = (Path(__file__).parent / "plan_loops.py").read_text()
exec(src[src.index("COORDS = {"):src.index("def place(")])


def place(city, state):
    lat, lng = COORDS[f"{city},{state}"]
    return {"city": city, "state": state, "lat": lat, "lng": lng}


def road(a, b):
    key = f"{a['lng']:.3f},{a['lat']:.3f};{b['lng']:.3f},{b['lat']:.3f}"
    if key in routes:
        return routes[key]["path"]
    import time, urllib.request
    url = f"https://router.project-osrm.org/route/v1/driving/{key}?overview=full&geometries=geojson"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "return-trip-hackathon-demo"}), timeout=30))
    c = r["routes"][0]["geometry"]["coordinates"]
    step = max(1, len(c) // 220)
    pts = c[::step] + ([c[-1]] if c[-1] != c[::step][-1] else [])
    routes[key] = {"path": [[round(x, 4), round(y, 4)] for x, y in pts], "miles": round(r["routes"][0]["distance"] / 1609.34)}
    (cache / "routes.json").write_text(json.dumps(routes))
    time.sleep(1.1)
    return routes[key]["path"]


STATUS_GROUP = {"BOOKED": "booked", "COVERED": "booked", "DISPATCHED": "booked", "AT_PICKUP": "in_transit", "PICKED_UP": "in_transit",
                "IN_TRANSIT": "in_transit", "AT_DELIVERY": "in_transit", "DELIVERED": "delivered", "POD_RECEIVED": "delivered",
                "CLOSED": "delivered", "ON_HOLD": "on_hold"}

# ---------- supply hubs: plant -> everywhere it ships ----------
hubs = defaultdict(lambda: {"spokes": defaultdict(list)})
for s in details.values():
    if s["status"] in ("CANCELLED", "TONU"):
        continue
    first, last = s["stops"][0], s["stops"][-1]
    fid = first.get("facility_id")
    if not fid:
        continue
    h = hubs[(s["customer_id"], fid)]
    h["spokes"][(last.get("facility_id"), s["consignee_city"], s["consignee_state"])].append(s)

shipper_hubs = []
for (cid, fid), h in hubs.items():
    fac = facilities.get(fid, {})
    origin_city = fac.get("city") or next(iter(h["spokes"].values()))[0]["shipper_city"]
    origin_state = fac.get("state") or next(iter(h["spokes"].values()))[0]["shipper_state"]
    hub = place(origin_city, origin_state)
    spokes = []
    for (dfid, dcity, dstate), ls in h["spokes"].items():
        week = [s for s in ls if WEEK <= date.fromisoformat(s["pickup_date"]) <= WEEK_END]
        pods = [s.get("pod", {}).get("on_time") for s in ls if (s.get("pod") or {}).get("on_time") is not None]
        dest = place(dcity, dstate)
        status_now = None
        for g in ("in_transit", "booked", "on_hold", "delivered"):
            if any(STATUS_GROUP.get(s["status"]) == g for s in week):
                status_now = g
                break
        spokes.append({
            "facility_id": dfid, "name": facilities.get(dfid, {}).get("name") or f"{dcity}, {dstate}", "destination": dest,
            "loads_all": len(ls), "loads_week": len(week), "status": status_now or "none_this_week",
            "week_loads": [{"shipment_id": s["shipment_id"], "status": s["status"], "pickup": s["pickup_date"], "sell": s["sell_total"],
                            "carrier": vendors.get(s.get("carrier_id"), {}).get("legal_name") if s.get("carrier_id") else None,
                            "equipment": s.get("equipment_type")} for s in sorted(week, key=lambda x: x["pickup_date"])],
            "spend_all": round(sum(s["sell_total"] for s in ls)), "on_time_pct": round(sum(1 for p in pods if p) / len(pods) * 100) if pods else None,
            "miles": ls[0]["miles"], "path": road(hub, dest),
        })
    spokes.sort(key=lambda x: (-x["loads_week"], -x["loads_all"]))
    allloads = [s for sp in h["spokes"].values() for s in sp]
    weekloads = [w for sp in spokes for w in sp["week_loads"]]
    shipper_hubs.append({
        "hub_id": f"{cid}:{fid}", "customer_id": cid, "customer": customers.get(cid, {}).get("legal_name", cid),
        "facility_id": fid, "plant": fac.get("name") or f"{origin_city} plant", "facility_type": fac.get("facility_type"),
        "hub": hub, "spokes": spokes,
        "week": {"from": str(WEEK), "to": str(WEEK_END), "loads": len(weekloads), "spend": round(sum(w["sell"] for w in weekloads)),
                 "in_transit": sum(1 for w in weekloads if STATUS_GROUP.get(w["status"]) == "in_transit"),
                 "delivered": sum(1 for w in weekloads if STATUS_GROUP.get(w["status"]) == "delivered"),
                 "booked": sum(1 for w in weekloads if STATUS_GROUP.get(w["status"]) == "booked")},
        "all": {"loads": len(allloads), "spend": round(sum(s["sell_total"] for s in allloads)), "destinations": len(spokes)},
    })
shipper_hubs.sort(key=lambda x: (-x["week"]["loads"], -x["all"]["loads"]))
(out / "shipper_hubs.json").write_text(json.dumps({"week": {"from": str(WEEK), "to": str(WEEK_END)}, "items": shipper_hubs}, indent=2) + "\n")

# ---------- drivers: today's load and the rest of the week ----------
OPEN = ("COVERED", "DISPATCHED", "AT_PICKUP", "PICKED_UP", "IN_TRANSIT", "AT_DELIVERY")
FLAG_TEXT = {"TWIC_REQUIRED": "TWIC card required", "SEAL_REQUIRED": "Seal required", "PPE_REQUIRED": "PPE required (vest, hard hat)",
             "NO_EARLY_ARRIVAL": "No early arrivals", "CHECK_IN_WINDOW": "Check in at the guard shack"}


def stop_json(st):
    fac = facilities.get(st.get("facility_id"), {})
    snap = st.get("address_snapshot") or {}
    rules = [FLAG_TEXT.get(f, f.replace("_", " ").lower()) for f in fac.get("compliance_flags") or []]
    if fac.get("appointment_required"): rules.append("Appointment required")
    if fac.get("lumper_policy"): rules.append(f"Lumper: {str(fac['lumper_policy']).replace('_', ' ').lower()}")
    if fac.get("pallet_exchange"): rules.append(f"Pallet exchange: {str(fac['pallet_exchange']).replace('_', ' ').lower()}")
    win = st.get("scheduled_window") or {}
    return {"type": st.get("stop_type"), "name": snap.get("name") or fac.get("name"), "address": snap.get("address1"),
            "city": snap.get("city"), "state": snap.get("state"), "window": [win.get("earliest_local"), win.get("latest_local")],
            "timezone": win.get("timezone"), "appointment": (st.get("appointment") or {}).get("status"),
            "confirmation": (st.get("appointment") or {}).get("confirmation_number"), "instructions": st.get("instructions"),
            "rules": rules, "arrived": st.get("actual_arrival"), "departed": st.get("actual_departure")}


by_driver = defaultdict(list)
for s in details.values():
    if s.get("driver_name") and s.get("carrier_id"):
        by_driver[(s["carrier_id"], s.get("truck_number"), s["driver_name"])].append(s)
drivers = []
for (cid, truck, name), ls in by_driver.items():
    ls.sort(key=lambda x: x["pickup_date"])
    current = next((s for s in ls if s["status"] in OPEN), None)
    if not current:
        continue
    nxt = [s for s in ls if s["pickup_date"] > current["pickup_date"] and s["status"] not in ("CLOSED", "CANCELLED", "TONU")]
    o, dst = place(current["shipper_city"], current["shipper_state"]), place(current["consignee_city"], current["consignee_state"])
    drivers.append({
        "driver_id": f"{cid}:{truck}:{name}", "name": name, "carrier": vendors.get(cid, {}).get("legal_name", cid), "carrier_id": cid,
        "truck": truck, "trailer": current.get("trailer_number"), "equipment": current.get("equipment_type"),
        "load": {"shipment_id": current["shipment_id"], "status": current["status"], "pro": current.get("pro_number"),
                 "rate_con": current.get("rate_con_number"), "miles": current["miles"], "commodity": ((current.get("freight_lines") or [{}])[0].get("description")),
                 "pieces": (current.get("freight_totals") or {}).get("pieces"), "weight_lb": (current.get("freight_totals") or {}).get("actual_weight_lb"),
                 "pay": current.get("buy_total"), "special_instructions": current.get("special_instructions"),
                 "origin": o, "destination": dst, "path": road(o, dst), "stops": [stop_json(st) for st in current["stops"]]},
        "next_loads": [{"shipment_id": s["shipment_id"], "pickup": s["pickup_date"], "from": f"{s['shipper_city']}, {s['shipper_state']}",
                        "to": f"{s['consignee_city']}, {s['consignee_state']}", "miles": s["miles"], "pay": s.get("buy_total")} for s in nxt[:3]],
    })
STATUS_ORDER = {"IN_TRANSIT": 0, "AT_DELIVERY": 1, "AT_PICKUP": 2, "PICKED_UP": 3, "DISPATCHED": 4, "COVERED": 5}
drivers.sort(key=lambda d: (STATUS_ORDER.get(d["load"]["status"], 9), d["name"]))
(out / "drivers.json").write_text(json.dumps({"items": drivers}, indent=2) + "\n")

print("hubs:", len(shipper_hubs), "| top:", [(h["customer"], h["plant"], h["week"]["loads"], len(h["spokes"])) for h in shipper_hubs[:5]])
print("drivers:", len(drivers), "| e.g.", [(d["name"], d["carrier_id"], d["truck"], d["load"]["status"], d["load"]["origin"]["city"] + "->" + d["load"]["destination"]["city"]) for d in drivers[:5]])
