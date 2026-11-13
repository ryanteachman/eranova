"""@tool decorator, the TOOLS dict and tool tiers."""

# auto runs immediately. approve tools only return {title, summary, payload, confidence};
# the loop queues that as an action and actions.EXECUTORS[name] does the write on approval.
TIERS = {"auto", "approve"}

TOOLS = {}


def tool(name, description, schema, tier="auto"):
    """Register a function as an agent tool under name, with a JSON schema for its arguments."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")

    def decorator(fn):
        TOOLS[name] = {"name": name, "description": description, "schema": schema,
                       "tier": tier, "fn": fn}
        return fn

    return decorator


def openai_tools():
    """Return every registered tool in the OpenAI chat-completions tools format."""
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}}
        for t in TOOLS.values()
    ]
