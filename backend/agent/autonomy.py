"""Decision modes: approval (humans decide every write), auto (AI runs low-risk writes), invisible (AI runs all)."""

import json
from collections import Counter

from .. import db
from ..brain import compat, pricing
from ..errors import BadRequest

MODES = ("approval", "auto", "invisible")
DEFAULT_MODE = "approval"

# What auto mode may do without a human. Anything outside these limits waits for approval.
RISK = {
    "min_confidence": 0.80,
    "max_quote_sell": 2500.0,
    "risky_categories": {"HAZMAT"} | compat.FOOD_CATEGORIES,
}

# Limits on AI-executed actions per UTC day, in auto and invisible mode. Past them, actions wait.
DAILY_CAPS = {"max_actions": 20, "max_sell": 50000.0}

AI_EXECUTED = ("running", "done", "failed")

RISK_CHECKS = {}


def risk_check(kind):
    """Register fn(action) -> {"risks": [...], "blockers": [...]} as the risk rules for an action kind."""
    def decorator(fn):
        RISK_CHECKS[kind] = fn
        return fn
    return decorator


# ---------- mode ----------

def get_mode():
    """Return the current decision mode."""
    mode = db.get_setting("mode", DEFAULT_MODE)
    return mode if mode in MODES else DEFAULT_MODE


def set_mode(mode, actor="human"):
    """Switch the decision mode and return the new status."""
    if mode not in MODES:
        raise BadRequest(f"mode must be one of {', '.join(MODES)}.")
    previous = get_mode()
    db.set_setting("mode", mode)
    db.audit(actor, "mode_changed", f"{previous} -> {mode}")
    return status()


def quote_sell(payload):
    """Estimate a create_return_quote payload's sell total, or None without buy lines."""
    if not payload.get("buy_lines"):
        return None
    margin = payload.get("target_margin_pct") or pricing.DEFAULT_MARGIN_PCT
    return pricing.estimate(payload["buy_lines"], margin)["sell_total"]


def ai_usage_today():
    """Return {actions, sell} for actions the AI executed today (UTC)."""
    today = db.now_iso()[:10]
    placeholders = ", ".join("?" for _ in AI_EXECUTED)
    with db.get_conn() as conn:
        rows = conn.execute(
            f"SELECT result FROM actions WHERE decided_by = 'ai' AND status IN ({placeholders}) "
            "AND substr(updated_at, 1, 10) = ?",
            (*AI_EXECUTED, today),
        ).fetchall()
    sell = sum((json.loads(r["result"]) if r["result"] else {}).get("sell_total") or 0 for r in rows)
    return {"actions": len(rows), "sell": round(sell, 2)}


def status():
    """Return the mode, the rules that govern it and today's AI usage."""
    return {
        "mode": get_mode(),
        "modes": list(MODES),
        "risk_rules": {**RISK, "risky_categories": sorted(RISK["risky_categories"])},
        "daily_caps": DAILY_CAPS,
        "ai_today": ai_usage_today(),
    }


# ---------- risk rules per action kind ----------

def _customer_history(customer_id):
    customers = {c["customer_id"]: c for c in db.load_records("customers")}
    loads = Counter(s.get("customer_id") for s in db.load_records("shipments"))
    return customers.get(customer_id), loads[customer_id]


def _action_status(action_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT status FROM actions WHERE action_id = ?", (action_id,)).fetchone()
    return row["status"] if row else None


@risk_check("create_return_quote")
def quote_risk(action):
    """A quote is low risk when it is confident, small, for a known active customer and not hazmat/food."""
    payload, risks = action["payload"] or {}, []
    confidence = action.get("confidence")
    if confidence is None or confidence < RISK["min_confidence"]:
        risks.append(f"Confidence {confidence if confidence is not None else 'unknown'} is under "
                     f"{RISK['min_confidence']:.2f}")
    sell = quote_sell(payload)
    if sell is None or sell > RISK["max_quote_sell"]:
        risks.append(f"Quote sell {'unknown' if sell is None else f'${sell:,.2f}'} is over the "
                     f"${RISK['max_quote_sell']:,.0f} auto limit")
    customer, loads = _customer_history(payload.get("customer_id"))
    if not customer or customer.get("status") != "ACTIVE" or not loads:
        risks.append(f"Customer {payload.get('customer_id')} is not an active customer with past loads")
    if payload.get("category") in RISK["risky_categories"]:
        risks.append(f"{payload['category']} freight always needs a human")
    return {"risks": risks, "blockers": []}


@risk_check("send_reply")
def reply_risk(action):
    """A customer reply can go once the quote it prices is done (or it prices nothing)."""
    quote_action_id = (action["payload"] or {}).get("quote_action_id")
    if quote_action_id and _action_status(quote_action_id) != "done":
        return {"risks": [], "blockers": [f"Waits for quote action {quote_action_id} to be approved"]}
    return {"risks": [], "blockers": []}


@risk_check("confirm_carrier_rate")
def rate_confirmation_risk(action):
    """A carrier rate confirmation is low risk at or under the target pay maximum."""
    payload = action["payload"] or {}
    amount, target_max = payload.get("amount"), payload.get("target_pay_max")
    if amount is None or target_max is None:
        return {"risks": ["No target pay range on the confirmation"], "blockers": []}
    if amount > target_max:
        return {"risks": [f"Agreed ${amount:,.2f} is over the ${target_max:,.2f} target max"], "blockers": []}
    return {"risks": [], "blockers": []}


# ---------- deciding ----------

def assess(action):
    """Return {level, reasons, blockers} for an action from its kind's risk rules."""
    check = RISK_CHECKS.get(action["kind"])
    found = check(action) if check else {
        "risks": [f"No risk rules for {action['kind']}; a human decides"], "blockers": []}
    level = "low" if not (found["risks"] or found["blockers"]) else "high"
    return {"level": level, "reasons": found["risks"], "blockers": found["blockers"]}


def _cap_reason(action):
    usage = ai_usage_today()
    if usage["actions"] >= DAILY_CAPS["max_actions"]:
        return f"Daily cap reached: the AI already executed {usage['actions']} actions today"
    sell = quote_sell(action["payload"] or {}) if action["kind"] == "create_return_quote" else None
    if sell and usage["sell"] + sell > DAILY_CAPS["max_sell"]:
        return (f"Daily cap reached: ${usage['sell']:,.2f} quoted by the AI today, "
                f"plus ${sell:,.2f} is over ${DAILY_CAPS['max_sell']:,.0f}")
    return None


def decide(action):
    """Return (mode, risk, execute) for a newly proposed or still-pending action."""
    mode = get_mode()
    risk = assess(action)
    risk["cap"] = None
    if mode == "approval":
        return mode, risk, False
    if risk["blockers"] or (mode == "auto" and risk["reasons"]):
        return mode, risk, False
    risk["cap"] = _cap_reason(action)
    return mode, risk, risk["cap"] is None


def hold_message(mode, risk):
    """Explain in one sentence why an action waits for a human (empty in approval mode)."""
    if mode == "approval":
        return ""
    why = risk["blockers"] + (risk["reasons"] if mode == "auto" else []) + ([risk["cap"]] if risk["cap"] else [])
    return "; ".join(why)
