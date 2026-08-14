"""The browser front end's Python side.

Nothing in here computes anything. `autocircuit.core` and `autocircuit.io` do the work, exactly
as they do for the CLI; this package only turns a request that arrived as JSON into a call and
the result back into JSON, so that the JavaScript on the other side of a worker boundary moves
bytes and strings and makes no decisions. `docs/WEB_UI_PLAN.md` section 4 is the rule it
implements: the web UI must not fork the science.
"""

from autocircuit.web.bridge import BRIDGE_VERSION, handle

__all__ = ["BRIDGE_VERSION", "handle"]
