"""LLM step 1: decide what kind of email this is."""

from typing import Literal

from pydantic import BaseModel, Field

from email_pipeline.llm import structured
from email_pipeline.parse import as_prompt_text

KINDS = ("QUOTE_REQUEST", "WASHOUT_CERT", "LAST_LOAD_INFO", "CARRIER_OFFER", "OTHER")
CONFIDENCE_THRESHOLD = 0.7


class Classification(BaseModel):
    kind: Literal["QUOTE_REQUEST", "WASHOUT_CERT", "LAST_LOAD_INFO", "CARRIER_OFFER", "OTHER"]
    confidence: float = Field(description="0.0-1.0: how sure you are, and whether the email is actionable as that kind")
    rationale: str = Field(description="One sentence citing the words in the email that decided it")


# Prompt for sorting freight-brokerage inbox mail into the five kinds the pipeline handles.
CLASSIFY_PROMPT = """You sort the inbox of a freight brokerage (Meridian Logistics). Pick exactly one kind:

QUOTE_REQUEST  - a shipper or customer asks us for a price or a truck to move freight (a lane, a date, freight).
WASHOUT_CERT   - a carrier sends proof that a trailer was washed out / sanitized (a wash ticket or certificate).
LAST_LOAD_INFO - a carrier tells us what a trailer last hauled, or where/when a truck will be empty, WITHOUT offering it for a load.
CARRIER_OFFER  - a carrier offers capacity: an empty truck looking for a load (often with a rate ask).
OTHER          - anything else: invoices, tracking updates, newsletters, chit-chat.

Tie-breakers:
- Any email that sends a wash ticket / washout certificate is WASHOUT_CERT, even if it also mentions the
  previous load or asks for freight.
- If a carrier both says what the trailer last hauled and asks for a load, use LAST_LOAD_INFO when the
  trailer's history is the main point, CARRIER_OFFER when the truck availability is.

Confidence: use 0.9+ when the kind is clear and the email has the key facts for that kind. Use 0.5 or
lower when the email is too vague to act on, even if you can guess the kind - e.g. a quote request with
no origin or destination ("do you have trucks next week?"), a washout with no trailer number."""


def classify_email(email):
    """Classify an email dict; returns {kind, confidence, rationale}."""
    result = structured(CLASSIFY_PROMPT, as_prompt_text(email), Classification)
    confidence = max(0.0, min(1.0, result.confidence))
    return {"kind": result.kind, "confidence": round(confidence, 2), "rationale": result.rationale}


def needs_review(classification):
    """True when the pipeline should stop and leave the email for a person."""
    return classification["kind"] == "OTHER" or classification["confidence"] < CONFIDENCE_THRESHOLD
