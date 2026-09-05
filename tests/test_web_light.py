"""Tests for `autocircuit.web.light`: the half of the bridge that answers without scipy.

The browser installs numpy, comes up, and installs scipy behind it, because scipy is 18.3 MB of
the 41 MB a first visit fetches and nothing on the Data screen uses it
(`docs/STARTUP_AND_EDITING_PLAN.md` section 3). That only works while the import path of the
data operations stays scipy-free -- a property nothing about the code *looks* like, and which
one convenient `from .fit import ...` would silently undo.

So the check that matters runs in a subprocess with scipy made unimportable, and asks for the
four operations the first load stage promises. A test in this process could not say anything: by
the time it runs, twenty other tests have imported scipy already.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import autocircuit
from autocircuit.web import BRIDGE_VERSION, handle
from autocircuit.web.light import LIGHT_OPERATIONS

SRC = Path(autocircuit.__file__).resolve().parent.parent

#: Run in a fresh interpreter that cannot import scipy at all. `sys.meta_path` is where an
#: import is resolved from, so a finder in front of the rest refuses the package and everything
#: under it -- which is what the worker's first stage looks like from Python's side, except that
#: there the module genuinely is not installed yet.
BLOCK_SCIPY = """
import importlib.abc, json, sys


class NoScipy(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "scipy" or name.startswith("scipy."):
            raise ImportError(f"scipy is not installed yet ({name})")
        return None


sys.meta_path.insert(0, NoScipy())

from autocircuit.web import handle

ask = lambda request: json.loads(handle(json.dumps(request)))
"""


def _run(script: str) -> dict[str, object]:
    """Run *script* under the scipy block and read the JSON its last line printed."""
    finished = subprocess.run(
        [sys.executable, "-c", BLOCK_SCIPY + script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout.strip().splitlines()[-1])


def test_the_data_operations_answer_with_scipy_unimportable(tmp_path: Path) -> None:
    csv = tmp_path / "example.csv"
    csv.write_text(
        "Frequency,Re(Z),Im(Z)\n"
        + "\n".join(f"{10**k},{10.0 + k},{-100.0 / 10**k}" for k in range(6))
        + "\n",
        encoding="utf8",
    )
    answers = _run(f"""
read = ask({{"op": "read", "path": {str(csv)!r}}})
spectrum = read["result"]["spectra"][0]
trim = ask({{"op": "trim", "spectrum": spectrum, "f_min": 100, "f_max": 10000}})
validate = ask({{"op": "validate", "spectrum": spectrum}})
version = ask({{"op": "version"}})
print(json.dumps({{
    "read": read["ok"],
    "points": len(spectrum["f"]["data"]),
    "trim": trim["ok"],
    "trimmed": len(trim["result"]["spectrum"]["f"]["data"]),
    "validate": validate["ok"],
    "version": version["result"],
    "scipy_imported": "scipy" in sys.modules,
}}))
""")
    assert answers["scipy_imported"] is False
    assert answers["read"] is True
    assert answers["points"] == 6
    assert answers["trim"] is True
    assert answers["trimmed"] == 3
    assert answers["validate"] is True


def test_version_says_what_the_first_stage_can_know(tmp_path: Path) -> None:
    """The handshake and the two menus, all answerable before the fitter exists."""
    answer = _run("""
print(json.dumps(ask({"op": "version"})))
""")
    assert answer["ok"] is True
    result = answer["result"]
    assert isinstance(result, dict)
    assert result["bridge"] == BRIDGE_VERSION
    assert result["formats"] == [
        "biologic",
        "gamry",
        "generic_csv",
        "keysight",
        "touchstone",
        "zview",
    ]
    assert [c["name"] for c in result["criteria"]] == [
        "aic",
        "aicc",
        "bic",
        "caic",
        "hqc",
        "waic",
        "ftest",
    ]
    assert result["default_criterion"] == "bic"
    # What the worker schedules on: it sends anything not in this list only once scipy is in, and
    # it reads the list from here rather than keeping its own.
    assert result["light_operations"] == sorted(LIGHT_OPERATIONS)
    # The fit and DRT wire versions are deliberately absent: they belong to modules that do not
    # exist yet, and inventing them here would be the front end trusting a number nothing checked.
    assert "fit" not in result
    assert "drt" not in result


def test_a_fitting_operation_before_scipy_fails_by_naming_the_missing_package() -> None:
    """Not a hang and not "unknown operation": the message says what is not there yet.

    The worker never sends one -- it waits for the second stage -- so this is what a caller who
    bypasses the worker sees, and it is the diagnosis they need.
    """
    answer = _run("""
print(json.dumps(ask({"op": "elements"})))
""")
    assert answer["ok"] is False
    error = answer["error"]
    assert isinstance(error, dict)
    assert "scipy" in error["message"]


def test_the_light_table_holds_exactly_the_operations_the_first_stage_promises() -> None:
    assert sorted(LIGHT_OPERATIONS) == ["read", "trim", "validate", "version"]


def test_the_full_bridge_answers_everything_through_the_same_handle() -> None:
    """One dispatch completed in two pieces: `handle` finds a heavy operation without help."""
    from autocircuit.web.bridge import OPERATIONS

    assert "runtime" in OPERATIONS
    assert set(OPERATIONS).isdisjoint(LIGHT_OPERATIONS)
    answer = json.loads(handle(json.dumps({"op": "runtime"})))
    assert answer["ok"] is True
    assert set(answer["result"]) == {"fit", "drt"}


@pytest.mark.parametrize("operation", ["version", "runtime", "elements"])
def test_every_answer_is_strictly_json(operation: str) -> None:
    json.dumps(json.loads(handle(json.dumps({"op": operation}))), allow_nan=False)
