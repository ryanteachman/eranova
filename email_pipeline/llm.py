"""One small helper for OpenAI structured output (a Pydantic model as the response format)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")

_client = None


def client():
    """The shared OpenAI client, created on first use (reads OPENAI_API_KEY / OPENAI_BASE_URL)."""
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def structured(system_prompt, user_text, response_model, model=MODEL):
    """Ask the model and return an instance of response_model (raises if the model refuses)."""
    resp = client().chat.completions.parse(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        response_format=response_model,
    )
    message = resp.choices[0].message
    if message.parsed is None:
        raise RuntimeError(f"LLM returned no structured output: {message.refusal or message.content}")
    return message.parsed
