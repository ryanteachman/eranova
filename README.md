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
```

Check it is up: `http://localhost:5000/api/health`.
