# Return Trip API contract

The Flask backend serves these routes at `http://localhost:5000`. Each `.json` file in this
folder is an example response. Build against the mocks now; the real routes will return the
same shapes.

If a route or field changes, the mock JSON and this table are updated together, and the change
is noted in `docs/status.md`.

## Routes

| Method | Route | Body | Returns | Mock |
|---|---|---|---|---|
| GET | `/api/network` | — | Network totals, cities and lane arcs | `network.json` |
| GET | `/api/city/<state>/<city>` | — | One city's inbound/outbound counts and ranked backhaul prospects | `city.json` |
| POST | `/api/fill` | `{prospect_id}` | `{action_id, status: "pending"}`, a quote proposal waiting for approval | `fill.json` |
| GET | `/api/actions?status=pending` | — | `{items: [Action]}` | `actions.json` |
| POST | `/api/actions/<id>/approve` | — | `Action` with `status: "done"` and `result` holding the new Meridian quote | `action_approved.json` |
| POST | `/api/actions/<id>/reject` | `{reason}` | `Action` with `status: "rejected"` | `action_rejected.json` |
| POST | `/api/agent/chat` | `{message}` | `{reply, tool_calls, actions_created}` | `agent_chat.json` |
| GET | `/api/audit?limit=50` | — | `{items: [{at, actor, event, detail}]}`, newest first | `audit.json` |
| * | `/api/email/...` | — | Owned by Asher; see `email_pipeline/` | — |

Example: `GET /api/city/TX/Dallas`.

## Shapes

**Network** (`/api/network`)

- `totals`: `empty_miles` (return-leg miles of one-way lanes), `empty_cost_usd`
  (`empty_miles × $2.00`), `one_way_lanes`, `loads`.
- `cities[]`: `{city, state, lat, lng, inbound, outbound}`.
- `arcs[]`: `{from, to, loads, miles, equipment}`. `from`/`to` are `{city, state, lat, lng}`.
  `equipment` maps Meridian equipment codes to load counts. The keys are whatever codes
  appear (`V`, `R`, `F`, `SB`, `SV`, …), not a fixed set.

**Prospect** (items of `prospects[]` in `/api/city/...`), sorted by `score`, highest first

| Field | Type | Notes |
|---|---|---|
| `prospect_id` | string | Pass this to `POST /api/fill`. |
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
| `reasons` | string[] | Human-readable reasons. When `ok` is false, the first one says what blocked it. |

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
| `status` | string | `pending`, `done`, `rejected`, `failed`. |
| `result` | object or null | `null` while pending. On `done`: `{quote_id, summary, sell_total, meridian_url}`. On `rejected`: `{reason}`. On `failed`: `{error}`. |
| `created_at` | string | UTC ISO-8601. |

**Chat** (`/api/agent/chat`)

- `reply`: the agent's answer (plain text).
- `tool_calls[]`: `{name, args, result_preview}` in call order.
- `actions_created[]`: action IDs the agent queued. Show them as approval cards.

## Errors

Every error returns `{"error": "<code>", "detail": "<sentence>"}` with status `400`, `404`,
`409` or `500`. A `409` from Meridian is passed through unchanged; its `detail` says what to do
next.
