"""Flask Blueprint `email_bp`, prefixed /api/email (Ryan: `from email_pipeline.routes import email_bp as bp`).

Standalone for testing: `python -m email_pipeline.routes` serves it on port 5001.
"""

from pathlib import Path

from flask import Blueprint, Flask, abort, jsonify, request

from email_pipeline import store
from email_pipeline.deps import STUBBED
from email_pipeline.haggle import haggle
from email_pipeline.parse import parse_file
from email_pipeline.pipeline import process_email
from email_pipeline.tools import inbox_row

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "demo" / "sample_emails"

email_bp = Blueprint("email_pipeline", __name__, url_prefix="/api/email")


@email_bp.before_app_request
def _ensure_tables():
    store.init_email_tables()


@email_bp.get("/inbox")
def inbox():
    """Inbox rows, newest first; ?status= filters."""
    return {"items": [inbox_row(r) for r in store.list_emails(request.args.get("status"))]}


@email_bp.get("/outbox")
def outbox():
    """Outbox drafts and sent replies; ?status= filters."""
    keys = ("reply_id", "email_id", "to_addr", "subject", "body", "status", "action_id", "created_at")
    rows = store.list_replies(status=request.args.get("status"))
    return {"items": [{k: r[k] for k in keys} for r in rows]}


@email_bp.get("/samples")
def samples():
    """File names of the demo emails the simulate button can load."""
    return {"items": sorted(p.name for p in SAMPLES_DIR.glob("*.json"))}


@email_bp.get("/health")
def health():
    """Which of Ryan's interfaces are still stubbed."""
    return {"ok": True, "stubbed": STUBBED}


@email_bp.get("/<email_id>")
def email_detail(email_id):
    """Full email row including body, extracted and matched, plus its replies."""
    row = store.get_email(email_id)
    if row is None:
        abort(404, description=f"No email {email_id}")
    row["replies"] = store.list_replies(email_id=email_id)
    return row


@email_bp.post("/ingest")
def ingest():
    """Process a posted email {from, subject, body[, to, received_at, attachments]}."""
    data = request.get_json(silent=True) or {}
    missing = [k for k in ("from", "subject", "body") if not data.get(k)]
    if missing:
        return jsonify({"error": "validation_error", "detail": f"Missing fields: {', '.join(missing)}"}), 422
    return process_email(data)


@email_bp.post("/simulate")
def simulate():
    """Load demo/sample_emails/<file> and ingest it (the demo button)."""
    name = Path((request.get_json(silent=True) or {}).get("file", "")).name  # no path tricks
    path = SAMPLES_DIR / name
    if not name or not path.is_file():
        return jsonify({"error": "not_found", "detail": f"No sample email '{name}'"}), 404
    return process_email(parse_file(path))


@email_bp.post("/<email_id>/haggle")
def haggle_route(email_id):
    """Stretch: negotiate with the simulated carrier on a CARRIER_OFFER email {target_pay_min?, target_pay_max?}."""
    data = request.get_json(silent=True) or {}
    try:
        return haggle(email_id, data.get("target_pay_min"), data.get("target_pay_max"))
    except ValueError as exc:
        return jsonify({"error": "conflict", "detail": str(exc)}), 409


def create_dev_app():
    """A tiny app with only email_bp, for working without Ryan's backend."""
    app = Flask(__name__)
    app.register_blueprint(email_bp)

    @app.after_request
    def cors(response):
        response.headers["Access-Control-Allow-Origin"] = "http://localhost:5173"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    return app


if __name__ == "__main__":
    create_dev_app().run(port=5001, debug=True)
