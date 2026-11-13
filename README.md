# Return Trip

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # fill in keys, or keep secret.txt in the repo root
```

## Run

```bash
python scripts/sync_data.py                   # first time: pull Meridian data + classify
flask --app backend run --debug --port 5000
python scripts/reset_demo.py                  # before a demo: decline Return Trip quotes
python -m pytest backend/tests                # offline tests (fake Meridian and OpenAI)
```

Check it is up: `http://localhost:5000/api/health`.
