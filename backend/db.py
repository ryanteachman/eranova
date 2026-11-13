"""SQLite connection and schema: cache, classifications, actions and audit tables."""

import json
import sqlite3
from datetime import datetime, timezone

from . import config

CACHE_TABLES = ("shipments", "vendors", "facilities", "customers")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments  (id TEXT PRIMARY KEY, data TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vendors    (id TEXT PRIMARY KEY, data TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facilities (id TEXT PRIMARY KEY, data TEXT NOT NULL, synced_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS customers  (id TEXT PRIMARY KEY, data TEXT NOT NULL, synced_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS classifications (
    shipment_id     TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    temp_controlled INTEGER NOT NULL,
    hazmat          INTEGER NOT NULL,
    confidence      REAL,
    rationale       TEXT,
    input_hash      TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_shipment ON events (shipment_id);

CREATE TABLE IF NOT EXISTS actions (
    action_id  TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    title      TEXT,
    summary    TEXT,
    payload    TEXT,
    tier       TEXT,
    confidence REAL,
    reasoning  TEXT,
    status     TEXT NOT NULL,
    result     TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode       TEXT,
    decided_by TEXT,
    risk       TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    actor  TEXT NOT NULL,
    event  TEXT NOT NULL,
    detail TEXT
);
"""


def now_iso():
    """Return the current UTC time as an ISO-8601 string ending in Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn():
    """Open a SQLite connection to DB_PATH whose rows can be read like dicts."""
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# Columns added after the first release; older databases get them on init_db().
ADDED_COLUMNS = {
    "classifications": ["input_hash"],
    "actions": ["mode", "decided_by", "risk"],
}


def init_db():
    """Create all backend tables if they do not exist yet, adding any columns older databases lack."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, added in ADDED_COLUMNS.items():
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column in added:
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")


def replace_records(table, records, id_field):
    """Replace a cache table's contents with these Meridian records and return how many were written."""
    if table not in CACHE_TABLES:
        raise ValueError(f"not a cache table: {table}")
    synced_at = now_iso()
    rows = [(str(r[id_field]), json.dumps(r), synced_at) for r in records]
    # Meridian resets can delete records and change ids, so stale rows must not survive a sync.
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table}")
        conn.executemany(f"INSERT INTO {table} (id, data, synced_at) VALUES (?, ?, ?)", rows)
    return len(rows)


def load_records(table):
    """Return every cached record in a cache table as a list of dicts."""
    if table not in CACHE_TABLES:
        raise ValueError(f"not a cache table: {table}")
    with get_conn() as conn:
        return [json.loads(row["data"]) for row in conn.execute(f"SELECT data FROM {table}")]


def get_setting(key, default=None):
    """Return a stored setting's value, or default when it was never set."""
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    """Store a setting's value."""
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))


def load_events():
    """Return every cached Meridian shipment event as a list of dicts."""
    with get_conn() as conn:
        return [json.loads(row["data"]) for row in conn.execute("SELECT data FROM events")]


def audit(actor, event, detail=""):
    """Append one row to the audit log."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (at, actor, event, detail) VALUES (?, ?, ?, ?)",
            (now_iso(), actor, event, detail),
        )
