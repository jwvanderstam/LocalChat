"""Settings → Account, run under node: the change-password form in `account.js`.

The server decides; the form only catches what the user can see for themselves, and
must show the server's own reason when it refuses. Asserted on what the module did:
the request it sent (or did not send), the message it showed, and the fields it left.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(NODE_MISSING, reason="node is not installed"),
]

_URL = "/api/users/me/password"
_STATUS = "password-status"


def _submit(current: str, new: str, confirm: str, answer: dict[str, Any] | None = None):
    return run_js(
        "account.js",
        fields={"current-password": current, "new-password": new, "confirm-password": confirm},
        routes=[(_URL, answer if answer is not None else {"success": True})],
    )


def _posts(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [json.loads(c["body"]) for c in result["calls"] if c["url"] == _URL and c["method"] == "POST"]


def test_a_valid_change_sends_both_passwords_once():
    result = _submit("old secret", "a new password!", "a new password!")
    assert _posts(result) == [{"current_password": "old secret", "new_password": "a new password!"}]


def test_success_clears_the_form_and_says_so():
    result = _submit("old secret", "a new password!", "a new password!")
    fields = [result["values"][k] for k in ("current-password", "new-password", "confirm-password")]
    assert (fields, result["html"][_STATUS]) == (["", "", ""], "Password changed.")


def test_a_mismatched_repeat_sends_nothing():
    result = _submit("old secret", "a new password!", "a new passw0rd!")
    assert (_posts(result), result["html"][_STATUS]) == ([], "The new passwords do not match.")


@pytest.mark.parametrize(("new", "sent"), [("x" * 11, 0), ("x" * 12, 1)], ids=["11", "12"])
def test_the_length_check_sits_exactly_at_twelve(new, sent):
    assert len(_posts(_submit("old secret", new, new))) == sent


def test_an_empty_current_password_sends_nothing():
    result = _submit("", "a new password!", "a new password!")
    assert (_posts(result), result["html"][_STATUS]) == (
        [], "Fill in your current and your new password.")


def test_a_refusal_shows_the_servers_reason_and_keeps_the_form():
    result = _submit("wrong", "a new password!", "a new password!",
                     {"success": False, "message": "Current password is incorrect"})
    assert (result["html"][_STATUS], result["values"]["new-password"]) == (
        "Current password is incorrect", "a new password!")
