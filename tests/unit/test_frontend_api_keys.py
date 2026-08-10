"""Workspace API keys are managed from the Users screen, not from curl.

A key is a principal in its own right, so it belongs on the screen that answers "who
can reach this workspace" — beside the people, not in a runbook. These run the real
``static/js/users.js`` under node: the listing is assembled per workspace and merged,
and the created key is surfaced once, which is the only moment it exists in plaintext.
"""

from __future__ import annotations

import pytest

from tests.utils.js_harness import NODE_MISSING, run_js

pytestmark = pytest.mark.skipif(NODE_MISSING, reason="node not installed")

WS_A = {"id": "ws-a", "name": "Localchat"}
WS_B = {"id": "ws-b", "name": "Default"}

KEY_A = {
    "id": "key-1", "name": "discord-bridge", "key_prefix": "lcw_AAAA",
    "role": "viewer", "created_at": "2026-08-08T10:00:00Z", "last_used_at": None,
}
KEY_B = {
    "id": "key-2", "name": "nightly-report", "key_prefix": "lcw_BBBB",
    "role": "editor", "created_at": "2026-08-07T10:00:00Z",
    "last_used_at": "2026-08-08T09:00:00Z",
}


def _routes(keys_a=(), keys_b=(), create=None):
    """Answer each call users.js makes. First matching substring wins, so order matters."""
    return [
        ("/api/users/me", {"role": "admin"}),
        ("ws-a/keys", create or {"success": True, "keys": list(keys_a)}),
        ("ws-b/keys", {"success": True, "keys": list(keys_b)}),
        ("/keys", create or {"success": True, "keys": []}),
        ("/api/users/", {"success": True, "workspaces": []}),
        ("/api/users", {"success": True, "users": []}),
        ("/api/workspaces", {"success": True, "workspaces": [WS_A, WS_B]}),
    ]


def _table(**kwargs) -> str:
    return run_js("users.js", routes=_routes(**kwargs))["html"]["keys-body"]


@pytest.mark.unit
class TestTheListing:
    def test_a_key_is_listed_by_name(self):
        assert "discord-bridge" in _table(keys_a=[KEY_A])

    def test_keys_from_every_workspace_are_merged(self):
        """Two workspaces, so a listing that overwrites instead of accumulating fails."""
        html = _table(keys_a=[KEY_A], keys_b=[KEY_B])
        assert "discord-bridge" in html and "nightly-report" in html

    def test_each_key_names_the_workspace_it_reaches(self):
        """The scope is the point of the key; a list without it is unreadable."""
        html = _table(keys_a=[KEY_A], keys_b=[KEY_B])
        assert "Localchat" in html and "Default" in html

    def test_the_role_is_shown(self):
        assert "viewer" in _table(keys_a=[KEY_A])

    def test_only_the_prefix_is_shown(self):
        """The full key is never returned by the listing; the prefix identifies it."""
        assert "lcw_AAAA" in _table(keys_a=[KEY_A])

    def test_an_unused_key_says_so_rather_than_showing_a_blank(self):
        assert "never" in _table(keys_a=[KEY_A])

    def test_a_used_key_shows_its_last_use_instead(self):
        html = _table(keys_b=[KEY_B])
        assert "never" not in html

    def test_no_keys_yields_a_prompt_not_an_empty_table(self):
        assert "No keys yet" in _table()


@pytest.mark.unit
class TestTheKeyIsSurfacedOnce:
    def test_the_created_key_is_put_where_the_admin_can_copy_it(self):
        """Only its hash is stored: a key this screen fails to show is unrecoverable."""
        created = {"success": True, "key": "lcw_PLAINTEXT_ONCE", "info": KEY_A}
        result = run_js("users.js", routes=_routes(create=created))
        assert result["values"]["kr-value"] == "lcw_PLAINTEXT_ONCE"

    def test_creation_posts_to_the_workspace_scoped_endpoint(self):
        """A key is minted under one workspace; a global endpoint would not be scoped."""
        created = {"success": True, "key": "lcw_X", "info": KEY_A}
        result = run_js("users.js", routes=_routes(create=created))
        posts = [c for c in result["calls"] if c["method"] == "POST" and "/keys" in c["url"]]
        assert posts and posts[0]["url"].startswith("/api/workspaces/")
