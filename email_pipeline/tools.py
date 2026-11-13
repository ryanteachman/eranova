"""Registers the email tools and executors with Ryan's agent, so the agent can work email from chat.

Ryan's backend imports this module on start-up, so the @tool and @executor decorators run.
An `approve`-tier tool only describes the write ({title, summary, payload, confidence, reasoning});
Ryan's loop queues it, and the matching @executor does the write when a person approves it.
"""

from backend.agent.actions import executor
from backend.agent.registry import tool
from backend.errors import Conflict

from email_pipeline import haggle, pipeline, reply, store

# Executors for the actions the email pipeline proposes.
executor("send_reply")(reply.execute_send_reply)
executor("confirm_carrier_rate")(haggle.execute_rate_confirmation)


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
    description="Send a drafted reply (simulated: marks it approved_sent; nothing leaves the system). "
                "Queued for human approval; the quote's price is filled in when it is sent.",
    schema={"type": "object", "properties": {"reply_id": {"type": "string"}}, "required": ["reply_id"]},
    tier="approve",
)
def send_reply(reply_id):
    """Describe sending this draft for the approval queue; reply.execute_send_reply does it on approval."""
    draft = store.get_reply(reply_id)
    if draft is None or draft["status"] != "draft":
        raise Conflict(f"No draft reply {reply_id}; it may already be sent or rejected.")
    return {
        "title": f"Reply to {draft['to_addr']}: {draft['subject']}",
        "summary": draft["body"][:280],
        "payload": {"reply_id": reply_id, "email_id": draft["email_id"],
                    "quote_action_id": store.quote_action_for_email(draft["email_id"])},
        "confidence": 1.0,
        "reasoning": f"Agent asked to send the drafted reply to email {draft['email_id']}.",
    }


@tool(
    name="haggle_with_carrier",
    description="Negotiate by e-mail with the carrier behind a CARRIER_OFFER email (simulated carrier), staying "
                "inside a target pay range from lane history; a deal is queued as a confirm_carrier_rate action.",
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
    """Return the haggle transcript, the deal amount and any confirm_carrier_rate action id."""
    return haggle.haggle(email_id, target_pay_min, target_pay_max)
