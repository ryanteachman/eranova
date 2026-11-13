"""Decline every Return Trip quote in Meridian and clear pending actions. Run from the repo root."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, meridian  # noqa: E402

MARKER = "return-trip:"
# Statuses /quotes/{id}/decline accepts (EXPIRED covers expired QUOTED and SENT quotes).
DECLINABLE = ["QUOTED", "SENT", "ACCEPTED", "EXPIRED"]


def return_trip_quotes():
    """Return every declinable quote whose notes contain the Return Trip marker."""
    found = {}
    for status in DECLINABLE:
        for quote in meridian.get_all("/quotes", status=status):
            if any(MARKER in (note.get("text") or "") for note in quote.get("notes") or []):
                found[quote["quote_id"]] = quote
    return list(found.values())


def main():
    """Decline Return Trip quotes, delete pending actions, and print what was done."""
    db.init_db()
    declined = 0
    for quote in return_trip_quotes():
        try:
            meridian.post(f"/quotes/{quote['quote_id']}/decline", {"reason": "Return Trip demo reset"})
            declined += 1
            print(f"declined quote {quote['quote_id']}")
        except meridian.MeridianError as exc:
            print(f"could not decline {quote['quote_id']}: {exc.detail}")
    with db.get_conn() as conn:
        cleared = conn.execute("DELETE FROM actions WHERE status = 'pending'").rowcount
    db.audit("system", "reset_demo", f"declined {declined} quotes, cleared {cleared} pending actions")
    print(f"declined {declined} quotes, cleared {cleared} pending actions")


if __name__ == "__main__":
    main()
