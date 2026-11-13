"""process_email: parse → classify → extract → match → propose actions → draft reply.

Each step is saved to the `emails` row before the next one starts, so a failure is visible in
the inbox (status `failed` plus the error) with everything that worked up to that point.
"""

import traceback

from email_pipeline import store
from email_pipeline.classify import classify_email, needs_review
from email_pipeline.deps import propose
from email_pipeline.extract import extract
from email_pipeline.match import match
from email_pipeline.parse import as_prompt_text, parse_json
from email_pipeline.reply import draft_reply


def _excerpt(text, limit=220):
    """First few hundred characters of the body on one line, for action reasoning."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def _cite(email_id, email):
    """A sentence pointing at the source email, used in every action's reasoning."""
    return f'Email {email_id} from {email["from"]} ("{email["subject"]}"): "{_excerpt(email["body"])}"'


def _quote_payload(email_id, extracted, matched):
    """The create_return_quote payload for a quote request: the full lane + freight from the email."""
    p = matched["prospect"]
    lines = [
        {k: line[k] for k in ("pieces", "weight_lb", "package_type", "description") if line.get(k) is not None}
        | {"hazmat": bool(extracted.get("hazmat"))}
        for line in extracted.get("freight_lines") or []
        if line.get("pieces") and line.get("weight_lb")
    ]
    location_keys = ("city", "state", "zip", "name", "facility_id")
    return {
        "source": "email",
        "source_email_id": email_id,
        "prospect_id": p["prospect_id"],
        "customer_id": p["customer_id"],
        "mode": "TL",
        "equipment_type": p["equipment"],
        "origin": {k: v for k, v in p["origin"].items() if k in location_keys and v},
        "destination": {k: v for k, v in p["destination"].items() if k in location_keys and v},
        "pickup_date": extracted.get("pickup_date"),
        "freight_lines": lines,
        "references": extracted.get("references") or [],
        "accessorials": extracted.get("accessorials") or [],
        "outbound_file": p["outbound_file"],
        "carrier_id": p["carrier_id"],
        "trailer_number": p["trailer_number"],
        "rate_ref": f"return-trip:{p['outbound_file']}",
    }


def _propose_quote(email_id, email, kind, classification, extracted, matched):
    """Queue a create_return_quote action when matching found a usable prospect; returns the action id or None."""
    p = matched.get("prospect") if matched else None
    if not p:
        return None
    party = matched.get("customer") or matched.get("carrier") or {}
    confidence = round(min(classification["confidence"], party.get("confidence") or 0.5), 2)

    if kind == "QUOTE_REQUEST":
        payload = _quote_payload(email_id, extracted, matched)
        o, d = p["origin"], p["destination"]
        title = f"Quote {p['customer_name']}: {o['city']}, {o['state']} → {d['city']}, {d['state']}"
        summary = (f"{p['category']} on {p['equipment']}, pickup {extracted.get('pickup_date') or 'TBD'}; "
                   f"rides the truck from outbound file {p['outbound_file']} ({p['carrier_id'] or 'carrier TBD'}).")
        why = "; ".join(p["reasons"])
    else:
        carrier = matched["carrier"]
        payload = {"source": "email", "source_email_id": email_id, "prospect_id": p["prospect_id"],
                   "carrier_id": carrier["entity_id"], "trailer_number": extracted.get("trailer_number")}
        title = f"Quote {p.get('customer_name') or p.get('customer_id')} for {carrier['label'] or carrier['hint']}'s empty truck"
        summary = f"{p.get('category')} from {p.get('origin')} to {p.get('destination')} (prospect {p['prospect_id']})."
        why = "; ".join(p["reasons"])

    reasoning = f"{_cite(email_id, email)}. Compatibility: {why}"
    action_id = propose("create_return_quote", title, summary, payload, confidence, reasoning)
    store.add_action_id(email_id, action_id)
    store.audit("action_proposed", {"email_id": email_id, "action_id": action_id, "kind": "create_return_quote"})
    return action_id


def _draft_and_propose_reply(email_id, email, kind, extracted, matched, quote_action_id, instructions=None):
    """Draft a reply into the outbox and queue a send_reply action; returns (reply_id, action_id)."""
    # Only a shipper's quote request gets the price; carriers never see our sell rate.
    if kind != "QUOTE_REQUEST":
        quote_action_id = None
    draft = draft_reply(email, extracted, matched, kind=kind, quote_pending=bool(quote_action_id),
                        instructions=instructions)
    reply_id = store.insert_reply(email_id, draft["to"], draft["subject"], draft["body"])
    store.audit("reply_drafted", {"email_id": email_id, "reply_id": reply_id})

    payload = {"reply_id": reply_id, "email_id": email_id, "quote_action_id": quote_action_id}
    summary = draft["body"][:280]
    reasoning = f"Reply to {_cite(email_id, email)}."
    if quote_action_id:
        reasoning += f" The price is filled in from quote action {quote_action_id} once that is approved."
    action_id = propose("send_reply", f"Reply to {draft['to']}: {draft['subject']}", summary, payload,
                        1.0, reasoning)
    store.update_reply(reply_id, action_id=action_id)
    store.add_action_id(email_id, action_id)
    store.audit("action_proposed", {"email_id": email_id, "action_id": action_id, "kind": "send_reply"})
    return reply_id, action_id


def missing_essentials(kind, extracted):
    """Facts an email of this kind must have before we act on it; returns the missing ones."""
    extracted = extracted or {}
    if kind == "QUOTE_REQUEST":
        need = {"origin city": (extracted.get("origin") or {}).get("city"),
                "destination city": (extracted.get("destination") or {}).get("city")}
    elif kind == "WASHOUT_CERT":
        need = {"trailer number": extracted.get("trailer_number")}
    elif kind == "LAST_LOAD_INFO":
        need = {"trailer number": extracted.get("trailer_number"), "last commodity": extracted.get("last_commodity")}
    elif kind == "CARRIER_OFFER":
        need = {"empty city": extracted.get("empty_city")}
    else:
        need = {}
    return [label for label, value in need.items() if not value]


def _result(email_id, actions_created=(), reply_id=None):
    """The process_email return shape, read back from the saved row."""
    row = store.get_email(email_id)
    return {
        "email_id": email_id,
        "status": row["status"],
        "kind": row["kind"],
        "confidence": row["confidence"],
        "rationale": row["rationale"],
        "extracted": row["extracted"],
        "matched": row["matched"],
        "actions_created": list(actions_created),
        "reply_id": reply_id,
        "error": row["error"],
    }


def process_email(email):
    """Run the whole pipeline on a new email dict (or re-run a stored email_id); returns the result dict."""
    store.init_email_tables()
    if isinstance(email, str):
        email_id = email
        row = store.get_email(email_id)
        if row is None:
            raise KeyError(f"no email {email_id}")
        email = {"from": row["from_addr"], "to": row["to_addr"], "subject": row["subject"], "body": row["body"],
                 "received_at": row["received_at"], "attachments": row["attachments"] or []}
        store.update_email(email_id, kind=None, confidence=None, extracted=None, matched=None, error=None)
    else:
        email = parse_json(email)
        email_id = store.insert_email(email)
        store.audit("email_received", {"email_id": email_id, "from": email["from"], "subject": email["subject"]})

    actions, reply_id = [], None
    try:
        store.update_email(email_id, status="processing")

        classification = classify_email(email)
        store.update_email(email_id, kind=classification["kind"], confidence=classification["confidence"],
                           rationale=classification["rationale"])
        store.audit("email_classified", {"email_id": email_id, **classification})
        if needs_review(classification):
            store.update_email(email_id, status="needs_review")
            store.audit("email_needs_review", {"email_id": email_id, "why": classification["rationale"]})
            return _result(email_id)

        kind = classification["kind"]
        extracted = extract(kind, email)
        store.update_email(email_id, extracted=extracted)
        store.audit("email_extracted", {"email_id": email_id, "kind": kind})
        missing = missing_essentials(kind, extracted)
        if missing:
            store.update_email(email_id, status="needs_review", error="Missing: " + ", ".join(missing))
            store.audit("email_needs_review", {"email_id": email_id, "missing": missing})
            return _result(email_id)

        matched = match(kind, email_id, email, extracted, as_prompt_text(email))
        store.update_email(email_id, matched=matched)
        store.audit("email_matched", {"email_id": email_id, "status": matched.get("status"),
                                      "reasons": matched.get("reasons")})

        quote_action_id = _propose_quote(email_id, email, kind, classification, extracted, matched)
        if quote_action_id:
            actions.append(quote_action_id)

        reply_id, reply_action_id = _draft_and_propose_reply(email_id, email, kind, extracted, matched,
                                                             quote_action_id)
        actions.append(reply_action_id)

        store.update_email(email_id, status="processed")
        store.audit("email_processed", {"email_id": email_id, "actions": actions, "reply_id": reply_id})
    except Exception as exc:
        store.update_email(email_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        store.audit("email_failed", {"email_id": email_id, "error": str(exc), "trace": traceback.format_exc()[-800:]})
    return _result(email_id, actions, reply_id)


def redraft_reply(email_id, instructions=None):
    """Draft a fresh reply for a processed email (e.g. with broker instructions); returns {reply_id, action_id}."""
    row = store.get_email(email_id)
    if row is None:
        raise KeyError(f"no email {email_id}")
    email = {"from": row["from_addr"], "subject": row["subject"], "body": row["body"]}
    matched = row["matched"] or {}
    quote_action_id = store.quote_action_for_email(email_id)
    reply_id, action_id = _draft_and_propose_reply(email_id, email, row["kind"], row["extracted"] or {}, matched,
                                                   quote_action_id, instructions)
    return {"reply_id": reply_id, "action_id": action_id}
