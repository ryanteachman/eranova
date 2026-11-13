# Status

## Asher (email pipeline)

**2026-11-13**
- **Done:** `email_pipeline/` specs 1–8 working end to end on stubs with live Meridian reads (parse, store, classify, extract, match, quote + reply proposals, tools, routes); 7 sample emails; contracts; `docs/email.md`. Stretch done too: carrier haggle → `cover_load`, and an IMAP poller behind `EMAIL_POLL_ENABLED`.
- **Doing:** swapping stubs for Ryan's real interfaces as they land (automatic via `deps.py`; check `/api/email/health`).
- **Blocked:** on Ryan for the mount, executors and the `backend/__init__.py` name collision (see `docs/requests.md`).
- @Ali: contracts are in `contracts/email_inbox.json`, `email_detail.json`, `email_outbox.json`, `email_process_result.json`. Extra routes: `GET /api/email/samples` (file names for the simulate buttons) and `POST /api/email/<id>/haggle`. Detail rows include `replies`.
