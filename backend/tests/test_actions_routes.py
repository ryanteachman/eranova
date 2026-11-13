"""Tests for the approval queue and the HTTP API."""

import json
import threading
from pathlib import Path

import pytest

from backend import meridian
from backend.agent import actions
from backend.brain import network
from backend.errors import Conflict, NotFound

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def top_prospect_id():
    return network.find_backhauls("Dallas", "TX")[0]["prospect_id"]


# ---------- approval queue ----------

def test_fill_approve_creates_and_prices_the_quote(client, fake_meridian):
    pid = top_prospect_id()
    filled = client.post("/api/fill", json={"prospect_id": pid}).get_json()
    assert filled["status"] == "pending"

    fake_meridian.calls.clear()
    action = client.post(f"/api/actions/{filled['action_id']}/approve").get_json()
    assert action["status"] == "done"
    assert action["result"] == {"quote_id": "7300901", "summary": "Quote 7300901 | QUOTED",
                                "sell_total": 1234.5,
                                "meridian_url": "https://tms.example/quotes/7300901"}

    (m1, p1, create), (m2, p2, price), (m3, p3, note) = fake_meridian.calls
    assert (m1, p1, m2, p2, m3, p3) == ("POST", "/quotes", "POST", "/quotes/7300901/price",
                                        "PUT", "/quotes/7300901")
    assert create["customer_id"] == "NORTHSTAR" and create["mode"] == "TL"
    assert create["origin"] == {"city": "Dallas", "state": "TX"}
    assert create["destination"] == {"city": "Chicago", "state": "IL"}
    assert price["rate_ref"].startswith("return-trip:")
    assert price["target_margin_pct"] == 10
    assert [line["charge_code"] for line in price["buy_lines"]] == ["FRT", "FSC"]
    assert "Return Trip" in note["note"]
    # Hours of Service dates from the prospect go onto the Meridian quote.
    assert create["pickup_date"] and create["delivery_date_target"] >= create["pickup_date"]


def test_fill_twice_returns_the_same_pending_action(client):
    pid = top_prospect_id()
    first = client.post("/api/fill", json={"prospect_id": pid}).get_json()
    second = client.post("/api/fill", json={"prospect_id": pid}).get_json()
    assert first["action_id"] == second["action_id"]
    assert len(client.get("/api/actions?status=pending").get_json()["items"]) == 1


def test_approve_twice_conflicts_and_only_writes_once(client, fake_meridian):
    action_id = client.post("/api/fill", json={"prospect_id": top_prospect_id()}).get_json()["action_id"]
    assert client.post(f"/api/actions/{action_id}/approve").status_code == 200
    again = client.post(f"/api/actions/{action_id}/approve")
    assert again.status_code == 409 and again.get_json()["error"] == "conflict"
    assert len([c for c in fake_meridian.calls if c[:2] == ("POST", "/quotes")]) == 1


def test_concurrent_approvals_run_the_executor_once(dallas, monkeypatch):
    calls, gate = [], threading.Event()

    def slow_executor(payload):
        calls.append(payload)
        gate.wait(2)
        return {"ok": True}

    monkeypatch.setitem(actions.EXECUTORS, "slow", slow_executor)
    action = actions.propose("slow", "t", "s", {"n": 1})
    outcomes = []

    def approve():
        try:
            outcomes.append(actions.approve(action["action_id"])["status"])
        except Conflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=approve) for _ in range(2)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict", "done"] and len(calls) == 1


def test_meridian_failure_marks_action_failed_and_names_the_draft_quote(client, fake_meridian):
    fake_meridian.fail[("POST", "/quotes/7300901/price")] = meridian.MeridianError(
        422, "validation_error", "target_margin_pct is out of range.")
    action_id = client.post("/api/fill", json={"prospect_id": top_prospect_id()}).get_json()["action_id"]
    action = client.post(f"/api/actions/{action_id}/approve").get_json()
    assert action["status"] == "failed"
    assert action["result"] == {"status": 422, "error": "Quote 7300901 was created but not "
                                                       "finished: target_margin_pct is out of range."}


def test_unexpected_executor_error_does_not_leave_action_running(dallas, monkeypatch):
    def broken(payload):
        raise KeyError("missing")

    monkeypatch.setitem(actions.EXECUTORS, "broken", broken)
    action = actions.propose("broken", "t", "s", {})
    assert actions.approve(action["action_id"])["status"] == "failed"


def test_reject_and_lookup_errors(client):
    action_id = client.post("/api/fill", json={"prospect_id": top_prospect_id()}).get_json()["action_id"]
    rejected = client.post(f"/api/actions/{action_id}/reject", json={"reason": "no freight"}).get_json()
    assert rejected["status"] == "rejected" and rejected["result"] == {"reason": "no freight"}
    assert client.post(f"/api/actions/{action_id}/approve").status_code == 409
    assert client.post("/api/actions/act_nope/approve").status_code == 404
    with pytest.raises(NotFound):
        actions.reject("act_nope")


def test_propose_requires_an_executor(dallas):
    with pytest.raises(ValueError):
        actions.propose("no_such_kind", "t", "s", {})


# ---------- routes ----------

def test_health_and_cors(client):
    response = client.get("/api/health")
    assert response.status_code == 200 and response.get_json()["ok"] is True
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert client.open("/api/fill", method="OPTIONS").status_code == 200


def test_city_route_hides_internal_pricing_lines(client):
    detail = client.get("/api/city/TX/Dallas").get_json()
    assert detail["city"] == "Dallas" and detail["inbound"] == 3
    assert detail["prospects"] and all("buy_lines" not in p for p in detail["prospects"])


def test_city_with_spaces_in_the_name(client):
    assert client.get("/api/city/TX/Fort%20Worth").get_json()["city"] == "Fort Worth"


@pytest.mark.parametrize("body, status", [
    ("not json", 400),
    ([1, 2], 400),
    ({}, 400),
    ({"prospect_id": "TX:Dallas:X:Y:Z:W:1"}, 404),
])
def test_fill_errors(client, body, status):
    if isinstance(body, str):
        response = client.post("/api/fill", data=body, content_type="application/json")
    else:
        response = client.post("/api/fill", json=body)
    assert response.status_code == status
    assert set(response.get_json()) == {"error", "detail"}


def test_fill_blocked_prospect_conflicts(client, monkeypatch):
    blocked = dict(network.find_backhauls("Dallas", "TX")[0], ok=False,
                   reasons=["Blocked: test reason."])
    monkeypatch.setattr(network, "find_prospect", lambda pid: blocked)
    response = client.post("/api/fill", json={"prospect_id": blocked["prospect_id"]})
    assert response.status_code == 409 and "Blocked: test reason." in response.get_json()["detail"]


def test_meridian_error_passes_through(client, fake_meridian):
    fake_meridian.fail[("POST", "/quotes/price-preview")] = meridian.MeridianError(
        409, "conflict", "Do the thing first.")
    response = client.post("/api/fill", json={"prospect_id": top_prospect_id()})
    assert response.status_code == 409
    assert response.get_json() == {"error": "conflict", "detail": "Do the thing first."}


def test_meridian_server_error_becomes_502(client, fake_meridian):
    fake_meridian.fail[("POST", "/quotes/price-preview")] = meridian.MeridianError(
        500, "internal_error", "Meridian broke.")
    assert client.post("/api/fill", json={"prospect_id": top_prospect_id()}).status_code == 502


def test_unknown_route_and_wrong_method_are_json(client):
    assert client.get("/api/nope").get_json()["error"] == "not_found"
    response = client.get("/api/fill")
    assert response.status_code == 405 and response.get_json()["error"] == "method_not_allowed"


def test_audit_limit_is_clamped(client):
    client.post("/api/fill", json={"prospect_id": top_prospect_id()})
    client.post("/api/fill", json={"prospect_id": "TX:Dallas:X:Y:Z:W:1"})
    assert len(client.get("/api/audit?limit=1").get_json()["items"]) == 1
    assert len(client.get("/api/audit?limit=-1").get_json()["items"]) == 1
    assert client.get("/api/audit?limit=abc").status_code == 400


def test_chat_requires_a_message(client):
    assert client.post("/api/agent/chat", json={}).status_code == 400
    assert client.post("/api/agent/chat", json={"message": 5}).status_code == 400


# ---------- contract ----------

def mock(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def test_responses_match_the_contract_mocks(client):
    network_mock, network_live = mock("network.json"), client.get("/api/network").get_json()
    assert set(network_live) == set(network_mock)
    assert set(network_live["totals"]) == set(network_mock["totals"])
    assert set(network_live["cities"][0]) == set(network_mock["cities"][0])
    assert set(network_live["arcs"][0]) == set(network_mock["arcs"][0])

    city_mock, city_live = mock("city.json"), client.get("/api/city/TX/Dallas").get_json()
    assert set(city_live) == set(city_mock)
    assert set(city_live["prospects"][0]) == set(city_mock["prospects"][0])

    filled = client.post("/api/fill", json={"prospect_id": city_live["prospects"][0]["prospect_id"]})
    assert set(filled.get_json()) == set(mock("fill.json"))
    pending = client.get("/api/actions?status=pending").get_json()["items"][0]
    assert set(pending) == set(mock("actions.json")["items"][0])
    approved = client.post(f"/api/actions/{pending['action_id']}/approve").get_json()
    assert set(approved) == set(mock("action_approved.json"))
    assert set(approved["result"]) == set(mock("action_approved.json")["result"])
    assert set(client.get("/api/audit").get_json()["items"][0]) == set(mock("audit.json")["items"][0])
