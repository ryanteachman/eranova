"""Stretch: Carrier Haggle by email.

A simulated carrier (an LLM with a personality) answers our offer for its empty truck. Our side is
plain code: open at target_pay_min, meet in the middle, never above target_pay_max. The target range
comes from lane history (what we paid per mile on this lane's head-haul direction). A deal is drafted
as a rate confirmation to the carrier and queued as a `confirm_carrier_rate` action; approving it marks
the confirmation sent (simulated). Covering the load in Meridian needs the backhaul quote booked first,
so that stays a separate step.
"""

import re
from statistics import median

from backend.agent.actions import propose
from backend.errors import Conflict
from pydantic import BaseModel, Field

from email_pipeline import reply, store
from email_pipeline.llm import structured
from email_pipeline.match import _city_state, shipments

BACKHAUL_MAX_SHARE = 0.85   # pay at most 85% of the head-haul per-mile rate for the trip home
BACKHAUL_MIN_SHARE = 0.65   # open at 65%
CARRIER_FLOOR_SHARE = 0.92  # the simulated carrier walks away below 92% of its own ask
DEFAULT_MILES = 400
MAX_ROUNDS = 4


class CarrierTurn(BaseModel):
    message: str = Field(description="The carrier's e-mail reply, 1-3 sentences, in character")
    accept: bool = Field(description="True only if accepting our latest offer as-is")
    counter_total: float | None = Field(description="Carrier's counter-offer in total dollars, null if accepting")


# Prompt for the simulated carrier dispatcher (role-play only; the walk-away number is enforced in code too).
CARRIER_PERSONA = """You are {name}, a truck dispatcher replying by e-mail to a freight broker.
Personality: friendly but stubborn, a little dramatic about fuel prices, always wants to get the truck home.
Your truck is empty in {origin} and you want to get it to {destination} ({miles} miles).
You asked for {ask_total:.0f} dollars all in. Privately, you will not go below {floor_total:.0f} dollars.
Each turn: accept the broker's latest offer if it is at or above your private floor and you think you can't
do better, otherwise counter with a total dollar amount between their offer and your last number."""


def _parse_rate_ask(rate_ask, miles):
    """'$2.15/mi' or '$1,900 all in' → total dollars (None if no number)."""
    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)", rate_ask or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    per_mile = "/mi" in rate_ask.lower() or "per mile" in rate_ask.lower() or value < 20
    return round(value * miles, 2) if per_mile else value


def lane_history(origin_state, dest_state):
    """Per-mile buy rates we paid on this lane (from Ryan's shipment cache): {per_mile:[...], direction}."""
    rows = [s for s in shipments() if s.get("status") in ("DELIVERED", "POD_RECEIVED", "CLOSED")]

    def rates(a, b):
        return [s["buy_total"] / s["miles"] for s in rows
                if s["shipper_state"] == a and s["consignee_state"] == b and s.get("buy_total") and s.get("miles")]

    same_way = rates(origin_state, dest_state)
    if same_way:
        return {"per_mile": same_way, "direction": f"{origin_state}→{dest_state}"}
    return {"per_mile": rates(dest_state, origin_state), "direction": f"{dest_state}→{origin_state} (head-haul)"}


def target_range(origin_state, dest_state, miles):
    """(target_pay_min, target_pay_max, explanation) from lane history."""
    history = lane_history(origin_state, dest_state)
    if not history["per_mile"]:
        return None, None, "no lane history"
    rpm = median(history["per_mile"])
    low, high = round(rpm * BACKHAUL_MIN_SHARE * miles, 2), round(rpm * BACKHAUL_MAX_SHARE * miles, 2)
    why = (f"median buy ${rpm:.2f}/mi over {len(history['per_mile'])} loads on {history['direction']}; "
           f"backhaul target {BACKHAUL_MIN_SHARE:.0%}-{BACKHAUL_MAX_SHARE:.0%} × {miles} mi")
    return low, high, why


def _carrier_turn(persona, transcript):
    """One reply from the simulated carrier, given the conversation so far."""
    convo = "\n".join(f"{t['who']}: {t['message']}" for t in transcript)
    return structured(persona, f"Conversation so far:\n{convo}\n\nWrite your next reply.", CarrierTurn)


def haggle(email_id, target_pay_min=None, target_pay_max=None, max_rounds=MAX_ROUNDS):
    """Negotiate with the simulated carrier for a CARRIER_OFFER email; returns the transcript and any action."""
    row = store.get_email(email_id)
    if row is None or row["kind"] != "CARRIER_OFFER":
        raise Conflict(f"{email_id} is not a processed CARRIER_OFFER email.")
    matched, extracted = row["matched"] or {}, row["extracted"] or {}
    prospect = matched.get("prospect")
    if not prospect:
        raise Conflict("No prospect to haggle over; nothing compatible was found for this truck.")

    origin_city, origin_state = _city_state(prospect["origin"])
    dest_city, dest_state = _city_state(prospect["destination"])
    miles = prospect.get("miles") or DEFAULT_MILES
    why = "given by the broker"
    if target_pay_min is None or target_pay_max is None:
        low, high, why = target_range(origin_state, dest_state, miles)
        if low is None:
            raise Conflict("No lane history; pass target_pay_min and target_pay_max.")
        target_pay_min = target_pay_min if target_pay_min is not None else low
        target_pay_max = target_pay_max if target_pay_max is not None else high

    carrier = matched["carrier"]
    ask_total = _parse_rate_ask(extracted.get("rate_ask"), miles) or target_pay_max * 1.15
    floor_total = round(ask_total * CARRIER_FLOOR_SHARE, 2)
    persona = CARRIER_PERSONA.format(name=carrier.get("label") or "the carrier", origin=f"{origin_city}, {origin_state}",
                                     destination=f"{dest_city}, {dest_state}", miles=miles,
                                     ask_total=ask_total, floor_total=floor_total)

    transcript, offer, deal = [], round(target_pay_min, 2), None
    for round_no in range(1, max_rounds + 1):
        transcript.append({"who": "broker", "amount": offer, "message":
                           f"We have {prospect.get('customer_name') or 'a load'} {origin_city}, {origin_state} → "
                           f"{dest_city}, {dest_state}, {miles} mi. We can do ${offer:,.2f} all in."})
        turn = _carrier_turn(persona, transcript)
        # The carrier's private floor is enforced here, not trusted to the model.
        if turn.accept and offer < floor_total:
            turn.accept, turn.counter_total = False, floor_total
        transcript.append({"who": "carrier", "amount": None if turn.accept else turn.counter_total,
                           "message": turn.message})
        if turn.accept:
            deal = offer
            break
        counter = turn.counter_total or ask_total
        if counter <= target_pay_max:
            deal = round(counter, 2)
            transcript.append({"who": "broker", "amount": deal, "message": f"Deal at ${deal:,.2f}. Sending it for approval."})
            break
        offer = round(min(target_pay_max, offer + (counter - offer) / 2), 2)

    action_id = None
    if deal is not None:
        # The agreed carrier pay goes in the confirmation as a real number: a person approves it before it "sends".
        body = (f"Confirming ${deal:,.2f} all in for your empty {extracted.get('equipment') or ''} truck: "
                f"{origin_city}, {origin_state} → {dest_city}, {dest_state} ({miles} mi), available "
                f"{extracted.get('available_date') or 'as offered'}. Rate confirmation and load details to follow "
                f"once the load is booked.\n\nMeridian Logistics - Return Trip desk")
        reply_id = store.insert_reply(email_id, row["from_addr"], f"Re: {row['subject']} - rate confirmed", body)
        payload = {"reply_id": reply_id, "email_id": email_id, "carrier_id": carrier["entity_id"],
                   "prospect_id": prospect["prospect_id"], "amount": deal, "miles": miles,
                   "rate_per_mile": round(deal / miles, 2), "trailer_number": extracted.get("trailer_number")}
        action_id = propose(
            "confirm_carrier_rate",
            f"Confirm {carrier.get('label')} at ${deal:,.2f}: {origin_city} → {dest_city}",
            f"Negotiated by e-mail in {len(transcript)} messages (target ${target_pay_min:,.0f}-${target_pay_max:,.0f}).",
            payload,
            0.8,
            f"Carrier offer in email {email_id} asked {extracted.get('rate_ask')}; target from {why}. "
            f"Settled at ${deal:,.2f}, inside the target range.",
            actor="email_pipeline",
        )["action_id"]
        store.update_reply(reply_id, action_id=action_id)
        store.add_action_id(email_id, action_id)
        store.audit("action_proposed", {"email_id": email_id, "action_id": action_id, "kind": "confirm_carrier_rate"})

    result = {"email_id": email_id, "target_pay_min": target_pay_min, "target_pay_max": target_pay_max,
              "target_basis": why, "carrier_ask": ask_total, "deal": deal, "action_id": action_id,
              "transcript": transcript}
    store.update_email(email_id, matched={**matched, "haggle": result})
    store.audit("haggle_finished", {"email_id": email_id, "deal": deal, "rounds": len(transcript)})
    return result


def execute_rate_confirmation(payload):
    """Executor for `confirm_carrier_rate`: mark the drafted rate confirmation sent (simulated)."""
    sent = reply.send_reply(payload["reply_id"])
    return {**sent, "carrier_id": payload["carrier_id"], "amount": payload["amount"],
            "rate_per_mile": payload["rate_per_mile"]}
