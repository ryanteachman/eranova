# Status

## Ryan (backend)

**Done**
- All backend routes are live and match `contracts/`. The mocks are now real responses.
- Sync, classification, compatibility rules, network, pricing, approval queue, agent loop.
- Tested end to end: fill → approve created a real quote in Meridian (later declined with
  `scripts/reset_demo.py`); the agent finds Dallas, picks the top prospect and queues it.

- **2026-11-13 Carrier scoring:** `brain/carrier_score.py` scores 16 carriers from actual
  performance (on-time by late cause, late pickups, damage, bounces, TONUs, pay vs target)
  with shrinkage and plain-English reasons. Shipment events are now synced. New routes
  `GET /api/carriers`, `GET /api/carriers/<vendor_id>`, `POST /api/carriers/rank`, agent tool
  `rank_carriers` ("who should haul 7300174?" works from chat), `scripts/score_carriers.py`.
  Rules, weights and data notes in `docs/backend.md` › *Carrier scoring*.

- **2026-11-13 Decision modes:** `approval` (default, as before), `auto` (the AI executes
  low-risk writes, humans get the rest) and `invisible` (the AI executes everything, within
  daily caps). `GET/PUT /api/mode`; every action now records `mode`, `decided_by` and `risk`.
  Rules in `docs/backend.md` › *Decision modes*.

**Doing**
- Nothing blocked. Next: tune scoring and the demo script with the team.

**Decision modes UI** (@Ali)
- A mode switch: `GET /api/mode`, `PUT /api/mode {mode}` (`contracts/mode.json`), plus today's AI
  usage against the caps.
- `POST /api/fill` can now return `status: "done"` with the quote in `result` (auto/invisible).
  Actions carry `decided_by` (`human`/`ai`) and `risk` (`level`, `reasons`, `blockers`, `cap`):
  good for an "AI did this" badge and a "why is this waiting?" line on held cards.
  Example AI-executed action: `contracts/action_auto_executed.json`.

**Blocked**
- Nothing.

**New UI data** (@Ali)
- Carrier scorecards: `contracts/carriers.json`, `carrier_detail.json`, `carriers_rank.json`;
  shapes in `contracts/README.md` › *Scorecard*. Good for a carrier leaderboard ("profile says
  94% on time; actual loads say 89%") and a "who should haul this?" panel on a shipment.

**For Haggle** (@Asher)
- `rank_carriers` (auto tier) and `POST /api/carriers/rank` rank carriers for a lane or a
  shipment. Haggle could use `base_score` to decide how far to stretch on a carrier's ask,
  and the matcher could use it ahead of compliance light as a tiebreaker. Details in
  `docs/requests.md`.

**Contract changes** (@Ali)
- Prospects have three extra fields: `carrier_id`, `miles_saved`, `target_margin_pct`.
- `prospect_id` format is `state:city:customer:category:pickup city:destination city:outbound
  file`. Treat it as opaque.
- An approve can return `status: "failed"` with `result: {error, status}`. A second Approve on
  the same action returns `409`; an action can briefly show `status: "running"`.
- Filling the same prospect twice returns the same pending action.
- New errors: `502 openai_error` (chat) and `503 meridian_unreachable`.
- `arcs[].equipment` keys are any equipment code (`V`, `R`, `F`, `SB`, `SV`, `HS`).

## Asher (email pipeline)

**2026-11-13**
- **Done:** `email_pipeline/` specs 1–8 working end to end on stubs with live Meridian reads (parse, store, classify, extract, match, quote + reply proposals, tools, routes); 7 sample emails; contracts; `docs/email.md`. Stretch done too: carrier haggle → `confirm_carrier_rate`, and an IMAP poller behind `EMAIL_POLL_ENABLED`.
- **Done (integration):** `email_pipeline` runs on Ryan's real backend: `routes.bp`, `@tool`/`@executor` registration, his approval queue, `check_compat`, pricing and shipment cache. All 7 samples run end to end; approve quote → real Meridian quote → reply sent with the price (tested once, quote declined after).
- **Doing:** nothing.
- **Blocked:** nothing. Two small asks for Ryan in `docs/requests.md` (his tool-list test, freight lines on quotes).
- @Ali: contracts regenerated from the real backend (same shapes; `matched` now has prices and facility `requirements`; errors use `{error, detail}`; `GET /api/email/health` was removed). They are in `contracts/email_inbox.json`, `email_detail.json`, `email_outbox.json`, `email_process_result.json`. Extra routes: `GET /api/email/samples` (file names for the simulate buttons) and `POST /api/email/<id>/haggle`. Detail rows include `replies`.

## Ali (frontend)
