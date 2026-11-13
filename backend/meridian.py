"""Meridian TMS API client."""

import requests

from . import config

TIMEOUT_SECONDS = 30
PAGE_LIMIT = 200


class MeridianError(Exception):
    """A Meridian error response, keeping its status, error code and detail sentence."""

    def __init__(self, status, error, detail):
        super().__init__(f"Meridian {status} {error}: {detail}")
        self.status = status
        self.error = error
        self.detail = detail


def _request(method, path, params=None, body=None):
    response = requests.request(
        method,
        config.TMS_API_BASE + path,
        headers={"x-api-key": config.TMS_API_KEY},
        params=params,
        json=body,
        timeout=TIMEOUT_SECONDS,
    )
    if response.ok:
        return response.json()
    try:
        data = response.json()
    except ValueError:
        data = {}
    raise MeridianError(
        response.status_code,
        data.get("error", "http_error"),
        data.get("detail", response.text[:200]),
    )


def get(path, **params):
    """GET a Meridian route and return the parsed JSON body."""
    return _request("GET", path, params=params)


def post(path, body=None):
    """POST a JSON body to a Meridian route and return the parsed JSON body."""
    return _request("POST", path, body=body if body is not None else {})


def put(path, body):
    """PUT a JSON body to a Meridian route and return the parsed JSON body."""
    return _request("PUT", path, body=body)


def get_all(path, **params):
    """GET every page of a Meridian list route and return all items as one list."""
    params.setdefault("limit", PAGE_LIMIT)
    items = []
    while True:
        page = get(path, **params)
        items.extend(page["items"])
        # A page can be empty while next_cursor is still set, so only stop on null.
        if not page.get("next_cursor"):
            return items
        params["cursor"] = page["next_cursor"]
