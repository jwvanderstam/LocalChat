"""S7 — an administrator setting someone's password is held to the same 12 characters.

Self-service change got the rule first (USER_PASSWORD_MIN_LENGTH). Creating a user only
refused an empty password, and the admin update took `data["password"]` as given, of any
length and any JSON type, straight into the hash.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import config
from tests.utils.auth import admin_headers, authenticated_state

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
_SHORT = "x" * (config.USER_PASSWORD_MIN_LENGTH - 1)
_EXACT = "x" * config.USER_PASSWORD_MIN_LENGTH
_REFUSAL = {"success": False, "message": "password must be at least 12 characters"}


def _client():
    from src.routes_fastapi.auth_routes import router

    state = authenticated_state(role="admin")
    state.db.create_user.return_value = USER
    state.db.update_user.return_value = True
    state.db.get_user_by_id.return_value = {"id": USER, "username": "jo", "role": "user"}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state = state
    client = TestClient(app, raise_server_exceptions=True)
    client.headers.update(admin_headers())
    return client, state.db


class TestCreatingAUser:
    def test_a_password_one_short_is_refused_before_the_database(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": "jo", "password": _SHORT})
        assert (resp.status_code, resp.json(), db.create_user.called) == (400, _REFUSAL, False)

    def test_a_password_at_the_minimum_creates_the_user(self):
        client, db = _client()
        resp = client.post("/api/users", json={"username": "jo", "password": _EXACT})
        assert (resp.status_code, db.create_user.called) == (201, True)


class TestResettingAPassword:
    def test_a_password_one_short_is_refused_and_nothing_is_written(self):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"password": _SHORT})
        assert (resp.status_code, resp.json(), db.update_user.called) == (400, _REFUSAL, False)

    @pytest.mark.parametrize("value", [123456789012345, None, ["a-long-enough-password"]],
                             ids=["number", "null", "list"])
    def test_a_password_that_is_not_a_string_is_refused(self, value):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"password": value})
        assert (resp.status_code, db.update_user.called) == (400, False)

    def test_a_password_at_the_minimum_is_stored(self):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"password": _EXACT})
        assert (resp.status_code, "hashed_password" in db.update_user.call_args.kwargs) == (200, True)

    def test_an_update_without_a_password_is_not_held_to_the_rule(self):
        client, db = _client()
        resp = client.put(f"/api/users/{USER}", json={"role": "admin"})
        assert (resp.status_code, "hashed_password" in db.update_user.call_args.kwargs) == (200, False)
