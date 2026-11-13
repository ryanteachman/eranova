"""Shared fixtures: a temporary database, a seeded Dallas dataset and a fake Meridian."""

import pytest

from backend import config, db, meridian
from backend.brain import pricing

FSC_PER_MILE = 0.5


def ship(shipment_id, origin, dest, customer, *, category="GENERAL", mode="TL", equipment="V",
         carrier="ACMECARR", trailer=None, miles=500, status="DELIVERED", frt=1000,
         consignee_facility="", description="General freight", hazmat=False,
         temp=False, weight=20000, pallets=10, pickup_date="2026-11-01"):
    """Build a Meridian-shaped shipment plus its classification row."""
    shipment = {
        "shipment_id": shipment_id, "status": status, "mode": mode, "equipment_type": equipment,
        "customer_id": customer, "shipper_city": origin[0], "shipper_state": origin[1],
        "consignee_city": dest[0], "consignee_state": dest[1], "miles": miles,
        "carrier_id": carrier, "trailer_number": trailer, "pickup_date": pickup_date,
        "freight_lines": [{"description": description, "hazmat": hazmat, "pieces": 10,
                           "package_type": "PALLET", "weight_lb": weight}],
        "freight_totals": {"actual_lb": weight, "pallet_positions": pallets},
        "vendor_costs": [{"charge_code": "FRT", "amount": frt, "status": "CONFIRMED"}] if frt else [],
        "stops": [{"stop_type": "PICKUP", "facility_id": ""},
                  {"stop_type": "DELIVERY", "facility_id": consignee_facility}],
    }
    label = {"shipment_id": shipment_id, "category": category, "temp_controlled": int(temp),
             "hazmat": int(hazmat), "confidence": 0.9, "rationale": "test", "input_hash": None}
    return shipment, label


def carrier(vendor_id, *, status="ACTIVE", cargo_expires="2099-01-01", hazmat=False):
    return {"vendor_id": vendor_id, "vendor_type": "TRUCKLOAD_CARRIER", "status": status,
            "hazmat_certified": hazmat,
            "insurance": [{"policy_type": "CARGO", "expiration_date": cargo_expires}]}


def facility(facility_id, city, state, facility_type="WAREHOUSE", name=None):
    return {"facility_id": facility_id, "name": name or facility_id, "city": city, "state": state,
            "facility_type": facility_type, "latitude": None, "longitude": None}


def customer(customer_id, *, status="ACTIVE", margin=10, city=None, state=None):
    addresses = [{"address_type": "MAIN", "city": city, "state": state}] if city else []
    return {"customer_id": customer_id, "legal_name": f"{customer_id} Inc.", "status": status,
            "margin_floor_pct": margin, "addresses": addresses}


def seed(shipments, vendors=(), facilities=(), customers=()):
    """Write a dataset into the cache tables and classifications."""
    db.replace_records("shipments", [s for s, _ in shipments], "shipment_id")
    db.replace_records("vendors", list(vendors), "vendor_id")
    db.replace_records("facilities", list(facilities), "facility_id")
    db.replace_records("customers", list(customers), "customer_id")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM classifications")
        conn.executemany(
            "INSERT INTO classifications (shipment_id, category, temp_controlled, hazmat, "
            "confidence, rationale, input_hash) VALUES (:shipment_id, :category, "
            ":temp_controlled, :hazmat, :confidence, :rationale, :input_hash)",
            [label for _, label in shipments],
        )


DALLAS = [
    ship("7300001", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL",
         trailer="T1", miles=925, frt=2000, consignee_facility="BBR-DC135",
         description="Machined steel components", weight=40000, pallets=20),
    ship("7300002", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL",
         trailer="T2", miles=925, frt=2200, consignee_facility="BBR-DC135",
         description="Machined steel components", weight=40000, pallets=20),
    ship("7300003", ("Houston", "TX"), ("Dallas", "TX"), "LONESTARCH", category="HAZMAT",
         carrier="BLUERIDGE", trailer="T9", miles=240, frt=700, consignee_facility="BBR-DC135",
         description="Industrial cleaning compound (UN1760)", hazmat=True),
    ship("7300004", ("Columbus", "OH"), ("Fort Worth", "TX"), "KEYSTONE-TX", trailer="T5",
         miles=1050, frt=2400, consignee_facility="KEYSTONE-FTW", description="Patio furniture"),
    ship("7300005", ("Pittsburgh", "PA"), ("Newark", "NJ"), "IRONPEAK", category="STEEL",
         mode="LTL", miles=370, consignee_facility="TRISTATE-EWR"),
    ship("7300006", ("Chicago", "IL"), ("Dallas", "TX"), "NORTHSTAR", category="STEEL",
         status="CANCELLED", trailer="T3", miles=925, consignee_facility="BBR-DC135"),
]
DALLAS_VENDORS = [carrier("ACMECARR"), carrier("BLUERIDGE"), carrier("BADWOLF", status="DO_NOT_USE")]
DALLAS_FACILITIES = [
    facility("BBR-DC135", "Dallas", "TX", "DC", name="Big-Box Retailer DC135"),
    facility("KEYSTONE-FTW", "Fort Worth", "TX", "WAREHOUSE"),
    facility("TRISTATE-EWR", "Newark", "NJ", "CROSS_DOCK"),
]
DALLAS_CUSTOMERS = [customer("NORTHSTAR"), customer("LONESTARCH"), customer("KEYSTONE-TX"),
                    customer("IRONPEAK"), customer("TRUENORTH", status="PROSPECT",
                                                    city="Denver", state="CO")]


class FakeMeridian:
    """Records Meridian calls and answers them like the sandbox would."""

    def __init__(self):
        self.calls = []
        self.fail = {}
        self.next_quote_id = 7300900

    def _maybe_fail(self, method, path):
        for (fail_method, prefix), error in self.fail.items():
            if fail_method == method and path.startswith(prefix):
                raise error

    def get(self, path, **params):
        self.calls.append(("GET", path, params))
        self._maybe_fail("GET", path)
        if path == "/fsc":
            return {"tl_per_mile": FSC_PER_MILE}
        if path.startswith("/shipments/"):
            return {"shipment_id": path.split("/")[-1]}
        if path == "/search":
            return {"references": [], "customers": [], "vendors": [], "facilities": []}
        return {"items": [], "count": 0, "next_cursor": None}

    def get_all(self, path, **params):
        return self.get(path, **params)["items"]

    def post(self, path, body=None):
        self.calls.append(("POST", path, body))
        self._maybe_fail("POST", path)
        if path == "/quotes/price-preview":
            return pricing.estimate(body["buy_lines"], body["target_margin_pct"])
        if path == "/quotes":
            self.next_quote_id += 1
            return {"quote_id": str(self.next_quote_id), "status": "DRAFT"}
        return {"ok": True}

    def put(self, path, body):
        self.calls.append(("PUT", path, body))
        self._maybe_fail("PUT", path)
        quote_id = path.split("/")[-1]
        return {"quote_id": quote_id, "summary": f"Quote {quote_id} | QUOTED", "sell_total": 1234.5}


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point every test at its own empty SQLite database."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "TMS_UI_URL", "https://tms.example")
    db.init_db()


@pytest.fixture(autouse=True)
def fake_meridian(monkeypatch):
    """Replace the Meridian client so no test touches the real sandbox."""
    fake = FakeMeridian()
    for name in ("get", "get_all", "post", "put"):
        monkeypatch.setattr(meridian, name, getattr(fake, name))
    monkeypatch.setattr(pricing, "_fsc_cache", {})
    return fake


@pytest.fixture
def dallas():
    """Seed the Dallas dataset."""
    seed(DALLAS, DALLAS_VENDORS, DALLAS_FACILITIES, DALLAS_CUSTOMERS)


@pytest.fixture
def client(dallas):
    from backend import create_app
    return create_app().test_client()
