"""SQLite tables owned by the email pipeline: emails, outbox and washouts."""

import json
import uuid
from datetime import datetime, timezone

from email_pipeline.deps import get_conn

EMAIL_STATUSES = ("new", "processing", "processed", "needs_review", "failed")
OUTBOX_STATUSES = ("draft", "approved_sent", "rejected")

# Columns holding JSON text; decoded on the way out.
JSON_COLUMNS = ("extracted", "matched", "action_ids", "attachments")


def now_iso():
    """Current UTC time as ISO-8601 with a Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_email_tables():
    """Create the emails, outbox and washouts tables if they don't exist yet."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS emails (
                email_id     TEXT PRIMARY KEY,
                from_addr    TEXT,
                to_addr      TEXT,
                subject      TEXT,
                body         TEXT,
                attachments  TEXT,
                received_at  TEXT,
                kind         TEXT,
                confidence   REAL,
                rationale    TEXT,
                extracted    TEXT,
                matched      TEXT,
                status       TEXT NOT NULL DEFAULT 'new',
                action_ids   TEXT,
                error        TEXT
            );
            CREATE TABLE IF NOT EXISTS outbox (
                reply_id     TEXT PRIMARY KEY,
                email_id     TEXT,
                to_addr      TEXT,
                subject      TEXT,
                body         TEXT,
                status       TEXT NOT NULL DEFAULT 'draft',
                action_id    TEXT,
                created_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS washouts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                carrier_id      TEXT,
                trailer_number  TEXT,
                washed_at       TEXT,
                facility        TEXT,
                cert_number     TEXT,
                source_email_id TEXT
            );
            """
        )


def _row_to_dict(row):
    """sqlite3.Row → dict with the JSON columns decoded."""
    if row is None:
        return None
    item = dict(row)
    for col in JSON_COLUMNS:
        if col in item and item[col]:
            item[col] = json.loads(item[col])
    return item


# ---------- emails ----------

def insert_email(email):
    """Store a parsed email as status 'new' and return its new email_id."""
    email_id = "em_" + uuid.uuid4().hex[:10]
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO emails (email_id, from_addr, to_addr, subject, body, attachments,
                                   received_at, status, action_ids)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'new', '[]')""",
            (email_id, email["from"], email.get("to"), email["subject"], email["body"],
             json.dumps(email.get("attachments", [])), email.get("received_at") or now_iso()),
        )
    return email_id


def update_email(email_id, **fields):
    """Update some columns of one email; dicts and lists are stored as JSON."""
    if not fields:
        return
    values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    assignments = ", ".join(f"{col} = ?" for col in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE emails SET {assignments} WHERE email_id = ?", (*values, email_id))


def get_email(email_id):
    """Return one email row as a dict (JSON columns decoded), or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE email_id = ?", (email_id,)).fetchone()
    return _row_to_dict(row)


def list_emails(status=None, limit=100):
    """Return inbox rows, newest first, optionally filtered by status."""
    sql = "SELECT * FROM emails"
    params = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY received_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def add_action_id(email_id, action_id):
    """Append an action id to the email's action_ids list."""
    email = get_email(email_id)
    ids = (email.get("action_ids") or []) + [action_id]
    update_email(email_id, action_ids=ids)


def quote_action_for_email(email_id):
    """The create_return_quote action id proposed for this email (from Ryan's actions table), or None."""
    ids = (get_email(email_id) or {}).get("action_ids") or []
    if not ids:
        return None
    marks = ",".join("?" * len(ids))
    with get_conn() as conn:
        row = conn.execute(
            f"SELECT action_id FROM actions WHERE kind = 'create_return_quote' AND action_id IN ({marks})", ids
        ).fetchone()
    return row["action_id"] if row else None


# ---------- outbox ----------

def insert_reply(email_id, to_addr, subject, body):
    """Store a draft reply in the outbox and return its reply_id."""
    reply_id = "rp_" + uuid.uuid4().hex[:10]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO outbox VALUES (?, ?, ?, ?, ?, 'draft', NULL, ?)",
            (reply_id, email_id, to_addr, subject, body, now_iso()),
        )
    return reply_id


def update_reply(reply_id, **fields):
    """Update some columns of one outbox row."""
    assignments = ", ".join(f"{col} = ?" for col in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE outbox SET {assignments} WHERE reply_id = ?", (*fields.values(), reply_id))


def get_reply(reply_id):
    """Return one outbox row as a dict, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM outbox WHERE reply_id = ?", (reply_id,)).fetchone()
    return dict(row) if row else None


def list_replies(status=None, email_id=None):
    """Return outbox rows, newest first, optionally filtered by status or email."""
    sql, clauses, params = "SELECT * FROM outbox", [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if email_id:
        clauses.append("email_id = ?")
        params.append(email_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, rowid DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------- washouts ----------

def insert_washout(carrier_id, trailer_number, washed_at, facility, cert_number, source_email_id):
    """Record a washout certificate and return its row id."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO washouts (carrier_id, trailer_number, washed_at, facility, cert_number,
                                     source_email_id) VALUES (?, ?, ?, ?, ?, ?)""",
            (carrier_id, str(trailer_number) if trailer_number else None, washed_at, facility,
             cert_number, source_email_id),
        )
        return cur.lastrowid


def washouts_for_trailer(trailer_number):
    """Return every washout on file for one trailer number."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM washouts WHERE trailer_number = ? ORDER BY washed_at DESC",
            (str(trailer_number),),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- audit ----------

def audit(event, detail):
    """Write one line to Ryan's audit_log as actor 'email_pipeline'."""
    if not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (at, actor, event, detail) VALUES (?, 'email_pipeline', ?, ?)",
            (now_iso(), event, detail),
        )
