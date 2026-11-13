# Email pipeline (owner: Asher)

Email is how the outside world reaches Return Trip. Shippers ask for prices on return lanes,
and carriers send washout certificates, last-load details and empty-truck offers. `email_pipeline/`
turns each email into structured data, checks it against trucks that are about to run home
empty, and queues a **draft quote + draft reply for human approval**. Nothing is ever really sent:
replies wait in the `outbox` table and only move to `approved_sent` when a person approves them.

## Run it

```bash
pip install -r requirements.txt            # openai + pydantic are used for the LLM steps
# .env needs TMS_API_BASE, TMS_API_KEY, OPENAI_API_KEY (optional: OPENAI_MODEL_FAST, default gpt-4o-mini)
python scripts/sync_data.py                # once: Ryan's cache of shipments, carriers, customers, categories

python -m email_pipeline run demo/sample_emails/01_quote_dallas_returns.json   # one sample
python -m email_pipeline run all                                             # every sample
python -m email_pipeline inbox | outbox
python -m email_pipeline approve <action_id>     # Ryan's approval queue (a quote approval creates it in Meridian)
python -m email_pipeline reject <action_id> [reason]

flask --app backend run --debug --port 5000      # the whole API, email routes at /api/email
```

Set `DB_PATH=/some/scratch.db` to try things without touching `return_trip.db` (sync into it first).
Approving a `create_return_quote` creates a real quote in Meridian; `python scripts/reset_demo.py`
declines Return Trip quotes afterwards.

**Demo order** (each email builds on the last):

| # | File | What happens |
|---|---|---|
| 1 | `01_quote_dallas_returns.json` | Big-Box DC135 asks to move Northstar returns from Dallas to Chicago. Acme's truck on outbound 7300156 empties at DC135 and is heading home to Chicago → `create_return_quote` + reply with `{{sell_total}}` |
| 2 | `02_quote_food_needs_reefer.json` | Valiant dairy returns from Aurora, kept at 34–38 °F. The dry vans arriving in Aurora are blocked; Canyon Freight's reefer (7300159) is heading home to Des Moines → quote |
| 3 | `07_quote_food_out_of_dallas.json` | Midway dry grocery from Dallas to Kansas City. Lone Star's UN1760 trailers are FSMA-blocked; clean trucks are offered instead |
| 4 | `04_last_load_hazmat.json` | Prairie Haul says trailer 53912 hauled caustic cleaner (UN1719) **after** our load, which Meridian doesn't know about. Food is now blocked for it and the Midway option on 53912 is flagged in `newly_blocked` |
| 5 | `03_washout_cert.json` | Lakeshore sends a wash ticket for 53661 → row in `washouts`, and the Midway option on 53661 shows up in `unblocked` |
| 6 | `05_carrier_empty_offer.json` | Gulfstream reefer empty in Newark, wants to head west → Ironpeak freight to Pittsburgh ranks first. Stretch: `POST /api/email/<id>/haggle` |
| 7 | `06_vague.json` | "do you have trucks next week?" → `needs_review`, no actions |

`07_quote_food_out_of_dallas.json` was added (spec asked for 6–8) so the washout and last-load
emails have a food request to block and unblock. All customers, carriers, facilities, trailers
and outbound files in the samples are real records in our Meridian environment.

## Pipeline steps (`pipeline.process_email`)

`process_email(email)` takes a JSON/`.eml`-shaped dict (or a stored `email_id` to re-run) and returns
`{email_id, status, kind, confidence, rationale, extracted, matched, actions_created, reply_id, error}`.

1. **Parse** (`parse.py`): `.eml` or JSON → `{from, to, subject, body, received_at, attachments[{filename, content_type, text}]}`.
   Text attachments are inlined into the prompt (the washout sample carries its certificate this way).
2. **Store**: insert into `emails` as `new`, then `processing`.
3. **Classify** (`classify.py`): `{kind, confidence, rationale}`. `OTHER` or confidence **< 0.7** → `needs_review`, stop.
4. **Extract** (`extract.py`): the schema for that kind (below). If the kind's essentials are missing
   (quote: origin and destination city; washout: trailer; last load: trailer and commodity; offer: empty city),
   → `needs_review`, stop. This is what reliably catches `06_vague`.
5. **Match** (`match.py`): Meridian records and prospects (below).
6. **Propose** `create_return_quote` if there is a usable prospect.
7. **Reply** (`reply.py`): draft → `outbox` (`draft`) → propose `send_reply`.
8. Status `processed`. Any exception → `failed` with `error`, keeping what was saved so far.

Every step writes a line to `audit_log` with `actor="email_pipeline"` (`email_received`,
`email_classified`, `email_extracted`, `email_matched`, `action_proposed`, `reply_drafted`,
`email_processed` / `email_needs_review` / `email_failed`, `reply_sent`, `haggle_finished`).

## Email kinds and schemas

Unknown fields are `null`. The prompts forbid guessing reference numbers, cert numbers or dates, and the
code drops any extracted reference (or cert number) that doesn't literally appear in the email.
Weekdays ("this Tue") are resolved against `received_at`. The model's output is cleaned before use: strings like
`"null"`, `"none"` or `"N/A"` become real nulls, and a state that isn't a 2-letter code is dropped, so a
missing state can still be filled in from the matched facility.

| Kind | Fields |
|---|---|
| `QUOTE_REQUEST` | `customer_hint, origin{city,state,zip,name}, destination{…}, pickup_date, equipment, freight_lines[{pieces, weight_lb, package_type, description}], accessorials[], references[{type,value}], temp_controlled, hazmat, category` |
| `WASHOUT_CERT` | `carrier_hint, trailer_number, washed_at, facility, cert_number` |
| `LAST_LOAD_INFO` | `carrier_hint, trailer_number, last_commodity, last_commodity_category, last_delivery_city, last_delivery_state, available_date` |
| `CARRIER_OFFER` | `carrier_hint, equipment, empty_city, empty_state, available_date, rate_ask, trailer_number, preferred_direction` |
| `OTHER` | nothing extracted; always `needs_review` |

Additions to the spec: `name` on locations (resolved to a Meridian `facility_id`, which also fills a missing
city/state), `category` on quotes (Ryan's category list, used for `check_compat`), `last_commodity_category`,
and `trailer_number` / `preferred_direction` on offers. `last_delivery_city/state` means *where the trailer
is empty now*.

## Matching (`match.py`)

Shipments, carriers, customers, facilities and freight categories come from Ryan's synced cache
(`db.load_records`, `classify.get_classifications`); names are resolved live with Meridian's `/search` and
`/vendors/lookup`. Nothing here writes to Meridian. **The LLM extracts; Ryan's `check_compat` decides.**

- **Customer:** the sender's address matched to a customer contact (0.95), else `/search` on `customer_hint`,
  retrying with shorter hints (one hit 0.9, several 0.6 with `alternatives`).
- **Carrier:** MC / DOT / SCAC found in the text → `/vendors/lookup` (0.98), else name search.
- **QUOTE_REQUEST:** `arriving_trucks(origin)` lists every truck on an active outbound load into the request's
  origin (from the cache; the trailer's last load comes from Ryan's `network.trailer_history`). Each truck is run
  through Ryan's `check_compat(last_category, equipment, candidate, carrier, trailer_number=…, last_load_note=…)`
  with the email's freight, plus a requested-equipment check. Scoring: +30 if the truck is heading home to the destination city
  (+15 same state), +20 if it empties 0–2 days before pickup, −20 if it empties after pickup. The result is
  `status: "prospect"` with `prospect` and the `options`, or `"none_found"` with `reasons`. All blocked trucks
  are kept in `blocked`. The chosen truck is priced with Ryan's `pricing`: lane miles (Meridian's average on the
  lane, else his distance estimate), `backhaul_buy_lines`, the customer's `margin_for` and a local `estimate`.
- **Hours of Service:** each truck also goes through `backend/brain/hos.py`: its driver's clocks are
  estimated from its outbound load, then the backhaul (local deadhead, loading, loaded miles) is played
  forward with the FMCSA break / 11-hour / 14-hour / 10-hour-reset rules. A truck whose earliest legal
  pickup is after the pickup facility closes on the requested day is blocked (`Blocked: HOS: …`); one with
  less than 2 hours of slack loses 10 points; every option gets `est_pickup` and `est_delivery`.
- **Tiebreakers** (trucks with equal scores, in this order): same pickup facility (the truck delivers at the
  dock we pick up from) → load status (DELIVERED > AT_DELIVERY > IN_TRANSIT > PICKED_UP/AT_PICKUP > DISPATCHED >
  COVERED > BOOKED: how sure we are the truck shows up) → carrier compliance (GREEN > YELLOW > RED) → known
  trailer number → lowest outbound file number (booked earliest; mainly keeps results the same from run to run).
  When a tie decides the winner, its reasons say which tiebreaker did it.
- **Options kept:** the top 5 usable options, plus every other option tied with the 5th one's score
  (already in tiebreak order), so a tie never silently drops a truck.
- **Facility requirements:** each resolved stop gets `requirements` from its Meridian facility record
  (`compliance_flags` such as seal / driver ID / TWIC, `appointment_required`, `lumper_policy: REQUIRED`). They are
  added to the quote's `accessorials` (e.g. `"driver ID required at pickup (BBR-DC135)"`, skipped when the email
  already said it) and passed to the reply prompt, so a gate rule like DC135's seal doesn't depend on the model
  spotting it in the email.
- **Trailer history from email:** if a `LAST_LOAD_INFO` email named a trailer, that last load overrides
  Meridian's history for the trailer in later quote matching (the reason says so).
- **WASHOUT_CERT:** insert into `washouts`; `unblocked` lists network prospects for that trailer that are now
  ok, and options on earlier quote emails that FSMA had blocked for that trailer.
- **LAST_LOAD_INFO / CARRIER_OFFER:** Ryan's `find_backhauls` at the truck's position, each prospect re-checked for
  *this* truck (its last load, equipment and carrier). Offers get +30 when the destination matches
  `preferred_direction`. `LAST_LOAD_INFO` also returns `newly_blocked`: food quote options that had planned
  on this trailer.

## Actions and replies

Actions go into Ryan's approval queue with `propose(…, actor="email_pipeline")`; his executor does the
write on approval. `create_return_quote` payload for an email quote request: the fields his executor needs
(`customer_id, equipment_type, category, origin, destination, miles, outbound_file, target_margin_pct,
buy_lines`) plus the email's details, which his executor doesn't send to Meridian yet (see requests):
```json
{"source": "email", "source_email_id": "em_…", "prospect_id": "email-em_…", "customer_id": "NORTHSTAR",
 "mode": "TL", "equipment_type": "V", "category": "RETAIL_RETURNS", "miles": 925, "target_margin_pct": 10,
 "buy_lines": [{"charge_code": "FRT", "…": "…"}, {"charge_code": "FSC", "…": "…"}],
 "origin": {"city": "Dallas", "state": "TX", "zip": "75241", "name": "Big-Box DC135", "facility_id": "BBR-DC135"},
 "destination": {"city": "Chicago", "state": "IL", "name": "…", "facility_id": "NORTHSTAR-CHI"},
 "pickup_date": "2026-11-17", "freight_lines": [{"pieces": 18, "weight_lb": 14200, "package_type": "PALLET", "description": "…", "hazmat": false}],
 "references": [{"type": "PO", "value": "4471882"}], "accessorials": ["live load", "seal required", "…"],
 "outbound_file": "7300147", "carrier_id": "ACMECARR", "trailer_number": "53631"}
```
For carrier emails it is Ryan's prospect (`prospect_id, customer_id, equipment_type, category, origin,
destination, miles, outbound_file, target_margin_pct, buy_lines`) plus `carrier_id` and `trailer_number`.
The approver sees the estimated buy/sell in the summary. Confidence = min(classification confidence,
customer/carrier match confidence). Reasoning quotes the email.

`send_reply` payload: `{reply_id, email_id, quote_action_id}`. Drafts never contain a price. A quote reply
carries `{{sell_total}}`, and approving `send_reply` (`reply.execute_send_reply`) fills it from the approved
quote's `result.sell_total` and appends the quote number. If the quote isn't approved yet, it refuses: Ryan's
queue marks that action `failed` (it can't be approved twice), so the reply is first queued again under a new
`send_reply` action, and the error message names it. Approve the quote, then that new action.
When a person rejects a `send_reply`, the outbox shows the draft as `rejected` (synced on read).
Carrier replies never get the placeholder. As a last safety net, any `$` figure the model writes is
replaced in the draft.

## Agent tools and executors (`tools.py`)

Registered with Ryan's `@tool` and `@executor` when his backend imports `email_pipeline.tools`.
Executors: `send_reply` → `reply.execute_send_reply`, `confirm_carrier_rate` → `haggle.execute_rate_confirmation`.

| Tool | Tier | Does |
|---|---|---|
| `list_emails(status?)` | auto | inbox rows |
| `read_email(email_id)` | auto | full email + extraction + match + replies |
| `process_email(email_id)` | auto | re-runs the pipeline (writes only our tables + proposes actions) |
| `draft_reply(email_id, instructions?)` | auto | new outbox draft + `send_reply` action |
| `send_reply(reply_id)` | approve | returns the proposal; on approval the executor marks it `approved_sent` (simulated) |
| `haggle_with_carrier(email_id, target_pay_min?, target_pay_max?)` | auto | stretch: simulated negotiation → `confirm_carrier_rate` action |

## HTTP routes (`routes.py`, Blueprint `bp`, mounted by Ryan at `/api/email`)

Errors use Ryan's `{error, detail}` body (e.g. `404 not_found` for an unknown email).

| Method | Route | Returns | Contract |
|---|---|---|---|
| GET | `/inbox?status=` | `{items:[{email_id, from_addr, subject, received_at, kind, confidence, status, action_ids}]}` | `contracts/email_inbox.json` |
| GET | `/<email_id>` | full row incl. `body`, `extracted`, `matched`, `replies` | `contracts/email_detail.json` |
| POST | `/ingest` `{from, subject, body}` | `process_email` result (422 if a field is missing) | `contracts/email_process_result.json` |
| POST | `/simulate` `{file}` | loads `demo/sample_emails/<file>` and ingests it (404 if unknown) | `contracts/email_process_result.json` |
| GET | `/outbox?status=` | `{items:[{reply_id, email_id, to_addr, subject, body, status, action_id, created_at}]}` | `contracts/email_outbox.json` |
| GET | `/samples` | `{items:[file names]}` for the simulate buttons | — |
| POST | `/<email_id>/haggle` | stretch: `{target_pay_min, target_pay_max, target_basis, carrier_ask, deal, action_id, transcript}` | — |

## Tables (`store.py`, created by `init_email_tables()`)

- `emails`: `email_id PK, from_addr, to_addr, subject, body, attachments, received_at, kind, confidence REAL, rationale, extracted, matched, status, action_ids, error`.
  `status` ∈ `new, processing, processed, needs_review, failed`. (`to_addr`, `attachments` and `rationale` were added to the spec.)
- `outbox`: `reply_id PK, email_id, to_addr, subject, body, status, action_id, created_at`. `status` ∈ `draft, approved_sent, rejected`.
- `washouts`: `id PK, carrier_id, trailer_number TEXT, washed_at, facility, cert_number, source_email_id`. Ryan's FSMA rule reads it.

## Integration with Ryan's backend

The pipeline uses Ryan's modules directly: `db` (connection, schema, cache, audit log), `meridian` (reads),
`agent.registry.tool`, `agent.actions` (`propose`, `executor`, `approve`/`reject` in the CLI),
`brain.compat.check_compat`, `brain.network` (`find_backhauls`, `trailer_history`, `distance_miles`),
`brain.pricing` and `brain.classify`. `email_pipeline/__init__.py` imports `backend` first, because the backend
imports `email_pipeline.routes` and `.tools` while it starts; that order avoids a circular import when the
pipeline is run on its own. `store.init_email_tables()` also runs Ryan's `db.init_db()`.
What I need from Ryan is in `docs/requests.md`.

## Stretch

- **Carrier Haggle** (`haggle.py`): the target range comes from lane history (median buy $/mi on the lane,
  or its head-haul direction) × miles, at 65–85% for a backhaul. Our side is deterministic: open at the minimum,
  meet in the middle, never above the maximum. The carrier is an LLM persona whose walk-away (92% of its ask) is
  also enforced in code. Lane history comes from Ryan's shipment cache. A deal drafts a rate confirmation to
  the carrier in the outbox and proposes `confirm_carrier_rate`; approving it marks the confirmation sent
  (simulated). It does not cover the load in Meridian: `/shipments/{id}/cover` needs the backhaul quote booked
  first. On sample 05: ask $795.50, target $683–$893, deals between about $730 and $750.
- **Real inbox** (`inbox_poll.py`): IMAP polling of UNSEEN mail into `process_email`, **off unless
  `EMAIL_POLL_ENABLED=1`** (`IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `EMAIL_POLL_SECONDS`).
  Not tested against a live mailbox; `.eml` parsing is tested.

## Prompts

Each prompt lives in code next to its schema, with a one-line comment on what it is for:
`classify.CLASSIFY_PROMPT`, `extract.QUOTE_PROMPT / WASHOUT_PROMPT / LAST_LOAD_PROMPT / OFFER_PROMPT`,
`reply.REPLY_PROMPT`, `haggle.CARRIER_PERSONA`.

## Known issues

- **LLM provider:** the pipeline uses OpenAI structured output (`gpt-4o-mini`, `OPENAI_MODEL_FAST`) through
  `llm.structured()`, not `anthropic` as the original plan said. Swapping providers only touches `llm.py`.
- Matching reads Ryan's cache, so it is only as fresh as the last `python scripts/sync_data.py`.
- Ryan's `create_return_quote` executor doesn't send `pickup_date`, `freight_lines` or references to Meridian,
  so a quote from an email has the lane and price but not the email's freight details (see requests).
- For carrier emails the quote's `rate_ref` points at the outbound file Ryan's finder paired with the freight,
  not at the emailing carrier's truck (which isn't on a Meridian file).
- Ryan's test `test_every_tool_is_registered_with_a_valid_schema` expects only his seven tools, so it fails now
  that the six email tools register (see requests). The other 68 tests pass.
- Last-load history from email lives only in our `emails` table; Ryan's own network and compat won't see it
  unless he reads `store.emailed_last_load()`.
- Every `simulate` creates a new email row (no de-duplication), so the demo button can be pressed repeatedly.
- The reply prompt is told the facility requirements, but the model doesn't always mention them; the quote
  payload carries them either way.
- The model's confidence on `06_vague` lands at 0.7–0.8; the missing-essentials check is what sends it to review.
- A carrier's rate ask repeated in a reply is replaced with "(pricing to follow)" by the no-dollars guard.
