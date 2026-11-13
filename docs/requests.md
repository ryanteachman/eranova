# Cross-owner requests

One line per ask: date/time, from → to, what, why.

- **2026-11-13** Asher → Ryan: **Bug in `backend/__init__.py`.** `agent` there is `backend.routes.agent`, but importing any `backend.agent.*` submodule afterwards (my `deps.py`, or your own routes importing the agent loop) rebinds `backend.agent` to the subpackage, and `create_app()` fails with `module 'backend.agent' has no attribute 'bp'`. Fix: `from .routes import agent as agent_routes` (or import each `bp` by name).
- **2026-11-13** Asher → Ryan: Mount the email routes. In `backend/routes/email.py`: `from email_pipeline.routes import email_bp as bp` (it already has `url_prefix="/api/email"`).
- **2026-11-13** Asher → Ryan: In `backend/agent/tools.py`, add `import email_pipeline.tools` so my six tools register (`send_reply` is tier `approve`; the rest are `auto`).
- **2026-11-13** Asher → Ryan: Executors in `actions.py`: `send_reply` → `email_pipeline.reply.execute_send_reply(payload)`; rejecting a `send_reply` → `email_pipeline.reply.reject_reply(payload["reply_id"])`; stretch `cover_load` → `POST /shipments/{id}/cover` with `{carrier_id, amount}`.
- **2026-11-13** Asher → Ryan: `create_return_quote` from email arrives with `source: "email"` and the full lane + freight instead of a known `prospect_id` (shape in `docs/email.md` › Actions). Please accept it: `POST /quotes` with `customer_id, mode, equipment_type, origin, destination, pickup_date, freight_lines`, then `/price` with `rate_ref`. For carrier emails it's `{prospect_id, carrier_id, trailer_number}`. Your `Action.result.sell_total` fills the reply's `{{sell_total}}`.
- **2026-11-13** Asher → Ryan: `washouts` columns as built: `id, carrier_id, trailer_number (TEXT), washed_at, facility, cert_number, source_email_id`. Your FSMA rule can match on `trailer_number` (+ `carrier_id` when not null).
- **2026-11-13** Asher → Ryan: Please put `carrier_id, trailer_number, trailer_last_category, available_date` on every `find_backhauls` prospect (next to `outbound_file, origin{city,state}, destination{city,state}, equipment, category, miles, score, ok, reasons`); quote matching uses them to judge the arriving truck.
- **2026-11-13** Asher → Ryan: `check_compat` candidate keys I send: `category, temp_controlled, hazmat, weight_lb, pallets, trailer_number, carrier_id`. The trailer for the washout lookup is in `candidate["trailer_number"]`.
- **2026-11-13** Asher → Ryan: Trailer history from carrier emails: `email_pipeline.store.emailed_last_load(trailer_number)` → `{email_id, category, commodity}` or `None`. Worth reading in `network.py`, since it knows loads Meridian doesn't.
- **2026-11-13** Asher → Ryan: `.env.example` should list `OPENAI_API_KEY=` and `OPENAI_MODEL_FAST=gpt-4o-mini` (the email pipeline's LLM).
