"""``get_caller()`` reads only what the workspace guard recorded, and only well-typed values.

The guard always records a string role, a string or no user id, and a bool, so the tests
that go through it never reach the branches that refuse anything else. These do, directly:
the nightly mutation gate found nine mutants of this function that no test failed on.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.utils.caller import RequestCaller
from src.utils.workspace import get_caller

pytestmark = pytest.mark.unit

_USER = "00000000-0000-4000-8000-000000000042"


def _request(**state: object) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(**state))


def test_a_request_no_guard_admitted_has_no_caller():
    assert get_caller(_request()) is None  # type: ignore[arg-type]


def test_a_role_that_is_not_a_string_is_no_caller():
    assert get_caller(_request(resolved_role=3, resolved_user_id=_USER)) is None  # type: ignore[arg-type]


def test_a_recorded_user_is_returned_with_their_role():
    caller = get_caller(_request(resolved_role="editor", resolved_user_id=_USER,  # type: ignore[arg-type]
                                 resolved_via_api_key=False))
    assert caller == RequestCaller(user_id=_USER, role="editor", via_api_key=False)


def test_a_user_id_that_is_not_a_string_is_recorded_as_no_user():
    caller = get_caller(_request(resolved_role="viewer", resolved_user_id=42))  # type: ignore[arg-type]
    assert caller == RequestCaller(user_id=None, role="viewer", via_api_key=False)


def test_a_role_without_a_user_or_key_flag_is_a_user_less_non_key_caller():
    caller = get_caller(_request(resolved_role="owner"))  # type: ignore[arg-type]
    assert caller == RequestCaller(user_id=None, role="owner", via_api_key=False)


def test_an_api_key_is_recorded_only_for_true_itself():
    keyed = get_caller(_request(resolved_role="viewer", resolved_via_api_key=True))  # type: ignore[arg-type]
    truthy = get_caller(_request(resolved_role="viewer", resolved_via_api_key="yes"))  # type: ignore[arg-type]
    assert keyed == RequestCaller(user_id=None, role="viewer", via_api_key=True)
    assert truthy == RequestCaller(user_id=None, role="viewer", via_api_key=False)
