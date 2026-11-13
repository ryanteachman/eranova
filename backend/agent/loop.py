"""OpenAI tool-calling loop."""

import json

from openai import OpenAI

from .. import config, db, meridian
from ..errors import ApiError
from . import actions, autonomy, tools  # noqa: F401  (tools registers itself on import)
from .registry import TOOLS, openai_tools

MAX_TURNS = 8
RESULT_CHARS = 6000
PREVIEW_CHARS = 160

SYSTEM_PROMPT = """You are Return Trip, an agent for Meridian Logistics, a freight brokerage.
Trucks deliver freight one way and drive home empty. Your job: find where trucks run empty,
find compatible freight for the trip home, and propose real backhaul quotes in Meridian.

Rules:
- Use network_overview to see where trucks run empty, then find_backhauls for a city.
- Only propose create_return_quote for prospects with ok = true. Never work around a blocked
  prospect; explain the blocking reason instead (compatibility rules are decided by code).
- create_return_quote is decided by the brokerage's decision mode: it is either queued for a
  human to approve or executed right away by the AI. Report exactly what its result says
  (waiting for approval, created automatically with the quote id, or failed) with the action id.
- If a Meridian call fails, read its detail sentence and correct your next call.
- Be brief and concrete: cities, customers, scores, dollars, reasons."""


def _client():
    return OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)


def describe_outcome(action):
    """One sentence for the model on what happened to a proposed action under the decision mode."""
    action_id, mode = action["action_id"], action.get("mode") or "approval"
    if action["status"] == "done":
        return (f"Executed automatically by the AI as {action_id} ({mode} mode): "
                f"{json.dumps(action['result'], default=str)[:400]}")
    if action["status"] == "failed":
        return f"The AI tried to execute {action_id} ({mode} mode) but it failed: {action['result'].get('error')}"
    why = autonomy.hold_message(mode, action.get("risk") or {"blockers": [], "reasons": [], "cap": None})
    return f"Queued for human approval as {action_id}" + (f" ({why})" if why else "")


def _run_tool(name, args, actions_created):
    """Run one tool call and return its result as text for the model."""
    entry = TOOLS.get(name)
    if entry is None:
        return f"Error: unknown tool {name!r}."
    try:
        if entry["tier"] == "approve":
            proposal = entry["fn"](**args)
            action = actions.propose(kind=name, **proposal)
            actions_created.append(action["action_id"])
            return describe_outcome(action)
        return json.dumps(entry["fn"](**args), default=str)[:RESULT_CHARS]
    except meridian.MeridianError as exc:
        return f"Meridian error {exc.status} {exc.error}: {exc.detail}"
    except ApiError as exc:
        return f"Error: {exc}"
    except TypeError as exc:
        # The model sent arguments that do not match the tool's signature.
        return f"Error: bad arguments for {name}: {exc}"


def run_agent(trigger, message, context=None):
    """Run the tool-calling loop for one message; return {reply, tool_calls, actions_created}."""
    user_text = message if context is None else f"{message}\n\nContext:\n{json.dumps(context, default=str)}"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_text}]
    db.audit(trigger, "agent_message", message[:500])

    client = _client()
    tool_calls, actions_created = [], []
    for _ in range(MAX_TURNS):
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL, messages=messages, tools=openai_tools(), temperature=0,
        )
        reply = response.choices[0].message
        if not reply.tool_calls:
            db.audit("agent", "agent_reply", (reply.content or "")[:500])
            return {"reply": reply.content or "", "tool_calls": tool_calls,
                    "actions_created": actions_created}

        messages.append(reply.model_dump(exclude_none=True))
        for call in reply.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _run_tool(name, args, actions_created)
            db.audit("agent", "tool_call", f"{name} {json.dumps(args)} -> {result[:300]}")
            tool_calls.append({"name": name, "args": args, "result_preview": result[:PREVIEW_CHARS]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return {"reply": "I stopped after the maximum number of steps. Here is what I did so far.",
            "tool_calls": tool_calls, "actions_created": actions_created}
