"""Ryan's interfaces, or the stand-ins from _stubs.py for any that haven't landed yet.

Each name is imported separately, so the switch-over happens piece by piece as Ryan's
modules fill in. `STUBBED` lists whatever is still a stand-in (shown at /api/email/health).
"""

import importlib

from email_pipeline import _stubs

STUBBED = []


def _load(module_name, attr):
    """Return backend.<module>.<attr> if it exists, else the same-named stub."""
    try:
        return getattr(importlib.import_module(module_name), attr)
    except (ImportError, AttributeError) as exc:
        STUBBED.append(f"{module_name}.{attr} ({type(exc).__name__}: {exc})")
        return getattr(_stubs, attr)


get_conn = _load("backend.db", "get_conn")
tool = _load("backend.agent.registry", "tool")
propose = _load("backend.agent.actions", "propose")
find_backhauls = _load("backend.brain.network", "find_backhauls")
check_compat = _load("backend.brain.compat", "check_compat")
meridian_get = _load("backend.meridian", "get")
