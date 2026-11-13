"""The whole pipeline with a scripted model, then the human approval flow through Ryan's queue."""

import pytest

from backend import db
from backend.agent import actions
from backend.agent.registry import TOOLS
from email_pipeline import store
from email_pipeline.pipeline import process_email

from .conftest import MIDWAY_EMAIL, quote_request

CLASSIFIED_QUOTE = {"kind": "QUOTE_REQUEST", "confidence": 0.9, "rationale": "asks for a price on a lane"}
# The model "forgets" the rule and writes a price: the code must replace it with the placeholder.
REPLY_WITH_A_PRICE = {"subject": "Re: Dallas to KC dry grocery - Mon 11/16",
                      "body": "Hi Chip,\n\nWe can move it for $1,500.\n\nMeridian Logistics - Return Trip desk"}


@pytest.fixture
def midway(fake_llm, dallas_trucks):
    """Run the Midway quote request (sample 07) through the pipeline."""
    fake_llm.script.update({"Classification": CLASSIFIED_QUOTE, "QuoteRequest": quote_request(),
                            "Reply": REPLY_WITH_A_PRICE})
    return process_email(MIDWAY_EMAIL)


def test_quote_request_proposes_a_priced_quote_and_a_reply(midway):
    assert midway["status"] == "processed" and midway["kind"] == "QUOTE_REQUEST"
    quote_id, reply_id = midway["actions_created"]
    quote, reply_action = actions.get(quote_id), actions.get(reply_id)
    assert (quote["kind"], quote["status"], reply_action["kind"]) == ("create_return_quote", "pending", "send_reply")

    payload = quote["payload"]
    assert payload["customer_id"] == "MIDWAYDST" and payload["outbound_file"] == "7300001"
    assert payload["pickup_date"] == "2026-11-16" and payload["delivery_date_target"] >= "2026-11-16"   # HOS date
    assert payload["buy_lines"] and payload["miles"] and payload["target_margin_pct"] == 10
    assert payload["freight_lines"] == [{"pieces": 20, "weight_lb": 31000.0, "package_type": "PALLET",
                                         "description": "canned goods and boxed dry grocery", "hazmat": False}]
    assert "Email em_" in quote["reasoning"]                                  # reasoning cites the email


def test_the_draft_never_contains_a_price(midway):
    body = store.get_reply(midway["reply_id"])["body"]
    assert "{{sell_total}}" in body and "$" not in body


def test_every_step_is_audited(midway):
    with db.get_conn() as conn:
        events = [r["event"] for r in conn.execute("SELECT event FROM audit_log WHERE actor = 'email_pipeline'")]
    for event in ("email_received", "email_classified", "email_extracted", "email_matched", "action_proposed",
                  "reply_drafted", "email_processed"):
        assert event in events


def test_reply_before_quote_is_refused_and_requeued_then_sends_with_the_price(midway, fake_meridian):
    quote_id, reply_id = midway["actions_created"]

    refused = actions.approve(reply_id)
    assert refused["status"] == "failed" and "queued again as act_" in refused["result"]["error"]
    requeued = store.get_reply(midway["reply_id"])["action_id"]
    assert requeued != reply_id and actions.get(requeued)["status"] == "pending"

    quote = actions.approve(quote_id)                                        # Ryan's executor, fake Meridian
    assert quote["status"] == "done" and quote["result"]["quote_id"] == "7300901"
    create = next(body for method, path, body in fake_meridian.calls if (method, path) == ("POST", "/quotes"))
    assert create["pickup_date"] == "2026-11-16" and create["delivery_date_target"] and create["freight_lines"]

    sent = actions.approve(requeued)
    assert sent["status"] == "done"
    body = store.get_reply(midway["reply_id"])["body"]
    assert "$1,234.50" in body and "Meridian quote #7300901" in body
    assert store.get_reply(midway["reply_id"])["status"] == "approved_sent"


def test_the_agents_send_reply_tool_only_proposes(midway):
    proposal = TOOLS["send_reply"]["fn"](midway["reply_id"])
    assert set(proposal) == {"title", "summary", "payload", "confidence", "reasoning"}
    assert store.get_reply(midway["reply_id"])["status"] == "draft"


def test_low_confidence_goes_to_review_with_no_actions(fake_llm, dallas_trucks):
    fake_llm.script["Classification"] = {"kind": "QUOTE_REQUEST", "confidence": 0.5, "rationale": "vague"}
    result = process_email(MIDWAY_EMAIL)
    assert (result["status"], result["actions_created"], result["reply_id"]) == ("needs_review", [], None)


def test_missing_essentials_go_to_review(fake_llm, dallas_trucks):
    # The 06 "trucks?" email: confident enough, but no lane at all.
    empty = {"city": None, "state": None, "zip": None, "name": None}
    fake_llm.script.update({"Classification": CLASSIFIED_QUOTE,
                            "QuoteRequest": quote_request(origin=empty, destination=empty, pickup_date=None)})
    result = process_email({"from": "skye@truenorthgear.example.com", "subject": "trucks?", "body": "trucks next week?"})
    assert result["status"] == "needs_review" and result["error"] == "Missing: origin city, destination city"


def test_a_crash_is_saved_as_failed(fake_llm, dallas_trucks):
    fake_llm.script.update({"Classification": CLASSIFIED_QUOTE, "QuoteRequest": RuntimeError("model timed out")})
    result = process_email(MIDWAY_EMAIL)
    assert result["status"] == "failed" and "model timed out" in result["error"]
    assert result["kind"] == "QUOTE_REQUEST"                                   # earlier steps were saved


def test_carrier_replies_never_get_the_price_placeholder(fake_llm, dallas_trucks):
    fake_llm.script.update({
        "Classification": {"kind": "WASHOUT_CERT", "confidence": 0.95, "rationale": "wash ticket"},
        "WashoutCert": {"carrier_hint": "Blue Ridge", "trailer_number": "T9", "washed_at": "2026-11-13",
                        "facility": "Hutchins TX", "cert_number": None},
        "Reply": {"subject": "Re: wash", "body": "Thanks! Rate is {{sell_total}} or $5.\n\nMeridian"},
    })
    result = process_email({"from": "d@blueridge.example.com", "subject": "wash T9", "body": "Trailer T9 washed."})
    assert result["matched"]["status"] == "recorded" and store.washouts_for_trailer("T9")
    body = store.get_reply(result["reply_id"])["body"]
    assert "{{sell_total}}" not in body and "$" not in body and "(pricing to follow)" in body
    assert [actions.get(a)["kind"] for a in result["actions_created"]] == ["send_reply"]    # no quote
