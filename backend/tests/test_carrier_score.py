"""Tests for carrier scoring: per-load rules, shrinkage, gates, fit, routes and event sync."""

import json

import pytest

from backend import db, meridian
from backend.brain import carrier_score as cs
from backend.brain import sync

TODAY = "2026-11-13"


def vendor(vendor_id, *, vendor_type="TRUCKLOAD_CARRIER", status="ACTIVE", cargo="2099-01-01",
           equipment=("V",), hazmat=False, lanes=(), stored=90):
    return {"vendor_id": vendor_id, "legal_name": f"{vendor_id} Inc.", "vendor_type": vendor_type,
            "status": status, "equipment_types": list(equipment), "hazmat_certified": hazmat,
            "lanes": [{"origin": o, "destination": d} for o, d in lanes],
            "insurance": [{"policy_type": "CARGO", "expiration_date": cargo}],
            "on_time_delivery_pct": stored, "compliance_light": "GREEN"}


def load(shipment_id, carrier, *, status="CLOSED", late_code=None, condition="CLEAR", pod=True,
         mode="TL", target_min=None, paid=None, dest=("Fort Worth", "TX"), delivered="2026-11-01",
         cancel_reason=None, milestones=(), window=None, appointment="CONFIRMED"):
    return {
        "shipment_id": shipment_id, "carrier_id": carrier, "status": status, "mode": mode,
        "equipment_type": "V", "shipper_city": "Chicago", "shipper_state": "IL",
        "consignee_city": dest[0], "consignee_state": dest[1], "pickup_date": delivered,
        "delivery_date_target": delivered, "cancel_reason": cancel_reason,
        "service_failure": late_code is not None, "service_failure_reason": late_code,
        "pod": {"received": pod, "on_time": late_code is None, "late_reason_code": late_code,
                "condition": condition} if pod else {"received": False},
        "target_pay_min": target_min, "target_pay_max": target_min * 1.2 if target_min else None,
        "vendor_costs": [{"charge_code": "FRT", "amount": paid, "status": "CONFIRMED",
                          "vendor_id": carrier}] if paid else [],
        "milestones": list(milestones),
        "stops": [{"scheduled_window": window, "appointment": {"status": appointment}},
                  {"appointment": {"status": "CONFIRMED"}}],
        "freight_lines": [{"description": "Steel", "hazmat": False}],
    }


def clean(prefix, carrier, n, **kwargs):
    return [load(f"{prefix}{i}", carrier, **kwargs) for i in range(n)]


def score(shipments, vendors, events=()):
    """Return {vendor_id: components} for a hand-made dataset."""
    stats = cs.carrier_stats(shipments, list(events), vendors)
    fleet = cs.fleet_rates(stats)
    return {vendor_id: cs.components(st, fleet) for vendor_id, st in stats.items()}, stats


# ---------- the plan's five tests ----------

def test_mechanical_late_lowers_reliability_but_weather_does_not():
    shipments = (clean("a", "A", 4) + [load("a9", "A", late_code="MECHANICAL")]
                 + clean("b", "B", 4) + [load("b9", "B", late_code="WEATHER")]
                 + clean("c", "C", 5))
    parts, stats = score(shipments, [vendor("A"), vendor("B"), vendor("C")])
    assert parts["A"]["reliability"] < parts["C"]["reliability"]
    assert parts["B"]["reliability"] == pytest.approx(parts["C"]["reliability"])
    assert stats["B"]["late"]["excused"] == 1
    assert cs.on_time_actual_pct(stats["B"]) == 100


def test_shrinkage_one_late_of_one_beats_five_late_of_ten():
    shipments = ([load("x1", "X", late_code="T3")]
                 + [load(f"y{i}", "Y", late_code="T3" if i < 5 else None) for i in range(10)]
                 + clean("z", "Z", 20))
    parts, _ = score(shipments, [vendor("X"), vendor("Y"), vendor("Z")])
    assert parts["X"]["reliability"] > parts["Y"]["reliability"]


def test_do_not_use_and_expired_cargo_are_excluded_with_reasons():
    db.replace_records("shipments", clean("g", "GOOD", 3), "shipment_id")
    db.replace_records("vendors", [vendor("GOOD"), vendor("DNU", status="DO_NOT_USE"),
                                   vendor("OLD", cargo="2026-11-01")], "vendor_id")
    result = cs.rank_carriers({"city": "Chicago", "state": "IL"}, {"city": "Dallas", "state": "TX"},
                              equipment_type="V", mode="TL", today=TODAY)
    assert [c["vendor_id"] for c in result["eligible"]] == ["GOOD"]
    reasons = {x["vendor_id"]: x["reason"] for x in result["excluded"]}
    assert "DO_NOT_USE" in reasons["DNU"] and "CARGO" in reasons["OLD"]


def test_truck_in_the_pickup_city_beats_an_equal_carrier_elsewhere():
    db.replace_records("shipments", clean("h", "HERE", 3, dest=("Dallas", "TX"))
                       + clean("f", "FAR", 3, dest=("Boston", "MA")), "shipment_id")
    db.replace_records("vendors", [vendor("HERE"), vendor("FAR")], "vendor_id")
    result = cs.rank_carriers({"city": "Dallas", "state": "TX"}, {"city": "Chicago", "state": "IL"},
                              equipment_type="V", today=TODAY)
    first, second = result["eligible"]
    assert first["vendor_id"] == "HERE" and first["score"] > second["score"]
    assert first["fit"] == 0.6 and "already at pickup" in first["reasons"][0]
    assert first["base_score"] == second["base_score"]


def test_no_cost_targets_means_neutral_cost():
    parts, _ = score(clean("n", "N", 3), [vendor("N")])
    assert parts["N"]["cost"] == 0.5


# ---------- per-load rules ----------

def test_late_delivery_causes():
    assert cs.late_delivery(load("1", "A")) is None
    assert cs.late_delivery(load("1", "A", late_code="t3")) == ("carrier", "T3")
    assert cs.late_delivery(load("1", "A", late_code="B1")) == ("excused", "B1")
    assert cs.late_delivery(load("1", "A", late_code="NS")) == ("unknown", "NS")
    assert cs.late_delivery(load("1", "A", late_code="ZZ")) == ("unknown", "ZZ")
    # No POD means lateness isn't known yet.
    assert cs.late_delivery(load("1", "A", late_code="T3", pod=False)) is None


def window(latest="2026-11-13T14:00:00"):
    return {"earliest_local": "2026-11-13T08:00:00", "latest_local": latest, "timezone": "America/Chicago"}


def arrived(at, tz="America/Chicago"):
    return {"milestone_code": "AT_SHIPPER", "complete": True, "event_at": at, "event_timezone": tz}


def test_late_pickup_compares_in_utc():
    # 14:00 Chicago (CST) is 20:00 UTC.
    on_time = load("1", "A", milestones=[arrived("2026-11-13T19:59:00Z")], window=window())
    late = load("2", "A", milestones=[arrived("2026-11-13T20:01:00Z")], window=window())
    local = load("3", "A", milestones=[arrived("2026-11-13T14:30:00")], window=window())
    assert cs.late_pickup(on_time) is False
    assert cs.late_pickup(late) is True
    assert cs.late_pickup(local) is True


def test_late_pickup_unknown_for_ltl_missing_data_and_status_jumps():
    assert cs.late_pickup(load("1", "A", mode="LTL", milestones=[arrived("2026-11-13T23:00:00Z")],
                               window=window())) is None
    assert cs.late_pickup(load("2", "A", milestones=[], window=window())) is None
    assert cs.late_pickup(load("3", "A", milestones=[arrived("2026-11-13T23:00:00Z")])) is None
    jumped = [arrived("2026-11-13T23:00:00Z"),
              {"milestone_code": "LOADED", "complete": True, "event_at": "2026-11-13T23:00:00Z"}]
    assert cs.late_pickup(load("4", "A", milestones=jumped, window=window())) is None


def test_damage_missed_appointments_and_extras():
    assert cs.damaged(load("1", "A", condition="SHORTAGE"))
    assert not cs.damaged(load("1", "A", condition="CLEAR"))
    assert cs.missed_appointment(load("1", "A", appointment="MISSED"))
    shipment = load("1", "A")
    shipment["vendor_costs"] = [
        {"charge_code": "DET", "status": "CONFIRMED", "vendor_id": "A"},
        {"charge_code": "LAY", "status": "CANCELLED", "vendor_id": "A"},
        {"charge_code": "DET", "status": "CONFIRMED", "vendor_id": "LUMPER"},
    ]
    assert cs.extra_charges(shipment, "A") == 1


def test_cost_ratio_ignores_cancelled_and_other_vendors_lines():
    shipment = load("1", "A", target_min=1000, paid=900)
    shipment["vendor_costs"] += [
        {"charge_code": "FRT", "amount": 5000, "status": "CANCELLED", "vendor_id": "A"},
        {"charge_code": "FRT", "amount": 5000, "status": "CONFIRMED", "vendor_id": "BOUNCED"},
    ]
    assert cs.cost_ratio(shipment, "A") == 0.9
    assert cs.cost_ratio(load("2", "A", paid=900), "A") is None


def test_cheaper_than_the_fleet_scores_better_on_cost():
    shipments = (clean("c", "CHEAP", 5, target_min=1000, paid=800)
                 + clean("e", "DEAR", 5, target_min=1000, paid=950))
    parts, _ = score(shipments, [vendor("CHEAP"), vendor("DEAR")])
    assert parts["CHEAP"]["cost"] > 0.5 > parts["DEAR"]["cost"]


def test_customer_cancelled_tonu_does_not_count_against_the_carrier():
    shipments = (clean("a", "A", 3) + [load("t1", "A", status="TONU", cancel_reason="CUSTOMER_CANCELLED")]
                 + clean("b", "B", 3) + [load("t2", "B", status="TONU", cancel_reason="NO_CAPACITY")])
    parts, stats = score(shipments, [vendor("A"), vendor("B")])
    assert (stats["A"]["tonu"], stats["A"]["tonu_excused"], stats["B"]["tonu"]) == (0, 1, 1)
    assert parts["A"]["quality"] > parts["B"]["quality"]


UNCOVER = {"event_type": "SYSTEM", "shipment_id": "7300154", "reason_code": "FELL_THROUGH",
           "note": "Uncovered (FELL_THROUGH): dispatcher stopped answering — cost lines cancelled — "
                   "was carrier BADWOLF, rate con RC-7300154-1, buy $2,583.00"}


def test_bounces_are_read_from_uncover_events():
    other = {"event_type": "SYSTEM", "shipment_id": "1", "note": "Covered with carrier BADWOLF"}
    assert cs.bounces([UNCOVER, other], {"BADWOLF", "ACMECARR"}) == [("BADWOLF", "FELL_THROUGH", "7300154")]
    assert cs.bounces([UNCOVER], {"ACMECARR"}) == []


def test_a_bounce_lowers_quality_and_shows_in_reasons():
    shipments = clean("a", "BADWOLF", 4) + clean("b", "B", 4)
    parts, stats = score(shipments, [vendor("BADWOLF"), vendor("B")], [UNCOVER])
    assert parts["BADWOLF"]["quality"] < parts["B"]["quality"]
    assert "Bounced 1 load (FELL_THROUGH)" in cs.reasons_for(vendor("BADWOLF"), stats["BADWOLF"])


def test_reasons_mention_profile_gaps_and_pluralize():
    shipments = [load(f"l{i}", "L", late_code="T3" if i < 3 else None) for i in range(10)]
    _, stats = score(shipments, [vendor("L", stored=98)])
    reasons = cs.reasons_for(vendor("L", stored=98), stats["L"])
    assert reasons[0] == "70% on time across 10 loads"
    assert "3 late deliveries, tractor or trailer not available (carrier fault)" in reasons
    assert "Profile says 98% on time; actual loads say 70%" in reasons
    assert 3 <= len(reasons) <= 5


def test_non_carrier_vendors_are_not_scored():
    stats = cs.carrier_stats([], [], [vendor("A"), vendor("LUMP", vendor_type="LUMPER")])
    assert set(stats) == {"A"}


# ---------- gates ----------

def test_gates_for_mode_equipment_and_hazmat():
    assert cs.gate(vendor("A"), "V", False, "TL", TODAY) is None
    assert "Does not haul TL" in cs.gate(vendor("L", vendor_type="LTL_CARRIER"), "V", False, "TL", TODAY)
    assert cs.gate(vendor("R", equipment=("R",)), "V", False, "TL", TODAY) is None  # a reefer can run dry
    assert "No equipment for R" in cs.gate(vendor("A"), "R", False, "TL", TODAY)
    assert cs.gate(vendor("A"), "V", True, "TL", TODAY) == "Not hazmat certified"
    assert cs.gate(vendor("H", hazmat=True), "V", True, "TL", TODAY) is None


def test_carrier_that_bounced_this_load_is_excluded():
    db.replace_records("shipments", clean("a", "BADWOLF", 3) + clean("b", "B", 3)
                       + [load("7300154", None, status="BOOKED")], "shipment_id")
    db.replace_records("vendors", [vendor("BADWOLF"), vendor("B")], "vendor_id")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO events VALUES ('e1', '7300154', ?)", (json.dumps(UNCOVER),))
    result = cs.rank_request(shipment_id="7300154")
    assert [c["vendor_id"] for c in result["eligible"]] == ["B"]
    assert result["excluded"] == [{"vendor_id": "BADWOLF", "legal_name": "BADWOLF Inc.",
                                   "reason": "Already bounced this load (FELL_THROUGH)"}]


# ---------- routes and the tool ----------

@pytest.fixture
def carriers_client():
    from backend import create_app
    db.replace_records("shipments", clean("a", "A", 3, dest=("Dallas", "TX")) + clean("b", "B", 3),
                       "shipment_id")
    db.replace_records("vendors", [vendor("A", lanes=[("TX", "IL")]), vendor("B"),
                                   vendor("LUMP", vendor_type="LUMPER")], "vendor_id")
    return create_app().test_client()


def test_carrier_routes(carriers_client):
    items = carriers_client.get("/api/carriers").get_json()["items"]
    assert {c["vendor_id"] for c in items} == {"A", "B"}
    assert set(items[0]) >= {"vendor_id", "legal_name", "compliance_light", "loads", "on_time_actual_pct",
                             "on_time_stored_pct", "late_by_cause", "damage", "bounces", "tonu",
                             "cost_score", "reliability", "quality", "base_score", "last_city", "reasons"}
    detail = carriers_client.get("/api/carriers/a").get_json()
    assert detail["vendor_id"] == "A" and len(detail["per_load"]) == 3
    assert carriers_client.get("/api/carriers/LUMP").status_code == 404

    ranked = carriers_client.post("/api/carriers/rank", json={
        "origin": {"city": "Dallas", "state": "tx"}, "destination": {"city": "Chicago", "state": "IL"},
        "equipment_type": "V"}).get_json()
    assert ranked["eligible"][0]["vendor_id"] == "A" and ranked["eligible"][0]["fit"] == 1.0


@pytest.mark.parametrize("body", [{"origin": "Dallas"}, {}, {"origin": {"city": "Dallas"}}])
def test_rank_route_validates_its_input(carriers_client, body):
    response = carriers_client.post("/api/carriers/rank", json=body)
    assert response.status_code == 400 and response.get_json()["error"] == "bad_request"


def test_rank_unknown_shipment_is_404(carriers_client, fake_meridian):
    fake_meridian.fail[("GET", "/shipments/")] = meridian.MeridianError(404, "not_found", "Shipment 1 not found")
    response = carriers_client.post("/api/carriers/rank", json={"shipment_id": "1"})
    assert response.status_code == 404


def test_rank_carriers_tool_returns_trimmed_cards(carriers_client):
    from backend.agent.registry import TOOLS
    result = TOOLS["rank_carriers"]["fn"](origin={"city": "Dallas", "state": "TX"},
                                          destination={"city": "Chicago", "state": "IL"})
    assert TOOLS["rank_carriers"]["tier"] == "auto"
    assert set(result["eligible"][0]) == {"vendor_id", "legal_name", "score", "base_score", "fit",
                                          "on_time_actual_pct", "loads", "compliance_light", "reasons"}


# ---------- event sync ----------

def test_sync_events_skips_final_shipments_unless_refresh(monkeypatch):
    db.replace_records("shipments", [load("closed", "A"), load("open", "A", status="IN_TRANSIT")],
                       "shipment_id")
    pulled = []

    def fake_get_all(path, **params):
        shipment_id = path.split("/")[2]
        pulled.append(shipment_id)
        return [{"event_id": f"{shipment_id}-e1", "shipment_id": shipment_id, "event_type": "NOTE"}]

    monkeypatch.setattr(meridian, "get_all", fake_get_all)
    assert sync.sync_events() == {"synced": 2, "skipped": 0}
    assert sync.sync_events() == {"synced": 1, "skipped": 1}
    assert pulled[-1] == "open"
    assert sync.sync_events(refresh=True) == {"synced": 2, "skipped": 0}
    assert len(db.load_events()) == 2

    db.replace_records("shipments", [load("open", "A", status="IN_TRANSIT")], "shipment_id")
    sync.sync_events()
    assert [e["shipment_id"] for e in db.load_events()] == ["open"]
