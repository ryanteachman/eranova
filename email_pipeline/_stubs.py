"""Temporary stand-ins for Ryan's backend interfaces, with the same signatures.

deps.py imports Ryan's real function when it exists and falls back to the one here, so
switching over at integration needs no code change. Nothing here writes to Meridian:
`get` is a real read-only call, `post` refuses, and `approve` fakes a quote result.
"""

import json
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("DB_PATH", str(ROOT / "return_trip.db"))
TMS_API_BASE = os.getenv("TMS_API_BASE", "").rstrip("/")
TMS_API_KEY = os.getenv("TMS_API_KEY", "")

TOOLS = {}


def now_iso():
    """Current UTC time as an ISO-8601 string with a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- backend.db ----------

def get_conn():
    """Open the shared SQLite database (rows come back as sqlite3.Row) and make sure Ryan's tables exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS actions (
            action_id TEXT PRIMARY KEY, kind TEXT, title TEXT, summary TEXT, payload TEXT,
            tier TEXT, confidence REAL, reasoning TEXT, status TEXT, result TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, actor TEXT, event TEXT, detail TEXT
        );
        """
    )
    return conn


# ---------- backend.meridian ----------

class MeridianError(Exception):
    """A Meridian API error with its status code and the server's detail sentence."""

    def __init__(self, status, error, detail):
        super().__init__(f"{status} {error}: {detail}")
        self.status, self.error, self.detail = status, error, detail


def get(path, **params):
    """GET a Meridian route and return the JSON body; raises MeridianError on a non-2xx answer."""
    resp = requests.get(
        TMS_API_BASE + path, headers={"x-api-key": TMS_API_KEY}, params=params, timeout=20
    )
    if not resp.ok:
        body = resp.json() if resp.content else {}
        raise MeridianError(resp.status_code, body.get("error", ""), body.get("detail", resp.text))
    return resp.json()


def post(path, body):
    """Refuse: the email pipeline never writes to Meridian; writes go through approved actions."""
    raise RuntimeError(f"email_pipeline must not POST to Meridian ({path}); propose an action instead")


# ---------- backend.agent.registry ----------

def tool(name, description, schema, tier="auto"):
    """Register a function as an agent tool in TOOLS and return it unchanged."""

    def register(func):
        TOOLS[name] = {"func": func, "description": description, "schema": schema, "tier": tier}
        return func

    return register


# ---------- backend.agent.actions ----------

def propose(kind, title, summary, payload, confidence, reasoning):
    """Insert a pending action into the approval queue and return its action_id."""
    action_id = "act_" + uuid.uuid4().hex[:10]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO actions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (action_id, kind, title, summary, json.dumps(payload), "approve", confidence,
             reasoning, "pending", None, now_iso(), now_iso()),
        )
    return action_id


def approve(action_id):
    """Stub approval: fakes a create_return_quote result, runs send_reply for real (our tables only)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
    if row is None:
        raise KeyError(action_id)
    payload = json.loads(row["payload"])
    if row["kind"] == "send_reply":
        from email_pipeline.reply import execute_send_reply
        result = execute_send_reply(payload)
    elif row["kind"] == "create_return_quote":
        result = {
            "quote_id": "STUB-" + action_id[-4:],
            "summary": "Stub quote (Ryan's executor not wired yet - nothing created in Meridian)",
            "sell_total": 1850.00,
            "meridian_url": None,
        }
    else:
        result = {"note": f"stub approve: no executor for {row['kind']}"}
    with get_conn() as conn:
        conn.execute(
            "UPDATE actions SET status = 'done', result = ?, updated_at = ? WHERE action_id = ?",
            (json.dumps(result), now_iso(), action_id),
        )
    return result


# ---------- backend.agent.loop ----------

def run_agent(trigger, message, context=None):
    """Stub agent loop: returns an empty answer until Ryan's loop lands."""
    return {"reply": "(agent loop not available yet)", "tool_calls": [], "actions_created": []}


# ---------- backend.brain ----------

ACTIVE_STATUSES = "BOOKED,COVERED,DISPATCHED,AT_PICKUP,PICKED_UP,IN_TRANSIT,AT_DELIVERY,DELIVERED"

# Keyword rules standing in for Ryan's LLM freight classifier.
CATEGORY_KEYWORDS = [
    ("WASTE", r"waste|salvage|refuse"),
    ("CHEMICAL", r"chemical|cleaning compound|cleaner|solvent|caustic|corrosive|acid"),
    ("FOOD", r"food|grocery|dairy|seafood|frozen|produce|meat|yogurt|cheese"),
    ("BEVERAGE", r"beverage|juice|soda|water|beer"),
    ("STEEL", r"steel|bracket|metal"),
    ("WOOD", r"lumber|wood"),
    ("PACKAGING", r"carton|packaging|pallets?, empty|totes|dunnage"),
    ("RETAIL_RETURNS", r"return|display|shelving"),
]

# What each customer could plausibly send back on the return leg (the "reverse-logistics patterns").
REVERSE_PATTERNS = {
    "NORTHSTAR": ("RETAIL_RETURNS", "Store returns and POS displays back to the Chicago dock", 14000, 16),
    "FROSTLINE": ("PACKAGING", "Empty CHEP pallets and reusable totes", 9000, 20),
    "VALIANTFD": ("FOOD", "Short-dated dairy returns", 18000, 14),
    "MIDWAYDST": ("FOOD", "Grocery overstock back to KC", 22000, 18),
    "BLUEHARBOR": ("PACKAGING", "Empty insulated fish totes", 6000, 12),
    "IRONPEAK": ("PACKAGING", "Returnable steel racks and dunnage", 12000, 10),
    "LONESTARCH": ("CHEMICAL", "Empty returnable drums", 4000, 20),
}


def guess_category(text, hazmat=False):
    """Map a freight description to one of Ryan's categories with keyword rules."""
    if hazmat:
        return "HAZMAT"
    for category, pattern in CATEGORY_KEYWORDS:
        if re.search(pattern, text or "", re.I):
            return category
    return "GENERAL"


@lru_cache(maxsize=1)
def _active_shipments():
    """All non-closed shipments, fetched once per process."""
    items, cursor = [], None
    while True:
        params = {"status": ACTIVE_STATUSES, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        page = get("/shipments", **params)
        items += page["items"]
        cursor = page.get("next_cursor")
        if not cursor:
            return items


@lru_cache(maxsize=64)
def _vendor(vendor_id):
    """One carrier record, cached."""
    return get(f"/vendors/{vendor_id}")


def find_backhauls(city, state):
    """Stub backhaul finder: for each truck arriving in city, a return-lane prospect for the same customer."""
    prospects = []
    for s in _active_shipments():
        if s["consignee_city"].lower() != city.lower() or s["consignee_state"].upper() != state.upper():
            continue
        if s.get("mode") != "TL":
            continue
        lines = s.get("freight_lines", [])
        last_category = guess_category(
            " ".join(l.get("description", "") for l in lines), any(l.get("hazmat") for l in lines)
        )
        category, description, weight_lb, pallets = REVERSE_PATTERNS.get(
            s["customer_id"], ("GENERAL", "General freight", 15000, 14)
        )
        candidate = {
            "category": category, "description": description, "weight_lb": weight_lb,
            "pallets": pallets, "temp_controlled": category == "FOOD" and s["equipment_type"] == "R",
            "hazmat": False, "trailer_number": s.get("trailer_number"),
        }
        carrier = _vendor(s["carrier_id"]) if s.get("carrier_id") else None
        ok, reasons = check_compat(last_category, s["equipment_type"], candidate, carrier)
        prospects.append({
            "prospect_id": f"stub-{s['shipment_id']}",
            "customer_id": s["customer_id"],
            "customer_name": s.get("shipper_name"),
            "origin": {"city": s["consignee_city"], "state": s["consignee_state"]},
            "destination": {"city": s["shipper_city"], "state": s["shipper_state"]},
            "equipment": s["equipment_type"],
            "category": category,
            "description": description,
            "score": 70 if ok else 0,
            "est_buy": None, "est_sell": None, "gp_pct": None,
            "miles": s.get("miles"),
            "outbound_file": s["shipment_id"],
            "carrier_id": s.get("carrier_id"),
            "trailer_number": s.get("trailer_number"),
            "trailer_last_category": last_category,
            "available_date": s.get("delivery_date_target"),
            "ok": ok,
            "reasons": reasons,
        })
    return prospects


def _washout_on_file(carrier_id, trailer_number):
    """True when the washouts table has a certificate for this trailer."""
    if not trailer_number:
        return False
    with get_conn() as conn:
        try:
            row = conn.execute(
                "SELECT 1 FROM washouts WHERE trailer_number = ? AND (carrier_id = ? OR carrier_id IS NULL)",
                (str(trailer_number), carrier_id),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    return row is not None


def check_compat(trailer_last_category, equipment, candidate, carrier):
    """Stub of Ryan's deterministic rules; returns (ok, reasons) with human-readable reasons.

    The trailer being checked travels in candidate["trailer_number"] (used for the washout lookup).
    """
    trailer_number = candidate.get("trailer_number")
    reasons, ok = [], True
    category = candidate.get("category") or "GENERAL"
    food = category in ("FOOD", "BEVERAGE")

    if candidate.get("temp_controlled") and equipment != "R":
        ok = False
        reasons.append(f"Blocked: freight is temperature-controlled but the truck is equipment {equipment}, not a reefer.")
    elif equipment in ("F", "SD") and category not in ("STEEL", "WOOD", "MACHINERY", "SCRAP"):
        ok = False
        reasons.append(f"Blocked: {equipment} is open-deck equipment; {category} freight needs an enclosed trailer.")
    else:
        reasons.append(f"Equipment {equipment} can carry {category} freight.")

    if trailer_last_category in ("CHEMICAL", "HAZMAT", "WASTE") and food:
        if _washout_on_file(carrier and carrier.get("vendor_id"), trailer_number):
            reasons.append(f"FSMA: trailer last hauled {trailer_last_category}, washout certificate on file.")
        else:
            ok = False
            reasons.append(
                f"Blocked: trailer last hauled {trailer_last_category}; FSMA requires a washout before food."
            )

    if candidate.get("hazmat") and not (carrier or {}).get("hazmat_certified"):
        ok = False
        reasons.append("Blocked: hazmat freight needs a hazmat-certified carrier.")

    if equipment == "V" and ((candidate.get("weight_lb") or 0) > 45000 or (candidate.get("pallets") or 0) > 26):
        ok = False
        reasons.append("Blocked: over a dry van's 45,000 lb / 26 pallet limit.")

    if carrier:
        today = date.today().isoformat()
        cargo_ok = any(
            p.get("policy_type") == "CARGO" and (p.get("expiration_date") or "") >= today
            for p in carrier.get("insurance", [])
        )
        if carrier.get("status") != "ACTIVE" or not cargo_ok:
            ok = False
            reasons.append(f"Blocked: carrier {carrier.get('vendor_id')} is not ACTIVE with a current CARGO policy.")
    return ok, reasons
