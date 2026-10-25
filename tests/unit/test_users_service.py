"""UsersService's decisions, written against QP-7's mutation survivors.

The route tests prove the rules over HTTP; these prove the identity a caller is given,
that no hash leaves the service, and which role changes count as removing an admin.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.services.passwords import verify_user_password
from src.services.users import UsersService

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
WORKSPACE = "11111111-1111-1111-1111-111111111111"
DEFAULT = "22222222-2222-2222-2222-222222222222"


def _db(connected: bool = True) -> MagicMock:
    db = MagicMock()
    db.is_connected = connected
    db.workspaces.default_id.return_value = DEFAULT
    db.members.role.return_value = "editor"
    db.users.get_by_id.return_value = {"id": USER, "username": "alice", "role": "user",
                                       "hashed_password": "pbkdf2:sha256:1$salt$hash"}
    return db


class TestIdentity:
    def test_names_the_global_role_and_the_role_in_the_given_workspace(self):
        db = _db()
        assert UsersService(db).identity(USER, WORKSPACE) == ("user", "editor")
        db.members.role.assert_called_once_with(WORKSPACE, USER)

    def test_without_a_workspace_reads_the_role_in_the_default_one(self):
        db = _db()
        UsersService(db).identity(USER, None)
        db.members.role.assert_called_once_with(DEFAULT, USER)

    def test_anonymous_has_no_identity(self):
        db = _db()
        assert UsersService(db).identity("anonymous", WORKSPACE) == (None, None)
        db.users.get_by_id.assert_not_called()

    def test_a_disconnected_database_gives_no_identity(self):
        db = _db(connected=False)
        assert UsersService(db).identity(USER, WORKSPACE) == (None, None)
        db.users.get_by_id.assert_not_called()

    def test_a_database_that_cannot_say_it_is_connected_is_not_available(self):
        assert UsersService(SimpleNamespace()).available is False  # type: ignore[arg-type]


class TestNoHashLeavesTheService:
    def test_create_returns_the_stored_user_without_its_hash(self):
        db = _db()
        db.users.create.return_value = USER
        created = UsersService(db).create_user("alice", "a-long-password", None, "user", None, "editor")
        assert created == {"id": USER, "username": "alice", "role": "user"}

    def test_list_returns_every_user_without_a_hash(self):
        db = _db()
        db.users.list_all.return_value = [{"id": USER, "username": "alice", "hashed_password": "h"}]
        assert UsersService(db).list_users(include_retired=False) == [{"id": USER, "username": "alice"}]


class TestUpdate:
    def test_a_new_password_is_stored_as_a_hash_that_verifies(self):
        db = _db()
        UsersService(db).update_user(USER, {}, password="a-new-long-password")
        stored = db.users.update.call_args.kwargs["hashed_password"]
        users = MagicMock()
        users.get_by_username.return_value = {"id": USER, "is_active": True, "hashed_password": stored}
        assert verify_user_password(users, "alice", "a-new-long-password") is not None

    def test_keeping_the_last_admin_an_admin_is_not_a_demotion(self):
        db = _db()
        db.users.get_by_id.return_value = {"id": USER, "role": "admin"}
        db.users.count_live_admins.return_value = 1
        db.users.update.return_value = True
        assert UsersService(db).update_user(USER, {"role": "admin"}, password=None) == {
            "id": USER, "role": "admin",
        }
