# Backend

Flask app in `backend/`. Owner: Ryan. The HTTP contract is in `contracts/README.md`.

## Setup

```bash
pip install -r requirements.txt
python scripts/sync_data.py                     # first time: pull Meridian + classify
flask --app backend run --debug --port 5000
python scripts/reset_demo.py                    # before a demo: decline Return Trip quotes
```

Rerun `sync_data.py` whenever Meridian data changes (for example after an organizer reset).
The network and prospects are computed from the SQLite cache; every write goes to Meridian.

Tests: `python -m pytest backend/tests`. They run offline: every test gets a temporary SQLite
database, and Meridian and OpenAI are replaced with fakes (`backend/tests/conftest.py`), so
they never write to the sandbox.

## Environment variables

Read from `.env` (see `.env.example`). The `TMS_*` values fall back to `secret.txt`. That file is
a labeled text file, not `KEY=VALUE`: the backend reads the first word after `Base URL:`,
`API key:` and `URL:` (an explanatory note can follow the value on the same line).

| Variable | Default | Used for |
|---|---|---|
| `TMS_API_BASE` | from `secret.txt` | Meridian base URL, ends in `/v1` |
| `TMS_API_KEY` | from `secret.txt` | Meridian `x-api-key` header |
| `TMS_UI_URL` | from `secret.txt` | Meridian web app, for `meridian_url` links |
| `OPENAI_API_KEY` | — | Classification and the agent |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI endpoint |
| `OPENAI_MODEL` | `gpt-4o` | Model for classification and the agent |
| `DB_PATH` | `return_trip.db` in the repo root | SQLite file |

## Modules

- `meridian.py`: `get`, `post`, `put`, `get_all` (follows `next_cursor` until `null`, even
  past empty pages). Errors raise `MeridianError(status, error, detail)` with Meridian's
  `detail` sentence unchanged; timeouts and connection errors become
  `MeridianError(503, "meridian_unreachable", ...)`.
- `db.py`: `get_conn()`, `init_db()` (also adds columns missing from older databases),
  `replace_records()`, `load_records()`, `audit()`.
- `errors.py`: `BadRequest` (400), `NotFound` (404), `Conflict` (409); the app turns them into
  `{error, detail}`.
- `brain/sync.py`: `sync_all()` pulls shipments, vendors, facilities and customers, then
  *replaces* the cache (a Meridian reset can delete records and change ids) and drops
  classifications for shipments that no longer exist. Everything is fetched before anything
  is written, so a failed pull leaves the old cache intact.
- `brain/classify.py`: `classify_all()` labels each shipment with OpenAI structured output
  (Pydantic model, temperature 0, 8 threads), cached in `classifications` with an
  `input_hash` of the text sent to the model. A shipment is reclassified when it is new or its
  freight changed, so a reused id never keeps a stale label. A Meridian `hazmat: true` line
  forces `HAZMAT`. The prompt defines every category and says all food, including dry and
  shelf-stable groceries, is `FOOD`, because the FSMA rule depends on it. A shipment that has
  not been classified yet is treated as `HAZMAT` if Meridian flags it, else `GENERAL`.
- `brain/compat.py`: `check_compat(...)`, the rules below.
- `brain/network.py`: `lane_flows()`, `one_way_cities()`, `trailer_history()`,
  `network_summary()`, `find_backhauls(city, state)`, `score_prospect()`, `city_detail()`,
  `find_prospect(prospect_id)`.
- `brain/pricing.py`: `backhaul_buy_lines()`, `estimate()` (local), `preview()` (Meridian).
- `agent/registry.py`, `agent/tools.py`, `agent/loop.py`, `agent/actions.py`: see *Agent*.

## Compatibility rules (as implemented)

The LLM classifies; these rules decide. Every rule adds a human-readable reason; any
`Blocked:` reason makes `ok` false.

1. **Equipment:** `R` hauls temp-controlled or dry. Dry equipment (`V`, `SB`, `SV`) hauls dry
   freight only. Flatbeds (`F`, `SD`, `HS`) haul only `STEEL`, `WOOD`, `MACHINERY`, `SCRAP`.
2. **FSMA:** if the trailer's last load was `CHEMICAL`, `HAZMAT` or `WASTE` and the candidate
   is `FOOD` or `BEVERAGE`, block unless `washouts` has a row for that `trailer_number`. The
   reason names the UN number when the last load had one: `Blocked: trailer last hauled
   HAZMAT (UN1760); FSMA requires a washout before food.`
3. **Hazmat:** a hazmat candidate needs `hazmat_certified: true` on the carrier.
4. **Size:** the candidate's average weight and pallet positions must fit the equipment.
5. **Carrier:** `status` `ACTIVE` and a `CARGO` policy expiring today or later.

## Backhaul finder

`find_backhauls(city, state)`:

1. **Trucks:** active TL and expedite shipments delivering to the city that have a carrier.
   Each truck's last category comes from `trailer_history()` (last shipment per
   `(carrier_id, trailer_number)`), or from the inbound load itself when there is no trailer
   number. Its home is the inbound load's origin.
2. **Candidate freight** picked up within `NEAR_MILES` of the city:
   - customers that already ship from a nearby city (their usual category, weight, equipment);
   - reverse logistics at nearby consignees, going back to the shipper's origin: `STEEL` →
     `SCRAP`, `WOOD` → `WOOD`, `PACKAGING` → `PACKAGING` (baled cartons), and `GENERAL`
     delivered to a DC, store or warehouse → `RETAIL_RETURNS`;
   - prospect customers with no loads yet whose main address is nearby (cold leads, profile
     assumed `GENERAL`, 20,000 lb, 12 pallets).
3. **Pairing:** a truck and candidate pair only if it saves miles: `miles_saved = trip home −
   deadhead to pickup − miles from the drop back home` must be positive. Pairings with an
   unknown distance (a city missing from `CITY_COORDS` and from known lanes) are skipped.
4. **Result:** one prospect per candidate: the best compatible truck, else the blocked pairing
   that saves the most miles (`ok: false`, `score: 0`).

`score_prospect()` (compat is a hard gate): 30 base + 25 warm lead (an `ACTIVE` customer
with loads on this pattern) + up to 30 for miles saved (full at `FULL_SCORE_MILES`) + 15 when
the freight usually moves on the truck's equipment. Capped at 100.

Miles: average shipment miles for known lanes (either direction), otherwise great-circle
distance × `ROAD_FACTOR`. Meridian facilities have no coordinates, so `CITY_COORDS` maps every
city in the data.

## Pricing

- `buy_frt = max(miles × BACKHAUL_RATE_PER_MILE, avg outbound buy FRT on the truck's lane ×
  OUTBOUND_SHARE)`.
- `buy_fsc = miles × tl_per_mile` from `GET /fsc` (cached per process).
- Margin: the customer's `margin_floor_pct`, else `DEFAULT_MARGIN_PCT`. FSC passes through at
  cost, so GP lands under the margin (every sandbox customer has a 10% floor, so GP is ~7%).
- `/api/city` estimates locally with the same formula as Meridian; the proposal calls
  `POST /quotes/price-preview`. Tested: both matched the created quote to the cent.

## Agent

- Tools register with `@tool(name, description, schema, tier)` in `agent/registry.py`.
  - `auto` tools run immediately.
  - `approve` tools only *prepare* a proposal and return `{title, summary, payload, confidence,
    reasoning}`. The loop queues it with `actions.propose(kind=name, ...)` and tells the model
    `Queued for human approval as <action_id>`.
  - The write happens in the executor registered with `@actions.executor(name)`, run by
    `actions.approve(action_id)`. Approval first moves the action from `pending` to `running`
    in one SQL update, so a double-clicked Approve runs the executor once (the second call gets
    `409`). Any executor error marks the action `failed`; a quote that was created but not
    priced is named in the error (`Quote 7300xxx was created but not finished: ...`) and stays
    a DRAFT in Meridian.
  - `propose()` returns the existing pending action when one with the same kind and payload is
    already queued, so repeated Fill clicks or agent calls don't create duplicates.
- Registered tools:

  | Tool | Tier | Does |
  |---|---|---|
  | `network_overview` | auto | Totals and the most one-way cities |
  | `find_backhauls` | auto | Ranked prospects for a city |
  | `create_return_quote` | approve | Proposes a quote; executor: `POST /quotes` → `POST /quotes/{id}/price` (`rate_ref: return-trip:<outbound file>`) → `PUT /quotes/{id}` with a note |
  | `get_shipment` | auto | `GET /shipments/{id}` |
  | `search` | auto | `GET /search` |
  | `price_preview` | auto | `POST /quotes/price-preview` |
  | `add_shipment_note` | auto | `POST /shipments/{id}/notes` |

- `run_agent(trigger, message, context=None)`: OpenAI tool-calling loop, temperature 0, at most
  `MAX_TURNS` model calls. Meridian and API errors go back to the model as the tool result so
  it can correct itself. Every message, tool call and reply goes to `audit_log`.
- Asher's code plugs in on import when present: `email_pipeline.tools` (tools and executors,
  e.g. `send_reply`) and `email_pipeline.routes.bp` (a Blueprint mounted at `/api/email`).

## Constants

| Constant | Value | Where |
|---|---|---|
| Empty cost per mile | $2.00 | `network.EMPTY_COST_PER_MILE` |
| Pickup radius | 100 mi | `network.NEAR_MILES` |
| Road factor | 1.2 | `network.ROAD_FACTOR` |
| Miles saved for full score | 1,000 | `network.FULL_SCORE_MILES` |
| Backhaul rate per mile | $1.20 | `pricing.BACKHAUL_RATE_PER_MILE` |
| Share of outbound buy | 0.60 | `pricing.OUTBOUND_SHARE` |
| Default margin | 18% | `pricing.DEFAULT_MARGIN_PCT` |
| Size limits | V/R 45,000 lb / 26 pallets, SB 10,000 / 12, SV 3,000 / 4 | `compat.SIZE_LIMITS` |
| Agent turns | 8 | `loop.MAX_TURNS` |
| Meridian page size / timeout | 200 / 30 s | `meridian.PAGE_LIMIT`, `meridian.TIMEOUT_SECONDS` |
| Classification threads | 8 | `classify.WORKERS` |

## Known issues

- **FSMA never fires on the current data.** The only hazmat trailers run Houston → Dallas,
  and no food ships near Dallas. The rule is tested with a synthetic case and gives the
  expected `Blocked: … (UN1760) …` reason.
- **No carrier is hazmat certified**, so any hazmat backhaul is blocked.
- **Reverse-logistics freight is inferred**, not booked demand: the weights reuse the inbound
  averages, and cold leads use an assumed profile.
- **Classification is not perfectly consistent:** 1 of 33 "Machined steel components"
  shipments came back `GENERAL`.
- `washouts` is read by `trailer_number` and is assumed to have that column (see
  `docs/requests.md`).
