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

**Updated 2026-11-13**

**Done**
- v3 map-first UI: Broker (ready loops, empty trips to fill, my loops with money in/out/margin/saved),
  Carrier (fleet + driver phone), Manufacturer (date-shift offers), weekly Reports, inbox actions.
- 3D map (MapLibre + deck.gl): real road routes (OSRM), status-colored direction arcs, overview of all loops.
- All loop, lane, report and learning numbers come from real Meridian data
  (`frontend/tools/plan_loops.py`, `frontend/tools/learn.py`). Earlier made-up loops are gone.

**Doing**
- Switching `api.js` from mocks to Ryan's live routes (contract field differences listed in `docs/requests.md`).

**Blocked**
- Tours, return lanes, reports and learned routes are frontend-only until ported to the backend.
- Inbox and agent chat show example data until Asher's `email_pipeline` lands.

