# Return Trip API contract

The Flask backend serves these routes at `http://localhost:5000`. Every route is live. Each
`.json` file in this folder is a real response captured from the backend against the Meridian
sandbox (the web app URL is replaced with `<TMS_UI_URL>`).

If a route or field changes, the mock JSON and this table are updated together, and the change
is noted in `docs/status.md`.

## Routes

| Method | Route | Body | Returns | Mock |
|---|---|---|---|---|
| GET | `/api/network` | — | Network totals, cities and lane arcs | `network.json` |
| GET | `/api/city/<state>/<city>` | — | One city's inbound/outbound counts and ranked backhaul prospects | `city.json` |
| POST | `/api/fill` | `{prospect_id}` | `{action_id, status, mode, decided_by, risk, result}`. In approval mode `status` is `pending`; in auto/invisible mode it can come back `done` (or `failed`) with the quote in `result` | `fill.json` |
| GET | `/api/mode` | — | `{mode, modes, risk_rules, daily_caps, ai_today: {actions, sell}}` | `mode.json` |
| PUT | `/api/mode` | `{mode: "approval" \| "auto" \| "invisible"}` | Same as `GET /api/mode` | `mode.json` |
| GET | `/api/actions?status=pending` | — | `{items: [Action]}` | `actions.json` |
| POST | `/api/actions/<id>/approve` | — | `Action` with `status: "done"` and `result` holding the new Meridian quote | `action_approved.json` |
| POST | `/api/actions/<id>/reject` | `{reason}` | `Action` with `status: "rejected"` | `action_rejected.json` |
| POST | `/api/agent/chat` | `{message}` | `{reply, tool_calls, actions_created}` | `agent_chat.json` |
| GET | `/api/audit?limit=50` | — | `{items: [{at, actor, event, detail}]}`, newest first | `audit.json` |
| GET | `/api/carriers` | — | `{items: [Scorecard]}`, best `base_score` first | `carriers.json` (first 3) |
| GET | `/api/carriers/<vendor_id>` | — | `Scorecard` plus `per_load` and `bounced_loads` | `carrier_detail.json` |
| POST | `/api/carriers/rank` | `{shipment_id}` or `{origin, destination, equipment_type, mode, hazmat}` | `{eligible: [Scorecard + fit + score], excluded: [{vendor_id, legal_name, reason}]}`, top 5 eligible | `carriers_rank.json` |
| * | `/api/email/...` | — | Owned by Asher; see `email_pipeline/` | — |

Example: `GET /api/city/TX/Dallas`.

## Shapes

**Network** (`/api/network`)

- `totals`: `empty_miles` (truckload and expedite loads × miles on one-way lanes; LTL is
  excluded), `empty_cost_usd` (`empty_miles × $2.00`), `one_way_lanes`, `loads` (active
  shipments; cancelled and TONU are excluded).
- `cities[]`: `{city, state, lat, lng, inbound, outbound}`.
- `arcs[]`: one per lane, `{from, to, loads, miles, equipment}`. `from`/`to` are
  `{city, state, lat, lng}`.
  `equipment` maps Meridian equipment codes to load counts. The keys are whatever codes
  appear (`V`, `R`, `F`, `SB`, `SV`, …), not a fixed set.

**Prospect** (items of `prospects[]` in `/api/city/...`), sorted by `score`, highest first

| Field | Type | Notes |
|---|---|---|
| `prospect_id` | string | Pass this to `POST /api/fill`. Treat it as opaque (it is `state:city:customer:category:pickup city:destination city:outbound file`). |
| `customer_id`, `customer_name` | string | Meridian customer. |
| `origin`, `destination` | `{city, state}` | The return leg. |
| `equipment` | string | Equipment code of the truck going home. |
| `category` | string | `FOOD`, `BEVERAGE`, `CHEMICAL`, `HAZMAT`, `WASTE`, `WOOD`, `STEEL`, `SCRAP`, `PACKAGING`, `RETAIL_RETURNS`, `MACHINERY`, `GENERAL`. |
| `score` | integer | 0–100. `0` when `ok` is false. |
| `est_buy`, `est_sell` | number | USD. |
| `gp_pct` | number | Margin on sell, one decimal. |
| `miles` | number | Return-leg miles. |
| `outbound_file` | string | Meridian file number of the load that brought the truck in. |
| `ok` | boolean | `false` means a compatibility rule blocked it. Show it, but don't offer Fill. |
| `reasons` | string[] | Human-readable reasons. When `ok` is false, the first one says what blocked it. The last one says where the freight comes from. |
| `carrier_id` | string | Carrier of the truck that would haul it. |
| `miles_saved` | number | Empty miles avoided on the trip home. |
| `target_margin_pct` | number | Margin used for `est_sell` (the customer's margin floor). |
| `pickup_date`, `delivery_date_target` | string `YYYY-MM-DD` or `null` | Hours of Service estimate: earliest legal pickup day and the delivery day. `null` when HOS blocked it. |
| `est_pickup`, `est_delivery` | string or `null` | The same estimate for display, in the pickup facility's local time, e.g. `"11/17 12:30 CST"`. |

`/api/city` returns one prospect per candidate load: the best compatible truck, or, when no
truck is compatible, a blocked prospect (`ok: false`, `score: 0`) explaining why.

**Action** (`/api/actions`, approve, reject)

| Field | Type | Notes |
|---|---|---|
| `action_id` | string | |
| `kind` | string | `create_return_quote`, or Asher's `send_reply`. |
| `title`, `summary` | string | One-line title and a short description for the approval card. |
| `payload` | object | What will be sent to Meridian. Its shape depends on `kind`. |
| `tier` | string | `approve`. |
| `confidence` | number | 0–1. |
| `reasoning` | string | Why the agent proposed it. |
| `status` | string | `pending`, `running` (being approved right now), `done`, `rejected`, `failed`. |
| `result` | object or null | `null` while pending. On `done`: `{quote_id, summary, sell_total, meridian_url}`. On `rejected`: `{reason}`. On `failed`: `{error, status}`, where `error` is Meridian's sentence. |
| `created_at` | string | UTC ISO-8601. |
| `mode` | string | Decision mode when it was proposed: `approval`, `auto`, `invisible`. |
| `decided_by` | string or null | `human` or `ai` once approved/rejected; `null` while pending. |
| `risk` | object | `{level: "low" \| "high", reasons: [str], blockers: [str], cap: str \| null}`. `reasons`: why auto mode won't run it alone. `blockers`: it waits on another action (no mode runs it). `cap`: the AI's daily limit was hit. Assessed in every mode, so the UI can show what auto would do. See `action_auto_executed.json` for an AI-executed action. |

**Chat** (`/api/agent/chat`)

- `reply`: the agent's answer (plain text).
- `tool_calls[]`: `{name, args, result_preview}` in call order.
- `actions_created[]`: action IDs the agent queued. Show them as approval cards.

**Scorecard** (`/api/carriers`, `/api/carriers/<vendor_id>`, items of `eligible[]`)

| Field | Type | Notes |
|---|---|---|
| `vendor_id`, `legal_name` | string | Carrier. Only carrier vendor types are scored (not lumpers or insurance). |
| `compliance_light` | string | `GREEN`, `YELLOW`, `RED` from Meridian. |
| `loads` | integer | Finished loads (`DELIVERED`, `POD_RECEIVED`, `CLOSED`). |
| `on_time_actual_pct` | integer or null | Percent of loads with a POD delivered on time. Excused lates count as on time, lates with no usable reason count as half late. `null` with no POD loads. |
| `on_time_stored_pct` | integer | What the carrier's Meridian profile claims. |
| `late_by_cause` | object | `{carrier, excused, unknown}` late delivery counts. |
| `damage`, `bounces`, `tonu` | integer | POD shortage/damage/refused; times removed from a load; carrier-caused TONUs. |
| `cost_score`, `reliability`, `quality` | number | Components, 0–1. |
| `base_score` | integer | 0–100 performance score (no load-specific fit). |
| `last_city` | object or null | `{city, state, shipment_id, date}`: where the carrier's latest load delivers. |
| `reasons` | string[] | 3–5 plain-English reasons. |

`/api/carriers/<vendor_id>` adds `per_load[]` (`{shipment_id, status, lane, pickup_date,
late_delivery: {cause, code} | null, late_pickup, condition, cost_ratio, extra_charges}`,
newest first) and `bounced_loads[]` (`{shipment_id, reason}`).

`eligible[]` items add `fit` (0–1: lane match + truck location) and `score` (0–100 for this
load). With `shipment_id`, the response also echoes `shipment_id`, and a carrier that already
bounced that load is excluded.

## Errors

Every error returns `{"error": "<code>", "detail": "<sentence>"}`:

| Status | `error` | When |
|---|---|---|
| `400` | `bad_request` | Body is not a JSON object, or a required field is missing |
| `404` | `not_found` | Unknown route, action or prospect |
| `405` | `method_not_allowed` | Known route, wrong method |
| `409` | `conflict` | Approving/rejecting an action that is not pending (including a double-clicked Approve), or filling a blocked prospect |
| `4xx` | Meridian's code | A Meridian error, passed through with its `detail` unchanged |
| `502` | Meridian's code | Meridian returned a server error |
| `502` | `openai_error` | The language model call failed (chat) |
| `503` | `meridian_unreachable` | Meridian could not be reached (timeout, connection error) |
| `500` | `internal_error` | Unexpected backend error |

`POST /api/actions/<id>/approve` returns `200` even when the Meridian write fails; check for
`status: "failed"`. `POST /api/fill` for a prospect that already has a pending action returns
that same action instead of queuing a duplicate.
