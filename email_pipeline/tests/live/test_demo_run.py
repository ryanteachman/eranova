"""The demo-order run we checked by hand, as assertions (live: real model, real Meridian data).

The expected trucks and files come from the team03 dataset as loaded on 2026-11-13. A Meridian reset
can change ids and dates, so if these fail after a reset, check the data before the code.
"""

from pathlib import Path

from email_pipeline.parse import parse_file
from email_pipeline.pipeline import process_email

SAMPLES = Path(__file__).resolve().parents[3] / "demo" / "sample_emails"


def run(name):
    return process_email(parse_file(SAMPLES / name))


def files(options):
    return {o.get("outbound_file") for o in options}


def test_demo_order_end_to_end():
    hero = run("01_quote_dallas_returns.json")
    assert hero["status"] == "processed" and hero["matched"]["status"] == "prospect"
    assert hero["matched"]["prospect"]["outbound_file"] == "7300147"           # Acme, won on load status
    assert hero["matched"]["prospect"]["customer_id"] == "NORTHSTAR"

    reefer = run("02_quote_food_needs_reefer.json")
    p = reefer["matched"]["prospect"]
    assert p["outbound_file"] == "7300159" and p["destination"]["state"] == "IA"   # the "null" state fix
    assert all(o["equipment"] != "R" for o in reefer["matched"]["blocked"])        # only dry vans blocked

    food = run("07_quote_food_out_of_dallas.json")
    blocked = {o["outbound_file"]: o["reasons"] for o in food["matched"]["blocked"]}
    assert food["matched"]["prospect"]["outbound_file"] == "7300147"
    assert any(r.startswith("Blocked: HOS") for r in blocked["7300156"])          # empties 11/17, pickup 11/16
    assert any("FSMA" in r and r.startswith("Blocked") for r in blocked["7300160"])  # UN1760 trailer 53518

    last_load = run("04_last_load_hazmat.json")
    assert last_load["kind"] == "LAST_LOAD_INFO"
    assert [b["outbound_file"] for b in last_load["matched"]["newly_blocked"]] == ["7300122"]   # trailer 53912

    washout = run("03_washout_cert.json")
    assert washout["kind"] == "WASHOUT_CERT" and washout["matched"]["status"] == "recorded"
    assert "7300158" in {u.get("outbound_file") for u in washout["matched"]["unblocked"]}       # trailer 53661

    offer = run("05_carrier_empty_offer.json")
    assert offer["matched"]["prospect"]["customer_id"] == "IRONPEAK"             # heads west, as asked

    vague = run("06_vague.json")
    assert vague["status"] == "needs_review" and vague["actions_created"] == []


def test_saturday_pickup_at_a_weekday_only_facility_is_blocked_by_hos():
    result = process_email({
        "from": "Marcus Bell <mbell@valiantfoods.example.com>", "subject": "Sat pickup Aurora -> Des Moines, reefer",
        "body": "Need a reefer Saturday 11/21 to pick up 10 pallets of yogurt (12,000 lb) at Grocer's Pride DC5, "
                "Aurora CO, going to our Des Moines plant. Keep at 34-38F.",
        "received_at": "2026-11-13T15:00:00Z"})
    assert result["matched"]["status"] == "none_found"
    assert any("closed on Sat 11/21" in r for r in result["matched"]["reasons"])
