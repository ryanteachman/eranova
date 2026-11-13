"""Pull Meridian shipments, vendors, facilities and customers into SQLite."""

import json
from concurrent.futures import ThreadPoolExecutor

from .. import db, meridian

EVENT_WORKERS = 8
# Activity logs of these shipments can no longer change.
FINAL_STATUSES = {"CLOSED", "CANCELLED", "TONU"}

# (Meridian route, cache table, id field)
SOURCES = [
    ("/shipments", "shipments", "shipment_id"),
    ("/vendors", "vendors", "vendor_id"),
    ("/facilities", "facilities", "facility_id"),
    ("/customers", "customers", "customer_id"),
]


def sync_all():
    """Replace the cache with every shipment, vendor, facility and customer in Meridian; return counts."""
    pulled = {table: (meridian.get_all(path), id_field) for path, table, id_field in SOURCES}
    counts = {}
    for table, (records, id_field) in pulled.items():
        counts[table] = db.replace_records(table, records, id_field)
        print(f"synced {counts[table]:>4} {table}")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM classifications WHERE shipment_id NOT IN (SELECT id FROM shipments)")
    db.audit("system", "sync", str(counts))
    return counts


def _save_events(shipment_id, events):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM events WHERE shipment_id = ?", (shipment_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO events (event_id, shipment_id, data) VALUES (?, ?, ?)",
            [(e["event_id"], shipment_id, json.dumps(e)) for e in events],
        )


def sync_events(refresh=False):
    """Pull each cached shipment's activity log into the events table; return {synced, skipped}."""
    shipments = db.load_records("shipments")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM events WHERE shipment_id NOT IN (SELECT id FROM shipments)")
        have = {row["shipment_id"] for row in conn.execute("SELECT DISTINCT shipment_id FROM events")}
    # Open shipments are always re-pulled: a carrier can still be bounced from them.
    todo = [s["shipment_id"] for s in shipments
            if refresh or s["shipment_id"] not in have or s.get("status") not in FINAL_STATUSES]

    def pull(shipment_id):
        return shipment_id, meridian.get_all(f"/shipments/{shipment_id}/events")

    with ThreadPoolExecutor(max_workers=EVENT_WORKERS) as pool:
        for shipment_id, events in pool.map(pull, todo):
            _save_events(shipment_id, events)
    counts = {"synced": len(todo), "skipped": len(shipments) - len(todo)}
    print(f"synced events for {counts['synced']} shipments, skipped {counts['skipped']}")
    db.audit("system", "sync_events", str(counts))
    return counts
