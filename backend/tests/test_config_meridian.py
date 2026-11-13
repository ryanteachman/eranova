"""Tests for secret.txt parsing and the Meridian client."""

import pytest
import requests

from backend import config, meridian

# Captured at import, before the autouse fixture swaps in the fake client.
REAL = {name: getattr(meridian, name) for name in ("get", "get_all", "post", "put")}

SECRET_TXT = (
    "Meridian TMS - hackathon environment for team03\r\n"
    "WEB APP\r\n"
    "  URL:       https://ui.example\r\n"
    "  Users:     JOHNDOE   (CSR)\r\n"
    "REST API\r\n"
    "  Base URL:  https://api.example/v1\r\n"
    "  API key:   abc123    (send as the x-api-key header)\r\n"
    "QUICK START\r\n"
    "  export TMS_API_KEY=wrong\r\n"
)


def test_secret_file_reads_labels_and_ignores_trailing_notes(tmp_path):
    path = tmp_path / "secret.txt"
    path.write_bytes(SECRET_TXT.encode("utf-8"))
    assert config.read_secret_file(path) == {
        "TMS_UI_URL": "https://ui.example",
        "TMS_API_BASE": "https://api.example/v1",
        "TMS_API_KEY": "abc123",
    }


def test_missing_secret_file_returns_nothing(tmp_path):
    assert config.read_secret_file(tmp_path / "nope.txt") == {}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = status < 400
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def real_client(monkeypatch):
    for name, fn in REAL.items():
        monkeypatch.setattr(meridian, name, fn)
    monkeypatch.setattr(config, "TMS_API_BASE", "https://api.example/v1")
    monkeypatch.setattr(config, "TMS_API_KEY", "key")
    sent = []

    def install(responses):
        def fake_request(method, url, **kwargs):
            sent.append((method, url, dict(kwargs.get("params") or {}), kwargs["headers"]))
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(meridian.requests, "request", fake_request)
        return sent

    return install


def test_get_all_follows_cursor_through_empty_pages(real_client):
    sent = real_client([
        FakeResponse(200, {"items": [1, 2], "next_cursor": "c1"}),
        FakeResponse(200, {"items": [], "next_cursor": "c2"}),
        FakeResponse(200, {"items": [3], "next_cursor": None}),
    ])
    assert meridian.get_all("/quotes", status="QUOTED") == [1, 2, 3]
    assert [params.get("cursor") for _, _, params, _ in sent] == [None, "c1", "c2"]
    assert all(params["limit"] == 200 and params["status"] == "QUOTED" for _, _, params, _ in sent)
    assert sent[0][3] == {"x-api-key": "key"}
    assert sent[0][1] == "https://api.example/v1/quotes"


def test_error_response_raises_meridian_error_with_detail(real_client):
    real_client([FakeResponse(409, {"error": "conflict", "detail": "Carrier is not compliant."})])
    with pytest.raises(meridian.MeridianError) as info:
        meridian.post("/shipments/1/cover", {})
    assert (info.value.status, info.value.error, info.value.detail) == (
        409, "conflict", "Carrier is not compliant.")


def test_non_json_error_still_raises(real_client):
    real_client([FakeResponse(502, ValueError("not json"))])
    with pytest.raises(meridian.MeridianError) as info:
        meridian.get("/dashboard/counts")
    assert info.value.status == 502 and info.value.error == "http_error"


def test_network_failure_becomes_meridian_error(real_client):
    real_client([requests.ConnectionError("down")])
    with pytest.raises(meridian.MeridianError) as info:
        meridian.get("/fsc")
    assert info.value.status == 503 and info.value.error == "meridian_unreachable"
