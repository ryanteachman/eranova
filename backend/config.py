"""Settings loaded from .env, falling back to the organizers' secret.txt."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SECRET_FILE = ROOT / "secret.txt"

# secret.txt is a labeled text file ("  Base URL: ..."), not KEY=VALUE lines.
SECRET_LABELS = {"Base URL": "TMS_API_BASE", "API key": "TMS_API_KEY", "URL": "TMS_UI_URL"}

load_dotenv(ROOT / ".env")


def read_secret_file(path=SECRET_FILE):
    """Parse secret.txt and return a dict with whichever of TMS_API_BASE / TMS_API_KEY it holds."""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        label, sep, value = line.replace("\r", "").strip().partition(":")
        label, words = label.strip(), value.split()
        # The value may be followed by an explanatory note on the same line.
        if sep and label in SECRET_LABELS and words:
            values[SECRET_LABELS[label]] = words[0]
    return values


_secret = read_secret_file()

TMS_API_BASE = (os.getenv("TMS_API_BASE") or _secret.get("TMS_API_BASE", "")).rstrip("/")
TMS_API_KEY = os.getenv("TMS_API_KEY") or _secret.get("TMS_API_KEY", "")
TMS_UI_URL = (os.getenv("TMS_UI_URL") or _secret.get("TMS_UI_URL", "")).rstrip("/")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
DB_PATH = os.getenv("DB_PATH", str(ROOT / "return_trip.db"))
