"""Tests for sync, classification, pricing and the network / backhaul finder."""

from types import SimpleNamespace

import pytest

from backend import db, meridian
from backend.brain import classify, network, pricing, sync

from .conftest import DALLAS, FSC_PER_MILE, carrier, customer, facility, seed, ship


# ---------- sync ----------

def test_sync_replaces_cache_and_drops_stale_classifications(monkeypatch):
    seed([ship("OLD1", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR")])
    data = {"/shipments": [{"shipment_id": "NEW1"}], "/vendors": [{"vendor_id": "V1"}],
            "/facilities": [], "/customers": [{"customer_id": "C1"}]}
    monkeypatch.setattr(meridian, "get_all", lambda path, **params: data[path])
    counts = sync.sync_all()
    assert counts == {"shipments": 1, "vendors": 1, "facilities": 0, "customers": 1}
    assert [s["shipment_id"] for s in db.load_records("shipments")] == ["NEW1"]
    assert classify.get_classifications() == {}


def test_failed_sync_leaves_cache_untouched(monkeypatch):
    seed([ship("KEEP", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR")])

    def flaky(path, **params):
        if path == "/facilities":
            raise meridian.MeridianError(503, "meridian_unreachable", "down")
        return []
    monkeypatch.setattr(meridian, "get_all", flaky)
    with pytest.raises(meridian.MeridianError):
        sync.sync_all()
    assert [s["shipment_id"] for s in db.load_records("shipments")] == ["KEEP"]


# ---------- classification ----------

class FakeParseClient:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self.parse))

    def parse(self, **kwargs):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        result = classify.Classification(**self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])


GENERAL = {"category": "GENERAL", "temp_controlled": False, "hazmat": False,
           "confidence": 0.8, "rationale": "x"}


def test_hazmat_flag_overrides_the_model():
    shipment, _ = ship("1", ("Houston", "TX"), ("Dallas", "TX"), "X", hazmat=True)
    result = classify.classify_shipment(shipment, FakeParseClient(GENERAL))
    assert result.category == "HAZMAT" and result.hazmat


def test_classify_all_caches_and_reclassifies_changed_freight(monkeypatch):
    a, _ = ship("A", ("Chicago", "IL"), ("Dallas", "TX"), "X", description="Steel")
    b, _ = ship("B", ("Chicago", "IL"), ("Dallas", "TX"), "X", description="Food")
    db.replace_records("shipments", [a, b], "shipment_id")
    fake = FakeParseClient(GENERAL)
    monkeypatch.setattr(classify, "_client", lambda: fake)

    assert classify.classify_all() == {"classified": 2, "skipped": 0, "failed": 0}
    assert classify.classify_all() == {"classified": 0, "skipped": 2, "failed": 0}
    assert fake.calls == 2

    b["freight_lines"][0]["description"] = "Frozen food"  # same id, different freight
    db.replace_records("shipments", [a, b], "shipment_id")
    assert classify.classify_all() == {"classified": 1, "skipped": 1, "failed": 0}


def test_classify_all_counts_failures(monkeypatch):
    a, _ = ship("A", ("Chicago", "IL"), ("Dallas", "TX"), "X")
    db.replace_records("shipments", [a], "shipment_id")
    monkeypatch.setattr(classify, "_client", lambda: FakeParseClient(RuntimeError("boom")))
    assert classify.classify_all() == {"classified": 0, "skipped": 0, "failed": 1}
    assert classify.get_classifications() == {}


def test_old_database_gets_input_hash_column(tmp_path, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "old.db"))
    with db.get_conn() as conn:
        conn.execute("CREATE TABLE classifications (shipment_id TEXT PRIMARY KEY, category TEXT "
                     "NOT NULL, temp_controlled INTEGER NOT NULL, hazmat INTEGER NOT NULL, "
                     "confidence REAL, rationale TEXT)")
    db.init_db()
    db.init_db()
    with db.get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(classifications)")}
    assert "input_hash" in columns


# ---------- pricing ----------

def test_buy_lines_use_the_larger_of_per_mile_and_outbound_share():
    lines = pricing.backhaul_buy_lines(925, avg_outbound_buy_frt=2100)
    assert lines[0] == {"charge_code": "FRT", "rate_basis": "FLAT", "quantity": 1, "rate": 1260.0,
                        "amount": 1260.0, "description": "Backhaul linehaul"}
    assert lines[1]["charge_code"] == "FSC" and lines[1]["rate_basis"] == "PER_MILE"
    assert lines[1]["quantity"] == 925 and lines[1]["amount"] == 925 * FSC_PER_MILE
    assert pricing.backhaul_buy_lines(925)[0]["amount"] == 1110.0
    assert pricing.backhaul_buy_lines(925, 1000)[0]["amount"] == 1110.0


def test_fsc_is_fetched_once(fake_meridian):
    pricing.backhaul_buy_lines(100)
    pricing.backhaul_buy_lines(200)
    assert [c for c in fake_meridian.calls if c[1] == "/fsc"] == [("GET", "/fsc", {})]


def test_estimate_margins_frt_and_passes_fsc_through():
    lines = [{"charge_code": "FRT", "amount": 1650.0}, {"charge_code": "FSC", "amount": 508.75}]
    assert pricing.estimate(lines, 18) == {
        "buy_total": 2158.75, "sell_total": 2520.95, "gp_amount": 362.2, "gp_pct": 14.4}


def test_margin_defaults_to_18():
    assert pricing.margin_for({"margin_floor_pct": 10}) == 10
    assert pricing.margin_for({}) == 18 and pricing.margin_for(None) == 18


# ---------- network ----------

def test_network_summary_totals(dallas):
    summary = network.network_summary()
    # Cancelled loads are excluded; LTL counts as a load but not as empty truck miles.
    assert summary["totals"] == {
        "empty_miles": 2 * 925 + 240 + 1050,
        "empty_cost_usd": (2 * 925 + 240 + 1050) * 2.0,
        "one_way_lanes": 4,
        "loads": 5,
    }
    dallas_city = next(c for c in summary["cities"] if c["city"] == "Dallas")
    assert (dallas_city["inbound"], dallas_city["outbound"]) == (3, 0)
    assert all(c["lat"] is not None for c in summary["cities"])
    arc = next(a for a in summary["arcs"] if a["from"]["city"] == "Chicago")
    assert arc["loads"] == 2 and arc["equipment"] == {"V": 2} and arc["miles"] == 925


def test_dallas_backhauls(dallas):
    prospects = network.find_backhauls("dallas", "tx")
    assert [(p["customer_id"], p["category"], p["origin"]["city"], p["destination"]["city"])
            for p in prospects] == [
        ("NORTHSTAR", "SCRAP", "Dallas", "Chicago"),
        ("KEYSTONE-TX", "RETAIL_RETURNS", "Fort Worth", "Columbus"),
    ]
    top = prospects[0]
    assert top["ok"] and top["score"] == 98 and top["miles_saved"] == 925
    assert top["carrier_id"] == "ACMECARR" and top["equipment"] == "V"
    # buy FRT = max(925 x 1.20, avg outbound FRT 2,100 x 0.60) = 1,260; FSC = 925 x 0.50.
    assert top["est_buy"] == 1260 + 462.5
    assert top["est_sell"] == round(1260 / 0.9, 2) + 462.5
    assert top["reasons"][-1].startswith("Source: reverse logistics")
    assert len({p["prospect_id"] for p in prospects}) == len(prospects)


def test_hazmat_truck_is_never_paired_with_a_return_that_moves_it_away_from_home(dallas):
    assert all(p["outbound_file"] != "7300003" for p in network.find_backhauls("Dallas", "TX"))


def test_find_prospect_round_trip(dallas):
    prospect = network.find_backhauls("Dallas", "TX")[0]
    assert network.find_prospect(prospect["prospect_id"]) == prospect
    assert network.find_prospect("nonsense") is None
    assert network.find_prospect("TX:Dallas:X:Y:Z:W:1") is None


def test_unknown_city_has_no_prospects(dallas):
    detail = network.city_detail("Nowhere", "ZZ")
    assert (detail["inbound"], detail["outbound"], detail["prospects"]) == (0, 0, [])


def test_fsma_block_shows_when_only_a_hazmat_trailer_can_take_food():
    seed(
        [ship("1", ("Houston", "TX"), ("Dallas", "TX"), "LONESTARCH", category="HAZMAT",
              carrier="BLUERIDGE", trailer="T9", miles=240, hazmat=True,
              description="Industrial cleaning compound (UN1760)"),
         ship("2", ("Fort Worth", "TX"), ("Houston", "TX"), "VALIANTFD", category="FOOD",
              carrier="ACMECARR", miles=265, mode="LTL")],
        [carrier("BLUERIDGE"), carrier("ACMECARR")], [],
        [customer("LONESTARCH"), customer("VALIANTFD")],
    )
    prospects = network.find_backhauls("Dallas", "TX")
    food = next(p for p in prospects if p["customer_id"] == "VALIANTFD")
    assert not food["ok"] and food["score"] == 0
    assert food["reasons"][0] == ("Blocked: trailer last hauled HAZMAT (UN1760); "
                                  "FSMA requires a washout before food.")


def test_trailer_history_uses_the_trailers_latest_load():
    seed(
        [ship("1", ("Houston", "TX"), ("Dallas", "TX"), "LONESTARCH", category="HAZMAT",
              trailer="T9", miles=240, pickup_date="2026-11-01", hazmat=True),
         ship("2", ("Houston", "TX"), ("Dallas", "TX"), "LONESTARCH", category="GENERAL",
              trailer="T9", miles=240, pickup_date="2026-11-05")],
        [carrier("ACMECARR")],
    )
    shipments = network._load()[0]
    assert network.trailer_history(shipments)[("ACMECARR", "T9")]["shipment_id"] == "2"


def test_unclassified_hazmat_shipment_is_still_treated_as_hazmat():
    shipment, _ = ship("1", ("Houston", "TX"), ("Dallas", "TX"), "X", hazmat=True)
    db.replace_records("shipments", [shipment], "shipment_id")
    loaded = network._load()[0][0]
    assert loaded["_category"] == "HAZMAT" and loaded["_hazmat"]


def test_cold_lead_prospect_scores_without_warm_bonus():
    seed(
        [ship("1", ("Rockford", "IL"), ("Aurora", "CO"), "FROSTLINE", category="FOOD",
              equipment="R", carrier="SUNRIDGE", miles=1000, temp=True)],
        [carrier("SUNRIDGE")], [],
        [customer("FROSTLINE"), customer("TRUENORTH", status="PROSPECT", city="Denver", state="CO")],
    )
    cold = next(p for p in network.find_backhauls("Aurora", "CO") if p["customer_id"] == "TRUENORTH")
    assert cold["ok"] and cold["category"] == "GENERAL"
    assert any(r.startswith("Cold lead") for r in cold["reasons"])
    assert cold["score"] < 70


def test_distance_uses_known_lane_miles_then_great_circle():
    assert network.distance_miles(("Dallas", "TX"), ("Dallas", "TX")) == 0
    assert network.distance_miles(("Dallas", "TX"), ("Nowhere", "ZZ")) is None
    fort_worth = network.distance_miles(("Dallas", "TX"), ("Fort Worth", "TX"))
    assert 25 < fort_worth < 45


def test_backhaul_prospects_carry_hours_of_service_dates(dallas):
    top = network.find_backhauls("Dallas", "TX")[0]
    assert top["pickup_date"] and top["delivery_date_target"] >= top["pickup_date"]
    assert top["est_pickup"] and top["est_delivery"]
    assert any(r.startswith("HOS: truck empty") for r in top["reasons"])
    assert top["reasons"][-1].startswith("Source:")


def test_hours_of_service_blocks_when_no_legal_pickup_day(monkeypatch):
    closed_mid_week = {"facility_id": "DC", "name": "DC", "city": "Dallas", "state": "TX", "facility_type": "DC",
                       "timezone": "America/Chicago", "avg_unload_minutes": 60,
                       # operating_hours with no weekday entries: closed every day, whatever today is
                       "operating_hours": {"note": "closed for renovation"}}
    seed([ship("1", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL", trailer="T1",
               miles=925, consignee_facility="DC", pickup_date="2026-11-01")],
         [carrier("ACMECARR")], [closed_mid_week], [customer("NORTHSTAR")])
    prospects = network.find_backhauls("Dallas", "TX")
    assert prospects and not prospects[0]["ok"] and prospects[0]["score"] == 0
    assert prospects[0]["reasons"][0].startswith("Blocked: HOS: no legal pickup within 3 days")


def test_old_inbound_loads_get_pickup_dates_from_today(dallas):
    from datetime import date
    today = date.today().isoformat()
    assert all(p["pickup_date"] >= today for p in network.find_backhauls("Dallas", "TX") if p["ok"])
