"""Pull Meridian shipments, vendors, facilities and customers into SQLite."""

from .. import db, meridian

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
