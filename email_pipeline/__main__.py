"""Command line for trying the pipeline without the UI.

    python -m email_pipeline run demo/sample_emails/01_quote_dallas_returns.json [more files...]
    python -m email_pipeline run all            # every sample, in file order
    python -m email_pipeline inbox
    python -m email_pipeline outbox
    python -m email_pipeline approve <action_id> # stub queue only, until Ryan's actions land
"""

import json
import sys
from pathlib import Path

from email_pipeline import store
from email_pipeline.deps import STUBBED
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
    if STUBBED:
        print(f"(using stubs for: {', '.join(STUBBED)})", file=sys.stderr)
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
        from email_pipeline._stubs import approve
        _print(approve(argv[1]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
