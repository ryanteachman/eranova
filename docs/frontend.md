# Frontend (owner: Ali)

## Product: tours

**What changed.** Return Trip now plans tours (loops), not single return trips. Filling one empty return leg still leaves the truck idle somewhere else. The AI brain chains real Meridian loads (A → B, C → D, back home), finds the missing leg that closes the loop, and proposes the whole tour, so the truck is never idle and gets home loaded.

**Why.** A closed loop is worth more to everyone than the same loads booked one by one: the broker earns more margin per load, the carrier is loaded most of the week and home on time, and the shipper gets a lower rate from a truck that is already nearby. In the mocks (generated from live Meridian loads and the rate engine) the 3 tours unlock +$1,182.78 profit vs booking one by one, and run 91% / 100% / 89% loaded vs 50%.

**Three roles.** A role switch in the top bar changes the right panel:

| Role | Who it is | What they see |
|---|---|---|
| Broker | Profits when a loop closes | Tours tab (TourBoard), plus the existing City, Approvals, Inbox and Agent tabs |
| Carrier | The trucking company running the loop | CarrierWeek: a phone-style "your week" screen with pay, % loaded, home by, idle days, Accept / Counter |
| Manufacturer / shipper | The customer whose freight rides the loop | ShipperOffers: `backhaul_rate` offers (a truck is already nearby) and `flex_date` offers (ship another day and save) |

**Pricing assumption.** Carriers take 8% less per leg for a guaranteed loop (`TOUR_DISCOUNT` in the mock generator). This is a placeholder until the backend owns the rule.

## Overview

Return Trip's frontend is a single-page dashboard that shows how Meridian's freight network runs one way (trucks drive home empty) and lets a human approve the agent's fixes. A dark US map with glowing one-way arcs and an empty-miles counter explains the problem; the right panel shows prospects, an approval queue, the email inbox and an agent chat. Every write the agent proposes waits for a human click.

The spec and source of truth is `frontend/CLAUDE.md`.

## How to run

```bash
cd frontend && npm install && npm run dev
```

- Opens at http://localhost:5173
- Vite proxies `/api` to Ryan's Flask backend at `localhost:5000` (`frontend/vite.config.js`)

Env vars (copy `frontend/.env.example` to `frontend/.env.local`, which is gitignored):

| Var | Meaning |
|---|---|
| `VITE_USE_MOCK` | `true` = in-memory mock API built from `frontend/mocks/`. `false` = Ryan's Flask API through the proxy. Defaults to mock unless set to `false`. |
| `VITE_MERIDIAN_WEB_URL` | Meridian web app URL from the team packet. Used by the split view and "Open in Meridian" links. Never commit it. |

## Stack

- React 18, Vite, plain JavaScript (JSX), plain CSS (`src/styles.css`, dark theme via CSS variables)
- `react-leaflet` 4 + `leaflet` for the map (CartoDB Dark Matter tiles)
- No UI kit, no state library, no TypeScript
- Note: the current Vite template ships React 19, but the spec says React 18 and `react-leaflet` 5 needs 19. So `react` 18.3 and `react-leaflet` 4.2 are pinned in `package.json`.

## Files

| File | Job |
|---|---|
| `src/api.js` | Every request. Exports `api` (real or mock, picked by `VITE_USE_MOCK`) and `meridianLink(result)`. |
| `src/usePoll.js` | Calls a function every N ms, returns `{data, error, refresh}`. |
| `src/App.jsx` | Top bar with role switch, map on the left, right panel per role (Broker: Tours, City, Approvals, Inbox, Agent; Carrier: CarrierWeek; Manufacturer: ShipperOffers), toasts. Holds role, selected city, filled trips and booked tours. |

## Components (`src/components/`)

| Component | What it does | API calls |
|---|---|---|
| TopBar | Title, role switch (Broker / Carrier / Manufacturer), EmptyCounter, lens toggles, "Split with Meridian" toggle, mock/live label | none (gets `totals` from App) |
| TourBoard | Broker's Tours tab. One card per loop: carrier, window, leg timeline (booked, needs carrier, empty, missing), tour vs one-by-one margin, "+$X profit unlocked", decision checks, "Book this loop" (approves the tour's `book_tour` action) | `getTours` → `GET /api/tours`, `approve` → `POST /api/actions/<action_id>/approve` (result shape: `book_tour` in `requests.md`) |
| CarrierWeek | Carrier role. Phone-style "your week": pay, per mile, % loaded, home by, idle days, legs, vs the one-by-one week; Accept / Counter (with note) | `getCarrierWeeks` → `GET /api/carrier-weeks`, `respondWeek` → `POST /api/carrier-weeks/<tour_id>/respond` |
| ShipperOffers | Manufacturer / shipper role. `backhaul_rate` offers (a truck is already nearby) and `flex_date` offers (ship another day and save), with price vs market and reasons; Accept / Decline | `getOffers` → `GET /api/offers`, `respondOffer` → `POST /api/offers/<offer_id>/respond` |
| EmptyCounter | Empty miles and $ lost, counts up on load, ticks down when a trip is filled | none (`totals` from `getNetwork`) |
| NetworkMap | Dark map, curved arcs by equipment, ghost trucks driving home empty, city dots, green arcs for filled trips; in Broker role, tour loops in each tour's `color` with missing legs pulsing until booked | none (data from App's `getNetwork` → `GET /api/network`) |
| CityPanel | Selected city header (in/out), prospect cards sorted by score | `getCity` → `GET /api/city/<state>/<city>`, `fill` → `POST /api/fill` |
| ProspectCard | Customer, lane, equipment and category badges, sell and GP%, miles, reasons, "Fill it". Blocked cards stay visible, greyed, with a red reason. | none (calls back to CityPanel) |
| ApprovalQueue | Pending actions with tier, confidence, collapsible reasoning, Approve / Reject (with reason), result + "Open in Meridian" | `getActions('pending')` (App polls every 3 s) → `GET /api/actions?status=pending`, `approve` → `POST /api/actions/<id>/approve`, `reject` → `POST /api/actions/<id>/reject` |
| AuditLog | Recent agent and human activity | `getAudit` → `GET /api/audit` |
| InboxPanel | "Simulate email 01-06" buttons, email list, body + extracted fields + linked actions, outbox drafts | `getInbox` → `GET /api/email/inbox`, `getOutbox` → `GET /api/email/outbox`, `simulateEmail` → `POST /api/email/simulate` |
| AgentChat | Chat with the agent, tool calls shown as chips that expand to `result_preview`, suggested prompt | `chat` → `POST /api/agent/chat` |
| MeridianFrame | iframe of Meridian's web app, with an "open in new window" fallback | none (uses `VITE_MERIDIAN_WEB_URL`) |
| Toasts | Small success / error messages; errors show the backend's `detail` sentence | none |

## Mock mode

- Mocks live in `frontend/mocks/`, not `../contracts/` as the spec says, because `contracts/` did not exist yet.
- `network.json` and `city_dallas.json` were generated from the live Meridian data (read-only API calls only). Prospects were priced with Meridian's rate engine at real lane miles.
- `tours.json`, `tour_actions.json`, `carrier_weeks.json` and `shipper_offers.json` were generated from live Meridian loads and the rate engine, with the 8% `TOUR_DISCOUNT` assumption applied to tour legs.
- The other mock files are hand-written to match the spec.
- The mock layer in `api.js` keeps state in memory (actions, tours, weeks, offers, audit, inbox, outbox), so Fill it → Approve → green arc and Book this loop → quotes → carrier and shipper responses work end to end without a backend. A page reload resets it.
- Switching to the real API is one line: `VITE_USE_MOCK=false` in `.env.local`, then restart `npm run dev`.

## Demo click path

1. Broker role (default). The map shows three loops, each in its own color, with the missing legs pulsing.
2. Open the Tours tab. Three tours, +$1,182.78 profit unlocked vs booking one by one.
3. Open T-101 (Sunridge, Great Lakes ⇄ Texas). The leg timeline shows booked, needs carrier, empty and missing legs, and the card reads "+$486.06 profit unlocked" (91% loaded vs 50%).
4. Click "Book this loop". Toast, quotes are created for the missing legs, the missing legs turn green on the map and the counter ticks down.
5. Switch to the Carrier role. Sunridge's phone: $6,546.34 for the week, 91% loaded, home Friday.
6. Click "Accept week".
7. Switch to the Manufacturer role. Pioneer's offer: "Ship Friday instead of Monday, save $95".
8. Click Accept.
9. Back to the Broker role. The Approvals tab and the Agent activity show everything: the booked tour, the carrier's accept and the shipper's accept.

## Known issues

- Empty cost uses a placeholder $2.00 per empty mile until the backend prices it.
- Mock data only has prospects for Dallas. Other cities show the in/out header with no cards.
- Meridian may refuse to be iframed (X-Frame-Options). Fallback: open it in a new window and put the two windows side by side.
- The Pool lens is a stretch goal and not built.
- The tour discount (carriers take 8% less per leg for a guaranteed loop, `TOUR_DISCOUNT` in the generator) is an assumption, not a real pricing rule.
- Tours, carrier weeks and shipper offers are mocks only until the backend routes exist.
