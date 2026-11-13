# Cross-owner requests

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
