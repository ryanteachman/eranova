"""Print every carrier's scorecard as a table. Run from the repo root after scripts/sync_data.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db  # noqa: E402
from backend.brain import carrier_score  # noqa: E402


def _pct(value):
    return "-" if value is None else f"{value}%"


def main():
    """Print carrier, loads, stored vs actual on-time, late causes, damage, bounces and base score."""
    db.init_db()
    cards = carrier_score.all_scorecards()
    header = f"{'carrier':11} {'name':26} {'loads':>5} {'stored':>7} {'actual':>7} " \
             f"{'late c/e/u':>10} {'dmg':>4} {'bnc':>4} {'score':>6}"
    print(header)
    print("-" * len(header))
    for c in cards:
        late = c["late_by_cause"]
        print(f"{c['vendor_id']:11} {(c['legal_name'] or '')[:26]:26} {c['loads']:>5} "
              f"{_pct(c['on_time_stored_pct']):>7} {_pct(c['on_time_actual_pct']):>7} "
              f"{late['carrier']}/{late['excused']}/{late['unknown']:<6} {c['damage']:>4} "
              f"{c['bounces']:>4} {c['base_score']:>6}")
    print(f"\n{len(cards)} carriers. late c/e/u = carrier fault / excused / unknown reason.")


if __name__ == "__main__":
    main()
