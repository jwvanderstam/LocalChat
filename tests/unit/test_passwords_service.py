"""The password module's decisions, written against QP-7's mutation survivors.

Every refusal costs one hash (S3); these prove what is refused, and that the stored
format is the one the rest of the application and existing rows expect.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.services.passwords import _dummy_hash, hash_user_password, verify_user_password

pytestmark = pytest.mark.unit

PASSWORD = "correct horse battery"


def _users(**row: object) -> MagicMock:
    users = MagicMock()
    users.get_by_username.return_value = (
        {"id": "u1", "username": "alice", "hashed_password": hash_user_password(PASSWORD), **row}
    )
    return users


def test_the_stored_hash_is_pbkdf2_sha256_with_a_sixteen_character_salt():
    method, salt, _ = hash_user_password(PASSWORD).split("$")
    assert method.startswith("pbkdf2:sha256")
    assert len(salt) == 16


def test_the_dummy_hash_is_computed_once():
    assert _dummy_hash() is _dummy_hash()


def test_an_active_user_with_the_right_password_is_returned_without_the_hash():
    assert verify_user_password(_users(is_active=True), "alice", PASSWORD) == {
        "id": "u1", "username": "alice", "is_active": True,
    }


def test_an_inactive_user_is_refused_even_with_the_right_password():
    assert verify_user_password(_users(is_active=False), "alice", PASSWORD) is None


def test_a_user_with_no_stored_hash_is_refused():
    users = MagicMock()
    users.get_by_username.return_value = {"id": "u1", "username": "alice", "is_active": True}
    assert verify_user_password(users, "alice", PASSWORD) is None
