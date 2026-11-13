"""Pull all Meridian data into SQLite and classify every shipment. Run from the repo root.

Usage: python scripts/sync_data.py [--refresh]   (--refresh re-pulls every shipment's events)
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db  # noqa: E402
from backend.brain import classify, sync  # noqa: E402


def main():
    """Init the database, sync Meridian and its events, classify shipments, then print the totals."""
    db.init_db()
    sync.sync_all()
    sync.sync_events(refresh="--refresh" in sys.argv)
    classify.classify_all()
    categories = Counter(c["category"] for c in classify.get_classifications().values())
    print("categories:", dict(categories.most_common()))


if __name__ == "__main__":
    main()
