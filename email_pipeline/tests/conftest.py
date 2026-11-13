"""Shared fixtures for the email pipeline tests.

Ryan's backend fixtures are reused as-is: `tmp_db` (every test gets its own empty SQLite file) and
`fake_meridian` (no test touches the real TMS) are autouse. On top of that, `fake_llm` replaces the
OpenAI call with scripted answers, and `dallas_trucks` seeds a small Dallas dataset for matching.
"""

import pytest

from backend.tests.conftest import (  # noqa: F401  (fixtures are found by name)
    FakeMeridian, carrier, customer, fake_meridian, seed, ship, tmp_db,
)
from email_pipeline import classify, extract, haggle, match, reply, store

CHICAGO_HOURS = {day: {"open": "05:00", "close": "22:00"}
                 for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


@pytest.fixture(autouse=True)
def email_tables(tmp_db, fake_meridian):
    """Our tables (emails, outbox, washouts) in the test database, and no cached /search answers.
    Depends on tmp_db so the tables land in the test's own database."""
    store.init_email_tables()
    match._search.cache_clear()


class FakeLLM:
    """Answers llm.structured() calls from a script keyed by the response model's class name.

    A value can be a dict (validated into the model), a list (one item per call), or an exception to raise.
    """

    def __init__(self):
        self.script, self.calls = {}, []

    def __call__(self, system_prompt, user_text, response_model, model=None):
        name = response_model.__name__
        self.calls.append((name, user_text))
        if name not in self.script:
            raise AssertionError(f"FakeLLM has no answer scripted for {name}")
        answer = self.script[name]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return response_model.model_validate(answer)


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace every module's `structured` (they import it by name) with one scripted fake."""
    fake = FakeLLM()
    for module in (classify, extract, reply, haggle):
        monkeypatch.setattr(module, "structured", fake)
    return fake


def dated(shipment, delivery_date, status):
    """Give a ship() record a delivery date and status (the backend helper has no parameter for them)."""
    shipment[0]["delivery_date_target"] = delivery_date
    shipment[0]["status"] = status
    return shipment


@pytest.fixture
def dallas_trucks():
    """Four trucks emptying in Dallas, like the real data: two Acme steel loads (one empties a day late),
    a Lone Star UN1760 hazmat trailer, and a Prairie Haul truck that delivered days ago."""
    shipments = [
        dated(ship("7300001", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL", trailer="T1",
                   miles=925, consignee_facility="BBR-DC135", pickup_date="2026-11-14"), "2026-11-16", "DISPATCHED"),
        dated(ship("7300002", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL", trailer=None,
                   miles=925, consignee_facility="BBR-DC135", pickup_date="2026-11-15"), "2026-11-17", "COVERED"),
        dated(ship("7300003", ("Houston", "TX"), ("Dallas", "TX"), "LONESTARCH", category="HAZMAT", carrier="BLUERIDGE",
                   trailer="T9", miles=240, consignee_facility="BBR-DC135", hazmat=True, pickup_date="2026-11-12",
                   description="Industrial cleaning compound (UN1760)"), "2026-11-13", "IN_TRANSIT"),
        dated(ship("7300004", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL", carrier="PRAIRIEHL",
                   trailer="T7", miles=925, consignee_facility="BBR-DC135", pickup_date="2026-11-11"),
              "2026-11-13", "DELIVERED"),
    ]
    midway = customer("MIDWAYDST")
    midway["contacts"] = [{"name": "Chip Delgado", "email": "cdelgado@midwaydist.example.com", "role": "OPS"}]
    dc135 = {"facility_id": "BBR-DC135", "name": "Big-Box Retailer DC135", "city": "Dallas", "state": "TX",
             "facility_type": "DC", "timezone": "America/Chicago", "avg_unload_minutes": 150,
             "operating_hours": CHICAGO_HOURS, "compliance_flags": ["SEAL_REQUIRED"]}
    seed(shipments, [carrier("ACMECARR"), carrier("BLUERIDGE"), carrier("PRAIRIEHL")], [dc135],
         [customer("NORTHSTAR"), customer("LONESTARCH"), midway])


def quote_request(**overrides):
    """An extracted QUOTE_REQUEST like sample 07: 20 pallets of dry grocery, Dallas → Kansas City, Mon 11/16."""
    data = {
        "customer_hint": "Midway Distributors",
        "origin": {"city": "Dallas", "state": "TX", "zip": None, "name": None},
        "destination": {"city": "Kansas City", "state": "MO", "zip": None, "name": None},
        "pickup_date": "2026-11-16",
        "equipment": "V",
        "freight_lines": [{"pieces": 20, "weight_lb": 31000.0, "package_type": "PALLET",
                           "description": "canned goods and boxed dry grocery"}],
        "accessorials": [],
        "references": [{"type": "PO", "value": "MD-55190"}],
        "temp_controlled": False,
        "hazmat": False,
        "category": "FOOD",
    }
    data.update(overrides)
    return data


MIDWAY_EMAIL = {
    "from": "Chip Delgado <cdelgado@midwaydist.example.com>",
    "to": "quotes@meridianlogistics.example.com",
    "subject": "Dallas to KC dry grocery - Mon 11/16",
    "body": "Pickup Big-Box DC135, Dallas TX Monday 11/16. Deliver Kansas City MO. 20 pallets, 31,000 lbs, dry "
            "grocery, food grade trailer please. Our PO is MD-55190.",
    "received_at": "2026-11-13T20:10:00Z",
    "attachments": [],
}
