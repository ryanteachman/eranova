"""LLM step 2: structured extraction, one schema and one function per email kind.

Unknown fields are null. The prompts forbid guessing reference numbers or dates, and
`_drop_invented_references` double-checks references against the email text.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from email_pipeline.llm import structured
from email_pipeline.parse import as_prompt_text

Equipment = Literal["V", "R", "F", "SD", "PO", "HS", "SB", "SV", "VC", "DD"]
PackageType = Literal["PALLET", "CRATE", "BOX", "SKID", "DRUM", "BUNDLE", "ROLL", "TOTE", "PIECE"]
Category = Literal[
    "FOOD", "BEVERAGE", "CHEMICAL", "HAZMAT", "WASTE", "WOOD", "STEEL", "SCRAP",
    "PACKAGING", "RETAIL_RETURNS", "MACHINERY", "GENERAL",
]

COMMON_RULES = """Rules:
- Use null for anything the email does not say. Never invent a reference number, cert number, trailer number or date.
- Dates are YYYY-MM-DD. A weekday ("Tue", "this Thursday") may be resolved against the date the email was received; if there is no day at all, use null.
- States are 2-letter codes. Equipment codes: V dry van, R reefer, F flatbed, SD step deck, PO power only, HS hotshot, SB box truck, SV sprinter, VC curtain van, DD double drop.
- Category is the freight family: FOOD, BEVERAGE, CHEMICAL, HAZMAT (any UN number or placarded load), WASTE, WOOD, STEEL, SCRAP, PACKAGING, RETAIL_RETURNS (store returns, RTV, salvage, displays coming back from stores), MACHINERY, GENERAL."""


# ---------- QUOTE_REQUEST ----------

class Location(BaseModel):
    city: str | None
    state: str | None
    zip: str | None
    name: str | None = Field(description="Facility or company name at this stop, e.g. 'Big-Box DC135'")


class FreightLine(BaseModel):
    pieces: int | None
    weight_lb: float | None
    package_type: PackageType | None
    description: str | None


class Reference(BaseModel):
    type: str = Field(description="PO, RA, BOL, SO, PU, etc. as written in the email")
    value: str


class QuoteRequest(BaseModel):
    customer_hint: str | None = Field(description="Who we would bill: company name as written, e.g. 'Northstar Manufacturing'")
    origin: Location
    destination: Location
    pickup_date: str | None
    equipment: Equipment | None = Field(description="Requested or clearly required equipment, e.g. R when temperature control is needed")
    freight_lines: list[FreightLine]
    accessorials: list[str] = Field(description="Extra services asked for, e.g. liftgate, appointment, lumper, inside delivery")
    references: list[Reference]
    temp_controlled: bool | None
    hazmat: bool | None
    category: Category | None = Field(description="Freight family of what is being shipped")


# Prompt for pulling a shipper's quote request into Meridian's quote fields.
QUOTE_PROMPT = f"""Extract a freight quote request from this email for a truckload broker.
The customer is the company that will pay (often named after "bill to"), not necessarily the sender's site.
{COMMON_RULES}"""


def extract_quote_request(email):
    """Pull lane, date, equipment, freight and references out of a QUOTE_REQUEST email."""
    data = structured(QUOTE_PROMPT, as_prompt_text(email), QuoteRequest).model_dump()
    data["references"] = _drop_invented_references(data["references"], email)
    return data


# ---------- WASHOUT_CERT ----------

class WashoutCert(BaseModel):
    carrier_hint: str | None = Field(description="Carrier company name, MC or DOT number as written")
    trailer_number: str | None
    washed_at: str | None = Field(description="Date (YYYY-MM-DD) or date-time of the washout")
    facility: str | None = Field(description="Wash facility name and city")
    cert_number: str | None


# Prompt for reading a carrier's washout / sanitation certificate (body or attachment).
WASHOUT_PROMPT = f"""Extract the trailer washout certificate details from this carrier email and its attachments.
{COMMON_RULES}"""


def extract_washout_cert(email):
    """Pull carrier, trailer, wash date, facility and certificate number out of a WASHOUT_CERT email."""
    data = structured(WASHOUT_PROMPT, as_prompt_text(email), WashoutCert).model_dump()
    if data["cert_number"] and not _appears_in(data["cert_number"], email):
        data["cert_number"] = None
    return data


# ---------- LAST_LOAD_INFO ----------

class LastLoadInfo(BaseModel):
    carrier_hint: str | None
    trailer_number: str | None
    last_commodity: str | None = Field(description="What the trailer last hauled, as written (include any UN number)")
    last_commodity_category: Category | None
    last_delivery_city: str | None = Field(description="City where the trailer is now empty / available for its next load")
    last_delivery_state: str | None = Field(description="State where the trailer is now empty / available")
    available_date: str | None


# Prompt for capturing a carrier's note about a trailer's previous load (FSMA trailer history).
LAST_LOAD_PROMPT = f"""Extract what this carrier says about a trailer's most recent load and where/when it is empty.
{COMMON_RULES}"""


def extract_last_load_info(email):
    """Pull carrier, trailer, last commodity and empty location/date out of a LAST_LOAD_INFO email."""
    return structured(LAST_LOAD_PROMPT, as_prompt_text(email), LastLoadInfo).model_dump()


# ---------- CARRIER_OFFER ----------

class CarrierOffer(BaseModel):
    carrier_hint: str | None
    equipment: Equipment | None
    empty_city: str | None
    empty_state: str | None
    available_date: str | None
    rate_ask: str | None = Field(description="The carrier's rate ask as written, e.g. '$2.10/mi' or '$1,900 all in'")
    trailer_number: str | None
    preferred_direction: str | None = Field(description="Where the carrier wants to head, including every city/state they name, e.g. 'west - Chicago/Rockford, PA or OH'")


# Prompt for reading a carrier's capacity offer (empty truck looking for a load).
OFFER_PROMPT = f"""Extract this carrier's capacity offer: the empty truck, where and when it is empty, and the rate ask.
{COMMON_RULES}"""


def extract_carrier_offer(email):
    """Pull equipment, empty location/date and rate ask out of a CARRIER_OFFER email."""
    return structured(OFFER_PROMPT, as_prompt_text(email), CarrierOffer).model_dump()


EXTRACTORS = {
    "QUOTE_REQUEST": extract_quote_request,
    "WASHOUT_CERT": extract_washout_cert,
    "LAST_LOAD_INFO": extract_last_load_info,
    "CARRIER_OFFER": extract_carrier_offer,
}


def extract(kind, email):
    """Run the extractor for this kind; returns None for OTHER."""
    extractor = EXTRACTORS.get(kind)
    return extractor(email) if extractor else None


# ---------- guards against invented values ----------

def _normalize(text):
    """Uppercase letters and digits only, the way Meridian's search normalizes references."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _appears_in(value, email):
    """True when value (normalized) occurs somewhere in the email text or attachments."""
    return _normalize(value) in _normalize(as_prompt_text(email))


def _drop_invented_references(references, email):
    """Keep only reference numbers that literally appear in the email."""
    return [ref for ref in references if ref.get("value") and _appears_in(ref["value"], email)]
