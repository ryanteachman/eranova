"""Turn a raw .eml file or a JSON email into one plain dict.

Output shape: {from, to, subject, body, received_at, attachments:[{filename, content_type, text}]}
"""

import json
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

TEXT_TYPES = ("text/plain", "text/csv", "text/html")


def parse_eml(raw_bytes):
    """Parse RFC 822 bytes into the standard email dict (plain-text body, text attachments inlined)."""
    msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""

    attachments = []
    for part in msg.iter_attachments():
        content_type = part.get_content_type()
        text = part.get_content() if content_type in TEXT_TYPES else None
        attachments.append({"filename": part.get_filename(), "content_type": content_type, "text": text})

    received_at = None
    if msg["Date"]:
        try:
            received_at = parsedate_to_datetime(msg["Date"]).isoformat()
        except (TypeError, ValueError):
            pass

    return {
        "from": str(msg["From"] or ""),
        "to": str(msg["To"] or ""),
        "subject": str(msg["Subject"] or ""),
        "body": body.strip(),
        "received_at": received_at,
        "attachments": attachments,
    }


def parse_json(data):
    """Normalize a JSON email (dict) into the standard email dict; accepts from/from_addr keys."""
    attachments = [
        {"filename": a.get("filename"), "content_type": a.get("content_type"), "text": a.get("text")}
        for a in data.get("attachments") or []
    ]
    return {
        "from": data.get("from") or data.get("from_addr") or "",
        "to": data.get("to") or data.get("to_addr") or "",
        "subject": data.get("subject") or "",
        "body": (data.get("body") or "").strip(),
        "received_at": data.get("received_at"),
        "attachments": attachments,
    }


def parse_file(path):
    """Read a .eml or .json file from disk and return the standard email dict."""
    path = Path(path)
    if path.suffix.lower() == ".eml":
        return parse_eml(path.read_bytes())
    return parse_json(json.loads(path.read_text(encoding="utf-8")))


def as_prompt_text(email):
    """Render the email (and any attachment text) as one block for an LLM prompt."""
    lines = [
        f"From: {email['from']}",
        f"To: {email.get('to', '')}",
        f"Date received: {email.get('received_at') or 'unknown'}",
        f"Subject: {email['subject']}",
        "",
        email["body"],
    ]
    for att in email.get("attachments", []):
        lines += ["", f"--- Attachment: {att.get('filename')} ({att.get('content_type')}) ---"]
        lines.append(att.get("text") or "(binary attachment, no text extracted)")
    return "\n".join(lines)
