"""Tests for the deterministic compatibility rules."""

from backend import db
from backend.brain import compat

from .conftest import carrier

ACTIVE = carrier("ACMECARR")
TODAY = "2026-11-13"


def load(category="GENERAL", temp=False, hazmat=False, weight=20000, pallets=10):
    return {"category": category, "temp_controlled": temp, "hazmat": hazmat,
            "weight_lb": weight, "pallet_positions": pallets}


def check(last, equipment, candidate, vendor=ACTIVE, **kwargs):
    return compat.check_compat(last, equipment, candidate, vendor, today=TODAY, **kwargs)


def test_compatible_load_passes_with_reasons():
    ok, reasons = check("STEEL", "V", load())
    assert ok
    assert reasons and not any(r.startswith("Blocked") for r in reasons)


def test_reefer_hauls_temp_controlled_and_dry_van_does_not():
    assert check("FOOD", "R", load("FOOD", temp=True))[0]
    ok, reasons = check("FOOD", "V", load("FOOD", temp=True))
    assert not ok and reasons[0].startswith("Blocked: FOOD freight needs a reefer")


def test_flatbed_only_hauls_flatbed_freight():
    assert check("STEEL", "F", load("SCRAP"))[0]
    ok, reasons = check("STEEL", "F", load("RETAIL_RETURNS"))
    assert not ok and "flatbed" in reasons[0]


def test_unknown_equipment_is_blocked():
    assert not check("STEEL", None, load())[0]


def test_fsma_blocks_food_after_hazmat_and_names_the_rule():
    ok, reasons = check("HAZMAT", "V", load("FOOD"), trailer_number="T9", last_load_note="UN1760")
    assert not ok
    assert reasons[0] == ("Blocked: trailer last hauled HAZMAT (UN1760); "
                          "FSMA requires a washout before food.")


def test_fsma_applies_to_chemical_and_waste_and_beverage():
    for last in ("CHEMICAL", "WASTE"):
        assert not check(last, "V", load("BEVERAGE"))[0]


def test_fsma_allows_food_after_non_contaminant():
    assert check("STEEL", "V", load("FOOD"))[0]


def test_fsma_washout_on_file_unblocks():
    with db.get_conn() as conn:
        conn.execute("CREATE TABLE washouts (trailer_number TEXT)")
        conn.execute("INSERT INTO washouts VALUES ('T9')")
    ok, reasons = check("HAZMAT", "V", load("FOOD"), trailer_number="T9")
    assert ok and any("washout certificate is on file" in r for r in reasons)
    assert not check("HAZMAT", "V", load("FOOD"), trailer_number="T10")[0]


def test_missing_washouts_table_means_no_washout():
    assert compat.washout_on_file("T9") is False


def test_hazmat_needs_certified_carrier():
    ok, reasons = check("STEEL", "V", load("HAZMAT", hazmat=True))
    assert not ok and "hazmat-certified" in reasons[0]
    assert check("STEEL", "V", load("HAZMAT", hazmat=True), vendor=carrier("X", hazmat=True))[0]


def test_dry_van_size_limit():
    assert check("STEEL", "V", load(weight=45000, pallets=26))[0]
    assert not check("STEEL", "V", load(weight=45001))[0]
    assert not check("STEEL", "V", load(pallets=27))[0]


def test_carrier_must_be_active_with_unexpired_cargo():
    assert not check("STEEL", "V", load(), vendor=carrier("X", status="PENDING"))[0]
    assert not check("STEEL", "V", load(), vendor=carrier("X", cargo_expires="2026-11-12"))[0]
    assert check("STEEL", "V", load(), vendor=carrier("X", cargo_expires=TODAY))[0]
    assert not check("STEEL", "V", load(), vendor={"vendor_id": "UNKNOWN"})[0]


def test_blocked_reasons_come_first():
    ok, reasons = check("HAZMAT", "V", load("FOOD", temp=True), vendor=carrier("X", status="INACTIVE"))
    assert not ok
    blocked = [r for r in reasons if r.startswith("Blocked")]
    assert reasons[:len(blocked)] == blocked and len(blocked) == 3
