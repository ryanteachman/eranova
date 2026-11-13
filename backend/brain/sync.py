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
    """Pull every shipment, vendor, facility and customer from Meridian and return counts per table."""
    counts = {}
    for path, table, id_field in SOURCES:
        records = meridian.get_all(path)
        counts[table] = db.upsert_records(table, records, id_field)
        print(f"synced {counts[table]:>4} {table}")
    db.audit("system", "sync", str(counts))
    return counts
