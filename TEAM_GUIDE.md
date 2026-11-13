# Meridian TMS — Team Guide

Meridian TMS is a working transportation management system for a fictional freight
brokerage, Meridian Logistics: customers, carriers, facilities, quotes, shipments, tracking
and documents, all behind a REST API. Your environment is yours alone — nothing you do
affects other teams.

## What you receive

Your credentials file contains:

| | |
|---|---|
| **UI URL** | the web app — log in with one of the users below |
| **API base URL** | ends in `/v1`; the API reference calls it `$TMS_API_BASE` |
| **API key** | send it as the `x-api-key` header |
| **Password** | your environment's login password, shared by all four users |

Keep the API key and password private to your team. The full API reference is
`API_DOCS.md`: every route with its parameters, plus status lifecycles, errors and codes.
Start with *Getting started* and the *Route index*.

## Logins (web app, or `POST /auth/login`)

| User ID | Name | Role |
|---|---|---|
| `JOHNDOE` | John Doe | CSR |
| `JANEDOE` | Jane Doe | DISPATCH |
| `JACKDOE` | Jack Doe | SALES |
| `JILLDOE` | Jill Doe | ACCOUNTING |

All four use your environment's password.

## First calls

```bash
export TMS_API_BASE="<your API base URL, ending in /v1>"
export TMS_API_KEY="<your API key>"

# Is it alive? Board counts for the dashboard
curl -s -H "x-api-key: $TMS_API_KEY" "$TMS_API_BASE/dashboard/counts"

# Find anything by number (file, PO, PRO, BOL, MC…) or name
curl -s -H "x-api-key: $TMS_API_KEY" "$TMS_API_BASE/search?q=northstar"

# Shipments that need a check call now
curl -s -H "x-api-key: $TMS_API_KEY" "$TMS_API_BASE/shipments?queue=tracking"
```

On Windows PowerShell, use `curl.exe` and `$env:TMS_API_BASE` / `$env:TMS_API_KEY`.

## Good to know

- **The data is fictional and resettable.** The organizers can reset your environment to its
  starting dataset; a reset wipes what you created and IDs may change. Your URLs, API key
  and password stay the same.
- **Dates are relative to the day the data was loaded** (deliveries due "today", overdue
  check calls, valid quotes).
- **Business rules are enforced.** A carrier must be compliant before it can cover a load, a
  rate confirmation is needed before dispatch, and a proof of delivery before the file can be
  closed. A blocked action returns `409` with a `detail` sentence that says why and what to
  do next — it is written to be read by programs as well as people.
- **Everything done with the API key is attributed to `API`** in the activity log, so your
  integration's actions are easy to find in the web app.
- **Quoting tools:** `POST /rate-engine/quotes` returns a market-rate buy side, and
  `POST /quotes/price-preview` / `POST /quotes/{id}/price` turn it into customer pricing
  (API_DOCS › *Rate engine* and *Quotes*).
- Please don't load-test the environment.
