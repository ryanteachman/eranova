"""Live fixtures: real OpenAI, real Meridian reads, and a copy of the synced return_trip.db.

Run with:  RUN_LIVE_EMAIL_TESTS=1 python -m pytest -q email_pipeline/tests/live
Needs `python scripts/sync_data.py` to have filled return_trip.db, plus OPENAI_API_KEY and the TMS keys.
Costs a little OpenAI usage. Nothing is approved, so nothing is written to Meridian.
"""

import os
import shutil

import pytest

from backend import config, db
from email_pipeline import match, store

REAL_DB = config.ROOT / "return_trip.db"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Overrides the offline fixture: a copy of the real database with the email tables emptied."""
    if os.getenv("RUN_LIVE_EMAIL_TESTS") != "1":
        pytest.skip("live test: set RUN_LIVE_EMAIL_TESTS=1 to run it")
    if not REAL_DB.exists():
        pytest.skip("return_trip.db not found: run `python scripts/sync_data.py` first")
    copy = tmp_path / "live.db"
    shutil.copy(REAL_DB, copy)
    monkeypatch.setattr(config, "DB_PATH", str(copy))
    db.init_db()
    store.init_email_tables()
    if not db.load_records("shipments"):
        pytest.skip("the shipment cache is empty: run `python scripts/sync_data.py` first")
    # Start from a clean inbox so washouts / trailer history from earlier runs can't change the results.
    with db.get_conn() as conn:
        for table in ("emails", "outbox", "washouts", "actions"):
            conn.execute(f"DELETE FROM {table}")


@pytest.fixture(autouse=True)
def fake_meridian():
    """Overrides the offline fixture: talk to the real Meridian (reads only in these tests)."""
    match._search.cache_clear()
    return None
