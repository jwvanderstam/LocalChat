"""QA-5 — a month-old conversation rendered as if every message were from today.

`formatTime` showed the hour and minute only. The hour was right; the day was
never shown, so a conversation from 10 August read as 13:09 today.

Assertions compare against values computed in the same JS runtime rather than
against a literal or a string length: `toLocaleTimeString` renders "03:56 PM" on a
US-locale runner and "15:56" on a Dutch one, and a length check quietly passes for
the wrong reason on one of them.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.utils.js_harness import JS_DIR, NODE_MISSING

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

_CLOCK_OPTS = "{ hour: '2-digit', minute: '2-digit' }"
_DATE_OPTS = "{ day: '2-digit', month: 'short' }"


def _eval(expr: str):
    """Evaluate *expr* with ui.js in scope, and return the JSON-decoded result."""
    source = (JS_DIR / "ui.js").read_text(encoding="utf-8")
    program = source + "\nconsole.log(JSON.stringify(" + expr + "));"
    out = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _format(expr: str) -> str:
    return _eval("formatTime(" + expr + ")")


class TestFormatTime:
    def test_todays_message_shows_only_the_time(self):
        """Dating every line would be noise in an active conversation."""
        assert _eval(
            "formatTime(new Date()) === new Date().toLocaleTimeString([], " + _CLOCK_OPTS + ")"
        ) is True

    def test_an_older_message_leads_with_its_date(self):
        """The regression: without a date it is indistinguishable from today."""
        stamp = "'2026-08-10T13:09:00Z'"
        expected = _eval("new Date(" + stamp + ").toLocaleDateString([], " + _DATE_OPTS + ")")
        assert _format(stamp).startswith(expected)

    def test_an_older_message_keeps_its_time(self):
        """The date is added in front, not swapped in for the clock."""
        stamp = "'2026-08-10T13:09:00Z'"
        expected = _eval("new Date(" + stamp + ").toLocaleTimeString([], " + _CLOCK_OPTS + ")")
        assert _format(stamp).endswith(expected)

    def test_yesterday_is_already_dated(self):
        """The boundary is the calendar day, not a 24-hour window."""
        yesterday = "new Date(Date.now() - 24 * 60 * 60 * 1000)"
        clock_only = _eval(yesterday + ".toLocaleTimeString([], " + _CLOCK_OPTS + ")")
        assert _format(yesterday) != clock_only

    def test_an_invalid_timestamp_renders_as_nothing(self):
        """new Date(undefined) is Invalid Date, whose toLocale* output is the
        literal string 'Invalid Date' — worse to show than an empty cell."""
        assert _format("undefined") == ""
        assert _format("'not a date'") == ""

    def test_a_date_object_is_accepted_as_well_as_a_string(self):
        """Live messages pass a Date; replayed history passes an ISO string."""
        assert _format("new Date('2026-08-10T13:09:00Z')") == _format("'2026-08-10T13:09:00Z'")
