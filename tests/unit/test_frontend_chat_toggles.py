"""The chat mode toggles must survive navigation (T3).

Switching to Document Management and back dropped web-enhanced mode and turned RAG
back on, because neither toggle was ever stored. The next answer then came from a
different configuration than the one on screen a moment earlier, with nothing
saying so. The model override beside them *was* persisted, which is what made the
omission easy to miss: the row looked like it remembered itself.

This file only exists because the harness now runs modules that import their
siblings (T5). `chat.js` imports three, so it could not be executed at all before —
the fix shipped without a test, which is the gap this closes.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

_RAG = "lc-rag-enabled"
_ENHANCE = "lc-enhance-enabled"


def _load(**stored: str) -> dict:
    return run_js("chat.js", preload=stored)


class TestRestoringOnLoad:
    """Asserted on the checkbox, never on the storage.

    Reading back the storage the test seeded itself is true whether or not the
    module did anything — the first version of this file passed against a chat.js
    with no persistence at all.
    """

    def test_a_stored_enhanced_setting_is_applied_to_the_checkbox(self):
        """The reported symptom: enhanced came back off after every page switch."""
        assert _load(**{_RAG: "true", _ENHANCE: "true"})["checked"]["enhance-toggle"] is True

    def test_rag_switched_off_stays_off(self):
        """RAG is checked in the markup, so a stored "off" is exactly what a missing
        restore silently reverses."""
        assert _load(**{_RAG: "false", _ENHANCE: "false"})["checked"]["rag-toggle"] is False

    def test_a_first_visit_writes_nothing(self):
        """Restoring must not fire the change handler and write back what it read,
        or the markup defaults are frozen into storage on first sight."""
        storage = _load()["storage"]
        assert _RAG not in storage
        assert _ENHANCE not in storage


class TestContradictoryStoredState:
    """Enhanced implies RAG. A stored pair that disagrees — an older build, or
    hand-edited storage — must not produce a mode the badge cannot describe."""

    def test_enhanced_without_rag_turns_rag_back_on(self):
        result = _load(**{_ENHANCE: "true", _RAG: "false"})
        assert result["checked"]["enhance-toggle"] is True
        assert result["checked"]["rag-toggle"] is True


class TestUnexpectedStoredValues:
    def test_a_junk_value_is_treated_as_off(self):
        """localStorage is a string store and anything can end up in it. Only "true"
        counts as on, so a stale or corrupted value fails closed rather than
        enabling a mode the user did not choose."""
        assert _load(**{_ENHANCE: "banana", _RAG: "true"})["checked"]["enhance-toggle"] is False

    def test_the_page_still_loads_with_junk_stored(self):
        assert _load(**{_ENHANCE: "banana", _RAG: "banana"})["calls"] is not None
