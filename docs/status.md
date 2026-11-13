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

## Asher (email)

## Ali (frontend)
