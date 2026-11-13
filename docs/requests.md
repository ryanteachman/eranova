# Cross-owner requests

One line per ask: date/time, from → to, what, why.

- **Ryan → Asher:** the backend loads your code on import, so please expose:
  - `email_pipeline/tools.py`: register tools with `from backend.agent.registry import tool`
    and executors (for example `send_reply`) with `from backend.agent.actions import executor`.
    An `approve`-tier tool returns `{title, summary, payload, confidence, reasoning}`; the
    executor receives that `payload` and returns a result dict.
  - `email_pipeline/routes.py`: a Flask `Blueprint` named `bp` with no `url_prefix`; it is
    mounted at `/api/email`.
  - `washouts` table: the FSMA rule runs `SELECT 1 FROM washouts WHERE trailer_number = ?`.
    Please include a `trailer_number` column, or tell me the real column name.
  - To run the agent from an email: `from backend.agent.loop import run_agent` →
    `run_agent("email", message, context={...})`.

- **2026-11-13** Asher → Ryan: answer to the request above, all done in `email_pipeline/`: tools and executors
  (`send_reply`, `confirm_carrier_rate`) register with your `@tool` / `@executor`; the `send_reply` tool is
  `approve`-tier and returns `{title, summary, payload, confidence, reasoning}`; `routes.bp` has no prefix;
  `washouts` has `trailer_number` (TEXT).
- **2026-11-13** Asher → Ryan: ~~**Bug in `backend/__init__.py`.**~~ Done on main (routes imported as `*_routes`).
- **2026-11-13** Asher → Ryan: ~~Mount the email routes.~~ Done on main: `backend/routes/email.py` mounts `email_pipeline.routes.bp`.
- **2026-11-13** Asher → Ryan: ~~In `backend/agent/tools.py`, add `import email_pipeline.tools`.~~ Done on main.
- **2026-11-13** Asher → Ryan: ~~Executors for `send_reply` / `cover_load`.~~ Registered from `email_pipeline/tools.py` instead. The haggle now proposes `confirm_carrier_rate` (marks a rate confirmation sent; no Meridian write), since covering needs a booked shipment.
- **2026-11-13** Asher → Ryan: ~~Prospect fields and `check_compat` keys.~~ No longer needed: email matching builds its truck list from your cache (`db.load_records`, `classify.get_classifications`, `network.trailer_history`) and calls `check_compat` with your signature.
- **2026-11-13** Asher → Ryan: ~~`backend/tests/test_agent.py::test_every_tool_is_registered_with_a_valid_schema` expects exactly your seven tools.~~ Done: the test now checks that the seven backend tools are a subset of what's registered.
- **2026-11-13** Asher → Ryan: ~~Send `pickup_date` and `freight_lines` to `POST /quotes`.~~ Done with Ryan's OK (executor sends `pickup_date`, `delivery_date_target` and `freight_lines` when present). Original ask: `create_return_quote` payloads from email also carry `pickup_date`, `freight_lines` (pieces, weight_lb, package_type, description, hazmat), `references` and `accessorials`. Could your executor send `pickup_date` and `freight_lines` to `POST /quotes` when present, so the quote has the email's freight? Shape in `docs/email.md` › Actions.
- **2026-11-13** Asher → Ryan: Rejecting a `send_reply` action doesn't tell the email pipeline; I sync it on read (outbox shows `rejected`), so nothing is needed unless you'd rather call `email_pipeline.reply.reject_reply(payload["reply_id"])` from `reject`.
- **2026-11-13** Asher → Ryan: `washouts` columns as built: `id, carrier_id, trailer_number (TEXT), washed_at, facility, cert_number, source_email_id`. Your FSMA rule matches on `trailer_number`, which works.
- **2026-11-13** Asher → Ryan: Trailer history from carrier emails: `email_pipeline.store.emailed_last_load(trailer_number)` → `{email_id, category, commodity}` or `None`. Worth reading in `network.py`, since it knows loads Meridian doesn't.
- **2026-11-13** Ryan → Asher: carrier scoring is in (`backend.brain.carrier_score`). Three things:
  - ~~One equipment table.~~ Done by Ryan: `match.py` now imports `EQUIPMENT_FITS` from
    `backend.brain.compat`; the local copy is gone.
  - ~~`match._frt_buy` counts `CANCELLED` FRT lines.~~ Done by Ryan: it now skips them, so a bounced carrier's
    cancelled pay (7300154) no longer inflates the outbound average used to price email backhauls.
  - Optional: `carrier_score.all_scorecards()` / `rank_carriers()` give each carrier a `base_score` (0–100,
    real on-time, damage, bounces, cost). It could replace compliance light as the matcher's tiebreaker, or let
    Haggle stretch further for a reliable carrier.
- **2026-11-13** Ryan → Asher (FYI, no action needed): decision modes are in (`backend/agent/autonomy.py`).
  `propose()` may now execute an action immediately as the AI (auto/invisible mode) and return it `done`.
  Your code keeps working: `_queue` still gets an `action_id`, and a `send_reply` waits until its quote is
  `done` (a blocker in every mode), then goes out automatically once the quote is approved. Re-queued replies
  are never auto-executed, so there's no loop. The risk rules for `send_reply` and `confirm_carrier_rate`
  live in `autonomy.py`; move them next to your executors with `@risk_check` if you prefer.
  One edit in your folder: `haggle.py` now adds `target_pay_min` / `target_pay_max` to the
  `confirm_carrier_rate` payload, so auto mode can check the deal is at or under the target max.
- **2026-11-13** Asher → Ryan: `.env.example` could list `OPENAI_MODEL_FAST=gpt-4o-mini` (the email pipeline's extraction model; it defaults to that when unset).
- **Ali → Ryan (frontend, 2026-11-13):** the v3 UI reads these routes. Today they are served by
  frontend mocks generated from real Meridian data by `frontend/tools/plan_loops.py` and
  `frontend/tools/learn.py`; the logic is in those two scripts, ready to port into `backend/brain/`.
  - [ ] `GET /api/tours`: loops built only from real loads (a truck already on a load chains into
    loads that still need a carrier). Shape: `frontend/mocks/tours.json`.
  - [ ] approve on a `book_tour` action covers each `needs_carrier` leg with the loop's carrier.
    Shape: `frontend/mocks/tour_actions.json`.
  - [ ] `GET /api/return-lanes`: one-way lanes with trucks home empty, empty miles, rate-engine
    market rate and real Meridian accounts in the city as leads (`return_lanes.json`).
  - [ ] `GET /api/network/backtest`: the whole-history replay, one by one vs loops
    (`network_backtest.json`).
  - [ ] `GET /api/carrier-weeks` and `POST /api/carrier-weeks/<tour_id>/respond`
    (`carrier_weeks.json`).
  - [ ] `GET /api/offers` and `POST /api/offers/<offer_id>/respond`: real date-shift offers
    (`shipper_offers.json`).
  - [ ] `GET /api/reports/weekly` and `GET /api/learned`: weekly reports and learned rules
    (`reports.json`, `learned.json`).
  - [ ] Only constant that is not Meridian data: `EMPTY_COST_PER_MILE = 2.27` (ATRI industry average).
- **2026-11-13** Asher → Ryan: ~~Wire HOS into `find_backhauls`.~~ Done with Ryan's OK: `find_backhauls` runs `hos.earliest_backhaul` per pairing; prospects gained `pickup_date`, `delivery_date_target`, `est_pickup`, `est_delivery` (contract updated). Original note: New module `backend/brain/hos.py` (FMCSA Hours of Service simulator, with `backend/tests/test_hos.py`), written by Asher in `backend/` since both the backhaul finder and email matching need it. Email matching uses it now. Worth adding to `find_backhauls` / `check_compat` so the Fill flow also blocks trucks that can't legally make a pickup; documented in `docs/backend.md` › *Hours of Service*.
