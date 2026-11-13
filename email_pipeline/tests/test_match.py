"""Step 5: matching a quote request to trucks emptying at its origin (rules, HOS, washouts, tiebreakers)."""

from email_pipeline import match, store

from .conftest import MIDWAY_EMAIL, quote_request


def match_midway(**overrides):
    email_id = store.insert_email(MIDWAY_EMAIL)
    return match.match_quote_request(email_id, MIDWAY_EMAIL, quote_request(**overrides))


def by_file(result):
    return {o["outbound_file"]: o for o in result["options"] + result["blocked"]}


def blocks(option):
    return [r for r in option["reasons"] if r.startswith("Blocked")]


def test_food_request_picks_the_clean_truck_that_empties_on_pickup_day(dallas_trucks):
    result = match_midway()
    p = result["prospect"]
    assert result["status"] == "prospect" and p["outbound_file"] == "7300001"
    assert result["customer"]["entity_id"] == "MIDWAYDST" and "customer contact" in result["customer"]["method"]
    # priced with Ryan's pricing: Dallas → Kansas City miles, FRT + FSC buy lines, the customer's margin
    assert p["miles"] > 0 and [line["charge_code"] for line in p["buy_lines"]] == ["FRT", "FSC"]
    assert p["est_sell"] > p["est_buy"] > 0 and p["target_margin_pct"] == 10
    # Hours of Service estimate carried onto the prospect
    assert p["est_pickup"].startswith("11/16") and p["delivery_date_target"] >= "2026-11-16"


def test_fsma_blocks_the_hazmat_trailer_for_food(dallas_trucks):
    hazmat = by_file(match_midway())["7300003"]
    assert not hazmat["ok"]
    assert blocks(hazmat) == ["Blocked: trailer last hauled HAZMAT (UN1760); FSMA requires a washout before food."]


def test_washout_on_file_unblocks_the_hazmat_trailer(dallas_trucks):
    store.insert_washout("BLUERIDGE", "T9", "2026-11-13", "Hutchins TX", "WO-1", "em_x")
    hazmat = by_file(match_midway())["7300003"]
    assert hazmat["ok"] and any("washout certificate is on file" in r for r in hazmat["reasons"])


def test_hos_blocks_a_truck_that_empties_after_the_pickup_day(dallas_trucks):
    late = by_file(match_midway())["7300002"]                     # empties 11/17, pickup requested 11/16
    assert not late["ok"] and blocks(late)[0].startswith("Blocked: HOS:")
    assert "after the pickup facility closes" in blocks(late)[0]


def test_hos_blocks_every_truck_on_a_day_the_facility_is_closed(dallas_trucks, monkeypatch):
    # The Saturday-at-Grocer's-Pride scenario: an unknown pickup facility uses default hours, so close
    # the pickup day by patching the hours lookup to "closed".
    from backend.brain import hos
    monkeypatch.setattr(hos, "facility_hours", lambda facility, day: None)
    result = match_midway()
    assert result["status"] == "none_found"
    assert any("closed on" in r for r in result["reasons"])


def test_trailer_history_from_a_carrier_email_blocks_food(dallas_trucks):
    # Prairie's 04 email: trailer T7 hauled caustic cleaner after our steel load; Meridian doesn't know.
    email_id = store.insert_email({"from": "ops@prairiehaul.example.com", "subject": "FYI trailer T7", "body": "..."})
    store.update_email(email_id, kind="LAST_LOAD_INFO", status="processed",
                       extracted={"trailer_number": "T7", "last_commodity": "caustic cleaner (UN1719)",
                                  "last_commodity_category": "HAZMAT"})
    prairie = by_file(match_midway())["7300004"]
    assert not prairie["ok"]
    assert prairie["reasons"][0].startswith(f"Trailer history from email {email_id}")
    assert any("FSMA requires a washout" in r for r in blocks(prairie))


def test_requested_reefer_blocks_dry_vans(dallas_trucks):
    result = match_midway(equipment="R", temp_controlled=True)
    assert result["status"] == "none_found"
    assert all("Blocked: request needs equipment R, truck is V." in o["reasons"] for o in result["blocked"])


def test_missing_lane_or_unknown_customer_is_none_found(dallas_trucks):
    assert match_midway(destination={"city": None, "state": None, "zip": None, "name": None})["status"] == "none_found"
    stranger = dict(MIDWAY_EMAIL, **{"from": "someone@unknown.example.com"})
    email_id = store.insert_email(stranger)
    result = match.match_quote_request(email_id, stranger, quote_request(customer_hint="Nobody Inc"))
    assert result["status"] == "none_found" and "not in Meridian" in result["reasons"][0]


# ---------- tiebreakers and options ----------

TIED = {"ok": True, "score": 80, "outbound_status": "IN_TRANSIT", "delivery_facility_id": "DC",
        "carrier_compliance": "GREEN", "trailer_number": "1", "carrier_lane": 0, "carrier_lane_note": None}


def option(file_no, **fields):
    return dict(TIED, outbound_file=file_no, carrier_id=fields.pop("carrier_id", "X"), reasons=[], **fields)


def test_lane_fit_exact_beats_reverse_beats_none():
    acme = {"lanes": [{"origin": "IL", "destination": "TX"}]}
    assert match.lane_fit(acme, "IL", "TX")[0] == 2
    assert match.lane_fit(acme, "TX", "IL") == (1, "runs IL→TX, the reverse of this trip")
    assert match.lane_fit(acme, "TX", "MO") == (0, None) and match.lane_fit({"lanes": None}, "TX", "IL") == (0, None)


def test_lane_is_the_first_tiebreaker():
    opts = [option("7300100", carrier_id="BLUERIDGE"),
            option("7300200", carrier_id="ACMECARR", carrier_lane=1, outbound_status="BOOKED",
                   carrier_lane_note="runs IL→TX, the reverse of this trip")]
    winner = match._rank_trucks(opts, "DC")[0]
    assert winner["outbound_file"] == "7300200"            # beats a better status and a lower file number
    assert winner["reasons"][-1].endswith("chosen on carrier lane (ACMECARR runs IL→TX, the reverse of this trip).")


def test_tiebreak_order_after_lane():
    # same facility → load status → compliance → known trailer → lower file number
    assert match._rank_trucks([option("1", delivery_facility_id="ELSEWHERE"), option("2")], "DC")[0]["outbound_file"] == "2"
    status = match._rank_trucks([option("1", outbound_status="COVERED"), option("2", outbound_status="DISPATCHED")], "DC")
    assert status[0]["outbound_file"] == "2" and "(DISPATCHED vs COVERED)" in status[0]["reasons"][-1]
    assert match._rank_trucks([option("1", carrier_compliance="YELLOW"), option("2")], "DC")[0]["outbound_file"] == "2"
    assert match._rank_trucks([option("1", trailer_number=None), option("2")], "DC")[0]["outbound_file"] == "2"
    assert match._rank_trucks([option("7300009"), option("7300002")], "DC")[0]["outbound_file"] == "7300002"


def test_full_tie_falls_back_without_crashing():
    winner = match._rank_trucks([option(None), option(None)], "DC")[0]
    assert winner["reasons"][-1].endswith("chosen on equal footing (first listed).")


def test_options_keep_every_truck_tied_at_the_cut_off():
    opts = [option(str(n), score=s) for n, s in enumerate([100, 90, 80, 80, 80, 80, 80, 50])]
    kept = match._top_options(opts)
    assert len(kept) == 7 and all(o["score"] >= 80 for o in kept)
