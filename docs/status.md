# Status

## Ryan (backend)

**Done**
- All backend routes are live and match `contracts/`. The mocks are now real responses.
- Sync, classification, compatibility rules, network, pricing, approval queue, agent loop.
- Tested end to end: fill → approve created a real quote in Meridian (later declined with
  `scripts/reset_demo.py`); the agent finds Dallas, picks the top prospect and queues it.

**Doing**
- Nothing blocked. Next: tune scoring and the demo script with the team.

**Blocked**
- Waiting on Asher's `email_pipeline` interface (see `docs/requests.md`).

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
