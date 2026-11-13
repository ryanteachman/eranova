"""The /api/email routes (through Ryan's app) and the carrier haggle stretch feature."""

import pytest

from backend.agent import actions
from backend.errors import Conflict
from email_pipeline import haggle, store

from .conftest import seed, ship


@pytest.fixture
def client(email_tables):
    from backend import create_app
    return create_app().test_client()


# ---------- routes ----------

def test_routes_answer_with_the_contract_shapes(client):
    assert client.get("/api/email/inbox").get_json() == {"items": []}
    assert client.get("/api/email/outbox").get_json() == {"items": []}
    assert len(client.get("/api/email/samples").get_json()["items"]) == 7


def test_route_errors_are_json(client):
    assert client.get("/api/email/em_nope").get_json() == {"error": "not_found", "detail": "No email em_nope."}
    ingest = client.post("/api/email/ingest", json={"from": "x@y.z"})
    assert ingest.status_code == 422 and "subject" in ingest.get_json()["detail"]
    assert client.post("/api/email/simulate", json={"file": "../../.env"}).status_code == 404   # no path tricks


def test_simulate_runs_a_sample_and_it_shows_in_the_inbox(client, fake_llm):
    fake_llm.script["Classification"] = {"kind": "OTHER", "confidence": 0.9, "rationale": "chit-chat"}
    result = client.post("/api/email/simulate", json={"file": "06_vague.json"}).get_json()
    assert result["status"] == "needs_review"
    inbox = client.get("/api/email/inbox?status=needs_review").get_json()["items"]
    assert [e["subject"] for e in inbox] == ["trucks?"]
    assert set(inbox[0]) == {"email_id", "from_addr", "subject", "received_at", "kind", "confidence", "status",
                             "action_ids"}


def test_rejecting_a_send_reply_shows_as_rejected_in_the_outbox(client):
    email_id = store.insert_email({"from": "a@b.c", "subject": "s", "body": "b"})
    reply_id = store.insert_reply(email_id, "a@b.c", "Re: s", "thanks")
    action = actions.propose("send_reply", "Reply", "thanks", {"reply_id": reply_id, "email_id": email_id}, 1.0, "test")
    store.update_reply(reply_id, action_id=action["action_id"])
    actions.reject(action["action_id"], "not needed")
    assert client.get("/api/email/outbox").get_json()["items"][0]["status"] == "rejected"


# ---------- haggle ----------

def test_rate_ask_parsing():
    assert haggle._parse_rate_ask("$2.15/mi", 370) == 795.5
    assert haggle._parse_rate_ask("$1,900 all in", 370) == 1900
    assert haggle._parse_rate_ask("call me", 370) is None


@pytest.fixture
def newark_offer():
    """Lane history on the head-haul (PA→NJ at $2.70/mi) and a processed Gulfstream offer out of Newark."""
    history = ship("7300050", ("Pittsburgh", "PA"), ("Newark", "NJ"), "IRONPEAK", miles=370, status="CLOSED")
    history[0]["buy_total"] = 999.0                                   # 999 / 370 = $2.70/mi
    seed([history])
    email_id = store.insert_email({"from": "Rosa <loads@gulfstreamx.example.com>", "subject": "empty reefer Newark",
                                   "body": "53' reefer empty Newark Thu, $2.15/mi"})
    store.update_email(email_id, kind="CARRIER_OFFER", status="processed",
                       extracted={"rate_ask": "$2.15/mi", "equipment": "R", "available_date": "2026-11-19",
                                  "trailer_number": None},
                       matched={"carrier": {"entity_id": "GULFSTRMX", "label": "Gulfstream Express Carriers"},
                                "prospect": {"prospect_id": "P1", "customer_name": "Ironpeak", "miles": 370,
                                             "origin": {"city": "Newark", "state": "NJ"},
                                             "destination": {"city": "Pittsburgh", "state": "PA"}}})
    return email_id


def test_haggle_settles_inside_the_target_and_queues_a_rate_confirmation(fake_llm, newark_offer):
    fake_llm.script["CarrierTurn"] = {"message": "Fuel's brutal. $760 and we're done.", "accept": False,
                                      "counter_total": 760}
    result = haggle.haggle(newark_offer)
    assert (result["target_pay_min"], result["target_pay_max"]) == (649.35, 849.15)   # 65-85% of $2.70/mi x 370
    assert result["deal"] == 760 and result["carrier_ask"] == 795.5
    action = actions.get(result["action_id"])
    assert action["kind"] == "confirm_carrier_rate" and action["payload"]["amount"] == 760

    done = actions.approve(result["action_id"])
    assert done["status"] == "done" and done["result"]["status"] == "approved_sent"
    assert "Confirming $760.00 all in" in done["result"]["body"]


def test_the_carriers_walk_away_price_is_enforced_in_code(fake_llm, newark_offer):
    # The model "accepts" our opening $649.35, below its private floor (92% of $795.50 = $731.86).
    fake_llm.script["CarrierTurn"] = {"message": "Deal!", "accept": True, "counter_total": None}
    assert haggle.haggle(newark_offer)["deal"] == 731.86


def test_haggle_refuses_emails_that_are_not_carrier_offers(fake_llm):
    email_id = store.insert_email({"from": "a@b.c", "subject": "s", "body": "b"})
    with pytest.raises(Conflict):
        haggle.haggle(email_id)
