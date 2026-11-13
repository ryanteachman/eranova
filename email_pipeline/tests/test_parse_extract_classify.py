"""Steps 1-4: parsing emails, cleaning the model's extraction, and the needs-review rules."""

from email.message import EmailMessage

from email_pipeline import extract, parse
from email_pipeline.classify import needs_review
from email_pipeline.pipeline import missing_essentials


# ---------- parse.py ----------

def test_eml_inlines_text_attachments_and_skips_binary_ones():
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "Lena Fitch <lfitch@cascadepkg.example.com>", "quotes@x", "Kent -> Portland"
    msg["Date"] = "Fri, 13 Nov 2026 10:00:00 -0800"
    msg.set_content("Need a dry van Kent WA to Portland OR Tue 11/17.")
    msg.add_attachment("bale count: 22", subtype="plain", filename="bales.txt")
    msg.add_attachment(b"%PDF-1.4", maintype="application", subtype="pdf", filename="bol.pdf")

    email = parse.parse_eml(bytes(msg))
    assert email["subject"] == "Kent -> Portland" and email["received_at"] == "2026-11-13T10:00:00-08:00"
    assert [(a["filename"], a["text"]) for a in email["attachments"]] == [("bales.txt", "bale count: 22\n"),
                                                                           ("bol.pdf", None)]
    prompt = parse.as_prompt_text(email)
    assert "bale count: 22" in prompt and "(binary attachment, no text extracted)" in prompt


def test_json_accepts_from_addr_and_strips_the_body():
    email = parse.parse_json({"from_addr": "a@b.c", "subject": "s", "body": "  hi  \n"})
    assert (email["from"], email["body"], email["attachments"]) == ("a@b.c", "hi", [])


def test_sample_emails_all_parse():
    from pathlib import Path
    samples = sorted((Path(__file__).resolve().parents[2] / "demo" / "sample_emails").glob("*.json"))
    assert len(samples) == 7
    for path in samples:
        email = parse.parse_file(path)
        assert email["from"] and email["subject"] and email["body"]


# ---------- extract.py: the model's output is cleaned before use ----------

def test_null_strings_become_none_and_bad_states_are_dropped():
    cleaned = extract._clean({"origin": {"city": "Aurora", "state": "co", "zip": "null"},
                              "destination": {"city": "Des Moines", "state": "null", "zip": "None"},
                              "empty_state": "Texas", "note": " N/A ", "freight_lines": []})
    assert cleaned == {"origin": {"city": "Aurora", "state": "CO", "zip": None},
                       "destination": {"city": "Des Moines", "state": None, "zip": None},
                       "empty_state": None, "note": None, "freight_lines": []}


def test_extract_drops_invented_and_empty_references(fake_llm):
    # The 02 bug: the model wrote "null" for the state; and it invented a PO number not in the email.
    fake_llm.script["QuoteRequest"] = {
        "customer_hint": "Valiant", "origin": {"city": "Aurora", "state": "CO", "zip": None, "name": None},
        "destination": {"city": "Des Moines", "state": "null", "zip": "null", "name": "Valiant Des Moines Plant"},
        "pickup_date": "2026-11-16", "equipment": "R", "freight_lines": [], "accessorials": [],
        "references": [{"type": "RMA", "value": "VF-RMA-2281"}, {"type": "PO", "value": "PO-99999"},
                       {"type": "BOL", "value": "N/A"}],
        "temp_controlled": True, "hazmat": None, "category": "FOOD",
    }
    email = {"from": "m@valiantfoods.example.com", "subject": "reefer", "received_at": None, "attachments": [],
             "body": "Pickup Aurora CO Mon 11/16, RMA # VF-RMA-2281 on the BOL."}
    data = extract.extract("QUOTE_REQUEST", email)
    assert data["destination"]["state"] is None and data["destination"]["zip"] is None
    assert data["references"] == [{"type": "RMA", "value": "VF-RMA-2281"}]


def test_washout_cert_number_must_appear_in_the_email(fake_llm):
    fake_llm.script["WashoutCert"] = {"carrier_hint": "Lakeshore", "trailer_number": "53661", "washed_at": "2026-11-13",
                                      "facility": "Hutchins TX", "cert_number": "WO-00000"}
    email = {"from": "d@lakeshore.example.com", "subject": "wash", "received_at": None, "body": "Trailer 53661 washed.",
             "attachments": [{"filename": "t.pdf", "content_type": "application/pdf", "text": "Cert No: WO-77841"}]}
    assert extract.extract("WASHOUT_CERT", email)["cert_number"] is None


def test_other_kind_extracts_nothing():
    assert extract.extract("OTHER", {"from": "", "subject": "", "body": ""}) is None


# ---------- review rules ----------

def test_needs_review_below_threshold_or_other():
    assert needs_review({"kind": "QUOTE_REQUEST", "confidence": 0.69})
    assert needs_review({"kind": "OTHER", "confidence": 0.99})
    assert not needs_review({"kind": "QUOTE_REQUEST", "confidence": 0.7})


def test_missing_essentials_per_kind():
    assert missing_essentials("QUOTE_REQUEST", {"origin": {"city": None}, "destination": {"city": None}}) == \
        ["origin city", "destination city"]                       # the 06 "trucks?" email
    assert missing_essentials("WASHOUT_CERT", {"trailer_number": None}) == ["trailer number"]
    assert missing_essentials("LAST_LOAD_INFO", {"trailer_number": "53912", "last_commodity": None}) == ["last commodity"]
    assert missing_essentials("CARRIER_OFFER", {"empty_city": "Newark"}) == []
