"""Tests for the tool registry, the OpenAI tool-calling loop and the demo reset script."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest

from backend import db, meridian
from backend.agent import actions, loop
from backend.agent.registry import TOOLS, openai_tools


def tool_call(call_id, name, args):
    return SimpleNamespace(id=call_id, type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class Message:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, exclude_none=False):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [{"id": c.id, "type": "function",
                                   "function": {"name": c.function.name,
                                                "arguments": c.function.arguments}}
                                  for c in self.tool_calls]
        return {k: v for k, v in data.items() if not (exclude_none and v is None)}


class ScriptedClient:
    """Plays back a list of assistant messages and records what the loop sent."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        message = self.script.pop(0) if self.script else Message(tool_calls=[
            tool_call("loop", "network_overview", {})])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.fixture
def scripted(monkeypatch):
    def install(script):
        client = ScriptedClient(script)
        monkeypatch.setattr(loop, "_client", lambda: client)
        return client
    return install


def test_every_tool_is_registered_with_a_valid_schema():
    expected = {"network_overview": "auto", "find_backhauls": "auto",
                "create_return_quote": "approve", "get_shipment": "auto", "search": "auto",
                "price_preview": "auto", "add_shipment_note": "auto"}
    assert {name: t["tier"] for name, t in TOOLS.items()} == expected
    for entry in openai_tools():
        assert entry["type"] == "function"
        assert entry["function"]["parameters"]["type"] == "object"
    assert all(name in actions.EXECUTORS for name, t in TOOLS.items() if t["tier"] == "approve")


def test_agent_finds_backhauls_and_queues_a_quote(dallas, scripted, fake_meridian):
    from backend.brain import network
    pid = network.find_backhauls("Dallas", "TX")[0]["prospect_id"]
    client = scripted([
        Message(tool_calls=[tool_call("1", "find_backhauls", {"city": "Dallas", "state": "TX"})]),
        Message(tool_calls=[tool_call("2", "create_return_quote", {"prospect_id": pid})]),
        Message(content="Queued it."),
    ])
    result = loop.run_agent("human", "Fill the Dallas backhaul")

    assert result["reply"] == "Queued it."
    assert [c["name"] for c in result["tool_calls"]] == ["find_backhauls", "create_return_quote"]
    action_id = result["actions_created"][0]
    assert result["tool_calls"][1]["result_preview"] == f"Queued for human approval as {action_id}"
    assert actions.get(action_id)["status"] == "pending"
    # Nothing was written to Meridian: only the price preview ran.
    assert not [c for c in fake_meridian.calls if c[1] == "/quotes"]
    # The tool result was sent back to the model, without internal pricing lines.
    tool_message = client.requests[1][-1]
    assert tool_message["role"] == "tool" and "buy_lines" not in tool_message["content"]
    with db.get_conn() as conn:
        events = [r["event"] for r in conn.execute("SELECT event FROM audit_log")]
    assert events.count("tool_call") == 2 and "agent_reply" in events


def test_meridian_errors_go_back_to_the_model(dallas, scripted, fake_meridian):
    fake_meridian.fail[("GET", "/shipments/")] = meridian.MeridianError(
        404, "not_found", "No shipment 999.")
    scripted([Message(tool_calls=[tool_call("1", "get_shipment", {"shipment_id": "999"})]),
              Message(content="That file does not exist.")])
    result = loop.run_agent("human", "Look up 999")
    assert result["tool_calls"][0]["result_preview"] == "Meridian error 404 not_found: No shipment 999."
    assert result["reply"] == "That file does not exist."


def test_bad_tool_calls_are_reported_not_raised(dallas, scripted):
    scripted([
        Message(tool_calls=[tool_call("1", "no_such_tool", {}),
                            tool_call("2", "find_backhauls", {"town": "Dallas"}),
                            tool_call("3", "create_return_quote", {"prospect_id": "bad"})]),
        Message(content="done"),
    ])
    previews = [c["result_preview"] for c in loop.run_agent("human", "x")["tool_calls"]]
    assert previews[0].startswith("Error: unknown tool")
    assert previews[1].startswith("Error: bad arguments for find_backhauls")
    assert previews[2].startswith("Error: Prospect bad not found")


def test_loop_stops_after_max_turns(dallas, scripted):
    client = scripted([])
    result = loop.run_agent("human", "loop forever")
    assert len(client.requests) == loop.MAX_TURNS
    assert len(result["tool_calls"]) == loop.MAX_TURNS
    assert "maximum number of steps" in result["reply"]


def test_context_is_sent_to_the_model(dallas, scripted):
    client = scripted([Message(content="ok")])
    loop.run_agent("email", "Reply to this", context={"email_id": "e1"})
    assert '"email_id": "e1"' in client.requests[0][1]["content"]


def test_openai_failure_returns_502(client, monkeypatch):
    def fail():
        raise openai.APIConnectionError(request=None)
    monkeypatch.setattr(loop, "_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: fail()))))
    response = client.post("/api/agent/chat", json={"message": "hi"})
    assert response.status_code == 502 and response.get_json()["error"] == "openai_error"


# ---------- scripts/reset_demo.py ----------

def load_reset_demo():
    path = Path(__file__).resolve().parents[2] / "scripts" / "reset_demo.py"
    spec = importlib.util.spec_from_file_location("reset_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reset_demo_declines_only_return_trip_quotes(dallas, monkeypatch, fake_meridian):
    quotes = {
        "QUOTED": [{"quote_id": "1", "notes": [{"text": "priced (rate_ref return-trip:7300001)"}]},
                   {"quote_id": "2", "notes": [{"text": "someone else's quote"}]}],
        "EXPIRED": [{"quote_id": "3", "notes": [{"text": "return-trip:7300002"}]},
                    {"quote_id": "1", "notes": [{"text": "return-trip:7300001"}]}],
    }
    monkeypatch.setattr(meridian, "get_all", lambda path, status: quotes.get(status, []))
    actions.propose("create_return_quote", "t", "s", {"a": 1})
    reset_demo = load_reset_demo()
    reset_demo.main()
    declined = sorted(p for m, p, _ in fake_meridian.calls if p.endswith("/decline"))
    assert declined == ["/quotes/1/decline", "/quotes/3/decline"]
    assert actions.list_actions("pending") == []
