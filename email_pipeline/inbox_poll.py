"""Stretch: poll a real IMAP test inbox into the pipeline. Off unless EMAIL_POLL_ENABLED=1.

    EMAIL_POLL_ENABLED=1 IMAP_HOST=imap.gmail.com IMAP_USER=... IMAP_PASSWORD=<app password> \
        python -m email_pipeline.inbox_poll

Reads UNSEEN messages, runs each through process_email, and marks them seen. Replies are still
only drafts in the outbox; nothing is ever sent.
"""

import imaplib
import os
import time

from email_pipeline.parse import parse_eml
from email_pipeline.pipeline import process_email

POLL_SECONDS = int(os.getenv("EMAIL_POLL_SECONDS", "60"))


def enabled():
    """True only when the flag is explicitly on."""
    return os.getenv("EMAIL_POLL_ENABLED", "0") == "1"


def poll_once():
    """Fetch unseen messages from the configured mailbox and process each; returns the results."""
    if not enabled():
        return []
    results = []
    with imaplib.IMAP4_SSL(os.environ["IMAP_HOST"]) as imap:
        imap.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
        imap.select(os.getenv("IMAP_FOLDER", "INBOX"))
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            results.append(process_email(parse_eml(msg_data[0][1])))
            imap.store(num, "+FLAGS", "\\Seen")
    return results


def main():
    """Poll forever (Ctrl-C to stop)."""
    if not enabled():
        print("EMAIL_POLL_ENABLED is not 1; not polling.")
        return
    while True:
        for r in poll_once():
            print(f"{r['email_id']}: {r['kind']} -> {r['status']}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
