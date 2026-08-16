"""The browser front end's Python side.

Nothing in here computes anything. `autocircuit.core` and `autocircuit.io` do the work, exactly
as they do for the CLI; this package only turns a request that arrived as JSON into a call and
the result back into JSON, so that the JavaScript on the other side of a worker boundary moves
bytes and strings and makes no decisions. `docs/WEB_UI_PLAN.md` section 4 is the rule it
implements: the web UI must not fork the science.

The import below is of :mod:`autocircuit.web.light` and not of :mod:`autocircuit.web.bridge`, and
that is the whole of the staged load: `light` answers the four operations that need only numpy and
imports the rest of the bridge when something asks for it, so the browser's first stage can come up
without scipy (`docs/STARTUP_AND_EDITING_PLAN.md` section 3.2). ``from autocircuit.web import
handle`` is the worker's one entry point and is unchanged.
"""

from autocircuit.web.light import BRIDGE_VERSION, handle

__all__ = ["BRIDGE_VERSION", "handle"]
