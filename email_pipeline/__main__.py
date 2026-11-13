"""Command line for trying the pipeline without the UI.

    python -m email_pipeline run demo/sample_emails/01_quote_dallas_returns.json [more files...]
    python -m email_pipeline run all            # every sample, in file order
    python -m email_pipeline inbox
    python -m email_pipeline outbox
    python -m email_pipeline approve <action_id> # Ryan's approval queue: approving a quote creates it in Meridian
    python -m email_pipeline reject <action_id>

Trucks and freight categories come from Ryan's cache, so run `python scripts/sync_data.py` once first.
"""

import json
import sys
from pathlib import Path

from backend import db
from backend.agent import actions

from email_pipeline import store
from email_pipeline.parse import parse_file
from email_pipeline.pipeline import process_email

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "demo" / "sample_emails"


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def run(paths):
    """Process each file and print a short summary line plus the full result."""
    if paths == ["all"]:
        paths = sorted(SAMPLES_DIR.glob("*.json"))
    for path in paths:
        result = process_email(parse_file(path))
        matched = result["matched"] or {}
        print(f"\n=== {Path(path).name}: {result['kind']} ({result['confidence']}) -> {result['status']}"
              f" | match: {matched.get('status')} | actions: {result['actions_created']}")
        if result["error"]:
            print("ERROR:", result["error"])
        _print(result)


def main(argv):
    """Entry point: dispatch on the first argument."""
    store.init_email_tables()
    if not db.load_records("shipments"):
        print("(Ryan's shipment cache is empty: run `python scripts/sync_data.py` first, "
              "or no trucks will match)", file=sys.stderr)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
    elif argv[0] == "run":
        run(argv[1:])
    elif argv[0] == "inbox":
        for row in store.list_emails():
            print(f"{row['email_id']}  {row['status']:<13} {row['kind'] or '':<15} {row['subject']}")
    elif argv[0] == "outbox":
        _print(store.list_replies())
    elif argv[0] == "approve":
        _print(actions.approve(argv[1], actor="cli"))
    elif argv[0] == "reject":
        _print(actions.reject(argv[1], argv[2] if len(argv) > 2 else None, actor="cli"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
