"""Registers the email tools in Ryan's agent registry so the agent can work email from chat.

Ryan's backend/agent/tools.py imports this module so the @tool decorators run.
"""

from email_pipeline import haggle, pipeline, reply, store
from email_pipeline.deps import tool


def inbox_row(row):
    """The short inbox shape shared by the tool and the /inbox route."""
    keys = ("email_id", "from_addr", "subject", "received_at", "kind", "confidence", "status", "action_ids")
    return {k: row.get(k) for k in keys}


@tool(
    name="list_emails",
    description="List inbox emails (newest first) with their kind, confidence and pipeline status.",
    schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": list(store.EMAIL_STATUSES),
                       "description": "Only emails with this status"},
        },
    },
    tier="auto",
)
def list_emails(status=None):
    """Return {items:[inbox rows]}."""
    store.init_email_tables()
    return {"items": [inbox_row(r) for r in store.list_emails(status)]}


@tool(
    name="read_email",
    description="Read one email in full: body, extracted fields and what it matched in Meridian.",
    schema={"type": "object", "properties": {"email_id": {"type": "string"}}, "required": ["email_id"]},
    tier="auto",
)
def read_email(email_id):
    """Return the full email row plus its outbox drafts, or an error dict."""
    row = store.get_email(email_id)
    if row is None:
        return {"error": f"No email {email_id}"}
    row["replies"] = store.list_replies(email_id=email_id)
    return row


@tool(
    name="process_email",
    description="Run the email pipeline on a stored email: classify, extract, match against open return "
                "trips, and queue a draft quote and reply for human approval. Writes only to the email "
                "tables and the approval queue.",
    schema={"type": "object", "properties": {"email_id": {"type": "string"}}, "required": ["email_id"]},
    tier="auto",
)
def process_email(email_id):
    """Re-run the pipeline on email_id and return the process_email result."""
    return pipeline.process_email(email_id)


@tool(
    name="draft_reply",
    description="Write a new draft reply to an email (optionally following instructions) and queue it for "
                "approval. Never includes a price; the approved quote's price is filled in on send.",
    schema={
        "type": "object",
        "properties": {
            "email_id": {"type": "string"},
            "instructions": {"type": "string", "description": "e.g. 'ask for the pickup appointment number'"},
        },
        "required": ["email_id"],
    },
    tier="auto",
)
def draft_reply(email_id, instructions=None):
    """Return {reply_id, action_id} for the new draft."""
    return pipeline.redraft_reply(email_id, instructions)


@tool(
    name="send_reply",
    description="Send a drafted reply (simulated: marks it approved_sent; nothing leaves the system).",
    schema={"type": "object", "properties": {"reply_id": {"type": "string"}}, "required": ["reply_id"]},
    tier="approve",
)
def send_reply(reply_id):
    """Mark the reply approved_sent, filling in the quote price; runs only after human approval."""
    return reply.send_reply(reply_id)


@tool(
    name="haggle_with_carrier",
    description="Negotiate by e-mail with the carrier behind a CARRIER_OFFER email (simulated carrier), staying "
                "inside a target pay range from lane history; a deal is queued as a cover_load action.",
    schema={
        "type": "object",
        "properties": {
            "email_id": {"type": "string"},
            "target_pay_min": {"type": "number"},
            "target_pay_max": {"type": "number"},
        },
        "required": ["email_id"],
    },
    tier="auto",
)
def haggle_with_carrier(email_id, target_pay_min=None, target_pay_max=None):
    """Return the haggle transcript, the deal amount and any cover_load action id."""
    try:
        return haggle.haggle(email_id, target_pay_min, target_pay_max)
    except ValueError as exc:
        return {"error": str(exc)}
