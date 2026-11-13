# Backend

Flask app in `backend/`. Owner: Ryan.

## Setup

```bash
pip install -r requirements.txt
python scripts/sync_data.py                     # first time: pull Meridian + classify
flask --app backend run --debug --port 5000
```

## Environment variables

Read from `.env` (see `.env.example`). `TMS_API_BASE` and `TMS_API_KEY` fall back to
`secret.txt`. That file is a labeled text file, not `KEY=VALUE`: the backend reads the first
word after `Base URL:` and `API key:`.

| Variable | Default | Used for |
|---|---|---|
| `TMS_API_BASE` | from `secret.txt` | Meridian base URL, ends in `/v1` |
| `TMS_API_KEY` | from `secret.txt` | Meridian `x-api-key` header |
| `OPENAI_API_KEY` | — | Classification and the agent |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI endpoint |
| `OPENAI_MODEL` | `gpt-4o` | Model for classification and the agent |
| `DB_PATH` | `return_trip.db` in the repo root | SQLite file |

## Modules

- `meridian.py`: `get`, `post`, `put`, `get_all` (follows `next_cursor` until `null`, even
  past empty pages). Errors raise `MeridianError(status, error, detail)`; the `detail` is
  Meridian's sentence, unchanged.
- `db.py`: `get_conn()`, `init_db()`, `upsert_records()`, `load_records()`, `audit()`. Cached
  Meridian records are stored as JSON in `shipments`, `vendors`, `facilities` and `customers`.
  The cache is for reads only; writes always go to Meridian.
- `brain/sync.py`: `sync_all()` pulls all four record types (`limit=200`). Current data: 160
  shipments, 18 vendors, 30 facilities, 14 customers.
- `brain/classify.py`: `classify_all()` sends each unclassified shipment's equipment and
  freight lines to OpenAI with structured output (a Pydantic model) and caches the result in
  `classifications`. It uses 8 threads and temperature 0. A Meridian `hazmat: true` freight
  line forces `HAZMAT`. The prompt defines every category and tells the model that all food,
  including dry and shelf-stable groceries, is `FOOD`, because the FSMA rule depends on it.
  To reclassify, delete the rows from `classifications` and rerun the script.

## Constants

| Constant | Value | Where |
|---|---|---|
| Meridian page size | 200 | `meridian.PAGE_LIMIT` |
| Meridian timeout | 30 s | `meridian.TIMEOUT_SECONDS` |
| Classification threads | 8 | `classify.WORKERS` |

## Known issues

- Facilities have no `latitude`/`longitude` in Meridian, so the network map needs a
  hard-coded city coordinate table.
- Classification is not perfectly consistent: 1 of 33 "Machined steel components" shipments
  came back `GENERAL` instead of `STEEL`.
