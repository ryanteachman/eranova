"""Tests for the decision modes: approval, auto and invisible."""

import pytest

from backend import db
from backend.agent import actions, autonomy, loop
from backend.brain import network


def set_mode(mode):
    autonomy.set_mode(mode)


def fill(client, index=0):
    prospect_id = network.find_backhauls("Dallas", "TX")[index]["prospect_id"]
    return client.post("/api/fill", json={"prospect_id": prospect_id}).get_json()


def audit_events():
    with db.get_conn() as conn:
        return [row["event"] for row in conn.execute("SELECT event FROM audit_log ORDER BY id")]


# ---------- what each mode does ----------

def test_approval_is_the_default_and_leaves_actions_pending(client):
    assert autonomy.get_mode() == "approval"
    filled = fill(client)
    assert (filled["status"], filled["mode"], filled["decided_by"]) == ("pending", "approval", None)
    # Risk is still assessed, so the UI can show what auto mode would do.
    assert filled["risk"]["level"] == "low"


def test_invisible_executes_immediately_as_the_ai(client, fake_meridian):
    set_mode("invisible")
    filled = fill(client)
    assert (filled["status"], filled["decided_by"]) == ("done", "ai")
    assert filled["result"]["quote_id"] == "7300901"
    assert [c[1] for c in fake_meridian.calls if c[0] in ("POST", "PUT")][-3:] == [
        "/quotes", "/quotes/7300901/price", "/quotes/7300901"]
    assert "action_auto_approved" in audit_events()


def test_auto_executes_a_low_risk_quote(client):
    set_mode("auto")
    filled = fill(client)
    assert (filled["status"], filled["decided_by"], filled["risk"]["level"]) == ("done", "ai", "low")


def test_auto_holds_a_risky_quote_for_a_human(client, monkeypatch):
    monkeypatch.setitem(autonomy.RISK, "max_quote_sell", 1000.0)
    set_mode("auto")
    filled = fill(client)
    assert filled["status"] == "pending" and filled["risk"]["level"] == "high"
    assert "over the $1,000 auto limit" in filled["risk"]["reasons"][0]
    assert "action_held" in audit_events()

    approved = client.post(f"/api/actions/{filled['action_id']}/approve").get_json()
    assert (approved["status"], approved["decided_by"]) == ("done", "human")


def test_invisible_ignores_risk_rules(client, monkeypatch):
    monkeypatch.setitem(autonomy.RISK, "max_quote_sell", 1000.0)
    set_mode("invisible")
    filled = fill(client)
    assert filled["status"] == "done" and filled["risk"]["level"] == "high"


def test_refilling_a_pending_action_redecides_it_under_the_new_mode(client):
    first = fill(client)
    assert first["status"] == "pending"
    set_mode("invisible")
    again = fill(client)
    assert again["action_id"] == first["action_id"]
    assert (again["status"], again["decided_by"]) == ("done", "ai")


def test_reject_records_the_human(client):
    filled = fill(client)
    rejected = client.post(f"/api/actions/{filled['action_id']}/reject", json={"reason": "no"}).get_json()
    assert (rejected["status"], rejected["decided_by"]) == ("rejected", "human")


# ---------- risk rules ----------

def quote_action(**overrides):
    payload = {"customer_id": "NORTHSTAR", "category": "SCRAP", "target_margin_pct": 10,
               "buy_lines": [{"charge_code": "FRT", "amount": 1000.0}, {"charge_code": "FSC", "amount": 400.0}]}
    payload.update(overrides.pop("payload", {}))
    return {"kind": "create_return_quote", "confidence": 0.9, "payload": payload, **overrides}


def test_quote_risk_rules(dallas):
    assert autonomy.assess(quote_action()) == {"level": "low", "reasons": [], "blockers": []}
    cases = {
        "Confidence 0.5 is under 0.80": quote_action(confidence=0.5),
        "Confidence unknown is under 0.80": quote_action(confidence=None),
        "is over the $2,500 auto limit": quote_action(payload={"buy_lines": [{"charge_code": "FRT", "amount": 5000}]}),
        "Customer TRUENORTH is not an active customer with past loads": quote_action(payload={"customer_id": "TRUENORTH"}),
        "Customer NOBODY is not an active customer": quote_action(payload={"customer_id": "NOBODY"}),
        "HAZMAT freight always needs a human": quote_action(payload={"category": "HAZMAT"}),
        "FOOD freight always needs a human": quote_action(payload={"category": "FOOD"}),
        "BEVERAGE freight always needs a human": quote_action(payload={"category": "BEVERAGE"}),
    }
    for expected, action in cases.items():
        risk = autonomy.assess(action)
        assert risk["level"] == "high" and any(expected in r for r in risk["reasons"]), expected


def test_rate_confirmation_risk_rules():
    def confirmation(**payload):
        return {"kind": "confirm_carrier_rate", "payload": payload}
    assert autonomy.assess(confirmation(amount=900, target_pay_max=1000))["level"] == "low"
    assert autonomy.assess(confirmation(amount=1000, target_pay_max=1000))["level"] == "low"
    over = autonomy.assess(confirmation(amount=1100, target_pay_max=1000))
    assert "over the $1,000.00 target max" in over["reasons"][0]
    assert autonomy.assess(confirmation(amount=900))["reasons"] == ["No target pay range on the confirmation"]


def test_unknown_kinds_are_high_risk():
    risk = autonomy.assess({"kind": "wire_money", "payload": {}})
    assert risk["level"] == "high" and "No risk rules for wire_money" in risk["reasons"][0]


# ---------- daily caps ----------

def test_daily_action_cap_falls_back_to_a_human(client, monkeypatch):
    monkeypatch.setitem(autonomy.DAILY_CAPS, "max_actions", 1)
    set_mode("invisible")
    assert fill(client, 0)["status"] == "done"
    second = fill(client, 1)
    assert second["status"] == "pending"
    assert second["risk"]["cap"].startswith("Daily cap reached: the AI already executed 1 actions today")
    assert autonomy.status()["ai_today"] == {"actions": 1, "sell": 1234.5}


def test_daily_sell_cap(client, monkeypatch):
    monkeypatch.setitem(autonomy.DAILY_CAPS, "max_sell", 1000.0)
    set_mode("invisible")
    filled = fill(client)
    assert filled["status"] == "pending" and "over $1,000" in filled["risk"]["cap"]


def test_human_approvals_do_not_count_against_the_cap(client, monkeypatch):
    monkeypatch.setitem(autonomy.DAILY_CAPS, "max_actions", 1)
    first = fill(client, 0)
    client.post(f"/api/actions/{first['action_id']}/approve")
    set_mode("invisible")
    assert fill(client, 1)["status"] == "done"


# ---------- dependencies and loops ----------

def test_reply_waits_for_its_quote_then_sends_when_the_quote_is_approved(client, monkeypatch):
    sent = []
    monkeypatch.setitem(actions.EXECUTORS, "send_reply", lambda payload: sent.append(payload) or {"sent": True})
    monkeypatch.setitem(autonomy.RISK, "max_quote_sell", 1000.0)
    set_mode("auto")

    quote = fill(client)
    assert quote["status"] == "pending"
    reply = actions.propose("send_reply", "Reply", "Price is {{sell_total}}",
                            {"reply_id": "r1", "quote_action_id": quote["action_id"]}, 1.0)
    assert reply["status"] == "pending"
    assert reply["risk"]["blockers"] == [f"Waits for quote action {quote['action_id']} to be approved"]

    client.post(f"/api/actions/{quote['action_id']}/approve")
    released = actions.get(reply["action_id"])
    assert (released["status"], released["decided_by"]) == ("done", "ai") and len(sent) == 1


def test_blockers_hold_even_in_invisible_mode(dallas, monkeypatch):
    monkeypatch.setitem(actions.EXECUTORS, "send_reply", lambda payload: {"sent": True})
    monkeypatch.setitem(actions.EXECUTORS, "slow_quote", lambda payload: {"ok": True})
    quote = actions.propose("slow_quote", "q", "s", {"n": 1})
    set_mode("invisible")
    reply = actions.propose("send_reply", "Reply", "s", {"reply_id": "r1", "quote_action_id": quote["action_id"]})
    assert reply["status"] == "pending"


def test_an_executor_that_requeues_itself_cannot_loop(dallas, monkeypatch):
    calls = []

    def requeue(payload):
        calls.append(payload)
        actions.propose("requeue", "again", "s", {"n": payload["n"] + 1})
        raise RuntimeError("not ready")

    monkeypatch.setitem(actions.EXECUTORS, "requeue", requeue)
    monkeypatch.setitem(autonomy.RISK_CHECKS, "requeue", lambda action: {"risks": [], "blockers": []})
    set_mode("invisible")
    first = actions.propose("requeue", "first", "s", {"n": 1})
    assert first["status"] == "failed" and len(calls) == 1
    assert [a["payload"]["n"] for a in actions.list_actions("pending")] == [2]


# ---------- mode routes ----------

def test_mode_routes(client):
    status = client.get("/api/mode").get_json()
    assert status["mode"] == "approval" and status["modes"] == ["approval", "auto", "invisible"]
    assert status["risk_rules"]["max_quote_sell"] == 2500.0
    assert status["risk_rules"]["risky_categories"] == ["BEVERAGE", "FOOD", "HAZMAT"]
    assert status["daily_caps"] == {"max_actions": 20, "max_sell": 50000.0}

    changed = client.put("/api/mode", json={"mode": "auto"})
    assert changed.status_code == 200 and changed.get_json()["mode"] == "auto"
    assert client.get("/api/mode").get_json()["mode"] == "auto"
    assert "mode_changed" in audit_events()


@pytest.mark.parametrize("body", [{"mode": "yolo"}, {}, [1]])
def test_mode_route_rejects_bad_input(client, body):
    response = client.put("/api/mode", json=body)
    assert response.status_code == 400 and response.get_json()["error"] == "bad_request"


def test_bad_stored_mode_falls_back_to_approval(dallas):
    db.set_setting("mode", "garbage")
    assert autonomy.get_mode() == "approval"


# ---------- agent ----------

def test_agent_is_told_what_the_mode_did(dallas):
    executed = {"action_id": "act_1", "status": "done", "mode": "invisible", "result": {"quote_id": "7300901"}}
    assert loop.describe_outcome(executed).startswith("Executed automatically by the AI as act_1 (invisible mode)")
    held = {"action_id": "act_2", "status": "pending", "mode": "auto",
            "risk": {"blockers": [], "reasons": ["HAZMAT freight always needs a human"], "cap": None}}
    assert loop.describe_outcome(held) == "Queued for human approval as act_2 (HAZMAT freight always needs a human)"
    waiting = {"action_id": "act_3", "status": "pending", "mode": "approval", "risk": None}
    assert loop.describe_outcome(waiting) == "Queued for human approval as act_3"
    failed = {"action_id": "act_4", "status": "failed", "mode": "auto", "result": {"error": "boom"}}
    assert loop.describe_outcome(failed) == "The AI tried to execute act_4 (auto mode) but it failed: boom"


# ---------- migration ----------

def test_old_actions_table_gets_the_new_columns(tmp_path, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "old.db"))
    with db.get_conn() as conn:
        conn.execute("CREATE TABLE actions (action_id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, "
                     "summary TEXT, payload TEXT, tier TEXT, confidence REAL, reasoning TEXT, "
                     "status TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.init_db()
    with db.get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(actions)")}
    assert {"mode", "decided_by", "risk"} <= columns
