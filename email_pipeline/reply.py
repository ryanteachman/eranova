"""Draft reply text with the LLM, and the simulated send (nothing ever leaves the building)."""

import json
import re

from pydantic import BaseModel

from email_pipeline import store
from email_pipeline.deps import get_conn
from email_pipeline.llm import structured

PRICE_PLACEHOLDER = "{{sell_total}}"


class Reply(BaseModel):
    subject: str
    body: str


# Prompt for writing a short broker reply; prices are never written, only the {{sell_total}} placeholder.
REPLY_PROMPT = """You write e-mail replies for a freight broker at Meridian Logistics. Keep them short
(3-7 sentences), professional and specific: repeat back the lane, date, trailer or reference so the
reader knows we understood. Sign off as "Meridian Logistics - Return Trip desk".

Never write a dollar amount or rate of your own. If the situation says a quote is being prepared, write the
price exactly as the placeholder {{sell_total}} (e.g. "all-in rate of {{sell_total}}"), and say it is
valid for 7 days. If no quote is being prepared, do not mention a price at all.
Do not promise anything the situation doesn't support. Reply subject: "Re: <original subject>"."""


def _place(loc):
    """'City, ST' from a location dict or string."""
    if isinstance(loc, dict):
        return ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
    return str(loc)


def _situation(kind, extracted, matched, quote_pending):
    """Plain-English facts for the reply prompt, built from the pipeline's results (not the LLM's)."""
    matched = matched or {}
    facts = [f"Email kind: {kind}"]
    if kind == "QUOTE_REQUEST":
        stop_reqs = [f"{stop}: {', '.join(loc['requirements'])}"
                     for stop, loc in (("pickup", matched.get("origin") or {}), ("delivery", matched.get("destination") or {}))
                     if loc.get("requirements")]
        if stop_reqs:
            facts.append("Facility requirements (from our records; confirm them in the reply): " + "; ".join(stop_reqs))
        if quote_pending:
            p = matched["prospect"]
            facts.append(f"We have a truck for it and a quote is being prepared for {p['customer_name']}.")
            facts.append(f"Include this exact sentence: \"Our all-in rate is {PRICE_PLACEHOLDER}, valid for 7 days.\"")
        else:
            facts.append("No quote yet. Reasons: " + "; ".join(matched.get("reasons", [])))
            facts.append("Ask for whatever is missing (lane, date, freight, bill-to) or say we're checking capacity.")
    elif kind == "WASHOUT_CERT":
        facts.append(f"Washout recorded for trailer {extracted.get('trailer_number')}.")
        if matched.get("unblocked"):
            facts.append("This clears the trailer for food-grade loads we were holding; we'll follow up with a load.")
    elif kind == "LAST_LOAD_INFO":
        blocked = matched.get("blocked", [])
        if any("FSMA" in r for o in blocked for r in o["reasons"]):
            facts.append("FSMA: we cannot put food or beverage in this trailer until we receive a washout certificate.")
        if matched.get("prospect"):
            p = matched["prospect"]
            facts.append(f"We may have a non-food load for the truck out of {_place(p['origin'])} "
                         f"to {_place(p['destination'])} - will confirm.")
    elif kind == "CARRIER_OFFER":
        if matched.get("prospect"):
            p = matched["prospect"]
            facts.append(f"We are working on a possible load out of {_place(p['origin'])} to {_place(p['destination'])} "
                         "and will confirm shortly. Do not accept or counter their rate yet.")
        else:
            facts.append("Nothing fits right now; thank them and say we'll reach out if something opens up.")
    return "\n".join(facts)


def draft_reply(email, extracted, matched, kind=None, quote_pending=False, instructions=None):
    """Write a reply draft; returns {to, subject, body}. Prices only ever appear as {{sell_total}}."""
    user_text = (
        f"Original email\nFrom: {email['from']}\nSubject: {email['subject']}\n\n{email['body']}\n\n"
        f"Situation (facts from our systems)\n{_situation(kind, extracted, matched, quote_pending)}"
    )
    if instructions:
        user_text += f"\n\nExtra instructions from the broker: {instructions}"
    reply = structured(REPLY_PROMPT, user_text, Reply)
    body = reply.body
    if quote_pending and PRICE_PLACEHOLDER not in body:
        line = f"Our all-in rate is {PRICE_PLACEHOLDER}, valid for 7 days."
        head, sep, signoff = body.rpartition("\n\n")  # keep it above the sign-off
        body = f"{head}\n\n{line}{sep}{signoff}" if sep else f"{body}\n\n{line}"
    if not quote_pending:
        body = body.replace(PRICE_PLACEHOLDER, "(pricing to follow)")
    # Belt and braces: no dollar figures in a draft, ever.
    body = re.sub(r"\$\s?\d[\d,]*(\.\d+)?", PRICE_PLACEHOLDER if quote_pending else "(pricing to follow)", body)
    return {"to": email["from"], "subject": reply.subject, "body": body}


def _quote_result(action_id):
    """Ryan's actions row for the quote: (status, result dict)."""
    with get_conn() as conn:
        row = conn.execute("SELECT status, result FROM actions WHERE action_id = ?", (action_id,)).fetchone()
    if row is None:
        return None, None
    return row["status"], json.loads(row["result"]) if row["result"] else None


def send_reply(reply_id, quote_action_id=None):
    """Simulated send: fill {{sell_total}} from the approved quote and mark the reply approved_sent."""
    reply = store.get_reply(reply_id)
    if reply is None:
        raise KeyError(f"no reply {reply_id}")
    if reply["status"] != "draft":
        raise ValueError(f"reply {reply_id} is already {reply['status']}")

    body = reply["body"]
    quote_action_id = quote_action_id or store.quote_action_for_email(reply["email_id"])
    if PRICE_PLACEHOLDER in body:
        status, result = _quote_result(quote_action_id) if quote_action_id else (None, None)
        if status != "done" or not result or result.get("sell_total") is None:
            raise ValueError(f"Approve the quote action {quote_action_id} first; this reply quotes its price.")
        body = body.replace(PRICE_PLACEHOLDER, f"${result['sell_total']:,.2f}")
        if result.get("quote_id"):
            body += f"\n\nMeridian quote #{result['quote_id']}"

    store.update_reply(reply_id, body=body, status="approved_sent")
    store.audit("reply_sent", {"reply_id": reply_id, "to": reply["to_addr"], "simulated": True})
    return {"reply_id": reply_id, "status": "approved_sent", "to": reply["to_addr"], "body": body}


def reject_reply(reply_id):
    """Mark a draft reply as rejected (call this when its send_reply action is rejected)."""
    store.update_reply(reply_id, status="rejected")
    store.audit("reply_rejected", {"reply_id": reply_id})
    return {"reply_id": reply_id, "status": "rejected"}


def execute_send_reply(payload):
    """Executor for Ryan's approval queue: approving a `send_reply` action calls this with its payload."""
    return send_reply(payload["reply_id"], payload.get("quote_action_id"))
