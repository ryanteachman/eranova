"""Step 3: tie extracted email data to Meridian records and return-trip prospects.

Reads only (GET /search, /vendors/lookup, /vendors/{id}, /customers, /shipments). The one write
is to our own `washouts` table. Compatibility is always decided by `check_compat`, never the LLM.
"""

import re
from datetime import date
from functools import lru_cache

from email_pipeline import store
from email_pipeline.deps import check_compat, find_backhauls, meridian_get

ACTIVE_STATUSES = "BOOKED,COVERED,DISPATCHED,AT_PICKUP,PICKED_UP,IN_TRANSIT,AT_DELIVERY,DELIVERED"
RISKY_LAST_LOADS = ("CHEMICAL", "HAZMAT", "WASTE")
FOOD_CATEGORIES = ("FOOD", "BEVERAGE")
# Which truck equipment can serve a requested equipment type.
EQUIPMENT_FITS = {"V": {"V", "R", "VC"}, "R": {"R"}, "F": {"F", "SD"}, "SD": {"SD"}, "VC": {"VC", "V"}}
MAX_OPTIONS = 5


# ---------- resolving customers, carriers and facilities ----------

def _safe_get(path, **params):
    """GET from Meridian, returning None instead of raising (matching must not crash the pipeline)."""
    try:
        return meridian_get(path, **params)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _search(q):
    """Cached GET /search."""
    return _safe_get("/search", q=q) or {}


@lru_cache(maxsize=64)
def get_vendor(vendor_id):
    """One carrier record (cached), or None."""
    return _safe_get(f"/vendors/{vendor_id}")


@lru_cache(maxsize=1)
def _customers():
    """All customers (there are only a handful), cached."""
    return (_safe_get("/customers", limit=200) or {}).get("items", [])


def _hint_variants(hint):
    """The hint, then shorter versions of it, so 'Sunridge Trucking Co' still finds 'Sunridge Trucking LLC'."""
    words = re.sub(r"[^\w\s&'-]", " ", hint or "").split()
    return [" ".join(words[:n]) for n in range(len(words), 0, -1) if len(" ".join(words[:n])) >= 3]


def _search_names(hint, category):
    """Search a name hint in one /search category; returns (hits, query_used)."""
    for q in _hint_variants(hint):
        hits = _search(q).get(category, [])
        if hits:
            return hits, q
    return [], None


def _unmatched(hint, why):
    return {"hint": hint, "entity_id": None, "label": None, "confidence": 0.0, "method": None, "note": why}


def resolve_customer(hint, sender):
    """Find the Meridian customer for a quote request: contact e-mail first, then name search."""
    sender_email = (re.search(r"[\w.+-]+@[\w.-]+", sender or "") or [None])[0]
    if sender_email:
        for cust in _customers():
            emails = {(c.get("email") or "").lower() for c in cust.get("contacts", [])}
            if sender_email.lower() in emails:
                return {"hint": hint, "entity_id": cust["customer_id"], "label": cust["legal_name"],
                        "confidence": 0.95, "method": f"sender {sender_email} is a customer contact"}
    if not hint:
        return _unmatched(hint, "no customer named in the email")
    hits, q = _search_names(hint, "customers")
    if not hits:
        return _unmatched(hint, f"no customer matches '{hint}'")
    best = hits[0]
    return {
        "hint": hint, "entity_id": best["entity_id"], "label": best["label"],
        "confidence": 0.9 if len(hits) == 1 else 0.6,
        "method": f"/search?q={q} ({len(hits)} hit{'s' if len(hits) > 1 else ''})",
        "alternatives": [h["entity_id"] for h in hits[1:]],
    }


def resolve_carrier(hint, email_text):
    """Find the Meridian carrier: MC/DOT/SCAC lookup first, then name search."""
    numbers = {
        "mc": re.search(r"\bMC[\s#:-]*(\d{5,7})\b", email_text, re.I),
        "dot": re.search(r"\b(?:US)?DOT[\s#:-]*(\d{5,8})\b", email_text, re.I),
        "scac": re.search(r"\bSCAC[\s#:-]*([A-Z]{2,4})\b", email_text),
    }
    for key, m in numbers.items():
        if m:
            items = (_safe_get("/vendors/lookup", **{key: m.group(1)}) or {}).get("items", [])
            if len(items) == 1:
                v = items[0]
                return {"hint": hint, "entity_id": v["vendor_id"], "label": v["legal_name"],
                        "confidence": 0.98, "method": f"/vendors/lookup?{key}={m.group(1)}"}
    if not hint:
        return _unmatched(hint, "no carrier named in the email")
    hits, q = _search_names(hint, "vendors")
    if not hits:
        return _unmatched(hint, f"no carrier matches '{hint}'")
    return {
        "hint": hint, "entity_id": hits[0]["entity_id"], "label": hits[0]["label"],
        "confidence": 0.9 if len(hits) == 1 else 0.6,
        "method": f"/search?q={q} ({len(hits)} hit{'s' if len(hits) > 1 else ''})",
        "alternatives": [h["entity_id"] for h in hits[1:]],
    }


# Meridian facility compliance flags in plain words, as they go on the quote and in the reply.
FLAG_TEXT = {"SEAL_REQUIRED": "seal required", "ID_REQUIRED": "driver ID required", "TWIC_REQUIRED": "TWIC card required",
             "SAFETY_VEST": "safety vest required", "STEEL_TOES": "steel-toe boots required",
             "NO_CELL_PHONES": "no cell phones on the dock"}


def facility_requirements(facility_id):
    """What a facility demands of the driver, from its Meridian record (flags, appointments, lumper); [] if unknown."""
    if not facility_id:
        return []
    facility = _safe_get(f"/facilities/{facility_id}") or {}
    reqs = [FLAG_TEXT.get(flag, flag.lower().replace("_", " ")) for flag in facility.get("compliance_flags") or []]
    if facility.get("appointment_required"):
        reqs.append("appointment required")
    if facility.get("lumper_policy") == "REQUIRED":
        reqs.append("lumper required")
    return reqs


def resolve_facility(location):
    """Fill location['facility_id'] from its stop name (e.g. 'Big-Box DC135'), a missing city/state, and the
    facility's own requirements (location['requirements'])."""
    location["facility_id"] = None
    location["requirements"] = []
    if not location.get("name"):
        return location
    hits, _ = _search_names(location["name"], "facilities")
    city = location.get("city")
    same_city = [h for h in hits if city and city.lower() in (h.get("sublabel") or "").lower()]
    if not (same_city or hits):
        return location
    hit = (same_city or hits)[0]
    location["facility_id"] = hit["entity_id"]
    location["requirements"] = facility_requirements(hit["entity_id"])
    # sublabel looks like "VALIANT-DSM | Des Moines, IA"
    place = (hit.get("sublabel") or "").split("|")[-1]
    if "," in place:
        fac_city, fac_state = (part.strip() for part in place.rsplit(",", 1))
        location["city"] = location.get("city") or fac_city
        location["state"] = location.get("state") or fac_state
    return location


# ---------- prospects ----------

def _top_options(options):
    """The ok options in their sorted order: the top MAX_OPTIONS plus any others tied with the last one's score."""
    ok = [o for o in options if o["ok"]]
    if len(ok) <= MAX_OPTIONS:
        return ok
    cutoff = ok[MAX_OPTIONS - 1]["score"] or 0
    return [o for o in ok if (o["score"] or 0) >= cutoff]


def _city_state(loc):
    """Prospect locations may be {city, state} dicts or 'City, ST' strings; return (city, state)."""
    if isinstance(loc, dict):
        return loc.get("city"), loc.get("state")
    if isinstance(loc, str) and "," in loc:
        city, state = loc.rsplit(",", 1)
        return city.strip(), state.strip()
    return loc, None


def _days_between(a, b):
    """b - a in days for two YYYY-MM-DD strings, or None."""
    try:
        return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days
    except (TypeError, ValueError):
        return None


def _trucks_at(city, state):
    """Trucks arriving in a city, taken from find_backhauls and de-duplicated by outbound file."""
    trucks = {}
    for p in find_backhauls(city, state):
        key = p.get("outbound_file") or p.get("prospect_id")
        trucks.setdefault(key, p)
    return list(trucks.values())


def _candidate_from_request(extracted):
    """The freight in a quote request, shaped as a check_compat candidate."""
    lines = extracted.get("freight_lines") or []
    category = extracted.get("category") or "GENERAL"
    if extracted.get("hazmat"):
        category = "HAZMAT"
    return {
        "category": category,
        "temp_controlled": bool(extracted.get("temp_controlled")),
        "hazmat": bool(extracted.get("hazmat")),
        "weight_lb": sum(l.get("weight_lb") or 0 for l in lines),
        "pallets": sum(l.get("pieces") or 0 for l in lines if l.get("package_type") in ("PALLET", "SKID", None)),
        "description": "; ".join(l.get("description") or "" for l in lines),
    }


def _option_for_truck(truck, candidate, requested_equipment, pickup_date, home_city, home_state):
    """Run check_compat for one arriving truck carrying the email's freight; returns an option dict."""
    carrier = get_vendor(truck["carrier_id"]) if truck.get("carrier_id") else None
    equipment = truck.get("equipment")
    cand = dict(candidate, trailer_number=truck.get("trailer_number"), carrier_id=truck.get("carrier_id"))
    last_category = truck.get("trailer_last_category")
    history = store.emailed_last_load(truck.get("trailer_number"))
    if history and history["category"]:
        last_category = history["category"]
    ok, reasons = check_compat(last_category, equipment, cand, carrier)
    reasons = list(reasons)
    if history and history["category"]:
        reasons.insert(0, f"Trailer history from email {history['email_id']}: last hauled "
                          f"{history['commodity']} ({history['category']}), not in Meridian.")

    if requested_equipment and equipment not in EQUIPMENT_FITS.get(requested_equipment, {requested_equipment}):
        ok = False
        reasons.append(f"Blocked: request needs equipment {requested_equipment}, truck is {equipment}.")
    if not truck.get("carrier_id"):
        reasons.append("No carrier assigned to the outbound load yet.")

    score = 50 if ok else 0
    truck_home_city, truck_home_state = _city_state(truck.get("destination"))
    if home_city and truck_home_city and truck_home_city.lower() == home_city.lower():
        score += 30
        reasons.append(f"Truck is heading home to {truck_home_city}, exactly where this freight goes.")
    elif home_state and truck_home_state == home_state:
        score += 15
        reasons.append(f"Truck is heading home to {truck_home_state}, same state as the delivery.")
    gap = _days_between(truck.get("available_date"), pickup_date)
    if gap is not None:
        if 0 <= gap <= 2:
            score += 20
            reasons.append(f"Truck empties {gap} day(s) before the requested pickup.")
        elif gap < 0:
            score -= 20
            reasons.append(f"Truck only empties {-gap} day(s) after the requested pickup.")
        else:
            reasons.append(f"Truck empties {gap} days before pickup (long wait).")
    return {
        "outbound_file": truck.get("outbound_file"),
        "outbound_status": truck.get("outbound_status"),
        "delivery_facility_id": truck.get("delivery_facility_id"),
        "carrier_id": truck.get("carrier_id"),
        "carrier_compliance": (carrier or {}).get("compliance_light"),
        "trailer_number": truck.get("trailer_number"),
        "equipment": equipment,
        "trailer_last_category": last_category,
        "available_date": truck.get("available_date"),
        "heading_home_to": f"{truck_home_city}, {truck_home_state}",
        "ok": ok,
        "score": max(score, 0),
        "reasons": reasons,
    }


# Tiebreakers for trucks with the same score, strongest first.
TIEBREAKERS = ["same pickup facility", "load status", "carrier compliance", "known trailer", "lower file number"]
# How sure we are the truck really shows up empty: further along in its outbound trip = more certain.
STATUS_CERTAINTY = {"DELIVERED": 6, "AT_DELIVERY": 5, "IN_TRANSIT": 4, "PICKED_UP": 3, "AT_PICKUP": 3,
                    "DISPATCHED": 2, "COVERED": 1, "BOOKED": 0}
COMPLIANCE_RANK = {"GREEN": 2, "YELLOW": 1, "RED": 0}


def _tiebreak_values(option, pickup_facility_id):
    """One value per TIEBREAKERS entry; bigger wins. The file number is negated so the lowest (oldest) wins."""
    file_no = str(option.get("outbound_file") or "")
    return (
        bool(pickup_facility_id) and option.get("delivery_facility_id") == pickup_facility_id,
        STATUS_CERTAINTY.get(option.get("outbound_status"), -1),
        COMPLIANCE_RANK.get(option.get("carrier_compliance"), -1),
        option.get("trailer_number") is not None,
        -int(file_no) if file_no.isdigit() else float("-inf"),
    )


def _rank_trucks(options, pickup_facility_id):
    """Sort truck options (ok first, then score, then the tiebreakers) and explain a tie on the winner."""
    options.sort(key=lambda o: (o["ok"], o["score"], *_tiebreak_values(o, pickup_facility_id)), reverse=True)
    if len(options) > 1 and options[0]["ok"] and options[1]["ok"] and options[0]["score"] == options[1]["score"]:
        win, lose = _tiebreak_values(options[0], pickup_facility_id), _tiebreak_values(options[1], pickup_facility_id)
        decided_by = next((name for name, a, b in zip(TIEBREAKERS, win, lose) if a != b),
                          "equal footing (first listed)")
        detail = {"load status": f" ({options[0]['outbound_status']} vs {options[1]['outbound_status']})",
                  "carrier compliance": f" ({options[0]['carrier_compliance']} vs {options[1]['carrier_compliance']})"}
        options[0]["reasons"].append(f"Tied on score with outbound file {options[1]['outbound_file']}; "
                                     f"chosen on {decided_by}{detail.get(decided_by, '')}.")
    return options


def match_quote_request(email_id, email, extracted):
    """Resolve the customer and look for a truck already running empty out of the request's origin."""
    origin, dest = extracted["origin"], extracted["destination"]
    customer = resolve_customer(extracted.get("customer_hint"), email["from"])
    resolve_facility(origin)
    resolve_facility(dest)
    result = {"customer": customer, "origin": origin, "destination": dest, "options": [], "prospect": None}

    missing = [label for label, value in (("origin", origin.get("city") and origin.get("state")),
                                          ("destination", dest.get("city") and dest.get("state")))
               if not value]
    if missing:
        result.update(status="none_found", reasons=[f"No {m} city/state in the email." for m in missing])
        return result

    candidate = _candidate_from_request(extracted)
    trucks = _trucks_at(origin["city"], origin["state"])
    options = [
        _option_for_truck(t, candidate, extracted.get("equipment"), extracted.get("pickup_date"),
                          dest["city"], dest["state"])
        for t in trucks
    ]
    _rank_trucks(options, origin.get("facility_id"))
    result["options"] = _top_options(options)
    result["blocked"] = [o for o in options if not o["ok"]]

    best = options[0] if options and options[0]["ok"] else None
    if not best:
        reasons = [f"No truck is running empty out of {origin['city']}, {origin['state']}."] if not options else \
            ["Every truck emptying there is blocked:"] + sorted({r for o in options for r in o["reasons"] if r.startswith("Blocked")})
        result.update(status="none_found", reasons=reasons)
        return result
    if not customer["entity_id"]:
        result.update(status="none_found", reasons=[f"A truck fits, but the customer '{customer['hint']}' is not in Meridian."])
        return result

    result["status"] = "prospect"
    result["prospect"] = {
        "prospect_id": f"email-{email_id}",
        "source": "email",
        "customer_id": customer["entity_id"],
        "customer_name": customer["label"],
        "origin": origin,
        "destination": dest,
        "equipment": extracted.get("equipment") or best["equipment"],
        "category": candidate["category"],
        "outbound_file": best["outbound_file"],
        "carrier_id": best["carrier_id"],
        "trailer_number": best["trailer_number"],
        "score": best["score"],
        "ok": True,
        "reasons": best["reasons"],
    }
    return result


# ---------- trailers ----------

def trailer_position(carrier_id, trailer_number):
    """Latest active Meridian shipment for this carrier's trailer, as {city, state, outbound_file, date}, or None."""
    if not carrier_id or not trailer_number:
        return None
    page = _safe_get("/shipments", carrier=carrier_id, status=ACTIVE_STATUSES, limit=200) or {}
    mine = [s for s in page.get("items", []) if str(s.get("trailer_number")) == str(trailer_number)]
    if not mine:
        return None
    s = max(mine, key=lambda s: s.get("delivery_date_target") or "")
    return {"city": s["consignee_city"], "state": s["consignee_state"], "outbound_file": s["shipment_id"],
            "date": s.get("delivery_date_target")}


def _rerun_prospect(prospect, trailer_last_category, equipment, carrier, trailer_number):
    """Re-check a finder prospect as if this specific truck took it; returns an option dict."""
    candidate = {
        "category": prospect.get("category") or "GENERAL",
        "temp_controlled": bool(prospect.get("temp_controlled")) or (
            prospect.get("category") in FOOD_CATEGORIES and prospect.get("equipment") == "R"),
        "hazmat": prospect.get("category") == "HAZMAT",
        "weight_lb": prospect.get("weight_lb"),
        "pallets": prospect.get("pallets"),
        "trailer_number": trailer_number,
        "carrier_id": carrier and carrier.get("vendor_id"),
    }
    ok, reasons = check_compat(trailer_last_category, equipment, candidate, carrier)
    return {
        "prospect_id": prospect.get("prospect_id"),
        "customer_id": prospect.get("customer_id"),
        "customer_name": prospect.get("customer_name"),
        "origin": prospect.get("origin"),
        "destination": prospect.get("destination"),
        "category": prospect.get("category"),
        "equipment": equipment,
        "miles": prospect.get("miles"),
        "score": max(prospect.get("score") or 0, 50) if ok else 0,
        "ok": ok,
        "reasons": list(reasons),
    }


def _prospects_for_truck(city, state, trailer_last_category, equipment, carrier, trailer_number):
    """Every prospect out of a city, re-checked for this truck; ok ones first."""
    options = [
        _rerun_prospect(p, trailer_last_category, equipment or p.get("equipment"), carrier, trailer_number)
        for p in find_backhauls(city, state)
    ]
    # The finder lists freight once per arriving truck; this truck only needs each load once.
    unique = {}
    for o in options:
        key = (o["customer_id"], str(o["origin"]), str(o["destination"]), o["category"])
        unique.setdefault(key, o)
    return sorted(unique.values(), key=lambda o: (o["ok"], o["score"] or 0), reverse=True)


def match_washout(email_id, email, extracted, email_text):
    """Store the washout certificate, then report which blocked prospects it now unblocks."""
    carrier = resolve_carrier(extracted.get("carrier_hint"), email_text)
    trailer = extracted.get("trailer_number")
    result = {"carrier": carrier, "trailer_number": trailer, "washout_id": None, "unblocked": [], "position": None}
    if not trailer:
        result.update(status="none_found", reasons=["No trailer number in the certificate; not recorded."])
        return result

    result["washout_id"] = store.insert_washout(
        carrier["entity_id"], trailer, extracted.get("washed_at"), extracted.get("facility"),
        extracted.get("cert_number"), email_id,
    )

    # 1. Finder prospects where this trailer is emptying, now re-checked with the washout on file.
    position = trailer_position(carrier["entity_id"], trailer)
    result["position"] = position
    if position:
        for p in find_backhauls(position["city"], position["state"]):
            if (str(p.get("trailer_number")) == str(trailer) and p.get("ok")
                    and p.get("category") in FOOD_CATEGORIES
                    and p.get("trailer_last_category") in RISKY_LAST_LOADS):
                result["unblocked"].append({"source": "network", "prospect_id": p.get("prospect_id"),
                                            "customer_id": p.get("customer_id"), "category": p.get("category"),
                                            "origin": p.get("origin"), "destination": p.get("destination")})

    # 2. Options on earlier quote-request emails that were blocked by FSMA for this trailer.
    for other in store.list_emails(status="processed"):
        other_matched = other.get("matched") or {}
        for opt in other_matched.get("blocked", []):
            fsma_blocked = any("FSMA" in r and r.startswith("Blocked") for r in opt.get("reasons", []))
            if str(opt.get("trailer_number")) == str(trailer) and fsma_blocked:
                result["unblocked"].append({"source": "email", "email_id": other["email_id"],
                                            "subject": other["subject"], "outbound_file": opt["outbound_file"],
                                            "carrier_id": opt["carrier_id"]})

    result["status"] = "recorded"
    result["reasons"] = [f"Washout for trailer {trailer} recorded"
                         + (f" for carrier {carrier['entity_id']}." if carrier["entity_id"] else " (carrier not matched).")]
    return result


def _quote_options_now_blocked(email_id, trailer, last_category):
    """Food quote requests that had planned on this trailer, which the emailed last load now rules out."""
    if not trailer or last_category not in RISKY_LAST_LOADS:
        return []
    hits = []
    for other in store.list_emails(status="processed"):
        if other["kind"] != "QUOTE_REQUEST" or other["email_id"] == email_id:
            continue
        if (other.get("extracted") or {}).get("category") not in FOOD_CATEGORIES:
            continue
        for opt in (other.get("matched") or {}).get("options", []):
            if str(opt.get("trailer_number")) == str(trailer) and not store.washouts_for_trailer(trailer):
                hits.append({"email_id": other["email_id"], "subject": other["subject"],
                             "outbound_file": opt["outbound_file"], "carrier_id": opt["carrier_id"],
                             "reason": f"Blocked: trailer {trailer} last hauled {last_category}; "
                                       "FSMA requires a washout before food."})
    return hits


def match_last_load(email_id, email, extracted, email_text):
    """Re-check the prospects at the truck's position using the last load the carrier told us about."""
    carrier_ref = resolve_carrier(extracted.get("carrier_hint"), email_text)
    carrier = get_vendor(carrier_ref["entity_id"]) if carrier_ref["entity_id"] else None
    trailer = extracted.get("trailer_number")
    city, state = extracted.get("last_delivery_city"), extracted.get("last_delivery_state")
    if not (city and state):
        pos = trailer_position(carrier_ref["entity_id"], trailer)
        city, state = (pos["city"], pos["state"]) if pos else (None, None)

    result = {"carrier": carrier_ref, "trailer_number": trailer, "position": {"city": city, "state": state},
              "last_commodity_category": extracted.get("last_commodity_category"), "options": [], "prospect": None}
    if not (city and state):
        result.update(status="none_found", reasons=["Can't tell where the truck is empty."])
        return result

    equipment = (carrier or {}).get("equipment_types", ["V"])[0] if carrier else None
    options = _prospects_for_truck(city, state, extracted.get("last_commodity_category"), equipment, carrier, trailer)
    result["options"] = _top_options(options)
    result["blocked"] = [o for o in options if not o["ok"]]
    result["newly_blocked"] = _quote_options_now_blocked(email_id, trailer, extracted.get("last_commodity_category"))
    usable = [o for o in options if o["ok"]]
    result["prospect"] = usable[0] if usable else None
    result["status"] = "prospect" if usable else "none_found"
    result["reasons"] = [] if usable else ["Nothing compatible with this trailer's last load out of "
                                           f"{city}, {state}."]
    return result


def match_carrier_offer(email_id, email, extracted, email_text):
    """Find prospects out of the city where the offered truck is empty."""
    carrier_ref = resolve_carrier(extracted.get("carrier_hint"), email_text)
    carrier = get_vendor(carrier_ref["entity_id"]) if carrier_ref["entity_id"] else None
    city, state = extracted.get("empty_city"), extracted.get("empty_state")
    result = {"carrier": carrier_ref, "position": {"city": city, "state": state}, "options": [], "prospect": None}
    if not (city and state):
        result.update(status="none_found", reasons=["The offer doesn't say where the truck is empty."])
        return result

    # Trailer history: what Meridian knows about this trailer, if the carrier gave a number.
    last_category = None
    if extracted.get("trailer_number"):
        pos = trailer_position(carrier_ref["entity_id"], extracted["trailer_number"])
        if pos:
            last_category = next((p.get("trailer_last_category") for p in find_backhauls(pos["city"], pos["state"])
                                  if p.get("outbound_file") == pos["outbound_file"]), None)

    options = _prospects_for_truck(city, state, last_category, extracted.get("equipment"), carrier,
                                   extracted.get("trailer_number"))
    wants = (extracted.get("preferred_direction") or "").lower()
    for o in options:
        dest_city, dest_state = _city_state(o["destination"])
        if o["ok"] and wants and ((dest_city and dest_city.lower() in wants)
                                  or (dest_state and re.search(rf"\b{dest_state.lower()}\b", wants))):
            o["score"] += 30
            o["reasons"].append(f"Heads where the carrier wants to go ({extracted['preferred_direction']}).")
    options.sort(key=lambda o: (o["ok"], o["score"]), reverse=True)
    result["options"] = _top_options(options)
    result["blocked"] = [o for o in options if not o["ok"]]
    usable = [o for o in options if o["ok"]]
    result["prospect"] = usable[0] if usable else None
    result["status"] = "prospect" if usable else "none_found"
    result["reasons"] = [] if usable else [f"No compatible freight out of {city}, {state} right now."]
    return result


def match(kind, email_id, email, extracted, email_text):
    """Dispatch to the matcher for this email kind."""
    if kind == "QUOTE_REQUEST":
        return match_quote_request(email_id, email, extracted)
    if kind == "WASHOUT_CERT":
        return match_washout(email_id, email, extracted, email_text)
    if kind == "LAST_LOAD_INFO":
        return match_last_load(email_id, email, extracted, email_text)
    if kind == "CARRIER_OFFER":
        return match_carrier_offer(email_id, email, extracted, email_text)
    return None
