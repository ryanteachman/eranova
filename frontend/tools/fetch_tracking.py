"""Where is my order: pull the tracking log of every open Meridian load (read-only).

For each open shipment it calls GET /shipments/{id}/events once and caches the result, then
looks up the coordinates of every city a driver reported from (OpenStreetMap Nominatim, cached).
hubs_drivers.py turns this into the manufacturer's "where are my loads" list.

Run:  python3 frontend/tools/fetch_tracking.py secret.txt
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

cache = Path(__file__).parent / ".cache"
txt = open(sys.argv[1], encoding="utf-8").read().replace("\r", "")
BASE = re.search(r"Base URL:\s*(\S+)", txt).group(1)
KEY = re.search(r"API key:\s*(\S+)", txt).group(1)
OPEN = {"BOOKED", "COVERED", "DISPATCHED", "AT_PICKUP", "PICKED_UP", "IN_TRANSIT", "AT_DELIVERY", "ON_HOLD", "DELIVERED"}

details = json.loads((cache / "details.json").read_text())
events_file = cache / "events.json"
events = json.loads(events_file.read_text()) if events_file.exists() else {}

for s in details.values():
    sid = s["shipment_id"]
    if s["status"] not in OPEN or sid in events:
        continue
    req = urllib.request.Request(f"{BASE}/shipments/{sid}/events?limit=50", headers={"x-api-key": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        events[sid] = json.load(r)["items"]
    events_file.write_text(json.dumps(events))
    time.sleep(0.5)  # gentle on the shared Meridian API
print("tracking logs:", len(events))

# coordinates for every reported city
geo_file = cache / "geo.json"
geo = json.loads(geo_file.read_text()) if geo_file.exists() else {}
cities = {(e["city"], e["state"]) for es in events.values() for e in es if e.get("city") and e.get("state")}
for city, state in sorted(cities):
    k = f"{city},{state}"
    if k in geo:
        continue
    q = urllib.parse.urlencode({"city": city, "state": state, "country": "USA", "format": "json", "limit": 1})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?{q}", headers={"User-Agent": "return-trip-hackathon-demo"})
    with urllib.request.urlopen(req, timeout=30) as r:
        hit = json.load(r)
    geo[k] = [round(float(hit[0]["lat"]), 4), round(float(hit[0]["lon"]), 4)] if hit else None
    geo_file.write_text(json.dumps(geo))
    time.sleep(1.1)  # Nominatim asks for at most one request a second
print("places:", len(geo), "missing:", [k for k, v in geo.items() if v is None])
