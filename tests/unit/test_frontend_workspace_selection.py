"""The active workspace in localStorage must belong to whoever is signed in now.

localStorage is scoped to the browser, not to the session. An admin working in
"Default" who signs out, and an editor with access only to another workspace who
signs in after them, shared one key: the editor inherited "Default", every page
sent it as ``X-Workspace-ID`` before the switcher had loaded, and the server
answered 403 to each one. The account looked broken until the workspace was
picked by hand.

These run the real ``static/js`` files under node, because both defects live in
branch logic no Python test can reach — the previous workspace bug shipped past
2550 green Python tests for the same reason. Asserting on the source text would
only restate the code.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = pytest.mark.skipif(NODE_MISSING, reason="node not installed")

ID_KEY = "localchat_active_workspace_id"
NAME_KEY = "localchat_active_workspace"

MINE = {"id": "ws-mine", "name": "Localchat"}
THEIRS = {"id": "ws-theirs", "name": "Default"}

INHERITED = {ID_KEY: THEIRS["id"], NAME_KEY: THEIRS["name"]}


def _switcher(preload: dict, workspaces: list[dict]) -> dict:
    return run_js(
        "workspace.js",
        preload=preload,
        routes=[("/api/workspaces", {"success": True, "workspaces": workspaces})],
    )["storage"]


@pytest.mark.unit
class TestStaleChoiceIsNotHonoured:
    """The reported bug: a workspace the server did not offer must not stay active."""

    def test_inherited_workspace_is_replaced_by_one_the_user_can_enter(self):
        assert _switcher(INHERITED, [MINE])[ID_KEY] == MINE["id"]

    def test_the_displayed_name_is_replaced_too(self):
        """A right id under the previous user's name is its own confusing failure."""
        assert _switcher(INHERITED, [MINE])[NAME_KEY] == MINE["name"]

    def test_a_user_with_no_workspaces_keeps_no_stale_id(self):
        """Otherwise every request carries a 403 header with nothing to correct it."""
        after = _switcher(INHERITED, [])
        assert ID_KEY not in after
        assert NAME_KEY not in after


@pytest.mark.unit
class TestValidChoicesSurvive:
    """The negative space: validation must not become "always reset to the first"."""

    def test_a_still_valid_choice_is_kept_even_when_it_is_not_first(self):
        stored = {ID_KEY: MINE["id"], NAME_KEY: MINE["name"]}
        assert _switcher(stored, [THEIRS, MINE])[ID_KEY] == MINE["id"]

    def test_first_login_with_no_stored_choice_picks_the_first_offered(self):
        assert _switcher({}, [MINE, THEIRS])[ID_KEY] == MINE["id"]


@pytest.mark.unit
class TestLoginClearsThePreviousAccount:
    """The switcher corrects the id late; login removes it before anything sends it."""

    def _login(self) -> dict:
        return run_js(
            "auth.js",
            preload=INHERITED,
            routes=[("/api/auth/login", {"success": True})],
        )["storage"]

    def test_signing_in_drops_the_previous_users_workspace_id(self):
        assert ID_KEY not in self._login()

    def test_signing_in_drops_the_previous_users_workspace_name(self):
        assert NAME_KEY not in self._login()
