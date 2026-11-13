"""Routes: /api/agent/chat and /api/audit."""

from flask import Blueprint, request

from .. import db
from ..agent import loop
from ..errors import BadRequest

bp = Blueprint("agent", __name__, url_prefix="/api")

MAX_AUDIT_LIMIT = 500


@bp.post("/agent/chat")
def chat():
    """Send one message to the agent and return its reply, tool calls and queued actions."""
    body = request.get_json(silent=True)
    message = body.get("message") if isinstance(body, dict) else None
    if not message or not isinstance(message, str):
        raise BadRequest("message is required.")
    return loop.run_agent("human", message)


@bp.get("/audit")
def audit():
    """Return the newest audit log entries (?limit=, default 50)."""
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), MAX_AUDIT_LIMIT))
    except ValueError:
        raise BadRequest("limit must be an integer.")
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT at, actor, event, detail FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(row) for row in rows]}
