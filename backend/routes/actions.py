"""Routes: /api/fill, /api/actions and /api/mode."""

from flask import Blueprint, request

from ..agent import actions, autonomy, tools
from ..errors import BadRequest

bp = Blueprint("actions", __name__, url_prefix="/api")


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    return body


@bp.post("/fill")
def fill():
    """Propose a create_return_quote action for a prospect; the decision mode may execute it at once."""
    prospect_id = _json_body().get("prospect_id")
    if not prospect_id:
        raise BadRequest("prospect_id is required.")
    proposal = tools.create_return_quote(prospect_id)
    action = actions.propose(kind="create_return_quote", actor="human", **proposal)
    return {key: action[key] for key in ("action_id", "status", "mode", "decided_by", "risk", "result")}


@bp.get("/mode")
def get_mode():
    """Return the decision mode, its rules and today's AI usage."""
    return autonomy.status()


@bp.put("/mode")
def put_mode():
    """Switch the decision mode: {mode: approval | auto | invisible}."""
    return autonomy.set_mode(_json_body().get("mode"))


@bp.get("/actions")
def list_actions():
    """List actions, optionally filtered by ?status=."""
    return {"items": actions.list_actions(request.args.get("status"))}


@bp.post("/actions/<action_id>/approve")
def approve(action_id):
    """Approve a pending action and run it against Meridian."""
    return actions.approve(action_id)


@bp.post("/actions/<action_id>/reject")
def reject(action_id):
    """Reject a pending action with an optional reason."""
    body = request.get_json(silent=True) or {}
    return actions.reject(action_id, body.get("reason") if isinstance(body, dict) else None)
