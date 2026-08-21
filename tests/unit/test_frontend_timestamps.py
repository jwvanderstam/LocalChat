"""QA-5 — a month-old conversation rendered as if every message were from today.

`formatTime` showed the hour and minute only. The hour was right; the day was
never shown, so a conversation from 10 August read as 13:09 today.
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


def _format(expr: str) -> str:
    """Call formatTime with *expr*, evaluated inside the module."""
    source = (JS_DIR / "ui.js").read_text(encoding="utf-8")
    program = f"{source}\nconsole.log(JSON.stringify(formatTime({expr})));"
    out = subprocess.run(
        ["node", "--input-type=module", "-e", program],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


class TestFormatTime:
    def test_todays_message_shows_only_the_time(self):
        """Adding a date to every line would be noise in an active conversation."""
        result = _format("new Date()")
        assert ":" in result
        # No day-month prefix: the whole string is the clock.
        assert len(result) <= 6

    def test_an_older_message_carries_its_date(self):
        """The regression: without this it is indistinguishable from today."""
        result = _format("'2026-08-10T13:09:00Z'")
        assert "10" in result
        assert "aug" in result.lower()

    def test_yesterday_is_already_dated(self):
        """The boundary is the calendar day, not 24 hours."""
        result = _format("new Date(Date.now() - 24 * 60 * 60 * 1000)")
        assert len(result) > 6, f"expected a dated stamp, got {result!r}"

    def test_an_invalid_timestamp_renders_as_nothing(self):
        """new Date(undefined) is Invalid Date, whose toLocale* is the literal
        string 'Invalid Date' — worse to show than an empty cell."""
        assert _format("undefined") == ""
        assert _format("'not a date'") == ""

    def test_a_date_object_is_accepted_as_well_as_a_string(self):
        """Live messages pass a Date; replayed history passes an ISO string."""
        assert _format("new Date('2026-08-10T13:09:00Z')") == _format("'2026-08-10T13:09:00Z'")
