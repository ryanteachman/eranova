"""What the brain learns from Meridian's own history, and the weekly reports built on it.

Everything here is measured from real Meridian records (run plan_loops.py first so the cache exists):
  - expected vs actual delivery: stop actual_arrival vs the scheduled window (local time zones)
  - dock waits (dwell): actual_departure - actual_arrival at each stop; over 2 h counts as detention
  - lead times: days from booking (created_at) to pickup, per manufacturer
  - transit speed and the quickest carrier per lane: pickup departure -> delivery arrival
  - on-time: the POD's on_time flag and Meridian's service_failure flag
Re-running it after new loads close is the "learning": every number and every rule it feeds back
(timing buffers, carrier ranking, lead-time hints) updates from the new history.

Run:  python3 frontend/tools/learn.py frontend/mocks
"""
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

out = Path(sys.argv[1])
cache = Path(__file__).parent / ".cache"
details = json.loads((cache / "details.json").read_text())
vendors = {v["vendor_id"]: v for v in json.loads((cache / "vendors.json").read_text())}
backtest = json.loads((out / "network_backtest.json").read_text())
DETENTION_FREE_H = 2  # Meridian's DET charge code: detention after 2 hours free


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def local(s, tz):
    return datetime.fromisoformat(s).replace(tzinfo=ZoneInfo(tz)) if s and tz else None


def hours(a, b):
    return (b - a).total_seconds() / 3600 if a and b else None


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(st.mean(xs), 1) if xs else None


def pct(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(1 for x in xs if x) / len(xs) * 100) if xs else None


rows = []
for s in details.values():
    if s["status"] in ("CANCELLED", "TONU"):
        continue
    first, last = s["stops"][0], s["stops"][-1]
    win = last.get("scheduled_window") or {}
    due = local(win.get("latest_local"), win.get("timezone"))
    arrived = utc(last.get("actual_arrival"))
    late_h = hours(due, arrived) if due and arrived else None
    pu_dwell = hours(utc(first.get("actual_arrival")), utc(first.get("actual_departure")))
    del_dwell = hours(arrived, utc(last.get("actual_departure")))
    transit_h = hours(utc(first.get("actual_departure")), arrived)
    pod = s.get("pod") or {}
    on_time = pod.get("on_time") if pod.get("on_time") is not None else (None if late_h is None else late_h <= 0)
    rows.append({
        "id": s["shipment_id"], "status": s["status"], "mode": s["mode"], "eq": s.get("equipment_type"),
        "carrier": s.get("carrier_id"), "customer": s["customer_id"], "shipper": s.get("shipper_name") or s["customer_id"],
        "lane": f"{s['shipper_city']}, {s['shipper_state']} → {s['consignee_city']}, {s['consignee_state']}",
        "pickup": date.fromisoformat(s["pickup_date"]), "booked": utc(s["created_at"]).date(),
        "miles": s["miles"], "sell": s["sell_total"] or 0, "buy": s["buy_total"] or 0,
        "on_time": on_time, "late_h": late_h, "service_failure": s.get("service_failure"),
        "pu_dwell": pu_dwell, "del_dwell": del_dwell, "transit_h": transit_h,
        "mph": round(s["miles"] / transit_h, 1) if transit_h and transit_h > 0 else None,
        "pu_fac": first.get("facility_id"), "del_fac": last.get("facility_id"),
        "pu_name": (first.get("address_snapshot") or {}).get("name"), "del_name": (last.get("address_snapshot") or {}).get("name"),
        "lead_days": (date.fromisoformat(s["pickup_date"]) - utc(s["created_at"]).date()).days,
    })


def group(key):
    g = defaultdict(list)
    for r in rows:
        if r[key]:
            g[r[key]].append(r)
    return g


# ---------- what the brain learned ----------
carriers = []
for cid, rs in group("carrier").items():
    carriers.append({"carrier_id": cid, "name": vendors.get(cid, {}).get("legal_name", cid), "loads": len(rs),
                     "on_time_pct": pct(r["on_time"] for r in rs), "avg_late_h": avg(r["late_h"] for r in rs if r["late_h"] and r["late_h"] > 0),
                     "avg_mph": avg(r["mph"] for r in rs), "revenue_paid": round(sum(r["buy"] for r in rs))})
carriers.sort(key=lambda c: (-(c["on_time_pct"] or 0), -c["loads"]))

facilities = []
fac = defaultdict(list)
for r in rows:
    if r["pu_dwell"] is not None: fac[(r["pu_fac"], r["pu_name"])].append(r["pu_dwell"])
    if r["del_dwell"] is not None: fac[(r["del_fac"], r["del_name"])].append(r["del_dwell"])
for (fid, name), ds in fac.items():
    if len(ds) < 3:
        continue
    facilities.append({"facility_id": fid, "name": name, "visits": len(ds), "avg_dwell_h": round(st.mean(ds), 1),
                       "detention_pct": round(sum(1 for x in ds if x > DETENTION_FREE_H) / len(ds) * 100),
                       "detention_hours": round(sum(max(0, x - DETENTION_FREE_H) for x in ds), 1)})
facilities.sort(key=lambda f: -f["avg_dwell_h"])

shippers = []
for cid, rs in group("customer").items():
    shippers.append({"customer_id": cid, "name": rs[0]["shipper"], "loads": len(rs), "spend": round(sum(r["sell"] for r in rs)),
                     "avg_lead_days": avg(r["lead_days"] for r in rs), "on_time_pct": pct(r["on_time"] for r in rs),
                     "avg_late_h": avg(r["late_h"] for r in rs if r["late_h"] and r["late_h"] > 0)})
shippers.sort(key=lambda s: -s["loads"])

lanes = []
for lane, rs in group("lane").items():
    timed = [r for r in rs if r["transit_h"]]
    by_c = defaultdict(list)
    for r in timed:
        if r["carrier"]: by_c[r["carrier"]].append(r["transit_h"])
    fastest = min(by_c.items(), key=lambda kv: st.mean(kv[1])) if by_c else None
    lanes.append({"lane": lane, "loads": len(rs), "avg_transit_h": avg(r["transit_h"] for r in timed),
                  "on_time_pct": pct(r["on_time"] for r in rs),
                  "fastest_carrier": vendors.get(fastest[0], {}).get("legal_name", fastest[0]) if fastest else None,
                  "fastest_h": round(st.mean(fastest[1]), 1) if fastest else None, "carriers": len(by_c)})
lanes.sort(key=lambda l: -l["loads"])

# rules the brain applies from what it learned (each one cites its evidence)
rules = []
slow_docks = [f for f in facilities if f["avg_dwell_h"] > DETENTION_FREE_H]
for f in slow_docks[:3]:
    rules.append({"area": "timing", "text": f"Add {round(f['avg_dwell_h'])} h at {f['name']} before chaining the next pickup",
                  "evidence": f"Average wait {f['avg_dwell_h']} h over {f['visits']} visits; {f['detention_pct']}% ran into detention"})
for l in [l for l in lanes if l["carriers"] > 1 and l["fastest_carrier"]][:3]:
    rules.append({"area": "carrier", "text": f"Offer {l['lane']} to {l['fastest_carrier']} first",
                  "evidence": f"Fastest on this lane: {l['fastest_h']} h door to door vs {l['avg_transit_h']} h average over {l['loads']} loads"})
weak = [c for c in carriers if c["on_time_pct"] is not None and c["on_time_pct"] < 85 and c["loads"] >= 4]
for c in weak[:2]:
    rules.append({"area": "carrier", "text": f"Rank {c['name']} lower on time-critical loops",
                  "evidence": f"On time {c['on_time_pct']}% over {c['loads']} loads"})
for s in [s for s in shippers if s["avg_lead_days"] is not None][:3]:
    rules.append({"area": "lead_time", "text": f"Expect {s['name']} loads about {round(s['avg_lead_days'])} days before pickup",
                  "evidence": f"Average booking lead time over {s['loads']} loads"})

all_late = [r["late_h"] for r in rows if r["late_h"] is not None]
learned = {
    "loads_learned_from": len([r for r in rows if r["on_time"] is not None or r["transit_h"]]),
    "headline": {
        "on_time_pct": pct(r["on_time"] for r in rows),
        "avg_late_h_when_late": avg(x for x in all_late if x > 0),
        "avg_dwell_h": avg([r["pu_dwell"] for r in rows] + [r["del_dwell"] for r in rows]),
        "detention_hours": round(sum(f["detention_hours"] for f in facilities), 1),
        "avg_lead_days": avg(r["lead_days"] for r in rows),
    },
    "carriers": carriers, "facilities": facilities[:10], "shippers": shippers, "lanes": lanes[:12], "rules": rules,
}
(out / "learned.json").write_text(json.dumps(learned, indent=2) + "\n")

# ---------- weekly history (Monday-start weeks) ----------
def week_of(d):
    return d - timedelta(days=d.weekday())


weeks = defaultdict(list)
for r in rows:
    weeks[week_of(r["pickup"])].append(r)
series = []
for wk in sorted(weeks):
    rs = weeks[wk]
    tl = [r for r in rs if r["mode"] in ("TL", "EXPEDITE")]
    series.append({"week": str(wk), "loads": len(rs), "revenue": round(sum(r["sell"] for r in rs)), "carrier_cost": round(sum(r["buy"] for r in rs)),
                   "margin": round(sum(r["sell"] - r["buy"] for r in rs)), "on_time_pct": pct(r["on_time"] for r in rs),
                   "empty_miles": round(sum(r["miles"] for r in tl))})  # one-way network: each truckload drives its distance home empty


def summary(rs):
    return {"loads": len(rs), "revenue": round(sum(r["sell"] for r in rs)), "carrier_cost": round(sum(r["buy"] for r in rs)),
            "margin": round(sum(r["sell"] - r["buy"] for r in rs)), "on_time_pct": pct(r["on_time"] for r in rs),
            "late_loads": sum(1 for r in rs if r["on_time"] is False),
            "avg_dwell_h": avg([r["pu_dwell"] for r in rs] + [r["del_dwell"] for r in rs]),
            "detention_hours": round(sum(max(0, (x or 0) - DETENTION_FREE_H) for r in rs for x in (r["pu_dwell"], r["del_dwell"])), 1),
            "miles": sum(r["miles"] for r in rs)}


# the latest full week with delivered loads, and the one before it
done_weeks = [w for w in sorted(weeks) if any(r["on_time"] is not None for r in weeks[w])]
this_wk, prev_wk = done_weeks[-1], done_weeks[-2]
reports = {
    "week": str(this_wk), "week_end": str(this_wk + timedelta(days=6)), "previous_week": str(prev_wk), "series": series,
    "broker": {"this": summary(weeks[this_wk]), "prev": summary(weeks[prev_wk]), "all": summary(rows),
               "network": backtest, "top_return_lanes": None},
    "carriers": {c: {"name": vendors.get(c, {}).get("legal_name", c), "this": summary([r for r in weeks[this_wk] if r["carrier"] == c]),
                     "all": summary([r for r in rows if r["carrier"] == c])} for c in group("carrier")},
    "shippers": {c: {"name": rs[0]["shipper"], "this": summary([r for r in weeks[this_wk] if r["customer"] == c]),
                     "all": summary(rs), "avg_lead_days": avg(r["lead_days"] for r in rs)} for c, rs in group("customer").items()},
}
(out / "reports.json").write_text(json.dumps(reports, indent=2) + "\n")

print("learned from", learned["loads_learned_from"], "loads:", learned["headline"])
print("rules:", len(rules))
for r in rules: print(" -", r["text"], "|", r["evidence"])
print("report week", reports["week"], "this:", reports["broker"]["this"], "\nprev:", reports["broker"]["prev"])
