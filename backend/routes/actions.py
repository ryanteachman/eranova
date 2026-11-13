"""Routes: /api/fill and /api/actions."""

from flask import Blueprint, request

from ..agent import actions, tools
from ..errors import BadRequest

bp = Blueprint("actions", __name__, url_prefix="/api")


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    return body


@bp.post("/fill")
def fill():
    """Queue a create_return_quote action for a prospect and return its id."""
    prospect_id = _json_body().get("prospect_id")
    if not prospect_id:
        raise BadRequest("prospect_id is required.")
    proposal = tools.create_return_quote(prospect_id)
    action = actions.propose(kind="create_return_quote", actor="human", **proposal)
    return {"action_id": action["action_id"], "status": action["status"]}


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
