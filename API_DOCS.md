# Meridian TMS — API Reference

Meridian TMS is a transportation management system for a freight brokerage. Its REST API
covers customers, carriers, facilities, quotes and pricing, shipments (booking, dispatch,
tracking, proof of delivery), documents and search.

## Getting started

**Base URL.** Every route in this document is relative to your environment's API base
URL, which ends in `/v1`. The examples use it as `$TMS_API_BASE`:

```bash
export TMS_API_BASE="<your API base URL, ending in /v1>"
export TMS_API_KEY="<your API key>"

curl -s -H "x-api-key: $TMS_API_KEY" "$TMS_API_BASE/dashboard/counts"
```

HTTPS and JSON only. There is no versioning beyond the `/v1` prefix.

**Authentication.** Every route except `POST /auth/login` needs one of two credentials:

| Scheme | Header | Use for | Actions are recorded as |
|---|---|---|---|
| API key | `x-api-key: <key>` | scripts and system integrations | `API` |
| Session token | `Authorization: Bearer <token>` | a person's session — get the token from `POST /auth/login` with a user account; it expires after 12 hours | the user's ID (e.g. `JOHNDOE`) |

If an `x-api-key` header is present it is the only credential checked: an invalid key is
`401` even when a valid Bearer token is also sent.

**Main resources.**

- **Customers** are the shippers and consignees you move freight for, with their contacts,
  addresses, reference requirements and pricing defaults.
- **Carriers** (vendors) carry compliance data. Only compliant carriers can cover a load.
- **Facilities** are shared pickup and delivery locations (docks, warehouses, distribution
  centers) with hours, scheduling rules and notes.
- **Quotes** price a load for a customer. Booking an accepted quote turns it into a
  **shipment** with the same number.
- **Shipments** move through a status lifecycle from booking, through delivery and proof of
  delivery, to a closed file.
- Quotes and shipments share one numbering sequence of 7-digit **file numbers** (e.g.
  `7300174`). Rate confirmation numbers derive from it: `RC-{file}-{rev}`.

## Conventions

### Requests

- Request bodies are JSON **objects** (`Content-Type: application/json`). A body that is not
  valid JSON, or not an object, is rejected with `400`.
- Path parameters are shown in `{braces}`.

### Responses

- Single-resource and action routes return the resource itself. Creation returns `201`; every
  other success returns `200`.
- List routes return one envelope:

  ```json
  {"items": [], "count": 0, "next_cursor": null}
  ```

  `count` is the number of items **in this page**, not a total.

### Pagination

List routes that page accept `limit` (default **50**, maximum **200**) and `cursor`. To get
the next page, send the previous response's `next_cursor` back as `cursor`; it is `null` on
the last page. A cursor only works with the same filters it was issued for. An invalid cursor
is `400`.

### Errors

Every error has the same body:

```json
{"error": "<code>", "detail": "<human-readable explanation>"}
```

| Status | `error` | Meaning |
|---|---|---|
| `400` | `bad_request` | Malformed JSON body, non-object body, invalid pagination cursor |
| `401` | `unauthorized` | Missing or invalid API key, missing/expired/invalid session token, failed login |
| `404` | `not_found` | Unknown ID or unknown route |
| `405` | `method_not_allowed` | Known route, wrong HTTP method |
| `409` | `conflict` | A business rule blocks the action (carrier compliance, wrong status, missing POD, closed file…) |
| `422` | `validation_error` | Missing or invalid fields, unknown enum values, bad filters or dates |
| `500` | `internal_error` | Unexpected server error |

A `409` `detail` is a complete sentence that says what blocked the action and what to do
next.

### Dates, times and money

- System timestamps (`created_at`, `updated_at`, `entered_at`, …) are UTC ISO-8601 with a `Z`
  suffix, e.g. `2026-07-04T16:49:28Z`.
- Stop scheduling times are **facility-local**: naive local times such as
  `2026-07-08T08:00:00`, paired with an IANA `timezone` such as `America/Chicago`.
  `mabd_date` ("must arrive by" date) and proof-of-delivery times are facility-local too.
- Plain dates (`pickup_date`, `valid_until`, filters) are `YYYY-MM-DD`.
- Events and milestones have two timestamps: `event_at` (when it happened; you may back-date
  it) and `entered_at` (when it was recorded, set by the server).
- Money is a JSON number in USD, rounded half-up to 2 decimals. Quotes and shipments keep two
  ledgers: `vendor_costs[]` (buy) and `customer_charges[]` (sell). The totals are computed
  for you: `buy_total`, `sell_total`, `gp_amount = sell_total − buy_total`, and `gp_pct`. That
  is margin on sell, not markup: an 18% margin means sell = buy ÷ 0.82.

### Audit fields

Records carry `created_at` / `created_by` / `updated_at` / `updated_by`. Status changes also
set `status_updated_at` / `status_updated_by`. The actor is the user's ID, or `API` for API-key
callers.

## Contents

- [Getting started](#getting-started)
- [Conventions](#conventions)
- [Route index](#route-index)
- [Authentication routes](#authentication-routes)
- [Dashboard and search](#dashboard-and-search)
- [Customers](#customers)
- [Carriers](#carriers)
- [Facilities](#facilities)
- [Quotes](#quotes)
- [Rate engine](#rate-engine)
- [Shipments](#shipments)
- [Documents](#documents)
- [Reference data](#reference-data)
- [Enums and codes](#enums-and-codes)

---

## Route index

| Method | Route | Purpose |
|---|---|---|
| `GET` | [`/auth/me`](#get-authme) | Returns the authenticated caller: the resolved `principal` plus the current `user` record. |
| `POST` | [`/auth/login`](#post-authlogin) | Exchanges a user account's ID and password for a signed session token (JWT). |
| `GET` | [`/dashboard/counts`](#get-dashboardcounts) | Returns the seven operational queue counts, always all seven, in the fixed order listed in the table below. |
| `GET` | [`/search`](#get-search) | Universal search. |
| `GET` | [`/customers`](#get-customers) | Lists customers sorted by legal name. |
| `GET` | [`/customers/{customer_id}`](#get-customerscustomer_id) | Returns one customer. |
| `POST` | [`/customers`](#post-customers) | Creates a customer and assigns its `customer_no`. |
| `PUT` | [`/customers/{customer_id}`](#put-customerscustomer_id) | Updates a customer's profile. |
| `GET` | [`/customers/{customer_id}/facilities`](#get-customerscustomer_idfacilities) | Lists the facilities linked to this customer, sorted by facility name. |
| `GET` | [`/vendors`](#get-vendors) | Lists carriers and other vendors sorted by legal name, each with its compliance light. |
| `GET` | [`/vendors/lookup`](#get-vendorslookup) | Finds carriers by MC, DOT or SCAC number, for example before adding a new carrier. |
| `GET` | [`/vendors/{vendor_id}`](#get-vendorsvendor_id) | Returns one carrier with its compliance light. |
| `POST` | [`/vendors`](#post-vendors) | Creates a carrier or other vendor and assigns its `vendor_no`. |
| `PUT` | [`/vendors/{vendor_id}`](#put-vendorsvendor_id) | Updates a carrier, including status changes; there is no separate status route. |
| `GET` | [`/facilities`](#get-facilities) | Lists facilities sorted by name, or resolves a partial name or code to a facility (for example `q=DC135` finds `BBR-DC135`). |
| `GET` | [`/facilities/{facility_id}`](#get-facilitiesfacility_id) | Returns one facility, including its appointment rules and notes. |
| `POST` | [`/facilities`](#post-facilities) | Creates a facility. |
| `PUT` | [`/facilities/{facility_id}`](#put-facilitiesfacility_id) | Updates a facility. |
| `GET` | [`/facilities/{facility_id}/shipments`](#get-facilitiesfacility_idshipments) | Lists the shipments that pick up or deliver at this facility, most recent pickup date first. |
| `POST` | [`/facilities/{facility_id}/notes`](#post-facilitiesfacility_idnotes) | Appends a note to the facility's `notes` feed, for example a new dock rule or a change in lead time. |
| `GET` | [`/quotes`](#get-quotes) | Lists quotes as *Quote* objects, each with its computed `status` and `summary`. |
| `GET` | [`/quotes/{quote_id}`](#get-quotesquote_id) | Returns one quote; `status` reads `EXPIRED` when the quote's validity has passed. |
| `POST` | [`/quotes`](#post-quotes) | Creates a `DRAFT` quote on a new file number, which is immediately resolvable through `GET /search`. |
| `PUT` | [`/quotes/{quote_id}`](#put-quotesquote_id) | Updates a quote's header, lane, freight and hand-entered money lines. |
| `POST` | [`/quotes/{quote_id}/rate`](#post-quotesquote_idrate) | Prices the quote from the rates on file and moves it to `QUOTED`. |
| `POST` | [`/quotes/price-preview`](#post-quotesprice-preview) | Computes the sell lines and totals that `POST /quotes/{quote_id}/price` would produce for the given buy lines and margin, without a quote. |
| `POST` | [`/quotes/{quote_id}/price`](#post-quotesquote_idprice) | Applies an externally priced buy side at a target margin, derives the sell side, and moves the quote to `QUOTED` with `rate_source. |
| `POST` | [`/quotes/{quote_id}/send`](#post-quotesquote_idsend) | Records that a `QUOTED` quote was sent to the customer. |
| `POST` | [`/quotes/{quote_id}/accept`](#post-quotesquote_idaccept) | Records the customer's acceptance from `QUOTED` or `SENT`: status becomes `ACCEPTED` and a note is appended. |
| `POST` | [`/quotes/{quote_id}/decline`](#post-quotesquote_iddecline) | Closes the quote as `DECLINED` (terminal), stores `declined_reason` and appends a note. |
| `POST` | [`/quotes/{quote_id}/clone`](#post-quotesquote_idclone) | Copies a quote to a new `DRAFT` on a new file number. |
| `POST` | [`/quotes/{quote_id}/book`](#post-quotesquote_idbook) | Converts the quote into a shipment on the same file number (`shipment_id` equals `quote_id`). |
| `POST` | [`/rate-engine/quotes`](#post-rate-enginequotes) | Prices one lane at market rates and returns the buy-side money lines. |
| `GET` | [`/shipments`](#get-shipments) | Lists shipments (the shipment board). |
| `POST` | [`/shipments`](#post-shipments) | Books a shipment directly, without a quote. |
| `GET` | [`/shipments/{shipment_id}`](#get-shipmentsshipment_id) | Returns one shipment, including its `summary` line. |
| `PUT` | [`/shipments/{shipment_id}`](#put-shipmentsshipment_id) | Edits header fields, stops and freight lines. |
| `POST` | [`/shipments/{shipment_id}/cover`](#post-shipmentsshipment_idcover) | Assigns the carrier and moves the shipment from `BOOKED` to `COVERED`, completing `COVERED` (`LTL`. |
| `POST` | [`/shipments/{shipment_id}/uncover`](#post-shipmentsshipment_iduncover) | Removes the carrier (a carrier bounce) and returns the shipment to `BOOKED`. |
| `POST` | [`/shipments/{shipment_id}/dispatch`](#post-shipmentsshipment_iddispatch) | Moves the shipment from `COVERED` to `DISPATCHED` and completes the `DISPATCHED` milestone (`TL`/`EXPEDITE`). |
| `POST` | [`/shipments/{shipment_id}/status`](#post-shipmentsshipment_idstatus) | Moves the shipment one or two steps forward between `DISPATCHED` and `DELIVERED`, places it `ON_HOLD`, or releases a hold. |
| `PUT` | [`/shipments/{shipment_id}/milestones/{code}`](#put-shipmentsshipment_idmilestonescode) | Marks one milestone complete or clears it. |
| `PUT` | [`/shipments/{shipment_id}/stops/{stop_seq}/appointment`](#put-shipmentsshipment_idstopsstop_seqappointment) | Sets or confirms a stop appointment. |
| `POST` | [`/shipments/{shipment_id}/check-calls`](#post-shipmentsshipment_idcheck-calls) | Records a tracking check call as a `CHECK_CALL` event and sets the next follow-up time (`next_tracking_at`). |
| `POST` | [`/shipments/{shipment_id}/pod`](#post-shipmentsshipment_idpod) | Records the proof of delivery. |
| `POST` | [`/shipments/{shipment_id}/costs`](#post-shipmentsshipment_idcosts) | Adds a vendor cost line (buy) and recalculates `buy_total`, `gp_amount` and `gp_pct`. |
| `PUT` | [`/shipments/{shipment_id}/costs/{cost_id}`](#put-shipmentsshipment_idcostscost_id) | Edits a vendor cost line and recalculates the money totals. |
| `POST` | [`/shipments/{shipment_id}/charges`](#post-shipmentsshipment_idcharges) | Adds a customer charge line (sell) and recalculates `sell_total`, `gp_amount` and `gp_pct`. |
| `PUT` | [`/shipments/{shipment_id}/charges/{charge_id}`](#put-shipmentsshipment_idchargescharge_id) | Edits a customer charge line and recalculates the money totals. |
| `POST` | [`/shipments/{shipment_id}/notes`](#post-shipmentsshipment_idnotes) | Adds a note to the activity log as a `NOTE` event. |
| `PUT` | [`/shipments/{shipment_id}/internal-notes`](#put-shipmentsshipment_idinternal-notes) | Replaces the shipment's `internal_notes` text. |
| `POST` | [`/shipments/{shipment_id}/close`](#post-shipmentsshipment_idclose) | Closes the file after proof of delivery: `status` moves from `POD_RECEIVED` to `CLOSED`, which is terminal. |
| `POST` | [`/shipments/{shipment_id}/cancel`](#post-shipmentsshipment_idcancel) | Cancels a shipment before delivery. |
| `GET` | [`/shipments/{shipment_id}/events`](#get-shipmentsshipment_idevents) | Returns the shipment's activity log, newest first by `entered_at`. |
| `GET` | [`/shipments/{shipment_id}/documents`](#get-shipmentsshipment_iddocuments) | Lists the documents attached to a shipment, newest first. |
| `GET` | [`/customers/{customer_id}/documents`](#get-customerscustomer_iddocuments) | Lists the documents attached to a customer, newest first. |
| `GET` | [`/vendors/{vendor_id}/documents`](#get-vendorsvendor_iddocuments) | Lists the documents attached to a carrier or other vendor (for example COI, carrier agreement), newest first. |
| `GET` | [`/quotes/{quote_id}/documents`](#get-quotesquote_iddocuments) | Lists the documents attached to a quote (the generated customer quotation PDFs), newest first. |
| `GET` | [`/documents/{owner_key}/{doc_id}/url`](#get-documentsowner_keydoc_idurl) | Returns a pre-signed download link for one stored document. |
| `POST` | [`/shipments/{shipment_id}/documents`](#post-shipmentsshipment_iddocuments) | Starts an upload to a shipment. |
| `POST` | [`/customers/{customer_id}/documents`](#post-customerscustomer_iddocuments) | Starts an upload to a customer. |
| `POST` | [`/vendors/{vendor_id}/documents`](#post-vendorsvendor_iddocuments) | Starts an upload to a carrier or other vendor (for example a COI or carrier agreement). |
| `POST` | [`/shipments/{shipment_id}/documents/generate`](#post-shipmentsshipment_iddocumentsgenerate) | Renders a PDF from the shipment's current data and attaches it to the shipment (`source` `GENERATED`). |
| `POST` | [`/quotes/{quote_id}/documents/generate`](#post-quotesquote_iddocumentsgenerate) | Renders the customer-facing quotation PDF and attaches it to the quote (`source` `GENERATED`, `visible_to_customer` `true`), named `Quote_{quote_id}_{version}.pdf`. |
| `GET` | [`/charge-codes`](#get-charge-codes) | Returns the charge-code catalog, sorted by `code`, in one page. |
| `GET` | [`/users`](#get-users) | Returns all user accounts, sorted by `user_id`, in one page — for user pickers and for displaying the `created_by` / `updated_by` audit values. |
| `GET` | [`/fsc`](#get-fsc) | Returns the fuel surcharge scheme that rating and the rate engine use. |

---

## Authentication routes

These routes exchange user-account credentials for a session token and report who the current caller is.

### GET /auth/me

Returns the authenticated caller: the resolved `principal` plus the current `user` record. Callers using the `x-api-key` header get the fixed API principal (`type` `api`, `user_id` `api`, `name` `API Client`, `initials` `API`, `role` `API`) and `user: null`.

**Returns** — `200` — `{principal, user}`; `principal` has `type` (`user` or `api`), `user_id`, `name`, `initials`, `role` and, for user sessions, `station`; `user` is the user record (`user_id`, `name`, `initials`, `role`, `station`, audit fields) without any password data, or `null` for API-key callers.

### POST /auth/login

Exchanges a user account's ID and password for a signed session token (JWT). This is the only route that needs no credentials. Send the token on later requests as `Authorization: Bearer <token>`; it expires 12 hours after issue and there is no refresh route — log in again.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | string | yes | User account ID, e.g. `JOHNDOE`. Case-sensitive; surrounding whitespace is ignored. |
| `password` | string | yes | The account password (`<password>`). |

**Returns** — `200` — `{token, user}`: the session token and the user record (`user_id`, `name`, `initials`, `role`, `station`, audit fields); password data is never returned.

**Errors** — `401` with the same detail (`Invalid user ID or password`) for an unknown user ID and a wrong password; `422` when `user_id` or `password` is missing or empty.

---

## Dashboard and search

These read-only routes return the operational work-queue counts and resolve free text or any reference number to the matching records.

### GET /dashboard/counts

Returns the seven operational queue counts, always all seven, in the fixed order listed in the table below. Counts are computed live on every call; "today" and "now" are evaluated in UTC.

**Tiles**

| `key` | `label` | Counts |
|---|---|---|
| `quotes_pending` | Quotes pending | Quotes with stored status `QUOTED` or `SENT` |
| `to_cover` | To cover | Shipments in `BOOKED` |
| `dispatched` | Dispatched | Shipments in `COVERED` or `DISPATCHED` |
| `in_transit` | In transit | Shipments in `AT_PICKUP`, `PICKED_UP`, `IN_TRANSIT` or `AT_DELIVERY` |
| `delivering_today` | Delivering today | Non-terminal shipments (including `ON_HOLD`) whose target delivery date is today |
| `awaiting_pod` | Delivered awaiting POD | Shipments in `DELIVERED` |
| `tracking_overdue` | Tracking overdue | Non-terminal shipments whose `next_tracking_at` is at or before now (`alert: true`) |

**Returns** — `200` — `{tiles}`: an array of `{key, label, count, filter_route, alert}`, where `filter_route` is the web-application path of the matching filtered list and `alert` is `true` only for `tracking_overdue`.

### GET /search

Universal search: paste any reference number or type part of a name and get the matching records, grouped by category. Reference lookup normalizes the query to uppercase letters and digits only, so `123-456789`, `123456789` and `123 456789` all find PRO `123-456789`; it matches exactly against every reference recorded on quotes and shipments (file numbers, PRO, BOL, PO, pickup, delivery and appointment confirmation numbers, rate confirmation numbers and other references). Name matching needs at least 2 characters, is case-insensitive, and matches a record when every whitespace-separated word of `q` appears in its ID, name, DBA name, city or state (carriers also match SCAC, MC and DOT numbers; facilities also match facility code and parent company).

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `q` | string | yes | Search text; leading and trailing whitespace is ignored. |

**Returns** — `200` — `{references, customers, vendors, facilities}`, each an array of at most 10 hits shaped `{entity_type, entity_id, label, sublabel, route}`; `entity_type` is `SHIPMENT` or `QUOTE` in `references`, and `CUSTOMER`, `VENDOR` or `FACILITY` in the name categories; `route` is the record's web-application path.

**Errors** — `422` when `q` is missing or blank.

---

## Customers

Customers are the shipper and consignee accounts you move freight for; each carries its profile, booking requirements and rating defaults.

### Objects

#### Customer object

Every customer read (list, detail, create, update) returns this object. Fields marked read-only are ignored when sent.

| Field | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | no | Mnemonic id, 2–24 characters of `A-Z`, `0-9`, `-`, `_`, uppercased (e.g. `NORTHSTAR`). Set on create only; generated from `legal_name` when omitted. |
| `customer_no` | string or integer | read-only | Account number assigned on create. |
| `legal_name` | string | yes | Legal name. |
| `dba_name` | string | no | Trading ("doing business as") name. |
| `status` | string | no | `ACTIVE` (default), `INACTIVE`, `PROSPECT`. |
| `customer_roles` | array of string | no | Any of `SHIPPER`, `CONSIGNEE`, `CONTROLLING`. Default `["SHIPPER", "CONTROLLING"]`. |
| `addresses` | array | no | *Address* objects. Default `[]`. |
| `contacts` | array | no | *Contact* objects with customer roles. Default `[]`. |
| `phone` | string | no | Main phone number. |
| `website` | string | no | Website. |
| `parent_customer_id` | string | no | Customer id of the parent account. |
| `salesperson_id` | string | no | User id of the salesperson. |
| `account_manager_id` | string | no | User id of the account manager. |
| `station` | string | no | Owning office code (e.g. `CHI`). |
| `required_references` | array | no | *Required reference* objects. |
| `default_dim_factor` | number | no | Dimensional-weight factor used on this customer's quotes and shipments. `194` when unset. |
| `discount_pct` | number | no | LTL sell-side discount off the base rate, as `63` or `0.63`. Overrides the standard 62% sell discount. |
| `default_service_level` | string | no | Preferred service level (see *Enums › Service level*). |
| `margin_floor_pct` | number | no | Target margin (percent of sell) used when a quote is rated without an explicit `target_margin_pct`; `18` when unset. |
| `accessorial_defaults` | array | no | Accessorial charge codes this customer usually needs (e.g. `LUM`). |
| `tsa_known_shipper_status` | string | no | `KNOWN`, `UNKNOWN`, `PENDING`. |
| `tsa_status_date` | date | no | Date the TSA status was established. |
| `tsa_expiry_date` | date | no | Date the TSA status expires. |
| `notes` | array | read-only | *Note* objects. |
| `created_at`, `updated_at` | datetime | read-only | Audit timestamps. |
| `created_by`, `updated_by` | string | read-only | Audit actor: the user's initials, or `API` for API-key calls. |

#### Address object

A postal address. Used for customer `addresses[]` and carrier `physical_address`.

| Field | Type | Required | Description |
|---|---|---|---|
| `address_type` | string | no | Customer addresses: `MAIN`, `BILLING`, `REMIT_TO`. Customer-facing quote documents use the `MAIN` address, then the first address. |
| `name` | string | no | Name or attention line. |
| `address1` | string | no | Street address. |
| `address2` | string | no | Suite, unit or building. |
| `city` | string | no | City. |
| `state` | string | no | State or province code (e.g. `IL`). |
| `zip` | string | no | Postal code. |
| `country` | string | no | Country code. |

#### Contact object

A person or desk at a customer, carrier or facility. The allowed `role` values depend on the parent record.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | no | Contact or desk name. |
| `title` | string | no | Job title. |
| `role` | string | no | Customers: `PRIMARY`, `AP`, `OPS`, `PRICING`, `AFTER_HOURS`. Carriers: `DISPATCH`, `QUOTING`, `CLAIMS`, `ACCOUNTING_AR`, `AFTER_HOURS`, `TRACKING`. Facilities: `RECEIVING`, `SHIPPING`, `SCHEDULING`, `SECURITY`. |
| `phone` | string | no | Phone number. |
| `email` | string | no | E-mail address. |
| `notify_events` | array of string | no | Customers: shipment events this contact wants to hear about (e.g. `BOOKED`, `DELIVERED`). |
| `favorite` | boolean | no | Carriers: marks the preferred contact. The preferred `DISPATCH` contact is printed on rate confirmations. |
| `hours` | string | no | Facilities: when the contact can be reached (e.g. `06:00-14:00 CT`). |

#### Note object

An attributed, timestamped note. Used by customers (read-only), carriers and facilities.

| Field | Type | Required | Description |
|---|---|---|---|
| `author` | string | — | Who wrote it: the user's initials, or `API` for API-key calls. Set by the server where notes are appended. |
| `timestamp` | datetime | — | When it was written. |
| `text` | string | yes | Note text. |

#### Required reference object

A reference number the customer expects on its freight, and the stage by which it is needed.

| Field | Type | Required | Description |
|---|---|---|---|
| `ref_type` | string | no | Reference type (see *Enums › Reference type*), e.g. `PO`. |
| `required_at` | string | no | `QUOTE`, `BOOKING`. |

#### Facility link object

The customer-specific view of a shared facility, returned as `link` on each item of `GET /customers/{customer_id}/facilities`.

| Field | Type | Required | Description |
|---|---|---|---|
| `relationship` | string | — | `SHIP_FROM`, `SHIP_TO`, `BOTH`. |
| `customer_alias` | string | — | The customer's own name for the facility. |
| `customer_facility_code` | string | — | The customer's own code for the facility (e.g. a DC number). |
| `frequency_note` | string | — | How often the customer uses the facility. |

### GET /customers

Lists customers sorted by legal name.

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `ACTIVE`, `INACTIVE`, `PROSPECT`. |
| `q` | string | no | Case-insensitive search over `customer_id`, `legal_name` and `dba_name`; every space-separated word must match one of them. |
| `limit` | integer | no | Page size, default 50, maximum 200. Out-of-range values are clamped. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** `200` with a list of *Customer* objects.

**Errors** `422` for an unknown `status` value or a non-integer `limit`.

### GET /customers/{customer_id}

Returns one customer.

**Path parameters**

| Name | Description |
|---|---|
| `customer_id` | Customer id, e.g. `NORTHSTAR`. |

**Returns** `200` with the *Customer* object.

### POST /customers

Creates a customer and assigns its `customer_no`. When `customer_id` is omitted, it is generated from `legal_name`: corporate words such as Inc, LLC and The are dropped, a first word of six or more characters is used on its own ("Northstar Manufacturing" → `NORTHSTAR`), and otherwise words are joined and cut to eight characters ("Acme Carrier Inc." → `ACMECARR`).

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `legal_name` | string | yes | Legal name. |
| `customer_id` | string | no | Explicit id, 2–24 characters of `A-Z`, `0-9`, `-`, `_` (uppercased). |
| `status` | string | no | `ACTIVE` (default), `INACTIVE`, `PROSPECT`. |
| other fields | — | no | Any writable field of the *Customer* object, with the defaults shown there. Read-only fields (`customer_no`, `notes` and audit fields) are ignored. |

**Returns** `201` with the new *Customer* object.

**Errors** `409` when the customer id already exists; `422` for an invalid id, an unknown enum value or a non-numeric number field.

### PUT /customers/{customer_id}

Updates a customer's profile. Only the fields you send change; arrays and objects you send replace the stored value whole, and `null` clears an optional field. Read-only and unknown fields are ignored, so a record read with `GET` can be sent back unchanged.

**Path parameters**

| Name | Description |
|---|---|
| `customer_id` | Customer id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| any writable field | — | no | Any writable field of the *Customer* object except `customer_id`. |

**Returns** `200` with the updated *Customer* object.

**Errors** `422` for an unknown enum value or a non-numeric number field.

### GET /customers/{customer_id}/facilities

Lists the facilities linked to this customer, sorted by facility name. Each item is a full *Facility* object (see Facilities) plus a `link` field holding the customer-specific *Facility link* object. Links are read-only through the API.

**Path parameters**

| Name | Description |
|---|---|
| `customer_id` | Customer id. |

**Returns** `200` with a single-page list (`next_cursor` is always `null`) of *Facility* objects, each with `link`.

---

## Carriers

Carriers and other vendors (lumpers, cartage companies, insurance vendors) live under `/vendors`, with their identifiers, capabilities, insurance and compliance status.

### Objects

#### Carrier object

Every carrier read (lookup, list, detail, create, update) returns this object with the computed compliance fields `compliance_light` and `insurance[].insurance_status`. Fields marked read-only are ignored when sent.

**Compliance light.** Each insurance policy is `GREEN`, `YELLOW` (expires within 30 days) or `RED` (expired, or no valid expiration date). The carrier's `compliance_light` is its worst policy light, forced to `RED` when `status` is `DO_NOT_USE` or `authority_status` is `REVOKED`; a carrier with no policies shows `GREEN`. The light is a summary. Covering a load (`POST /shipments/{shipment_id}/cover`) checks two things and refuses with `409` if either fails: the carrier's `status` must be `ACTIVE` (so `PENDING`, `INACTIVE` and `DO_NOT_USE` carriers are blocked), and it must have at least one `CARGO` policy that has not expired.

| Field | Type | Required | Description |
|---|---|---|---|
| `vendor_id` | string | no | Mnemonic id, 2–24 characters of `A-Z`, `0-9`, `-`, `_`, uppercased (e.g. `ACMECARR`). Set on create only; generated from `legal_name` when omitted. |
| `vendor_no` | string or integer | read-only | Vendor account number assigned on create. |
| `legal_name` | string | yes | Legal name. |
| `dba_name` | string | no | Trading ("doing business as") name. |
| `vendor_type` | string | yes | `TRUCKLOAD_CARRIER`, `LTL_CARRIER`, `CARTAGE_AGENT`, `EXPEDITE_CARRIER`, `AIRLINE`, `INSURANCE_VENDOR`, `LUMPER`, `OTHER`. |
| `status` | string | no | `PENDING` (default), `ACTIVE`, `INACTIVE`, `DO_NOT_USE`. Only `ACTIVE` carriers can cover loads. |
| `status_reason` | string | no | Why the carrier has its status. Required when `status` is `DO_NOT_USE`. |
| `scac` | string | no | Standard Carrier Alpha Code; stored uppercased. |
| `mc_number` | string | no | MC docket number (e.g. `MC-784512`). |
| `dot_number` | string | no | USDOT number. |
| `ein` | string | no | Employer identification number. |
| `phone` | string | no | Main phone number. |
| `email` | string | no | Main e-mail address. |
| `physical_address` | object | no | *Address* object. |
| `service_types` | array of string | no | Modes the carrier runs, e.g. `TL`, `LTL`, `EXPEDITE`. |
| `equipment_types` | array of string | no | Equipment codes (see *Enums › Equipment type*). Default `[]`. |
| `lanes` | array | no | *Lane* objects. Default `[]`. |
| `hazmat_certified` | boolean | no | Certified to haul hazardous materials. Default `false`. |
| `authority_status` | string | no | Operating authority: `ACTIVE`, `REVOKED`, `NONE` (default). |
| `safety_rating` | string | no | `SATISFACTORY`, `CONDITIONAL`, `UNRATED` (default). |
| `insurance` | array | no | *Insurance policy* objects. Default `[]`. |
| `compliance_light` | string | read-only | `GREEN`, `YELLOW`, `RED`, as described above. |
| `loads_completed` | number | no | Scorecard: loads completed. |
| `on_time_pickup_pct` | number | no | Scorecard: on-time pickup percentage. |
| `on_time_delivery_pct` | number | no | Scorecard: on-time delivery percentage. |
| `claims_count` | number | no | Scorecard: number of claims. |
| `last_used_date` | date | no | Scorecard: date the carrier last hauled a load. |
| `contacts` | array | no | *Contact* objects with carrier roles. Default `[]`. |
| `notes` | array | no | *Note* objects. Default `[]`. Sending `notes` replaces the whole list. |
| `created_at`, `updated_at` | datetime | read-only | Audit timestamps. |
| `created_by`, `updated_by` | string | read-only | Audit actor: the user's initials, or `API` for API-key calls. |

#### Insurance policy object

| Field | Type | Required | Description |
|---|---|---|---|
| `policy_type` | string | no | `AUTO_LIABILITY`, `CARGO`, `GENERAL_LIABILITY`. |
| `insurer` | string | no | Insurance company. |
| `policy_number` | string | no | Policy number. |
| `limit` | number | no | Coverage limit in USD. |
| `expiration_date` | date | no | Expiration date. A policy without one reads as `RED`. |
| `source` | string | no | Where the certificate came from: `AGENT_DIRECT`, `CARRIER_PROVIDED`. |
| `insurance_status` | string | read-only | `GREEN`, `YELLOW` (expires within 30 days), `RED` (expired or no expiration date). |

#### Lane object

| Field | Type | Required | Description |
|---|---|---|---|
| `origin` | string | no | Origin area, e.g. a state code (`IL`). |
| `destination` | string | no | Destination area (`TX`). |
| `note` | string | no | Free-text note about the lane. |

### GET /vendors

Lists carriers and other vendors sorted by legal name, each with its compliance light.

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `type` | string | no | A `vendor_type` value, e.g. `TRUCKLOAD_CARRIER`. |
| `status` | string | no | `PENDING`, `ACTIVE`, `INACTIVE`, `DO_NOT_USE`. |
| `q` | string | no | Case-insensitive search over `vendor_id`, `legal_name`, `dba_name`, `scac`, `mc_number` and `dot_number`; every space-separated word must match one of them. |
| `limit` | integer | no | Page size, default 50, maximum 200. Out-of-range values are clamped. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** `200` with a list of *Carrier* objects.

**Errors** `422` for an unknown `type` or `status` value or a non-integer `limit`.

### GET /vendors/lookup

Finds carriers by MC, DOT or SCAC number, for example before adding a new carrier. A carrier matching any of the supplied numbers is returned once; results are sorted by `vendor_id`.

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `mc` | string | one of `mc`, `dot`, `scac` | MC number. Only the digits are compared, so `MC-784512`, `MC 784512` and `784512` match the same carrier. |
| `dot` | string | one of `mc`, `dot`, `scac` | DOT number, compared on digits only. |
| `scac` | string | one of `mc`, `dot`, `scac` | Exact SCAC, case-insensitive. |

**Returns** `200` with a single-page list (`next_cursor` is always `null`) of *Carrier* objects; empty when nothing matches.

**Errors** `422` when none of `mc`, `dot` or `scac` is given.

### GET /vendors/{vendor_id}

Returns one carrier with its compliance light.

**Path parameters**

| Name | Description |
|---|---|
| `vendor_id` | Vendor id, e.g. `ACMECARR`. |

**Returns** `200` with the *Carrier* object.

### POST /vendors

Creates a carrier or other vendor and assigns its `vendor_no`. New vendors start as `PENDING` until onboarding is complete; send `status: ACTIVE` to activate immediately. When `vendor_id` is omitted, it is generated from `legal_name` the same way as customer ids ("Acme Carrier Inc." → `ACMECARR`).

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `legal_name` | string | yes | Legal name. |
| `vendor_type` | string | yes | `TRUCKLOAD_CARRIER`, `LTL_CARRIER`, `CARTAGE_AGENT`, `EXPEDITE_CARRIER`, `AIRLINE`, `INSURANCE_VENDOR`, `LUMPER`, `OTHER`. |
| `vendor_id` | string | no | Explicit id, 2–24 characters of `A-Z`, `0-9`, `-`, `_` (uppercased). |
| `status` | string | no | `PENDING` (default), `ACTIVE`, `INACTIVE`, `DO_NOT_USE`. |
| `status_reason` | string | no | Required when `status` is `DO_NOT_USE`. |
| other fields | — | no | Any writable field of the *Carrier* object, with the defaults shown there. Read-only fields (`vendor_no`, `compliance_light`, `insurance[].insurance_status`, audit fields) are ignored. |

**Returns** `201` with the new *Carrier* object.

**Errors** `409` when the vendor id already exists; `422` for `DO_NOT_USE` without `status_reason`, an invalid id, an unknown enum value, an `insurance[].expiration_date` that is not `YYYY-MM-DD`, or a non-numeric number field.

### PUT /vendors/{vendor_id}

Updates a carrier, including status changes; there is no separate status route. Only the fields you send change; arrays and objects you send (such as `insurance`, `contacts` or `notes`) replace the stored value whole, and `null` clears an optional field. Read-only and unknown fields are ignored, so a record read with `GET` can be sent back unchanged.

**Path parameters**

| Name | Description |
|---|---|
| `vendor_id` | Vendor id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| any writable field | — | no | Any writable field of the *Carrier* object except `vendor_id`. |
| `status_reason` | string | no | Must be present (sent now or already stored) whenever the resulting `status` is `DO_NOT_USE`. |

**Returns** `200` with the updated *Carrier* object, compliance recalculated.

**Errors** `422` when the result would be `DO_NOT_USE` without a `status_reason`.

---

## Facilities

Facilities are shared records for the docks, warehouses, stores and plants your shipments pick up from and deliver to, holding their address, hours, appointment rules and an append-only feed of notes.

### Objects

#### Facility object

Fields marked read-only are ignored when sent.

| Field | Type | Required | Description |
|---|---|---|---|
| `facility_id` | string | no | Id, 2–24 characters of `A-Z`, `0-9`, `-`, `_`, uppercased (e.g. `BBR-DC135`). Set on create only; taken from `code` when omitted, else generated from `name`. |
| `code` | string | no | Facility code. Defaults to `facility_id`. |
| `name` | string | yes | Facility name. |
| `facility_type` | string | no | Facility type (see *Enums › Facility type*). Default `WAREHOUSE`. |
| `roles` | string | no | `SHIPPER`, `CONSIGNEE`, `BOTH` (default). A single value, not a list. |
| `parent_company` | string | no | Company that operates the facility. |
| `status` | string | no | `ACTIVE` (default), `INACTIVE`. |
| `address1` | string | no | Street address. |
| `address2` | string | no | Suite, unit or building. |
| `city` | string | yes | City. |
| `state` | string | yes | State or province code (e.g. `TX`). |
| `zip` | string | no | Postal code. |
| `country` | string | no | Country code. |
| `latitude` | number | no | Latitude. |
| `longitude` | number | no | Longitude. |
| `timezone` | string | no | IANA time zone, e.g. `America/Chicago`. Appointment windows at this facility are in this zone. |
| `external_codes` | object | no | Codes other parties use for this facility, keyed by party (e.g. `{"BBR": "DC135"}`). Default `{}`. |
| `operating_hours` | object | no | *Hours* object. |
| `receiving_hours` | object | no | *Hours* object for when the dock receives freight. |
| `dock_count` | number | no | Number of dock doors. |
| `first_come_first_served` | boolean | no | Arrivals are worked in order without appointments. Default `false`. |
| `avg_unload_minutes` | number | no | Typical unload time in minutes. |
| `driver_assist` | string | no | Unloading model: `NO_TOUCH`, `DRIVER_ASSIST`, `LUMPER`. |
| `appointment_required` | boolean | no | Pickups and deliveries need an appointment. Default `false`. |
| `scheduling_method` | string | no | How appointments are booked: `NONE_FCFS`, `PHONE`, `EMAIL`, `PORTAL`. On create, defaults to `NONE_FCFS` when `appointment_required` is not `true`. |
| `scheduling_phone` | string | no | Phone number for booking appointments. |
| `scheduling_email` | string | no | E-mail address for booking appointments. |
| `portal_vendor` | string | no | Scheduling portal provider (see *Enums › Portal vendor*). |
| `portal_url` | string | no | Scheduling portal address. |
| `portal_credentials_note` | string | no | Where to find the portal login. |
| `appointment_lead_time_hours` | number | no | Minimum notice, in hours, for booking an appointment. |
| `reschedule_policy_note` | string | no | Rules for rescheduling. |
| `appointment_grace_minutes` | number | no | Minutes late an arrival can be and keep its appointment. |
| `mabd_program` | boolean | no | The facility enforces must-arrive-by dates. Default `false`. |
| `mabd_program_note` | string | no | Details of the must-arrive-by program, such as chargebacks. |
| `lumper_policy` | string | no | `NONE`, `OPTIONAL`, `REQUIRED`. |
| `lumper_fee_min` | number | no | Typical minimum lumper fee in USD. |
| `lumper_fee_max` | number | no | Typical maximum lumper fee in USD. |
| `pallet_exchange` | string | no | `NONE`, `EXCHANGE_REQUIRED`, `CHEP`, `PECO`. |
| `compliance_flags` | array of string | no | Site rules drivers must follow (see *Enums › Compliance flag*). Default `[]`. |
| `special_instructions` | string | no | Free-text instructions for drivers. |
| `contacts` | array | no | *Contact* objects with facility roles. Default `[]`. |
| `notes` | array | read-only | *Note* objects, oldest first. Added only with `POST /facilities/{facility_id}/notes`. |
| `shipment_count` | number | read-only | Number of shipments that have used the facility. |
| `last_used_at` | datetime | read-only | When a shipment was last linked to the facility. |
| `created_at`, `updated_at` | datetime | read-only | Audit timestamps. |
| `created_by`, `updated_by` | string | read-only | Audit actor: the user's initials, or `API` for API-key calls. |

#### Hours object

Opening hours by day, in the facility's `timezone`. Keys are `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`; a missing or `null` day means closed.

| Field | Type | Required | Description |
|---|---|---|---|
| `<day>.open` | string | no | Opening time, `HH:MM` (24-hour). |
| `<day>.close` | string | no | Closing time, `HH:MM` (24-hour). |

#### Facility shipment object

One shipment that picks up or delivers at the facility, returned by `GET /facilities/{facility_id}/shipments`.

| Field | Type | Required | Description |
|---|---|---|---|
| `facility_id` | string | — | The facility. |
| `shipment_id` | string | — | The shipment. |
| `role` | string | — | `PICKUP` or `DELIVERY` (intermediate stops count as `DELIVERY`). |
| `lane` | string | — | Origin and destination, e.g. `Chicago, IL → Dallas, TX`. |
| `status` | string | — | The shipment's current status (see *Enums › Shipment status*). |
| `customer_id` | string | — | The shipment's customer. |
| `pickup_date` | date | — | The shipment's pickup date. |
| `date_shipment` | string | — | Ordering key, `{pickup_date}#{shipment_id}`. |

### GET /facilities

Lists facilities sorted by name, or resolves a partial name or code to a facility (for example `q=DC135` finds `BBR-DC135`).

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `q` | string | no | Case-insensitive search over `name`, `city` and `code`; every space-separated word must appear in one of them, anywhere in the text. |
| `city` | string | no | Exact city, case-insensitive. |
| `parent` | string | no | Exact `parent_company`. Use the stored capitalization. |
| `limit` | integer | no | Page size, default 50, maximum 200. Out-of-range values are clamped. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** `200` with a list of *Facility* objects.

**Errors** `422` for a non-integer `limit`.

### GET /facilities/{facility_id}

Returns one facility, including its appointment rules and notes.

**Path parameters**

| Name | Description |
|---|---|
| `facility_id` | Facility id, e.g. `BBR-DC135`. |

**Returns** `200` with the *Facility* object.

### POST /facilities

Creates a facility. Only `name`, `city` and `state` are required, so a partial record can be created from the details at hand and completed later. The id is `facility_id` if given, else `code`, else generated from `name` the same way as customer ids.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Facility name. |
| `city` | string | yes | City. |
| `state` | string | yes | State or province code. |
| `facility_id` | string | no | Explicit id, 2–24 characters of `A-Z`, `0-9`, `-`, `_` (uppercased). |
| `code` | string | no | Facility code; also used as the id when `facility_id` is omitted. |
| `timezone` | string | no | IANA time zone such as `America/Chicago`. |
| other fields | — | no | Any writable field of the *Facility* object, with the defaults shown there. Read-only fields (`notes`, `shipment_count`, `last_used_at`, audit fields) are ignored. |

**Returns** `201` with the new *Facility* object.

**Errors** `409` when the facility id already exists; `422` for an invalid id, a `timezone` that is not an IANA zone name (`Region/City`), an unknown enum value or a non-numeric number field.

### PUT /facilities/{facility_id}

Updates a facility. Only the fields you send change; arrays and objects you send (such as `contacts` or `receiving_hours`) replace the stored value whole, and `null` clears an optional field. `notes`, `shipment_count`, `last_used_at` and other read-only fields are ignored, so a record read with `GET` can be sent back unchanged.

**Path parameters**

| Name | Description |
|---|---|
| `facility_id` | Facility id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| any writable field | — | no | Any writable field of the *Facility* object except `facility_id`. |

**Returns** `200` with the updated *Facility* object.

**Errors** `422` for a `timezone` that is not an IANA zone name, an unknown enum value or a non-numeric number field.

### GET /facilities/{facility_id}/shipments

Lists the shipments that pick up or deliver at this facility, most recent pickup date first.

**Path parameters**

| Name | Description |
|---|---|
| `facility_id` | Facility id. |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `limit` | integer | no | Page size, default 50, maximum 200. Out-of-range values are clamped. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** `200` with a list of *Facility shipment* objects.

### POST /facilities/{facility_id}/notes

Appends a note to the facility's `notes` feed, for example a new dock rule or a change in lead time. The note is stamped with the caller as `author` and the current time; existing notes are never changed.

**Path parameters**

| Name | Description |
|---|---|
| `facility_id` | Facility id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Note text. Must not be blank. |

**Returns** `200` with the updated *Facility* object.

---

## Quotes

Quotes price a lane for a customer before anything is booked and convert into a shipment on the same file number once the customer agrees.

### Quote lifecycle

| Status | Meaning | Entered via |
|---|---|---|
| `DRAFT` | Created, not yet priced | `POST /quotes`, `POST /quotes/{quote_id}/clone` |
| `QUOTED` | Priced | `POST /quotes/{quote_id}/rate` or `POST /quotes/{quote_id}/price`, from `DRAFT`, `QUOTED` or `SENT` (re-pricing a `SENT` quote returns it to `QUOTED`) |
| `SENT` | Marked as sent to the customer | `POST /quotes/{quote_id}/send`, from `QUOTED` |
| `ACCEPTED` | Customer agreed to the price | `POST /quotes/{quote_id}/accept`, from `QUOTED` or `SENT` |
| `CONVERTED` | Booked as a shipment (terminal) | `POST /quotes/{quote_id}/book`, from `QUOTED`, `SENT` or `ACCEPTED` |
| `DECLINED` | Closed without booking (terminal) | `POST /quotes/{quote_id}/decline`, from `QUOTED`, `SENT` or `ACCEPTED` |

- Any other move returns `409` ("Quote cannot move from X to Y").
- **`EXPIRED` is computed, never stored.** A quote whose stored status is `DRAFT`, `QUOTED` or `SENT` and whose `valid_until` is before today (UTC) reads as `EXPIRED` on every read. An expired quote cannot be sent, accepted or booked (`409`); re-pricing it with `/rate` or `/price` makes it `QUOTED` again with a fresh `valid_until`. Edits, `/decline` and `/clone` still work on an expired quote. `ACCEPTED` quotes never expire.
- **Edit lock after acceptance.** `PUT /quotes/{quote_id}` works only while the stored status is `DRAFT`, `QUOTED` or `SENT`. Once a quote is `ACCEPTED`, `DECLINED` or `CONVERTED`, it can no longer be edited or re-priced (`409`); clone it to revise.

**Money.** Every quote carries two ledgers: `vendor_costs[]`, the buy side (what will be paid to carriers and other vendors, *Cost line* objects), and `customer_charges[]`, the sell side (what the customer is charged, *Charge line* objects). The server totals them into `buy_total` (excluding `CANCELLED` cost lines) and `sell_total`, with `gp_amount = sell_total − buy_total` and `gp_pct = gp_amount ÷ sell_total × 100` (one decimal; `null` when `sell_total` is 0), so GP is a margin of sell, not a markup on buy. `target_margin_pct` follows the same convention: a margined sell line is `buy ÷ (1 − target_margin_pct / 100)`, rounded half-up to cents.

**Pricing paths.** `/rate` prices the quote from the rates on file for its lane and mode. `/price` applies an externally priced buy side at a target margin, typically the `lines[]` returned by `POST /rate-engine/quotes`; `/price-preview` returns the same numbers without touching a quote.

**Summary.** Every quote read includes `summary`, a one-line, pipe-delimited description that carries the sell total only (never buy or GP), e.g. `Quote 7300201 | QUOTED | NORTHSTAR | TL TL_DRY_VAN V | Chicago, IL -> Dallas, TX | 925 mi | sell $3,411.28 | valid until 09/15/26`. Segments without data are omitted.

**Attribution.** Actions record the caller in `quoted_by`, `created_by`, `updated_by` and the `notes[]` trail: the user's initials for a signed-in user, `API` for API-key calls.

### Objects

In the object definitions below, `yes`/`no` in the Required column apply on input; `read-only` fields are computed by the server and ignored if sent.

#### Quote object

| Field | Type | Required | Description |
|---|---|---|---|
| `quote_id` | string | read-only | File number (numeric string, e.g. `7300174`). Quotes and shipments share one number sequence. |
| `status` | string | read-only | `DRAFT`, `QUOTED`, `SENT`, `ACCEPTED`, `DECLINED`, `CONVERTED`, or computed `EXPIRED`. Changed only by the action routes. |
| `summary` | string | read-only | One-line description, sell side only. |
| `customer_id` | string | yes | Customer the quote is for (e.g. `NORTHSTAR`). Cannot be changed after creation. |
| `contact` | object | no | Free-form contact details for this quote (e.g. `name`, `phone`), stored as sent. Default `{}`. |
| `mode` | string | yes | `TL`, `EXPEDITE` or `LTL`. |
| `service_level` | string | no | Must belong to `mode`; see *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `origin` | object | yes | *Quote location* object. |
| `destination` | object | yes | *Quote location* object. |
| `pickup_date` | date | no | Requested pickup date. |
| `delivery_date_target` | date | no | Target delivery date. |
| `transit_days_est` | integer | no | Estimated transit days, ≥ 0. |
| `miles` | number | no | Lane miles, > 0. Updated by `/rate` when it resolves miles. |
| `declared_value` | number | no | Declared cargo value, > 0. When set, pricing adds a sell-only `INSD` (cargo insurance) line. |
| `freight_lines` | array | no | *Freight line* objects. |
| `pieces` | integer | read-only | Total pieces. |
| `actual_lb` | number | read-only | Total actual weight (sum of line `weight_lb`). |
| `dim_weight_lb` | integer | read-only | Total dimensional weight. |
| `chargeable_lb` | integer | read-only | Greater of rounded-up `actual_lb` and `dim_weight_lb`. |
| `cubic_ft` | number | read-only | Total cube from line dimensions. |
| `density_pcf` | number | read-only | `actual_lb ÷ cubic_ft`; `null` without dimensions. |
| `pallet_positions` | integer | read-only | Estimated trailer floor positions for `PALLET`/`SKID` lines with dimensions. |
| `dim_factor_used` | integer | read-only | Dim factor applied: the customer's negotiated factor, else 194. |
| `vendor_costs` | array | no | Buy side: *Cost line* objects. |
| `customer_charges` | array | no | Sell side: *Charge line* objects. |
| `buy_total` | number | read-only | Sum of non-`CANCELLED` cost lines. |
| `sell_total` | number | read-only | Sum of charge lines. |
| `gp_amount` | number | read-only | `sell_total − buy_total`. |
| `gp_pct` | number | read-only | `gp_amount` as a percent of `sell_total`, one decimal; `null` when `sell_total` is 0. |
| `rate_source` | string | read-only | How the buy linehaul was priced: `SPOT` (market estimate), `CONTRACT` (tariff), `MANUAL` (hand-entered `FRT` cost line), `EXTERNAL` (`/price`); `null` until priced. |
| `target_margin_pct` | number | no | Target margin of sell, in percent (> 0 on create/update). Overwritten with the margin applied by `/rate` or `/price`. |
| `valid_until` | date | no | Last day the price is valid. Default: today + 7 days. |
| `salesperson_id` | string | no | Default: the customer's salesperson. |
| `quoted_by` | string | read-only | Who created the quote (or the clone). |
| `notes` | array | read-only | Activity trail, oldest first. Add entries with `note` on `PUT /quotes/{quote_id}`. |
| `notes[].author` | string | read-only | User initials, or `API`. |
| `notes[].timestamp` | datetime | read-only | When the entry was written. |
| `notes[].text` | string | read-only | E.g. `rated TL: buy $3,129.00 / sell $3,612.00 / GP 13.4%`. |
| `sent_at` | datetime | read-only | Set by `/send`. |
| `declined_reason` | string | read-only | Set by `/decline`. |
| `shipment_id` | string | read-only | Shipment created by `/book` (equal to `quote_id`). |
| `created_at`, `updated_at` | datetime | read-only | Creation and last-change times. |
| `created_by`, `updated_by` | string | read-only | Who created and last changed the quote. |

#### Quote location object

Used for a quote's `origin` and `destination`. A quote names a lane, not resolved stops; facilities and full addresses are supplied when the quote is booked.

| Field | Type | Required | Description |
|---|---|---|---|
| `city` | string | yes | City name. |
| `state` | string | yes | 2-letter state code (stored uppercase). |
| `zip` | string | no | Postal code. |
| `name` | string | no | Place or company name. |
| `facility_id` | string | no | Facility id if known (e.g. `BBR-DC135`); stored as sent, not checked. |

Other fields are dropped.

#### Freight line object

Shared by quotes and shipments. Dimensional fields are recomputed by the server on every write.

| Field | Type | Required | Description |
|---|---|---|---|
| `line_no` | integer | read-only | 1-based position of the line. |
| `pieces` | integer | yes | Handling units, ≥ 1. |
| `weight_lb` | number | yes | Total weight of the line in pounds (all pieces), > 0. |
| `package_type` | string | no | See *Enums › Package type*. |
| `description` | string | no | Commodity description. |
| `length_in` | number | no | Per-piece length in inches, > 0. Length, width and height are all needed for dimensional weight, cube and density. |
| `width_in` | number | no | Per-piece width in inches, > 0. |
| `height_in` | number | no | Per-piece height in inches, > 0. |
| `freight_class` | number | no | NMFC freight class; see *Enums › Freight class*. For LTL pricing it overrides the class derived from density; the highest class on the file governs. |
| `nmfc` | string | no | NMFC item number. |
| `hazmat` | boolean | no | Default `false`. |
| `dim_factor` | integer | read-only | Dim factor applied to this line. |
| `dim_weight_lb` | integer | read-only | `ceil(L × W × H ÷ dim_factor) × pieces`; 0 without all three dimensions. |
| `chargeable_lb` | integer | read-only | Greater of rounded-up `weight_lb` and `dim_weight_lb`. |

#### Charge line object

A sell-side line in `customer_charges[]`: an amount charged to the customer. Shared by quotes and shipments.

| Field | Type | Required | Description |
|---|---|---|---|
| `charge_id` | string | no | Line id. Generated when omitted; send it back unchanged to keep a line's id when replacing a whole ledger. |
| `charge_code` | string | yes | Charge code, stored uppercase (e.g. `FRT` linehaul, `FSC` fuel surcharge, `INSD` cargo insurance); see *Enums › Charge codes*. |
| `description` | string | no | Line description. |
| `rate_basis` | string | no | `FLAT` (default), `PER_MILE`, `PER_CWT`, `PER_LB`, `PER_HOUR`, `PCT_OF_FRT`, `PCT_OF_VALUE`. |
| `quantity` | number | no | Default 1. A count for `FLAT`, miles for `PER_MILE`, hundredweight for `PER_CWT`, pounds for `PER_LB`, hours for `PER_HOUR`; not used by the percentage bases. |
| `rate` | number | no | Default 0. Price per unit; for `PCT_OF_FRT` and `PCT_OF_VALUE`, the percentage. |
| `amount` | number | no | Line total. When omitted, `quantity × rate`, rounded half-up to cents. Quote lines with a percentage basis must include `amount`; on shipments it is computed from the same ledger's `FRT` lines (`PCT_OF_FRT`) or the declared value (`PCT_OF_VALUE`). |
| `status` | string | no | `ESTIMATED` (default), `APPROVED`. |
| `auto_flag` | boolean | no | `true` on lines generated by pricing. Default `false`. On a quote, lines with `auto_flag: true` and `override_flag: false` are replaced by the next `/rate` or `/price`; all other lines are kept. |
| `override_flag` | boolean | no | `true` when the amount was set by hand; keeps a generated line from being replaced. Default `false`. |
| `minimum` | number | no | Shipments only: floor applied when the server computes `amount`. Ignored on quote lines. |

#### Cost line object

A buy-side line in `vendor_costs[]`: an amount to be paid to a carrier or other vendor. Shared by quotes and shipments.

| Field | Type | Required | Description |
|---|---|---|---|
| `cost_id` | string | no | Line id. Generated when omitted; send it back unchanged to keep a line's id when replacing a whole ledger. |
| `vendor_id` | string | no | Vendor (carrier) to be paid (e.g. `ACMECARR`). `null` on market estimates priced before a carrier is chosen. Required when adding a cost line to a shipment. |
| `charge_code` | string | yes | As on *Charge line*. |
| `description` | string | no | Line description. |
| `rate_basis` | string | no | As on *Charge line*; default `FLAT`. |
| `quantity` | number | no | As on *Charge line*; default 1. |
| `rate` | number | no | As on *Charge line*; default 0. |
| `amount` | number | no | As on *Charge line*. |
| `status` | string | no | `ESTIMATED` (default), `CONFIRMED`, `CANCELLED`. `CANCELLED` lines stay on the file but are excluded from `buy_total`. |
| `auto_flag` | boolean | no | As on *Charge line*. |
| `override_flag` | boolean | no | As on *Charge line*. |
| `minimum` | number | no | As on *Charge line* (shipments only). |

### GET /quotes

Lists quotes as *Quote* objects, each with its computed `status` and `summary`.

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `DRAFT`, `QUOTED`, `SENT`, `ACCEPTED`, `DECLINED`, `CONVERTED` or `EXPIRED`. Matches the status as read, so `QUOTED` excludes quotes that now read `EXPIRED`. |
| `customer` | string | no | Customer id. |
| `from` | date | no | Earliest creation date, inclusive. |
| `to` | date | no | Latest creation date, inclusive. |
| `limit` | integer | no | Page size, 1–200. Default 50. |
| `cursor` | string | no | The `next_cursor` value from the previous response; omit for the first page. |

Ordering and paging:

- With `customer`: newest first, paged with `cursor`.
- With `status` and no `customer`: ordered by `valid_until`, earliest first, paged with `cursor`. `status=EXPIRED` returns every expired quote in one response (`limit` is not applied; `next_cursor` is `null`).
- With neither: the newest `limit` quotes as a single page (`next_cursor` is always `null`).
- The computed-status match, and `from`/`to` when `customer` is absent, are applied after a page is read, so a page can hold fewer than `limit` items (even none) while `next_cursor` is still set. Keep requesting until `next_cursor` is `null`.

**Returns** `200` — `{items, count, next_cursor}`: an array of *Quote* objects, the number of items in this page, and the cursor for the next page (`null` when there are no more).

**Errors** `400` for an unrecognized `cursor`.

### GET /quotes/{quote_id}

Returns one quote; `status` reads `EXPIRED` when the quote's validity has passed.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Returns** `200` — the *Quote* object.

### POST /quotes

Creates a `DRAFT` quote on a new file number, which is immediately resolvable through `GET /search`. The server computes freight and money totals; money lines are stored as sent and no pricing runs (call `/rate` or `/price` next).

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | yes | Id of an existing customer. |
| `mode` | string | yes | `TL`, `EXPEDITE` or `LTL`. |
| `origin` | object | yes | *Quote location* object (`city` and 2-letter `state` required). |
| `destination` | object | yes | *Quote location* object. |
| `service_level` | string | no | Must belong to `mode`; see *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `freight_lines` | array | no | *Freight line* objects. Needed before `/rate` can price `EXPEDITE` or `LTL`, and before booking (unless supplied at booking). |
| `vendor_costs` | array | no | Hand-entered *Cost line* objects. An `FRT` cost line here is kept by `/rate` as the buy linehaul. |
| `customer_charges` | array | no | Hand-entered *Charge line* objects. |
| `pickup_date` | date | no | Requested pickup date. |
| `delivery_date_target` | date | no | Target delivery date. |
| `valid_until` | date | no | Default: today + 7 days. |
| `miles` | number | no | > 0. |
| `declared_value` | number | no | > 0. |
| `target_margin_pct` | number | no | > 0. Stored for reference; `/rate` and `/price` take the margin from their own request. |
| `transit_days_est` | integer | no | ≥ 0. |
| `salesperson_id` | string | no | Default: the customer's salesperson. |
| `contact` | object | no | Free-form contact details; default `{}`. |

Read-only *Quote* fields are ignored.

**Returns** `201` — the new *Quote* object.

**Errors** `422` when `customer_id` is not an existing customer, or when a percentage-basis money line has no `amount`.

### PUT /quotes/{quote_id}

Updates a quote's header, lane, freight and hand-entered money lines; the server recomputes freight and money totals. The status does not change and no pricing runs, so call `/rate` or `/price` after changing the lane or freight. Allowed while the stored status is `DRAFT`, `QUOTED` or `SENT`, including quotes that read `EXPIRED`.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Body**

Send only the fields to change. Objects and arrays replace the stored value as a whole.

| Field | Type | Required | Description |
|---|---|---|---|
| `mode` | string | no | `TL`, `EXPEDITE` or `LTL`. When changing the mode, also send a matching `service_level` (or `null`). |
| `service_level` | string | no | Checked against the resulting `mode`; see *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `origin` | object | no | Complete *Quote location* object. |
| `destination` | object | no | Complete *Quote location* object. |
| `freight_lines` | array | no | Replaces all *Freight line* objects. |
| `vendor_costs` | array | no | Replaces the whole buy ledger (*Cost line* objects). |
| `customer_charges` | array | no | Replaces the whole sell ledger (*Charge line* objects). |
| `pickup_date` | date | no | `null` clears. |
| `delivery_date_target` | date | no | `null` clears. |
| `valid_until` | date | no | `null` clears (a quote without `valid_until` never expires). |
| `miles` | number | no | > 0; `null` clears. |
| `declared_value` | number | no | > 0; `null` clears. |
| `target_margin_pct` | number | no | > 0; `null` clears. |
| `transit_days_est` | integer | no | ≥ 0; `null` clears. |
| `salesperson_id` | string | no | Stored as sent. |
| `contact` | object | no | Stored as sent. |
| `note` | string | no | Appends an entry to `notes[]`. |

`customer_id` and read-only fields are ignored.

**Returns** `200` — the updated *Quote* object.

**Errors** `409` when the stored status is `ACCEPTED`, `DECLINED` or `CONVERTED` ("… locked for edits; clone it to revise").

### POST /quotes/{quote_id}/rate

Prices the quote from the rates on file and moves it to `QUOTED`. Generated money lines are rebuilt, hand-entered and overridden lines are kept, totals are recomputed (freight with the customer's dim factor), `rate_source` and `target_margin_pct` are set, and a note with buy, sell and GP is appended.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Body**

All fields optional; an empty body is valid.

| Field | Type | Required | Description |
|---|---|---|---|
| `target_margin_pct` | number | no | Margin of sell for margined lines, 0 ≤ x < 100. Default: the customer's `margin_floor_pct`, else 18. The quote's stored `target_margin_pct` is not used as a default. |
| `miles` | number | no | > 0. Default: the quote's `miles`, else the lane's default mileage. Stored on the quote. |
| `valid_until` | date | no | New validity date. When omitted, an expired quote gets today + 7 days; otherwise `valid_until` is unchanged. |

How each mode prices (lanes without their own rates use the mode's default rates):

- **TL** — buy `FRT` is the lane's market estimate as one `FLAT` line with no vendor (`rate_source: SPOT`). Buy `FSC` is the current per-mile fuel surcharge × miles (`PER_MILE`; miles are required). Sell `FRT` = buy `FRT` ÷ (1 − margin); sell `FSC` equals the buy `FSC` with no margin, so `gp_pct` lands slightly under the target.
- **EXPEDITE** — buy `FRT` is priced per pound at `chargeable_lb` from the lane's weight breaks (`MIN`, 100, 500, 1000, 2000 lb; the highest break at or below the weight applies), floored at the break's minimum charge (`CONTRACT`). Sell `FRT` = buy `FRT` ÷ (1 − margin). `FSC` on each side is the current fuel percentage of that side's `FRT`. Requires freight lines with weight.
- **LTL** — the freight class comes from density, or from the highest explicit `freight_class`. `FRT` = hundredweight × the class base rate × (1 − discount), floored at the class minimum, with a deeper discount on the buy side than on the sell side (defaults 72% buy, 62% sell; the customer's negotiated discount overrides) (`CONTRACT`). The target margin does not affect LTL sell. `FSC` on each side is the current fuel percentage of that side's `FRT`. Requires weight, plus dimensions or a `freight_class`.
- **All modes** — when the quote has `declared_value`, a sell-only `INSD` line at the `INSD` charge code's default percentage of declared value (minimum $25.00).
- **Generated and kept lines** — lines with `auto_flag: true` and `override_flag: false` are rebuilt; all other lines are kept, and their charge codes are not generated again. A kept `FRT` cost line is used as the buy linehaul and sets `rate_source: MANUAL`. Lines are ordered `FRT`, `FSC`, then accessorials.

**Returns** `200` — the priced *Quote* object.

**Errors** `409` when the stored status is `ACCEPTED`, `DECLINED` or `CONVERTED`, or when no rate is on file for the lane (TL without a hand-entered `FRT` cost line, missing EXPEDITE weight breaks, or no LTL rate for the class); `422` when TL miles cannot be resolved, EXPEDITE or LTL freight weight, dimensions or class are missing, or `target_margin_pct` is out of range.

### POST /quotes/price-preview

Computes the sell lines and totals that `POST /quotes/{quote_id}/price` would produce for the given buy lines and margin, without a quote: nothing is created or changed. The result matches `/price` to the cent for a quote with the same `declared_value` and no hand-entered or overridden lines.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `buy_lines` | array | yes | Non-empty array of buy lines, typically the `lines[]` returned by `POST /rate-engine/quotes`, passed as is. Each line takes the *Cost line* input fields (`charge_code`, `description`, `rate_basis`, `quantity`, `rate`, `amount`); percentage-basis lines need `amount`. |
| `target_margin_pct` | number | yes | Margin of sell, 0 ≤ x < 100. |
| `declared_value` | number | no | ≥ 0. When greater than 0, adds a sell-only `INSD` line (the `INSD` charge code's default percentage, minimum $25.00). |

Sell lines follow the rules of `POST /quotes/{quote_id}/price`.

**Returns** `200` — `{customer_charges, buy_total, sell_total, gp_amount, gp_pct}`; each `customer_charges` item carries only `charge_code`, `description`, `rate_basis`, `quantity`, `rate` and `amount` (no ids or flags), and `gp_pct` has one decimal.

### POST /quotes/{quote_id}/price

Applies an externally priced buy side at a target margin, derives the sell side, and moves the quote to `QUOTED` with `rate_source: EXTERNAL`. Validity is always refreshed, so an expired quote can be priced. A note with buy, sell, GP and `rate_ref` is appended.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `buy_lines` | array | yes | Non-empty array of buy lines, typically the `lines[]` returned by `POST /rate-engine/quotes`, passed as is. Each line takes the *Cost line* input fields; percentage-basis lines need `amount`. |
| `target_margin_pct` | number | yes | Margin of sell, 0 ≤ x < 100. |
| `valid_until` | date | no | Default: today + 7 days. |
| `rate_ref` | string | no | Reference for the external rate (e.g. the rate engine's `rate_id`); recorded in the note only. |

Buy side:

- The supplied lines become cost lines with `auto_flag: false` and `override_flag: false`, so they are treated as hand-entered: a later `/rate` keeps them and reports `rate_source: MANUAL`. `vendor_id` stays `null` unless supplied.
- Generated cost lines from an earlier `/rate` are dropped. Hand-entered or overridden cost lines are kept unless a supplied line has the same charge code, so re-pricing replaces `FRT`/`FSC` instead of stacking them.

Sell side (generated charge lines are rebuilt; hand-entered or overridden charge lines are kept and suppress derivation for their codes):

- `FRT` — one `FLAT` line "Linehaul" at buy ÷ (1 − margin).
- `FSC` with `PCT_OF_FRT` — the same percentage applied to the sell `FRT` (blended GP equals the target).
- `FSC` with any other basis — identical to the buy line, with no margin (blended `gp_pct` lands under the target).
- Any other code — one `FLAT` line at buy ÷ (1 − margin) with the buy line's description.
- One sell line per charge code (the first supplied line with that code).
- When the quote has `declared_value`, a sell-only `INSD` line is added.

**Returns** `200` — the priced *Quote* object.

**Errors** `409` when the stored status is `ACCEPTED`, `DECLINED` or `CONVERTED`.

### POST /quotes/{quote_id}/send

Records that a `QUOTED` quote was sent to the customer: status becomes `SENT`, `sent_at` is stamped and a note is appended. Nothing is transmitted to the customer. No body.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Returns** `200` — the updated *Quote* object.

**Errors** `409` unless the quote reads `QUOTED`, including when it has expired ("… expired on {date} — cannot send; re-rate to refresh pricing").

### POST /quotes/{quote_id}/accept

Records the customer's acceptance from `QUOTED` or `SENT`: status becomes `ACCEPTED` and a note is appended. The price is then locked against edits and re-pricing; clone the quote to revise it. No body.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Returns** `200` — the updated *Quote* object.

**Errors** `409` from any other status, or when the quote has expired.

### POST /quotes/{quote_id}/decline

Closes the quote as `DECLINED` (terminal), stores `declined_reason` and appends a note. Allowed from `QUOTED`, `SENT` or `ACCEPTED`, including a quote that reads `EXPIRED`.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `reason` | string | no | Free-text reason, stored as `declined_reason`. |

**Returns** `200` — the updated *Quote* object.

**Errors** `409` when the stored status is `DRAFT`, `DECLINED` or `CONVERTED`.

### POST /quotes/{quote_id}/clone

Copies a quote to a new `DRAFT` on a new file number; works from any status, including expired, declined and converted quotes, and leaves the source unchanged. The copy keeps the customer, contact, mode, service level, equipment, lane, dates, transit days, miles, freight lines and totals, both money ledgers, `rate_source`, `target_margin_pct`, `declared_value` and salesperson. Money lines get new ids, status `ESTIMATED`; `valid_until` is today + 7 days, `quoted_by` is the caller, and `notes` restarts with "created by cloning {quote_id}". No body.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote to copy. |

**Returns** `201` — the new *Quote* object.

### POST /quotes/{quote_id}/book

Converts the quote into a shipment on the same file number (`shipment_id` equals `quote_id`). The body supplies the stops; mode, service level, equipment, freight lines and both money ledgers come from the quote, with money-line statuses reset to `ESTIMATED`. The shipment is created `BOOKED` and the quote becomes `CONVERTED` with `shipment_id` set.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | File number of the quote. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `stops` | array | yes | At least 2 ordered *Stop* objects, each with a `facility_id` or a full address. Not compared with the quote's origin and destination. |
| `freight_terms` | string | no | `PREPAID` (default), `COLLECT`, `THIRD_PARTY`. |
| `references` | array | no | Header references as `{type, value}` objects, as on `POST /shipments`. |
| `customer_id` | string | no | Default: the quote's customer. Normally omitted. |
| `miles` | number | no | Default: the quote's `miles`. |
| `transit_days_est` | integer | no | Default: the quote's value. |
| `declared_value` | number | no | Default: the quote's value. Does not reprice the copied `INSD` line. |
| `salesperson_id` | string | no | Default: the quote's salesperson. |
| `pickup_date` | date | no | Used only when the first stop has no `scheduled_window`. Default: the quote's `pickup_date`. |
| `delivery_date_target` | date | no | Used only when the last stop has no `scheduled_window`. Default: the quote's value. |
| `service_level` | string | no | Used only when the quote has none. |
| `equipment_type` | string | no | Used only when the quote has none. |
| `freight_lines` | array | no | *Freight line* objects, used only when the quote has none (at least one line is required to book). |
| `account_manager_id` | string | no | Default: the customer's account manager. |
| `station` | string | no | Default: the customer's station. |
| `insurance_type` | string | no | Shipment header field. |
| `special_instructions` | string | no | Shipment header field. |
| `internal_notes` | string | no | Shipment header field. |
| `track_owner` | string | no | Shipment header field. |

`vendor_costs` and `customer_charges` in the body are ignored; the money lines always come from the quote.

**Returns** `201` — the created *Shipment* object, including `summary`.

**Errors** `409` when the stored status is not `QUOTED`, `SENT` or `ACCEPTED`, when the quote has expired; `422` listing stop problems per stop, or when no freight line is available. The quote is unchanged when booking fails.

---

## Rate engine

The rate engine returns a market-rate buy side (carrier cost) for a lane without creating or changing any record.

### POST /rate-engine/quotes

Prices one lane at market rates and returns the buy-side money lines. Its `lines[]` are exactly the money-line input shape for `POST /quotes/{quote_id}/price` and `POST /quotes/price-preview` — pass them unchanged as `buy_lines`. Results are deterministic for the same lane, mode and pickup date; when no rate exists for the specific state pair, the mode's default market rate is used, and `market_context` is a reference band only — always price from `lines[]`.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `mode` | string | yes | `TL` (flat lane rate + per-mile fuel), `EXPEDITE` (per-lb weight-break rate on chargeable weight + % fuel), or `LTL` (per-cwt class rate on actual weight + % fuel). |
| `origin` | object | yes | Origin location. |
| `origin.state` | string | yes | 2-letter state code (case-insensitive). The lane is `{origin.state}-{destination.state}`. |
| `origin.city` | string | no | Accepted; not used for pricing. |
| `origin.zip` | string | no | Accepted; not used for pricing. |
| `destination` | object | yes | Destination location. |
| `destination.state` | string | yes | 2-letter state code (case-insensitive). |
| `destination.city` | string | no | Accepted; not used for pricing. |
| `destination.zip` | string | no | Accepted; not used for pricing. |
| `pickup_date` | date | no | Anchors `rate_id` and `market_context`. Default: today (UTC). |
| `miles` | number | no | Lane miles, greater than 0. Default: the lane's standard mileage. TL needs miles from one of the two sources. |
| `service_level` | string | no | Must belong to `mode` (see *Enums › Service level*). Validated only; does not change the price. |
| `equipment_type` | string | no | See *Enums › Equipment type*. Validated only; does not change the price. |
| `freight_lines` | array | EXPEDITE, LTL | Freight being shipped. Optional for TL. |
| `freight_lines.pieces` | integer | yes | Piece count, at least 1. |
| `freight_lines.weight_lb` | number | yes | Total weight of the line in pounds, greater than 0. |
| `freight_lines.length_in` | number | no | Per-piece length in inches. Dimensions drive dim weight (factor 194) and LTL density. |
| `freight_lines.width_in` | number | no | Per-piece width in inches. |
| `freight_lines.height_in` | number | no | Per-piece height in inches. |
| `freight_lines.package_type` | string | no | See *Enums › Package type*. |
| `freight_lines.freight_class` | number | no | NMFC class (see *Enums › Freight class*). For LTL, the highest explicit class overrides the density-derived class. |
| `freight_lines.description` | string | no | Accepted; not used for pricing. |
| `freight_lines.hazmat` | boolean | no | Accepted; not used for pricing. Default `false`. |
| `freight_lines.nmfc` | string | no | Accepted; not used for pricing. |
| `accessorials` | array | no | Charge codes (strings, case-insensitive) added to the buy at their catalog default rate and basis (see *Enums › Charge codes*); per-mile codes use `miles`, per-cwt actual weight, per-lb chargeable weight, percentage-of-freight codes the `FRT` line amount, and all others a quantity of 1. |

**Returns** — `200` — `{rate_id, generated_at, valid_for_hours, mode, lane, miles, chargeable_lb, freight_class, transit_days_est, buy_total, lines, market_context}`: `valid_for_hours` is 24; `chargeable_lb` is `null` without freight lines; `freight_class` is set for LTL only; `transit_days_est` is a planning estimate from miles (`null` without miles); each of `lines[]` is `{charge_code, description, rate_basis, quantity, rate, amount}` (an `FRT` line, an `FSC` line, then any accessorials); `buy_total` is the sum of line amounts; `market_context` is `{low, target, high, sample_size, trend_pct_wk, source}` with `target` equal to `buy_total`.

**Errors** — `409` when no market rate exists for the lane (or, for LTL, the freight class) and no default rate exists for the mode; `422` when EXPEDITE or LTL has no weighted freight lines, LTL has neither dimensions nor an explicit `freight_class`, TL has no miles and the lane has no standard mileage, or an accessorial code is unknown or cannot be priced by the engine (`FRT`, `FSC`, `INSD` — add those on the quote instead).

---

## Shipments

A shipment is a booked load: its stops, freight, carrier, buy and sell money lines, milestones and proof of delivery, plus an append-only activity log.

### Status lifecycle

**Operational status** (`status`) moves forward along one chain:

`BOOKED` → `COVERED` → `DISPATCHED` → `AT_PICKUP` → `PICKED_UP` → `IN_TRANSIT` → `AT_DELIVERY` → `DELIVERED` → `POD_RECEIVED` → `CLOSED`

`ON_HOLD` is a side state reachable from any open status; it remembers the status it left (`held_from`). `CLOSED`, `CANCELLED` and `TONU` are terminal: no further status changes are possible.

| Status | Set by |
|---|---|
| `BOOKED` | `POST /shipments` or `POST /quotes/{quote_id}/book`; back to `BOOKED` via `POST /shipments/{shipment_id}/uncover` |
| `COVERED` | `POST /shipments/{shipment_id}/cover` |
| `DISPATCHED` | `POST /shipments/{shipment_id}/dispatch` |
| `AT_PICKUP` … `DELIVERED`, `ON_HOLD` and hold release | `POST /shipments/{shipment_id}/status` |
| `POD_RECEIVED` | `POST /shipments/{shipment_id}/pod` |
| `CLOSED` | `POST /shipments/{shipment_id}/close` |
| `CANCELLED`, `TONU` | `POST /shipments/{shipment_id}/cancel` |

| Gate | Route | Rule | On failure |
|---|---|---|---|
| Carrier compliance | `/cover` | Shipment is `BOOKED`; carrier status is `ACTIVE` and it has `CARGO` insurance that has not expired; `LTL` also needs a `pro_number`. | `409` |
| Rate confirmation before dispatch | `/dispatch` | Shipment is `COVERED`. `TL`/`EXPEDITE`: a rate confirmation generated for the current carrier (`POST /shipments/{shipment_id}/documents/generate`), `driver_name` and `driver_phone`. `LTL`: `pro_number`. | `409` listing every missing item |
| Status transitions | `/status` | Forward only, one or two steps; statuses owned by other routes are refused; terminal shipments are frozen. | `409` |
| Appointment / MABD | `/stops/{stop_seq}/appointment` | A window ending after the stop's `mabd_date` (end of day) needs `acknowledge_mabd: true`. | `409` |
| ON_HOLD | `/status` | Release returns only to `held_from`. A held shipment cannot take a POD but can be cancelled. | `409` |
| POD before close | `/close` | Shipment is `POD_RECEIVED`, which only `/pod` sets. | `409` |
| Cancel / TONU | `/cancel` | Only before `DELIVERED` (for a held shipment, checked against `held_from`). | `409` |
| Money lines frozen | `/charges`, `/costs` | Once `CLOSED`, charge and cost lines cannot be added or edited. | `409` |

**Timestamps.** System-generated times (`created_at`, `updated_at`, `status_updated_at`, `entered_at`, default `next_tracking_at`) are UTC (`2026-07-08T13:05:00Z`). Stop scheduling data is facility-local: `scheduled_window` bounds and POD `delivered_at_local` are local datetimes (`2026-07-08T08:00:00`) paired with an IANA time zone, and `mabd_date` is a local date. The server converts event times into the stop's zone before comparing them with windows and MABD. Events and milestones carry two times: `event_at` is when it happened (supplied by you, back-dating is allowed; send UTC, or a local datetime plus `event_timezone`; defaults to now) and `entered_at` is when it was recorded (always the server clock).

### Objects

#### Shipment object

Returned by every shipment route except `POST /shipments/{shipment_id}/notes` and `GET /shipments/{shipment_id}/events`. Fields without a value can be `null` or absent. Fields marked read-only are computed or set by action routes, and are ignored or refused when sent to `PUT /shipments/{shipment_id}`.

| Field | Type | Required | Description |
|---|---|---|---|
| `shipment_id` | string | read-only | File number (e.g. `7300174`). Quotes and shipments share one number sequence; a shipment booked from a quote keeps the quote's number. |
| `quote_id` | string | read-only | Source quote, when booked from one. |
| `status` | string | read-only | Operational status. See *Enums › Shipment status*. |
| `status_updated_at`, `status_updated_by` | datetime, string | read-only | Last status change and who made it. |
| `held_from`, `hold_reason` | string | read-only | Set while `ON_HOLD`: the status to return to and the hold reason. |
| `cancel_reason` | string | read-only | Set by `/cancel`. |
| `mode` | string | yes | `TL`, `EXPEDITE`, `LTL`. Fixed after booking. |
| `service_level` | string | no | Must belong to the mode. See *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `customer_id` | string | yes | Customer that owns the shipment. Fixed after booking. |
| `freight_terms` | string | no | `PREPAID` (default), `COLLECT`, `THIRD_PARTY`. |
| `miles` | number | no | Lane miles. |
| `transit_days_est` | integer | no | Estimated transit days. |
| `declared_value` | number | no | Declared cargo value in USD; base for `PCT_OF_VALUE` money lines. |
| `insurance_type` | string | no | Free text. |
| `salesperson_id`, `account_manager_id` | string | no | User ids. `account_manager_id` defaults from the customer. |
| `station` | string | no | Owning office code. Defaults from the customer. |
| `special_instructions` | string | no | Shipment-level instructions. |
| `internal_notes` | string | no | Free-text internal notes panel (separate from the activity log). Default `""`. |
| `track_owner` | string | no | User responsible for tracking. |
| `stops` | array | yes | *Stop* objects, ordered by `stop_seq`. |
| `pickup_date` | date | read-only | Date of stop 1's `earliest_local`. |
| `delivery_date_target` | date | read-only | Date of the last stop's `earliest_local`. |
| `shipper_name`, `shipper_city`, `shipper_state` | string | read-only | From stop 1's address. |
| `consignee_name`, `consignee_city`, `consignee_state` | string | read-only | From the last stop's address. |
| `freight_lines` | array | yes | *Freight line* objects. |
| `freight_totals` | object | read-only | Totals across freight lines: `pieces`, `actual_lb`, `dim_weight_lb`, `chargeable_lb`, `cubic_ft`, `density_pcf`, `pallet_positions`, `dim_factor_used`. |
| `dim_factor_used` | integer | read-only | Dimensional factor: the customer's `default_dim_factor`, else `194`. |
| `carrier_id` | string | read-only | Assigned carrier (vendor id). Set by `/cover`, cleared by `/uncover`. |
| `carrier_contact`, `driver_name`, `driver_phone`, `truck_number`, `trailer_number` | string | read-only | Carrier details, set by `/cover` and `/dispatch`. |
| `pro_number` | string | read-only | Carrier PRO number. |
| `target_pay_min`, `target_pay_max` | number | read-only | Target carrier pay range, set by `/cover`. |
| `rate_con_number` | string | read-only | Current rate confirmation number, `RC-{shipment_id}-{revision}`. |
| `rate_con_rev` | integer | read-only | Rate confirmation revision count. |
| `rate_con_doc_id` | string | read-only | Document id of the current carrier's rate confirmation; required for `TL`/`EXPEDITE` dispatch. |
| `vendor_costs` | array | read-only | *Cost line* objects (buy). Change them with the `/costs` routes. |
| `customer_charges` | array | read-only | *Charge line* objects (sell). Change them with the `/charges` routes. |
| `buy_total` | number | read-only | Sum of cost lines that are not `CANCELLED`. |
| `sell_total` | number | read-only | Sum of charge lines. |
| `gp_amount` | number | read-only | `sell_total - buy_total`. |
| `gp_pct` | number | read-only | `gp_amount / sell_total × 100`, one decimal; `null` when `sell_total` is 0. |
| `milestones` | array | read-only | *Milestone* objects from the mode's template. |
| `next_tracking_at` | datetime | no | When the shipment is next due for a check call (UTC). Drives the tracking queue. |
| `pod` | object | read-only | *POD* object; `{"received": false}` until `/pod`. |
| `service_failure` | boolean | read-only | `true` when delivery was later than the delivery deadline (the earlier of the last delivery stop's window end and MABD end of day). |
| `service_failure_reason` | string | read-only | Late reason code, `LATE` when none was given. |
| `references` | array | no | *Reference* objects. Includes stop references and server-added numbers. |
| `summary` | string | read-only | One-line summary: `{shipment_id} {status} \| {customer_id}: {origin city},{ST} → {destination city},{ST} \| PU {MM/DD HH:MM-HH:MM TZ} \| DEL {MM/DD HH:MM-HH:MM TZ} (MABD {MM/DD}) \| {carrier_id} \| appt {status} #{confirmation}`. Segments are omitted when data is missing. Times are facility-local, with `ET`, `CT`, `MT`, `PT`, `AKT` or `HT` (other zones show the city part of the IANA name). Not included in `GET /shipments` rows. |
| `created_at`, `updated_at` | datetime | read-only | Audit timestamps. |
| `created_by`, `updated_by` | string | read-only | Audit actor: the user's initials, or `API` for API-key calls. |

#### Stop object

| Field | Type | Required | Description |
|---|---|---|---|
| `stop_seq` | integer | no | 1-based position. Defaults to the array position; must be unique. |
| `stop_type` | string | no | `PICKUP`, `DELIVERY`, `INTERMEDIATE`. Defaults to `PICKUP` for the first stop, `DELIVERY` for the last and `INTERMEDIATE` in between. |
| `facility_id` | string | conditional | Facility to use (e.g. `BBR-DC135`). Its address is copied into `address_snapshot`, so later facility edits don't change the shipment. Send either `facility_id` or a full `address_snapshot`; when both are sent, the facility wins. |
| `address_snapshot` | object | conditional | *Address snapshot* object. Required when `facility_id` is not sent. `address` is accepted as an alias. |
| `scheduled_window` | object | no | *Scheduled window* object. |
| `mabd_date` | date | no | Must-arrive-by date, facility-local. Checked by the appointment route and used for service-failure checks. |
| `appointment` | object | no | *Appointment* object. `status` defaults to `NEEDED` when the facility requires appointments, else `NOT_REQUIRED`. |
| `references` | array | no | *Reference* objects for this stop (PO, pickup number, …). Also copied to the shipment's `references`. |
| `instructions` | string | no | Stop-level instructions. |
| `actual_arrival`, `actual_departure` | datetime | no | Stored as sent; status changes do not set them. |

#### Address snapshot object

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Location name. |
| `address1` | string | yes | Street address. |
| `city` | string | yes | City. |
| `state` | string | yes | State or province code. |
| `zip` | string | yes | Postal code. |
| `timezone` | string | yes | IANA time zone (e.g. `America/Chicago`). |

All fields are required when the address is sent explicitly. When the stop uses `facility_id`, the snapshot is copied from the facility and is read-only.

#### Scheduled window object

| Field | Type | Required | Description |
|---|---|---|---|
| `earliest_local` | local datetime | yes | Window start, facility-local. |
| `latest_local` | local datetime | yes | Window end, facility-local; must not be before `earliest_local`. |
| `timezone` | string | no | IANA zone. Defaults to the stop's existing window zone or the address snapshot's zone. |

#### Appointment object

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `NOT_REQUIRED`, `NEEDED`, `REQUESTED`, `CONFIRMED`, `RESCHEDULED`, `MISSED`. |
| `confirmation_number` | string | no | Facility's appointment number. |
| `method_used` | string | no | How it was booked (e.g. `PHONE`, `EMAIL`, `PORTAL`). |
| `portal_ref` | string | no | Scheduling portal reference. |
| `scheduled_by` | string | no | Who booked it. The appointment route defaults it to the caller. |

#### Reference object

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | no | See *Enums › Reference type*. Case-insensitive; default `OTHER`. |
| `value` | string | yes | Non-empty reference value (e.g. `PO-944464`). |

References are searchable through `GET /search`. The server adds its own: `SHIPMENT` (the file number) at booking, `PRO` from cover or dispatch, `PU_NUMBER` or `DELIVERY_NUMBER` from appointment confirmations, and `RATE_CON` when a rate confirmation is generated. References are only ever added.

#### Milestone object

| Field | Type | Required | Description |
|---|---|---|---|
| `milestone_code` | string | read-only | See *Enums › Milestone codes*. |
| `label` | string | read-only | Display label (e.g. `Carrier Assigned`). |
| `sequence` | integer | read-only | Order in the mode's template. |
| `complete` | boolean | read-only | Whether the milestone has happened. |
| `event_at` | datetime | read-only | When it happened. |
| `event_timezone` | string | read-only | IANA zone of a local `event_at`. |
| `entered_at` | datetime | read-only | When it was recorded. |
| `entered_by` | string | read-only | Who recorded it. |
| `source` | string | read-only | `AUTO` (completed by a lifecycle route) or `MANUAL` (`PUT …/milestones/{code}`). |

Lifecycle routes complete milestones automatically: booking → `NEW`; `/cover` → `COVERED` (`LTL`: `TENDERED_TO_CARRIER`); rate confirmation generated → `RATE_CON_SENT` (`TL`/`EXPEDITE`); `/dispatch` → `DISPATCHED` (`TL`/`EXPEDITE`); `AT_PICKUP` → `AT_SHIPPER`; `PICKED_UP` → `LOADED` (`LTL`: `PICKED_UP`); `IN_TRANSIT` → `IN_TRANSIT`; `AT_DELIVERY` → `AT_CONSIGNEE` (`LTL`: `OUT_FOR_DELIVERY`); `DELIVERED` → `DELIVERED`; `/pod` → `POD_RECEIVED`. `/close` completes no milestone. The `TL`-only `24H_PICKUP_CONF` and `24H_DELIVERY_CONF` are completed only through `PUT …/milestones/{code}`.

#### POD object

| Field | Type | Required | Description |
|---|---|---|---|
| `received` | boolean | read-only | `true` once a POD is recorded. |
| `signed_by` | string | read-only | Name of the person who signed. |
| `delivered_at_local` | local datetime | read-only | Delivery time, facility-local. |
| `timezone` | string | read-only | IANA zone of `delivered_at_local`. |
| `pieces` | integer | read-only | Pieces received. |
| `condition` | string | read-only | `CLEAR`, `SHORTAGE`, `DAMAGE`, `REFUSED`. |
| `notes` | string | read-only | Free text. |
| `doc_id` | string | read-only | Linked POD document id. |
| `on_time` | boolean | read-only | `false` when delivered after the delivery deadline. |
| `late_reason_code` | string | read-only | Present when late; `LATE` when none was given. |

#### Event object

One row of the activity log. Check calls, notes, status changes, appointments, document generation, milestone edits and system actions all appear as events. Fields with no value are omitted.

| Field | Type | Required | Description |
|---|---|---|---|
| `event_id` | string | read-only | Event id. |
| `event_seq` | string | read-only | Sort key, ordered by `entered_at`. |
| `shipment_id` | string | read-only | Owning shipment. |
| `event_type` | string | read-only | `STATUS_CHANGE`, `CHECK_CALL`, `NOTE`, `SYSTEM`, `APPOINTMENT`, `DOCUMENT`, `MILESTONE`. |
| `note` | string | read-only | Event text. |
| `visibility` | string | read-only | `INTERNAL` or `PUBLIC`. Only notes can be created as `PUBLIC`. |
| `event_at` | datetime | read-only | When it happened; defaults to `entered_at`. |
| `event_timezone` | string | read-only | IANA zone of a local `event_at`. |
| `entered_at` | datetime | read-only | When it was recorded. |
| `entered_by` | string | read-only | Who recorded it. |
| `status_code` | string | read-only | X12-style status code: `X3`, `AF`, `X6`, `X1` or `D1` on status changes; `X6` by default on check calls. |
| `reason_code` | string | read-only | Reason code (uncover, cancel or caller-supplied). |
| `city`, `state` | string | read-only | Reported location. |
| `eta` | datetime | read-only | Reported ETA (check calls). |
| `next_tracking_at_set` | datetime | read-only | Follow-up time set by a check call. |

### GET /shipments

Lists shipments (the shipment board). Filters combine. With `queue=tracking`, returns the tracking queue instead: open shipments whose `next_tracking_at` is now or earlier.

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | Comma-separated statuses, case-insensitive (e.g. `IN_TRANSIT,AT_PICKUP`). See *Enums › Shipment status*. |
| `mode` | string | no | `TL`, `EXPEDITE`, `LTL`. |
| `customer` | string | no | Customer id (e.g. `NORTHSTAR`). |
| `carrier` | string | no | Carrier vendor id (e.g. `ACMECARR`). |
| `pickup_from` | date | no | Earliest `pickup_date` (inclusive). |
| `pickup_to` | date | no | Latest `pickup_date` (inclusive). |
| `queue` | string | no | `tracking` returns the tracking queue; all other filters are ignored. `due=tracking` does the same. |
| `limit` | integer | no | Page size, default 50. Values are clamped to 1–200. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** — `200` `{items, count, next_cursor}` of *Shipment* objects without `summary`, newest `pickup_date` first (then `shipment_id` descending). Tracking-queue rows are sorted by oldest `next_tracking_at` first and carry `overdue` (`true` when the time has passed). The queue returns one page (`limit` rows at most, `next_cursor` always `null`).

**Errors** — `400` invalid cursor.

### POST /shipments

Books a shipment directly, without a quote. Allocates the next file number as `shipment_id`, sets `status` to `BOOKED`, and builds the mode's milestones with `NEW` complete.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `customer_id` | string | yes | Existing customer id. |
| `mode` | string | yes | `TL`, `EXPEDITE`, `LTL` (case-insensitive). |
| `stops` | array | yes | At least two *Stop* objects, in order. |
| `freight_lines` | array | yes | At least one *Freight line* object; `pieces` (integer ≥ 1) and `weight_lb` (> 0) required on each. |
| `service_level` | string | no | Must belong to `mode`. See *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `freight_terms` | string | no | `PREPAID` (default), `COLLECT`, `THIRD_PARTY`. |
| `customer_charges` | array | no | Starting *Charge line* objects; `charge_code` required on each. When `amount` is omitted it is calculated from `rate_basis`, `quantity` and `rate`. A `PCT_OF_FRT` line uses the `FRT` lines listed before it. |
| `vendor_costs` | array | no | Starting *Cost line* objects, with the same rules. |
| `references` | array | no | Shipment-level *Reference* objects. |
| `miles` | number | no | Lane miles. |
| `transit_days_est` | integer | no | Estimated transit days. |
| `declared_value` | number | no | Declared cargo value. |
| `insurance_type` | string | no | Free text. |
| `pickup_date` | date | no | Used only when stop 1 has no `scheduled_window`. Default today. |
| `delivery_date_target` | date | no | Used only when the last stop has no `scheduled_window`. |
| `salesperson_id` | string | no | User id. |
| `account_manager_id` | string | no | User id. Default from the customer. |
| `station` | string | no | Office code. Default from the customer. |
| `special_instructions` | string | no | Shipment-level instructions. |
| `internal_notes` | string | no | Internal notes panel text. |
| `track_owner` | string | no | User responsible for tracking. |

All other *Shipment* fields are read-only.

**Returns** — `201` the *Shipment* object.

### GET /shipments/{shipment_id}

Returns one shipment, including its `summary` line.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Returns** — `200` the *Shipment* object.

### PUT /shipments/{shipment_id}

Edits header fields, stops and freight lines. Recomputes freight totals, pickup and delivery dates and shipper/consignee fields. Money lines are not recalculated; use the `/costs` and `/charges` routes. Writes a `SYSTEM` event listing the changed fields.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `service_level` | string | no | Must belong to the shipment's mode. See *Enums › Service level*. |
| `equipment_type` | string | no | See *Enums › Equipment type*. |
| `freight_terms` | string | no | `PREPAID`, `COLLECT`, `THIRD_PARTY`. |
| `miles` | number | no | Lane miles. |
| `transit_days_est` | integer | no | Estimated transit days. |
| `declared_value` | number | no | Declared cargo value. |
| `insurance_type` | string | no | Free text. |
| `salesperson_id`, `account_manager_id` | string | no | User ids. |
| `station` | string | no | Office code. |
| `special_instructions` | string | no | Shipment-level instructions. |
| `internal_notes` | string | no | Replaces the internal notes panel text. |
| `track_owner` | string | no | User responsible for tracking. |
| `next_tracking_at` | datetime | no | Next check-call time (UTC); `null` takes the shipment off the tracking queue. |
| `stops` | array | no | Replaces all stops (*Stop* objects, at least two). An empty array is ignored. |
| `freight_lines` | array | no | Replaces all *Freight line* objects. An empty array is ignored. |
| `references` | array | no | *Reference* objects added to the existing ones. |

`shipment_id`, `status`, `mode` and `customer_id` cannot be changed here. Other read-only fields are ignored.

**Returns** — `200` the updated *Shipment* object.

**Errors** — `422` when `shipment_id`, `status`, `mode` or `customer_id` is sent with a different value.

### POST /shipments/{shipment_id}/cover

Assigns the carrier and moves the shipment from `BOOKED` to `COVERED`, completing `COVERED` (`LTL`: `TENDERED_TO_CARRIER`). With `amount`, cancels vendor-less estimated `FRT`/`FSC` cost lines and adds a `CONFIRMED` flat `FRT` cost line for the carrier. Without `amount`, those estimate lines are assigned to the carrier.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `carrier_id` | string | yes | Carrier vendor id (e.g. `ACMECARR`). |
| `amount` | number | no | Agreed carrier linehaul pay. `buy_rate` is accepted as an alias. |
| `pro_number` | string | no | Carrier PRO number; required for `LTL`. Added as a `PRO` reference. |
| `carrier_contact` | string | no | Carrier contact name. |
| `driver_name`, `driver_phone` | string | no | Driver details (needed later for `TL`/`EXPEDITE` dispatch). |
| `truck_number`, `trailer_number` | string | no | Equipment numbers. |
| `target_pay_min`, `target_pay_max` | number | no | Target carrier pay range. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the shipment is not `BOOKED`, the carrier is not `ACTIVE`, the carrier has no unexpired `CARGO` insurance, or an `LTL` shipment has no `pro_number`; `404` unknown carrier.

### POST /shipments/{shipment_id}/uncover

Removes the carrier (a carrier bounce) and returns the shipment to `BOOKED`. Cancels that carrier's cost lines; unchanged auto-generated estimates are kept as vendor-less estimates instead. Clears the carrier, driver, equipment, PRO, rate-confirmation and target-pay fields (so dispatch needs a new rate confirmation), and un-completes the `COVERED`, `TENDERED_TO_CARRIER`, `RATE_CON_SENT` and `DISPATCHED` milestones. The removed carrier details are kept in the `SYSTEM` event note.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `reason` | string | yes | `FELL_THROUGH`, `RATE_DISPUTE`, `EQUIPMENT`, `OTHER` (case-insensitive). |
| `note` | string | no | Added to the event note. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` unless the shipment is `COVERED` or `DISPATCHED`.

### POST /shipments/{shipment_id}/dispatch

Moves the shipment from `COVERED` to `DISPATCHED` and completes the `DISPATCHED` milestone (`TL`/`EXPEDITE`). Body fields are saved before the checks run, so you can supply missing driver details or a PRO in the same call.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `driver_name`, `driver_phone` | string | conditional | Required for `TL`/`EXPEDITE` unless already set at cover. |
| `truck_number`, `trailer_number` | string | no | Equipment numbers. |
| `pro_number` | string | conditional | Required for `LTL` unless already set. Added as a `PRO` reference. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the shipment is not `COVERED`; for `TL`/`EXPEDITE`, when no rate confirmation exists for the current carrier or `driver_name`/`driver_phone` is missing (all missing items are listed); for `LTL`, when `pro_number` is missing.

### POST /shipments/{shipment_id}/status

Moves the shipment one or two steps forward between `DISPATCHED` and `DELIVERED`, places it `ON_HOLD`, or releases a hold. Completes the matching milestones (on a two-step jump, also the skipped status's milestones, all with the same `event_at`) and writes a `STATUS_CHANGE` event. On `DELIVERED`, sets `service_failure` by comparing the delivery time with the earlier of the last delivery stop's window end and its MABD end of day, in the stop's time zone.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | string | yes | Target status (case-insensitive): `AT_PICKUP`, `PICKED_UP`, `IN_TRANSIT`, `AT_DELIVERY`, `DELIVERED`, `ON_HOLD`, or the shipment's `held_from` status to release a hold. |
| `hold_reason` | string | conditional | Required for `ON_HOLD`: `PAPERWORK`, `CLAIM`, `CUSTOMER_REQUEST`, `OTHER`. `reason` is accepted as an alias. |
| `event_at` | datetime | no | When it happened. Default now. |
| `event_timezone` | string | no | IANA zone for a local `event_at`. |
| `city`, `state` | string | no | Location recorded on the event. |
| `note` | string | no | Added to the event note. |
| `reason_code` | string | no | Recorded on the event. |
| `late_reason_code` | string | no | Becomes `service_failure_reason` when a `DELIVERED` update is late. Default `reason_code`, then `LATE`. |

A two-step jump may skip `DISPATCHED` (for example `COVERED` → `AT_PICKUP`); this completes the `DISPATCHED` milestone but not `RATE_CON_SENT`, and the dispatch checks do not run.

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` for an unknown status, the current status, a terminal shipment, a backward move, a jump of more than two steps, a status set by another route (`BOOKED`, `COVERED`, `DISPATCHED`, `POD_RECEIVED`, `CLOSED`, `CANCELLED`, `TONU`; the detail names the route), or a hold release to any status other than `held_from`; `422` `ON_HOLD` without a valid `hold_reason`.

### PUT /shipments/{shipment_id}/milestones/{code}

Marks one milestone complete or clears it. Use it for the manual `24H_PICKUP_CONF` and `24H_DELIVERY_CONF` confirmations and for corrections. Completing sets `source` to `MANUAL`; completing an already-complete milestone overwrites its times. Writes a `MILESTONE` event.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |
| `code` | Milestone code in this shipment's mode template. See *Enums › Milestone codes*. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `complete` | boolean | yes | `true` to complete; `false` to clear the milestone's completion and times. |
| `event_at` | datetime | no | When it happened. Default now. |
| `event_timezone` | string | no | IANA zone for a local `event_at`. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `404` when `code` is not part of this shipment's mode template.

### PUT /shipments/{shipment_id}/stops/{stop_seq}/appointment

Sets or confirms a stop appointment. A new `scheduled_window` replaces the stop's window and recalculates `pickup_date`/`delivery_date_target`. Appointment fields are merged into the existing appointment. A `confirmation_number` is added as a reference (`PU_NUMBER` on a pickup stop, `DELIVERY_NUMBER` otherwise) on both the stop and the shipment. Writes an `APPOINTMENT` event, plus a `SYSTEM` warning when a MABD conflict is acknowledged.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |
| `stop_seq` | Stop sequence number (integer). |

**Body**

At least one of `status`, `scheduled_window` or `confirmation_number` is required.

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | string | no | `NOT_REQUIRED`, `NEEDED`, `REQUESTED`, `CONFIRMED`, `RESCHEDULED`, `MISSED`. |
| `scheduled_window` | object | no | *Scheduled window* object; replaces the stop's window. |
| `confirmation_number` | string | no | Facility's appointment number (e.g. `BBR-DC135-45213`). |
| `acknowledge_mabd` | boolean | no | Set `true` to accept a window that ends after the stop's `mabd_date`. |
| `method_used` | string | no | How it was booked (e.g. `PORTAL`). |
| `portal_ref` | string | no | Scheduling portal reference. |
| `scheduled_by` | string | no | Who booked it. Default the caller. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the window's `latest_local` is after the stop's `mabd_date` end of day and `acknowledge_mabd` is not `true`; `404` unknown stop.

### POST /shipments/{shipment_id}/check-calls

Records a tracking check call as a `CHECK_CALL` event and sets the next follow-up time (`next_tracking_at`). Without `next_tracking_at`, the default depends on the shipment: `DELIVERED` → now + 24 h; delivery date is today (UTC) → now + 2 h; otherwise tomorrow at 08:00 UTC. Terminal shipments get no follow-up.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `note` | string | yes | What was reported. |
| `next_tracking_at` | datetime | no | Next follow-up time (UTC). Replaces the default. |
| `city`, `state` | string | no | Reported location. |
| `eta` | datetime | no | Reported ETA. |
| `status_code` | string | no | X12-style status code. Default `X6`. |
| `reason_code` | string | no | Recorded on the event. |
| `event_at` | datetime | no | When the call happened. Default now. |
| `event_timezone` | string | no | IANA zone for a local `event_at`. |
| `track_owner` | string | no | Reassigns the tracking owner. |

**Returns** — `200` the updated *Shipment* object.

### POST /shipments/{shipment_id}/pod

Records the proof of delivery. Moves the shipment to `POD_RECEIVED`; from `AT_DELIVERY`, also completes the `DELIVERED` milestone with the POD time. Clears `next_tracking_at`. A delivery after the deadline sets `pod.on_time` to `false` and `service_failure` to `true`.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `signed_by` | string | yes | Name of the person who signed. |
| `delivered_at_local` | local datetime | yes | Delivery time, facility-local. |
| `timezone` | string | yes | IANA zone of `delivered_at_local`. |
| `condition` | string | yes | `CLEAR`, `SHORTAGE`, `DAMAGE`, `REFUSED` (case-insensitive). |
| `pieces` | integer | no | Pieces received. |
| `notes` | string | no | Free text. |
| `doc_id` | string | no | Id of an uploaded POD document. |
| `late_reason_code` | string | no | Used when the delivery is late. Default `LATE`. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when a POD was already received, the shipment is terminal or `ON_HOLD`, or the status is not `AT_DELIVERY` or `DELIVERED`.

### POST /shipments/{shipment_id}/costs

Adds a vendor cost line (buy) and recalculates `buy_total`, `gp_amount` and `gp_pct`.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body** — a *Cost line* object:

| Field | Type | Required | Description |
|---|---|---|---|
| `vendor_id` | string | yes | Vendor being paid (e.g. `ACMECARR`). |
| `charge_code` | string | yes | See *Enums › Charge codes*. |
| `description` | string | no | Line description. |
| `rate_basis` | string | no | `FLAT` (default), `PER_MILE`, `PER_CWT`, `PER_LB`, `PER_HOUR`, `PCT_OF_FRT`, `PCT_OF_VALUE`. |
| `quantity` | number | no | Default `1`. |
| `rate` | number | no | Default `0`. For percentage bases, the percent. |
| `amount` | number | no | Default `rate_basis` × `quantity` × `rate`, at least `minimum`. `PCT_OF_FRT` uses the non-cancelled `FRT` cost lines; `PCT_OF_VALUE` uses `declared_value`. |
| `minimum` | number | no | Minimum amount when `amount` is calculated. |
| `status` | string | no | `ESTIMATED` (default), `CONFIRMED`, `CANCELLED`. |
| `override_flag` | boolean | no | Marks the amount as manually set. Default `false`. |

`cost_id` is assigned by the server.

**Returns** — `201` the updated *Shipment* object.

**Errors** — `409` when the shipment is `CLOSED`.

### PUT /shipments/{shipment_id}/costs/{cost_id}

Edits a vendor cost line and recalculates the money totals.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |
| `cost_id` | Cost line id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `charge_code` | string | no | See *Enums › Charge codes*. |
| `description` | string | no | Line description. |
| `vendor_id` | string | no | Reassigns the vendor. |
| `rate_basis` | string | no | `FLAT`, `PER_MILE`, `PER_CWT`, `PER_LB`, `PER_HOUR`, `PCT_OF_FRT`, `PCT_OF_VALUE`. |
| `quantity`, `rate` | number | no | Changing `rate_basis`, `quantity` or `rate` recalculates `amount`. |
| `amount` | number | no | Sets the amount directly and sets `override_flag` to `true`. |
| `status` | string | no | `ESTIMATED`, `CONFIRMED`, `CANCELLED`. |

Other fields are ignored.

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the shipment is `CLOSED`; `404` unknown `cost_id`.

### POST /shipments/{shipment_id}/charges

Adds a customer charge line (sell) and recalculates `sell_total`, `gp_amount` and `gp_pct`.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body** — a *Charge line* object:

| Field | Type | Required | Description |
|---|---|---|---|
| `charge_code` | string | yes | See *Enums › Charge codes*. |
| `description` | string | no | Line description. |
| `rate_basis` | string | no | `FLAT` (default), `PER_MILE`, `PER_CWT`, `PER_LB`, `PER_HOUR`, `PCT_OF_FRT`, `PCT_OF_VALUE`. |
| `quantity` | number | no | Default `1`. |
| `rate` | number | no | Default `0`. For percentage bases, the percent. |
| `amount` | number | no | Default `rate_basis` × `quantity` × `rate`, at least `minimum`. `PCT_OF_FRT` uses the `FRT` charge lines; `PCT_OF_VALUE` uses `declared_value`. |
| `minimum` | number | no | Minimum amount when `amount` is calculated. |
| `status` | string | no | `ESTIMATED` (default), `APPROVED`. |
| `override_flag` | boolean | no | Marks the amount as manually set. Default `false`. |

`charge_id` is assigned by the server.

**Returns** — `201` the updated *Shipment* object.

**Errors** — `409` when the shipment is `CLOSED`.

### PUT /shipments/{shipment_id}/charges/{charge_id}

Edits a customer charge line and recalculates the money totals.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |
| `charge_id` | Charge line id. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `charge_code` | string | no | See *Enums › Charge codes*. |
| `description` | string | no | Line description. |
| `rate_basis` | string | no | `FLAT`, `PER_MILE`, `PER_CWT`, `PER_LB`, `PER_HOUR`, `PCT_OF_FRT`, `PCT_OF_VALUE`. |
| `quantity`, `rate` | number | no | Changing `rate_basis`, `quantity` or `rate` recalculates `amount`. |
| `amount` | number | no | Sets the amount directly and sets `override_flag` to `true`. |
| `status` | string | no | `ESTIMATED`, `APPROVED`. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the shipment is `CLOSED`; `404` unknown `charge_id`.

### POST /shipments/{shipment_id}/notes

Adds a note to the activity log as a `NOTE` event. This is separate from the `internal_notes` panel.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `note` | string | yes | Note text. |
| `visibility` | string | no | `INTERNAL` (default) or `PUBLIC`. |
| `event_at` | datetime | no | When it happened. Default now. |
| `event_timezone` | string | no | IANA zone for a local `event_at`. |

**Returns** — `201` the created *Event* object.

### PUT /shipments/{shipment_id}/internal-notes

Replaces the shipment's `internal_notes` text. No event is written.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `internal_notes` | string | yes | Full replacement text. The field must be present; `""` or `null` clears it. |

**Returns** — `200` the updated *Shipment* object.

### POST /shipments/{shipment_id}/close

Closes the file after proof of delivery: `status` moves from `POD_RECEIVED` to `CLOSED`, which is terminal. Clears `next_tracking_at`, completes no milestone and writes a `STATUS_CHANGE` event. Once `CLOSED`, charge and cost lines can no longer be added or edited. The body is ignored.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` unless the shipment is `POD_RECEIVED`. The detail names the next step, e.g. "Shipment 7300174 is IN_TRANSIT — record the POD before closing the file". A shipment that is `ON_HOLD` must be released first; one that is already `CLOSED`, `CANCELLED` or `TONU` cannot be closed.

### POST /shipments/{shipment_id}/cancel

Cancels a shipment before delivery. By default the status becomes `CANCELLED` and every cost line is cancelled. With `tonu: true` (truck ordered, not used) the status becomes `TONU` and carrier cost lines are kept; `bill_customer: true` also adds a `TONU` charge line at the catalog rate. Clears hold fields and `next_tracking_at`.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `reason` | string | yes | `CUSTOMER_CANCELLED`, `DUPLICATE`, `NO_CAPACITY`, `OTHER` (case-insensitive). |
| `tonu` | boolean | no | Cancel as `TONU`. Default `false`. |
| `bill_customer` | boolean | no | With `tonu`, adds a `TONU` customer charge. Ignored otherwise. Default `false`. |
| `note` | string | no | Added to the event note. |

**Returns** — `200` the updated *Shipment* object.

**Errors** — `409` when the shipment is already terminal, or when it (or its `held_from` status) is `DELIVERED` or later.

### GET /shipments/{shipment_id}/events

Returns the shipment's activity log, newest first by `entered_at`.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | File number. |

**Query parameters**

| Name | Type | Required | Description |
|---|---|---|---|
| `type` | string | no | `STATUS_CHANGE`, `CHECK_CALL`, `NOTE`, `SYSTEM`, `APPOINTMENT`, `DOCUMENT`, `MILESTONE` (exact case). With a filter, a page can hold fewer than `limit` rows even when more exist; keep following `next_cursor`. |
| `limit` | integer | no | Page size, default 50. Values are clamped to 1–200. |
| `cursor` | string | no | `next_cursor` from the previous page. |

**Returns** — `200` `{items, count, next_cursor}` of *Event* objects.

**Errors** — `400` invalid cursor.

---

## Documents

Documents are files (PDFs, images, paperwork) attached to a shipment, customer, carrier (vendor) or quote, uploaded and downloaded through short-lived pre-signed links.

**Owner keys.** Every document belongs to one owner, identified by an `owner_key`: `SHIPMENT#{shipment_id}`, `CUSTOMER#{customer_id}`, `VENDOR#{vendor_id}` or `QUOTE#{quote_id}`. When an owner key appears in a URL path, encode `#` as `%23` (e.g. `SHIPMENT%237300137`).

**Upload flow.**

1. Call `POST /shipments/{shipment_id}/documents`, `POST /customers/{customer_id}/documents` or `POST /vendors/{vendor_id}/documents` with `doc_type`, `file_name` and `mime_type`. The response contains the document record (`doc`) and a pre-signed `upload_url`.
2. Within 15 minutes, send the file bytes with an HTTP `PUT` to `upload_url`, with a `Content-Type` header exactly equal to the `mime_type` you declared. Send no API credentials on this request — the link itself is the authorization.
3. To view or download, call `GET /documents/{owner_key}/{doc_id}/url` for a 15-minute pre-signed download link.

The document is listed as soon as step 1 succeeds; its download link works only once the file has been uploaded. Quotes take no uploads — their documents are generated with `POST /quotes/{quote_id}/documents/generate`.

**Doc types and versions.** `doc_type` is one of the values in *Enums › Document type*. Each new document of the same `doc_type` on the same owner gets the next `version` (1, 2, 3 …); earlier versions are kept. `visible_to_customer` is set automatically: `true` for `POD`, `BOL` and `QUOTE`, `false` for every other type (rate confirmations are never customer-visible).

**Document record.** `owner_key`, `doc_id`, `doc_type`, `file_name`, `mime_type`, `size` (bytes; `null` for uploaded files), `version`, `source` (see *Enums › Document source*), `visible_to_customer`, `uploaded_by`, `uploaded_at`, and the audit fields `created_at`, `created_by`, `updated_at`, `updated_by`.

### GET /shipments/{shipment_id}/documents

Lists the documents attached to a shipment, newest first. All documents are returned in one page.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | Shipment (file) number, e.g. `7300137`. |

**Returns** — `200` — list envelope of document records (`next_cursor` is always `null`); an unknown shipment returns an empty list.

### GET /customers/{customer_id}/documents

Lists the documents attached to a customer, newest first. All documents are returned in one page.

**Path parameters**

| Name | Description |
|---|---|
| `customer_id` | Customer ID, e.g. `NORTHSTAR`. |

**Returns** — `200` — list envelope of document records (`next_cursor` is always `null`); an unknown customer returns an empty list.

### GET /vendors/{vendor_id}/documents

Lists the documents attached to a carrier or other vendor (for example COI, carrier agreement), newest first. All documents are returned in one page.

**Path parameters**

| Name | Description |
|---|---|
| `vendor_id` | Vendor ID, e.g. `ACMECARR`. |

**Returns** — `200` — list envelope of document records (`next_cursor` is always `null`); an unknown vendor returns an empty list.

### GET /quotes/{quote_id}/documents

Lists the documents attached to a quote (the generated customer quotation PDFs), newest first. All documents are returned in one page.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | Quote (file) number. |

**Returns** — `200` — list envelope of document records (`next_cursor` is always `null`); an unknown quote returns an empty list.

### GET /documents/{owner_key}/{doc_id}/url

Returns a pre-signed download link for one stored document. The link is valid for 15 minutes, needs no API credentials, and opens the file inline under its original file name.

**Path parameters**

| Name | Description |
|---|---|
| `owner_key` | The document's owner key with `#` encoded as `%23`, e.g. `SHIPMENT%237300137`. |
| `doc_id` | The document ID from the document record, e.g. `doc_98da56991a9b452aadc7`. |

**Returns** — `200` — `{url}`: the pre-signed download link.

### POST /shipments/{shipment_id}/documents

Starts an upload to a shipment: creates the document record and returns a pre-signed upload link (see *Upload flow*). Uploading a `RATE_CONFIRMATION` file stores it but does not satisfy the dispatch requirement — only a rate confirmation generated with `POST /shipments/{shipment_id}/documents/generate` does.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | Shipment (file) number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | string | yes | See *Enums › Document type*. |
| `file_name` | string | yes | File name; any directory path is stripped. Must not be empty after stripping. |
| `mime_type` | string | yes | Content type of the file, e.g. `application/pdf`. The upload `PUT` must send exactly this `Content-Type`. |
| `source` | string | no | `UPLOAD`, `EMAIL`, `GENERATED` or `API`. Default: `API` for API-key callers, `UPLOAD` for user sessions. |

**Returns** — `201` — `{doc, upload_url}`: the new document record and the 15-minute pre-signed upload link.

### POST /customers/{customer_id}/documents

Starts an upload to a customer: creates the document record and returns a pre-signed upload link (see *Upload flow*).

**Path parameters**

| Name | Description |
|---|---|
| `customer_id` | Customer ID, e.g. `NORTHSTAR`. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | string | yes | See *Enums › Document type*. |
| `file_name` | string | yes | File name; any directory path is stripped. Must not be empty after stripping. |
| `mime_type` | string | yes | Content type of the file, e.g. `application/pdf`. The upload `PUT` must send exactly this `Content-Type`. |
| `source` | string | no | `UPLOAD`, `EMAIL`, `GENERATED` or `API`. Default: `API` for API-key callers, `UPLOAD` for user sessions. |

**Returns** — `201` — `{doc, upload_url}`: the new document record and the 15-minute pre-signed upload link.

### POST /vendors/{vendor_id}/documents

Starts an upload to a carrier or other vendor (for example a COI or carrier agreement): creates the document record and returns a pre-signed upload link (see *Upload flow*).

**Path parameters**

| Name | Description |
|---|---|
| `vendor_id` | Vendor ID, e.g. `ACMECARR`. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | string | yes | See *Enums › Document type*. |
| `file_name` | string | yes | File name; any directory path is stripped. Must not be empty after stripping. |
| `mime_type` | string | yes | Content type of the file, e.g. `application/pdf`. The upload `PUT` must send exactly this `Content-Type`. |
| `source` | string | no | `UPLOAD`, `EMAIL`, `GENERATED` or `API`. Default: `API` for API-key callers, `UPLOAD` for user sessions. |

**Returns** — `201` — `{doc, upload_url}`: the new document record and the 15-minute pre-signed upload link.

### POST /shipments/{shipment_id}/documents/generate

Renders a PDF from the shipment's current data and attaches it to the shipment (`source` `GENERATED`). `RATE_CONFIRMATION` produces the carrier-facing rate confirmation (buy side only, never customer-visible), named `RateCon_{shipment_id}_{rev}.pdf`: it increments the shipment's rate confirmation revision and sets `rate_con_number` to `RC-{shipment_id}-{rev}` (revisions are never reused, even after the carrier is removed and a new one assigned), satisfies the TL/EXPEDITE dispatch requirement for the current carrier, completes the `RATE_CON_SENT` milestone (TL and EXPEDITE), makes the number searchable, and logs a `DOCUMENT` event. `BOL` produces the bill of lading, named `BOL_{shipment_id}.pdf`, showing the carrier's legal name and SCAC (or `TBD` when no carrier is assigned), and logs a `DOCUMENT` event.

**Path parameters**

| Name | Description |
|---|---|
| `shipment_id` | Shipment (file) number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | string | yes | `RATE_CONFIRMATION` or `BOL`. |

**Returns** — `201` — `{doc, shipment}`: the new document record and the updated shipment.

**Errors** — `409` for `RATE_CONFIRMATION` when the shipment has no carrier assigned (cover it first); `422` for any other `doc_type`.

### POST /quotes/{quote_id}/documents/generate

Renders the customer-facing quotation PDF and attaches it to the quote (`source` `GENERATED`, `visible_to_customer` `true`), named `Quote_{quote_id}_{version}.pdf`. The PDF shows the sell side only — carrier costs, buy totals, margin and market-rate figures never appear. It adds a note to the quote and does not change its status; generating again after the quote is accepted is allowed.

**Path parameters**

| Name | Description |
|---|---|
| `quote_id` | Quote (file) number. |

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | string | yes | Must be `QUOTE`. |

**Returns** — `201` — `{doc, quote}`: the new document record and the updated quote.

**Errors** — `409` unless the quote's status is `QUOTED`, `SENT` or `ACCEPTED`: a `DRAFT` quote must be priced first, an `EXPIRED` quote must be re-rated, and `DECLINED` or `CONVERTED` quotes can no longer generate documents; `422` when `doc_type` is not `QUOTE`.

---

## Reference data

These read-only routes return the catalogs used across the API: charge codes, user accounts and the fuel surcharge scheme.

### GET /charge-codes

Returns the charge-code catalog, sorted by `code`, in one page. Each entry has `code`, `description`, `category`, `default_rate_basis` (see *Enums › Rate basis*), `default_rate` (`null` for `FRT` and `FSC`, which are always rated per shipment), `min_charge` (or `null`), `auto_flag` (`true` for codes the rating engine adds automatically), `edi_sac_code`, and audit fields. The full catalog is listed under *Enums › Charge codes*.

**Returns** — `200` — list envelope of charge codes (`next_cursor` is always `null`).

### GET /users

Returns all user accounts, sorted by `user_id`, in one page — for user pickers and for displaying the `created_by` / `updated_by` audit values. Each entry has `user_id`, `name`, `initials`, `role` (see *Enums › User role*), `station`, and audit fields; password data is never returned.

**Returns** — `200` — list envelope of users (`next_cursor` is always `null`).

### GET /fsc

Returns the fuel surcharge scheme that rating and the rate engine use. Fields: `scheme_id` (`DOE_DEFAULT`), `effective_date` (date), `doe_diesel_avg` (weekly diesel index, $/gal), `tl_per_mile` (TL fuel surcharge in $ per mile), `expedite_pct` and `ltl_pct` (EXPEDITE and LTL fuel surcharge as a percentage of the `FRT` line), `note`, and audit fields.

**Returns** — `200` — the fuel surcharge scheme object.

**Errors** — `404` when no fuel surcharge scheme is configured.

---

## Enums and codes

This appendix lists every enumerated value the API accepts or returns, plus the milestone codes, the charge-code catalog and the rate-basis rules; values are case-sensitive.

### Mode

| Value | Meaning |
|---|---|
| `TL` | Truckload |
| `EXPEDITE` | Expedited (hotshot, sprinter, straight truck) |
| `LTL` | Less-than-truckload |

### Service level

A service level must belong to the record's mode.

| Mode | Values |
|---|---|
| `TL` | `TL_DRY_VAN`, `TL_REEFER`, `TL_FLATBED`, `TL_PARTIAL` |
| `EXPEDITE` | `EXPEDITE_HOTSHOT`, `EXPEDITE_SPRINTER`, `EXPEDITE_STRAIGHT_TRUCK` |
| `LTL` | `LTL_STANDARD`, `LTL_GUARANTEED`, `LTL_VOLUME` |

### Equipment type

| Value | Meaning |
|---|---|
| `V` | Dry van |
| `R` | Reefer |
| `F` | Flatbed |
| `SD` | Step deck |
| `PO` | Power only |
| `HS` | Hotshot |
| `SB` | Straight box truck |
| `SV` | Sprinter van |
| `VC` | Curtain van |
| `DD` | Double drop |

### Package type

`PALLET`, `CRATE`, `BOX`, `SKID`, `DRUM`, `BUNDLE`, `ROLL`, `TOTE`, `PIECE`

### Freight class

Standard NMFC classes accepted in `freight_class`: `50`, `55`, `60`, `65`, `70`, `77.5`, `85`, `92.5`, `100`, `110`, `125`, `150`, `175`, `200`, `250`, `300`, `400`, `500`. When no explicit class is given, LTL rating derives the class from density (actual pounds per cubic foot):

| Density at least (lb/ft³) | Class |
|---|---|
| 50 | 50 |
| 35 | 55 |
| 30 | 60 |
| 22.5 | 65 |
| 15 | 70 |
| 13.5 | 77.5 |
| 12 | 85 |
| 10.5 | 92.5 |
| 9 | 100 |
| 8 | 110 |
| 7 | 125 |
| 6 | 150 |
| 5 | 175 |
| 4 | 200 |
| 3 | 250 |
| 2 | 300 |
| 1 | 400 |
| below 1 | 500 |

### Quote status

| Value | Meaning |
|---|---|
| `DRAFT` | Created, not yet priced |
| `QUOTED` | Priced |
| `SENT` | Sent to the customer |
| `ACCEPTED` | Accepted by the customer |
| `DECLINED` | Declined (final) |
| `CONVERTED` | Booked into a shipment with the same file number (final) |
| `EXPIRED` | Read-only, computed: a `DRAFT`, `QUOTED` or `SENT` quote whose `valid_until` is before today (UTC). Never stored or set by callers; accepted as a list filter. |

Allowed transitions: `DRAFT` → `QUOTED`; `QUOTED` → `QUOTED`, `SENT`, `ACCEPTED`, `DECLINED`, `CONVERTED`; `SENT` → `QUOTED`, `ACCEPTED`, `DECLINED`, `CONVERTED`; `ACCEPTED` → `CONVERTED`, `DECLINED`.

### Rate source

| Value | Meaning |
|---|---|
| `SPOT` | Rated from the lane's market spot rate |
| `CONTRACT` | Rated from a contract rate |
| `MANUAL` | Money lines entered or kept by hand |
| `EXTERNAL` | Priced from caller-supplied buy lines via `POST /quotes/{quote_id}/price` |

### Shipment status

Lifecycle order:

| # | Value | Meaning | Set by |
|---|---|---|---|
| 1 | `BOOKED` | Booked, no carrier yet | Booking; also the result of removing the carrier (`POST /shipments/{shipment_id}/uncover`) |
| 2 | `COVERED` | Carrier assigned | `POST /shipments/{shipment_id}/cover` |
| 3 | `DISPATCHED` | Driver dispatched | `POST /shipments/{shipment_id}/dispatch` |
| 4 | `AT_PICKUP` | Arrived at pickup | `POST /shipments/{shipment_id}/status` |
| 5 | `PICKED_UP` | Loaded and departed pickup | `POST /shipments/{shipment_id}/status` |
| 6 | `IN_TRANSIT` | En route | `POST /shipments/{shipment_id}/status` |
| 7 | `AT_DELIVERY` | Arrived at delivery | `POST /shipments/{shipment_id}/status` |
| 8 | `DELIVERED` | Delivered | `POST /shipments/{shipment_id}/status` |
| 9 | `POD_RECEIVED` | Proof of delivery recorded | `POST /shipments/{shipment_id}/pod` |
| 10 | `CLOSED` | File closed (final) | `POST /shipments/{shipment_id}/close` |

Side statuses:

| Value | Meaning |
|---|---|
| `ON_HOLD` | Paused from any non-final status; releasing returns it to the status it left |
| `CANCELLED` | Cancelled before delivery (final) |
| `TONU` | Truck ordered, not used — cancelled with carrier costs still payable (final) |

Final statuses (`CLOSED`, `CANCELLED`, `TONU`) accept no further status changes.

### Uncover reason

`FELL_THROUGH`, `RATE_DISPUTE`, `EQUIPMENT`, `OTHER`

### Cancel reason

`CUSTOMER_CANCELLED`, `DUPLICATE`, `NO_CAPACITY`, `OTHER`

### Hold reason

`PAPERWORK`, `CLAIM`, `CUSTOMER_REQUEST`, `OTHER`

### Freight terms

`PREPAID`, `COLLECT`, `THIRD_PARTY`

### Stop type

`PICKUP`, `DELIVERY`, `INTERMEDIATE`

### Appointment status

`NOT_REQUIRED`, `NEEDED`, `REQUESTED`, `CONFIRMED`, `RESCHEDULED`, `MISSED`

### Vendor cost status

Status of a buy-side (carrier cost) line: `ESTIMATED`, `CONFIRMED`, `CANCELLED`. `CANCELLED` lines stay on the record but are excluded from `buy_total`.

### Customer charge status

Status of a sell-side (customer charge) line: `ESTIMATED`, `APPROVED`.

### POD condition

`CLEAR`, `SHORTAGE`, `DAMAGE`, `REFUSED`

### Late reason code

| Value | Meaning |
|---|---|
| `NS` | Normal status (no exception) |
| `AI` | Mechanical breakdown |
| `AO` | Weather or natural disaster |
| `B1` | Consignee closed |
| `T3` | Tractor or trailer not available |
| `D1` | Carrier dispatch error |
| `WEATHER` | Weather |
| `MECHANICAL` | Mechanical |

These are the conventional values; the field is not validated. A late proof of delivery recorded without a code stores `LATE`.

### Reference type

`PO`, `BOL`, `PRO`, `PU_NUMBER`, `DELIVERY_NUMBER`, `MABD`, `RATE_CON`, `QUOTE`, `SHIPMENT`, `SEAL`, `TRAILER`, `RELEASE_NUMBER`, `SO`, `OTHER` (default when `type` is omitted)

### Event type

`STATUS_CHANGE`, `CHECK_CALL`, `NOTE`, `SYSTEM`, `APPOINTMENT`, `DOCUMENT`, `MILESTONE`

### Event visibility

`INTERNAL` (default), `PUBLIC`

### Status event code

X12-style status codes carried on status-change and check-call events. The field is not validated on check calls.

| Value | Meaning |
|---|---|
| `X3` | Arrived at pickup (recorded on `AT_PICKUP`) |
| `AF` | Departed pickup with shipment (recorded on `PICKED_UP`) |
| `X6` | En route (recorded on `IN_TRANSIT`; default on check calls) |
| `X1` | Arrived at delivery (recorded on `AT_DELIVERY`) |
| `D1` | Unloading complete / delivered (recorded on `DELIVERED`) |
| `SD` | Shipment delayed |
| `OA` | Additional status code |
| `P1` | Additional status code |

### Customer status

| Value | Meaning |
|---|---|
| `ACTIVE` | Active customer |
| `INACTIVE` | Inactive |
| `PROSPECT` | Not yet trading |

### Customer role

`SHIPPER`, `CONSIGNEE`, `CONTROLLING`

### Address type

`MAIN`, `BILLING`, `REMIT_TO`

### Customer contact role

`PRIMARY`, `AP`, `OPS`, `PRICING`, `AFTER_HOURS`

### TSA known-shipper status

`KNOWN`, `UNKNOWN`, `PENDING`

### Required-reference stage

The stage at which a customer-required reference must be present: `QUOTE`, `BOOKING`

### Vendor type

`TRUCKLOAD_CARRIER`, `LTL_CARRIER`, `CARTAGE_AGENT`, `EXPEDITE_CARRIER`, `AIRLINE`, `INSURANCE_VENDOR`, `LUMPER`, `OTHER`

### Vendor status

| Value | Meaning |
|---|---|
| `PENDING` | Onboarding; default for new vendors |
| `ACTIVE` | Approved; the only status that can be assigned to a shipment |
| `INACTIVE` | Not in use |
| `DO_NOT_USE` | Blocked; requires `status_reason` and forces the compliance light to `RED` |

### Authority status

`ACTIVE`, `REVOKED` (forces the compliance light to `RED`), `NONE`

### Safety rating

`SATISFACTORY`, `CONDITIONAL`, `UNRATED`

### Insurance policy type

`AUTO_LIABILITY`, `CARGO` (an unexpired `CARGO` policy is required to assign the carrier to a shipment), `GENERAL_LIABILITY`

### Insurance source

`AGENT_DIRECT`, `CARRIER_PROVIDED`

### Compliance light

Read-only, computed on every vendor read: `insurance_status` on each policy and `compliance_light` on the vendor (the worst policy light).

| Value | Meaning |
|---|---|
| `GREEN` | Policy valid for more than 30 days (also the vendor light when no policies are on file) |
| `YELLOW` | Policy expires within 30 days |
| `RED` | Policy expired or has no expiration date; vendor light is also `RED` when `status` is `DO_NOT_USE` or `authority_status` is `REVOKED` |

### Vendor contact role

`DISPATCH`, `QUOTING`, `CLAIMS`, `ACCOUNTING_AR`, `AFTER_HOURS`, `TRACKING`

### Facility type

`DC`, `WAREHOUSE`, `STORE`, `PLANT`, `YARD`, `PORT`, `AIRPORT`, `CROSS_DOCK`, `RESIDENCE`

### Facility role

`SHIPPER`, `CONSIGNEE`, `BOTH`

### Facility status

`ACTIVE`, `INACTIVE`

### Scheduling method

`NONE_FCFS` (no appointment; first come, first served), `PHONE`, `EMAIL`, `PORTAL`

### Portal vendor

`MERIDIAN_DOCK`, `OPENDOCK`, `DATADOCKS`, `ONE_NETWORK`, `RETAILER_PROPRIETARY`, `OTHER`

### Driver assist

`NO_TOUCH`, `DRIVER_ASSIST`, `LUMPER`

### Lumper policy

`NONE`, `OPTIONAL`, `REQUIRED`

### Pallet exchange

`NONE`, `EXCHANGE_REQUIRED`, `CHEP`, `PECO`

### Compliance flag

`CTPAT`, `SAFETY_VEST`, `NO_CELL_PHONES`, `SEAL_REQUIRED`, `ID_REQUIRED`, `STEEL_TOES`, `NO_IDLING`, `CHECK_IN_2H_EARLY`, `TWIC_REQUIRED`

### Facility contact role

`RECEIVING`, `SHIPPING`, `SCHEDULING`, `SECURITY`

### Facility link relationship

`SHIP_FROM`, `SHIP_TO`, `BOTH`

### Document type

| Value | Meaning | Customer-visible by default |
|---|---|---|
| `RATE_CONFIRMATION` | Carrier rate confirmation | no |
| `BOL` | Bill of lading | yes |
| `POD` | Proof of delivery | yes |
| `LUMPER_RECEIPT` | Lumper receipt | no |
| `SCALE_TICKET` | Scale ticket | no |
| `COI` | Certificate of insurance | no |
| `CARRIER_AGREEMENT` | Carrier agreement | no |
| `PHOTO` | Photo | no |
| `QUOTE` | Customer quotation PDF | yes |
| `OTHER` | Anything else | no |

### Document source

`UPLOAD`, `EMAIL`, `GENERATED` (rendered by the system), `API`

### User role

`CSR`, `DISPATCH`, `SALES`, `ACCOUNTING`, `ADMIN`. Callers using the `x-api-key` header carry role `API`.

### Principal type

`user` (Bearer-token session), `api` (`x-api-key` caller)

### Milestone source

`AUTO` (completed by a lifecycle action), `MANUAL` (set with `PUT /shipments/{shipment_id}/milestones/{code}`)

### Milestone codes

Each shipment gets the milestone list for its mode at booking. A milestone row is `{milestone_code, label, sequence, complete, event_at, event_timezone, entered_at, entered_by, source}`. The number in each mode column is the milestone's `sequence`; a dash means the code does not exist for that mode.

| Code | Label | TL | EXPEDITE | LTL | Completed by |
|---|---|---|---|---|---|
| `NEW` | New Shipment | 1 | 1 | 1 | Booking |
| `COVERED` | Carrier Assigned | 2 | 2 | — | `POST /shipments/{shipment_id}/cover` |
| `TENDERED_TO_CARRIER` | Tendered to Carrier | — | — | 2 | `POST /shipments/{shipment_id}/cover` |
| `RATE_CON_SENT` | Rate Confirmation Sent | 3 | 3 | — | Generating a `RATE_CONFIRMATION` |
| `DISPATCHED` | Driver Dispatched | 4 | 4 | — | `POST /shipments/{shipment_id}/dispatch` |
| `24H_PICKUP_CONF` | 24HR Prior Confirmation to Pickup | 5 | — | — | Manual only |
| `AT_SHIPPER` | Onsite at Shipper | 6 | 5 | — | Status `AT_PICKUP` |
| `LOADED` | Loaded | 7 | 6 | — | Status `PICKED_UP` |
| `PICKED_UP` | Picked Up | — | — | 3 | Status `PICKED_UP` |
| `IN_TRANSIT` | In Transit | 8 | 7 | 4 | Status `IN_TRANSIT` |
| `24H_DELIVERY_CONF` | 24HR Prior Confirmation to Delivery | 9 | — | — | Manual only |
| `AT_CONSIGNEE` | Arrived at Consignee | 10 | 8 | — | Status `AT_DELIVERY` |
| `OUT_FOR_DELIVERY` | Out for Delivery | — | — | 5 | Status `AT_DELIVERY` |
| `DELIVERED` | Delivered | 11 | 9 | 6 | Status `DELIVERED` |
| `POD_RECEIVED` | POD Received | 12 | 10 | 7 | `POST /shipments/{shipment_id}/pod` |

A forward status jump also completes the milestones of the skipped statuses, with the same event time; a jump over `DISPATCHED` completes `DISPATCHED` but not `RATE_CON_SENT`. Removing the carrier (`POST /shipments/{shipment_id}/uncover`) clears `COVERED`, `TENDERED_TO_CARRIER`, `RATE_CON_SENT` and `DISPATCHED`. Any milestone can be completed or cleared with `PUT /shipments/{shipment_id}/milestones/{code}`.

### Charge codes

The catalog returned by `GET /charge-codes`. "Auto" codes are added by the rating engine.

| Code | Name | Category | Default basis | Default rate | Auto |
|---|---|---|---|---|---|
| `APPT` | Appointment / Scheduled Delivery | `ACCESSORIAL` | `FLAT` | 50 | |
| `DET` | Detention (after 2 hr free) | `ACCESSORIAL` | `PER_HOUR` | 75 | |
| `FRT` | Freight / Linehaul | `LINEHAUL` | `FLAT` | — (rated per shipment) | yes |
| `FSC` | Fuel Surcharge | `FUEL` | `PCT_OF_FRT` | — (from `GET /fsc`; TL uses `PER_MILE`) | yes |
| `GTD` | Guaranteed Delivery / Time-Definite | `SERVICE` | `PCT_OF_FRT` | 20 | |
| `HAZ` | Hazmat Handling | `ACCESSORIAL` | `FLAT` | 75 | |
| `IDL` | Inside Delivery | `ACCESSORIAL` | `FLAT` | 125 | |
| `INSD` | Cargo Insurance / Declared Value | `INSURANCE` | `PCT_OF_VALUE` | 0.55 (minimum 25) | yes |
| `LAY` | Layover (per night) | `ACCESSORIAL` | `FLAT` | 250 | |
| `LGD` | Liftgate Delivery | `ACCESSORIAL` | `FLAT` | 85 | |
| `LGP` | Liftgate Pickup | `ACCESSORIAL` | `FLAT` | 85 | |
| `LUM` | Lumper / Unloading Labor | `ACCESSORIAL` | `FLAT` | 175 | |
| `REWEIGH` | Reweigh Fee | `ACCESSORIAL` | `FLAT` | 35 | |
| `RSD` | Residential Delivery | `ACCESSORIAL` | `FLAT` | 120 | |
| `RSP` | Residential Pickup | `ACCESSORIAL` | `FLAT` | 95 | |
| `SEC` | Security Screening | `ACCESSORIAL` | `PER_LB` | 0.08 | |
| `STOP` | Extra Stop | `ACCESSORIAL` | `FLAT` | 100 | yes |
| `STOR` | Storage (per day) | `ACCESSORIAL` | `FLAT` | 25 | |
| `TONU` | Truck Ordered Not Used | `PENALTY` | `FLAT` | 250 | |

Rates are in USD per unit of the basis; percentage bases are percents.

### Rate basis

How a money line's `amount` is computed from `quantity` and `rate` when `amount` is omitted. An explicit `amount` is always used as sent. Defaults: `rate_basis` `FLAT`, `quantity` 1, `rate` 0.

| Value | `quantity` means | `amount` |
|---|---|---|
| `FLAT` | Count (usually 1) | `quantity × rate` |
| `PER_MILE` | Miles | `quantity × rate` |
| `PER_CWT` | Hundredweight (pounds ÷ 100) | `quantity × rate` |
| `PER_LB` | Pounds | `quantity × rate` |
| `PER_HOUR` | Hours | `quantity × rate` |
| `PCT_OF_FRT` | Ignored | `rate`% of the same ledger's non-cancelled `FRT` lines |
| `PCT_OF_VALUE` | Ignored | `rate`% of the shipment's `declared_value` |

Amounts are rounded half-up to 2 decimals. On shipment lines, a supplied `minimum` floors the computed amount, and when several lines are sent in one request a `PCT_OF_FRT` line is computed from the `FRT` lines listed before it — put `FRT` first. On manually entered quote lines, `PCT_OF_FRT` and `PCT_OF_VALUE` require an explicit `amount`.
