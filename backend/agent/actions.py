"""Approval queue: propose, approve, reject and execute actions."""

import contextvars
import json
import uuid

from .. import config, db, meridian
from ..errors import Conflict, NotFound
from . import autonomy

EXECUTORS = {}

FIELDS = ("action_id", "kind", "title", "summary", "payload", "tier", "confidence",
          "reasoning", "status", "result", "created_at", "mode", "decided_by", "risk")

# True while an executor runs. Actions proposed from inside one (e.g. a re-queued reply) are never
# auto-executed, so an executor can't trigger itself in a loop.
_INSIDE_EXECUTOR = contextvars.ContextVar("inside_executor", default=False)


def executor(kind):
    """Register the function that performs an approved action of this kind: fn(payload) -> result dict."""
    def decorator(fn):
        EXECUTORS[kind] = fn
        return fn
    return decorator


def _row_to_action(row):
    action = {field: row[field] for field in FIELDS}
    for field in ("payload", "result", "risk"):
        action[field] = json.loads(action[field]) if action[field] else None
    return action


def get(action_id):
    """Return one action as a dict, or None if it does not exist."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
    return _row_to_action(row) if row else None


def list_actions(status=None):
    """Return actions newest first, optionally only those with this status."""
    sql, args = "SELECT * FROM actions", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    with db.get_conn() as conn:
        rows = conn.execute(sql + " ORDER BY created_at DESC, rowid DESC", args).fetchall()
    return [_row_to_action(row) for row in rows]


def propose(kind, title, summary, payload, confidence=None, reasoning=None, actor="agent"):
    """Queue an action, then let the decision mode run it as the AI or leave it pending; return it."""
    if kind not in EXECUTORS:
        raise ValueError(f"no executor registered for {kind!r}")
    # A double-clicked Fill or a repeated agent call must not queue the same write twice; the
    # existing action is decided again under the current mode instead.
    for existing in list_actions("pending"):
        if existing["kind"] == kind and existing["payload"] == payload:
            return _apply_mode(existing)
    now = db.now_iso()
    action_id = "act_" + uuid.uuid4().hex[:8]
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO actions (action_id, kind, title, summary, payload, tier, confidence, "
            "reasoning, status, result, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'approve', ?, ?, 'pending', NULL, ?, ?)",
            (action_id, kind, title, summary, json.dumps(payload), confidence, reasoning, now, now),
        )
    db.audit(actor, "action_proposed", f"{action_id} {kind}: {title}")
    return _apply_mode(get(action_id))


def _apply_mode(action):
    """Record the mode's decision on a pending action and execute it as the AI when allowed."""
    mode, risk, execute = autonomy.decide(action)
    if _INSIDE_EXECUTOR.get():
        execute = False
    with db.get_conn() as conn:
        conn.execute("UPDATE actions SET mode = ?, risk = ? WHERE action_id = ?",
                     (mode, json.dumps(risk), action["action_id"]))
    if execute:
        db.audit("ai", "action_auto_approved", f"{action['action_id']} ({mode} mode, risk {risk['level']})")
        return approve(action["action_id"], actor="ai")
    if mode != "approval":
        db.audit("ai", "action_held", f"{action['action_id']} ({mode} mode): {autonomy.hold_message(mode, risk)}")
    return get(action["action_id"])


def _release_waiting():
    """Re-decide pending actions that were only waiting on another action (e.g. a reply on its quote)."""
    if autonomy.get_mode() == "approval" or _INSIDE_EXECUTOR.get():
        return
    for action in list_actions("pending"):
        if (action.get("risk") or {}).get("blockers"):
            _apply_mode(action)


def _pending(action_id):
    action = get(action_id)
    if action is None:
        raise NotFound(f"Action {action_id} not found.")
    if action["status"] != "pending":
        raise Conflict(f"Action {action_id} is {action['status']}, not pending.")
    return action


def _finish(action_id, status, result):
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE actions SET status = ?, result = ?, updated_at = ? WHERE action_id = ?",
            (status, json.dumps(result), db.now_iso(), action_id),
        )
    return get(action_id)


def _run(action, actor):
    """Run the executor; return (status, result). Errors mark the action failed instead of raising."""
    token = _INSIDE_EXECUTOR.set(True)
    try:
        return "done", EXECUTORS[action["kind"]](action["payload"])
    except meridian.MeridianError as exc:
        db.audit(actor, "action_failed", f"{action['action_id']}: {exc}")
        return "failed", {"error": exc.detail, "status": exc.status}
    except Exception as exc:
        # Never leave a claimed action stuck in "running".
        db.audit(actor, "action_failed", f"{action['action_id']}: {type(exc).__name__}: {exc}")
        return "failed", {"error": f"Unexpected error: {exc}", "status": 500}
    finally:
        _INSIDE_EXECUTOR.reset(token)


def approve(action_id, actor="human"):
    """Run the executor for a pending action as actor (human or ai); return it marked done or failed."""
    action = _pending(action_id)
    # Claim the action atomically so two concurrent approvals cannot both run the executor.
    with db.get_conn() as conn:
        claimed = conn.execute(
            "UPDATE actions SET status = 'running', decided_by = ?, updated_at = ? "
            "WHERE action_id = ? AND status = 'pending'",
            (actor, db.now_iso(), action_id),
        ).rowcount
    if not claimed:
        raise Conflict(f"Action {action_id} is already being approved.")
    status, result = _run(action, actor)
    finished = _finish(action_id, status, result)
    if status == "done":
        db.audit(actor, "action_approved", f"{action_id} -> {json.dumps(result)[:300]}")
        _release_waiting()
    return finished


def reject(action_id, reason=None, actor="human"):
    """Mark a pending action rejected with an optional reason and return it."""
    _pending(action_id)
    with db.get_conn() as conn:
        conn.execute("UPDATE actions SET decided_by = ? WHERE action_id = ?", (actor, action_id))
    db.audit(actor, "action_rejected", f"{action_id}: {reason or 'no reason given'}")
    return _finish(action_id, "rejected", {"reason": reason})


@executor("create_return_quote")
def create_return_quote(payload):
    """Create the backhaul quote in Meridian: POST /quotes, price it, then add a note."""
    outbound = payload["outbound_file"]
    quote = meridian.post("/quotes", {
        "customer_id": payload["customer_id"],
        "mode": "TL",
        "equipment_type": payload["equipment_type"],
        "origin": payload["origin"],
        "destination": payload["destination"],
        "miles": payload["miles"],
        "target_margin_pct": payload["target_margin_pct"],
    })
    quote_id = quote["quote_id"]
    try:
        meridian.post(f"/quotes/{quote_id}/price", {
            "buy_lines": payload["buy_lines"],
            "target_margin_pct": payload["target_margin_pct"],
            "rate_ref": f"return-trip:{outbound}",
        })
        quote = meridian.put(f"/quotes/{quote_id}", {
            "note": f"Return Trip backhaul for the truck on file {outbound} "
                    f"({payload.get('category', 'freight')}). Approved by a human in Return Trip."
        })
    except meridian.MeridianError as exc:
        raise meridian.MeridianError(
            exc.status, exc.error, f"Quote {quote_id} was created but not finished: {exc.detail}"
        ) from exc
    return {
        "quote_id": quote_id,
        "summary": quote.get("summary"),
        "sell_total": quote.get("sell_total"),
        "meridian_url": f"{config.TMS_UI_URL}/quotes/{quote_id}" if config.TMS_UI_URL else None,
    }
