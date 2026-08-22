"""TQ-3, second batch — the workspace authorisation path.

After the first batch the surviving mutants concentrated here, in
``check_workspace_access`` and ``_check_api_key_access``. These are the functions
that decide whether a caller may read or write in a workspace, so a mutation that
survives is a rule nothing was checking.

The sharpest of them is the default in ``_ROLE_LEVELS.get(role, -1)``. Mutated to
``+1`` an unrecognised role outranks ``viewer`` — so a role this application has
never heard of, from a typo in a grant or an older schema, is admitted rather than
refused. Nothing objected, because every existing test uses a role from the table.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.security_fastapi import (
    _check_api_key_access,
    _enforce_workspace_role,
    check_workspace_access,
    create_access_token,
)

pytestmark = pytest.mark.unit

_USER = "88888888-8888-8888-8888-888888888888"
_WS = "ws-1"


def _request(*, token: str | None = None, db=None, api_key: str | None = None) -> MagicMock:
    req = MagicMock()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if api_key:
        headers["X-API-Key"] = api_key
    req.headers.get = lambda k, default="": headers.get(k, default)
    req.cookies = {}
    req.app.state.db = db
    req.query_params = {}
    req.path_params = {}
    # Explicit: get_workspace_id() reads request.state.resolved_workspace_id, and on
    # a bare MagicMock that attribute is a truthy stand-in — so a request meant to
    # carry no workspace silently carries one, and the "no workspace" path is never
    # reached. The same trap tests/utils/auth.py records for three other answers.
    req.state.resolved_workspace_id = None
    return req


def _member_db(role: str | None = "editor") -> MagicMock:
    """A database that answers the workspace-membership path."""
    db = MagicMock()
    db.is_connected = True
    db.get_workspace_member_role.return_value = role
    db.get_default_workspace_id.return_value = _WS
    db.get_user_workspaces.return_value = []
    db.resolve_workspace_api_key.return_value = None
    db.is_token_revoked.return_value = False
    return db


def _key_db(workspace: str = _WS, role: str = "editor") -> MagicMock:
    db = MagicMock()
    db.is_connected = True
    db.resolve_workspace_api_key.return_value = (workspace, role)
    return db


def _user_token() -> str:
    return create_access_token(_USER, {"role": "user"})


class TestUnknownRolesRankBelowEveryone:
    """Mutants 163, 164, 166, 197, 198, 200 — the defaults in the level lookup."""

    def test_a_member_with_an_unrecognised_role_is_refused(self):
        denial = check_workspace_access(
            _request(token=_user_token(), db=_member_db("wizard")), _WS, "viewer"
        )
        assert denial is not None, "an unrecognised role was accepted"
        assert denial[0] == 403

    def test_an_api_key_with_an_unrecognised_role_is_refused(self):
        denial = _check_api_key_access(
            _request(db=_key_db(role="wizard")), "lcw_key", _WS, "viewer"
        )
        assert denial is not None
        assert denial[0] == 403

    def test_a_viewer_still_satisfies_a_viewer_requirement(self):
        """Over-correction guard: the minimum's default mutated upward would raise
        the bar for every known role and lock viewers out of reading."""
        assert check_workspace_access(
            _request(token=_user_token(), db=_member_db("viewer")), _WS, "viewer"
        ) is None

    def test_an_api_key_viewer_still_satisfies_a_viewer_requirement(self):
        assert _check_api_key_access(
            _request(db=_key_db(role="viewer")), "lcw_key", _WS, "viewer"
        ) is None

    def test_an_owner_outranks_an_editor_requirement(self):
        """The ordering itself, so the table cannot be flattened unnoticed."""
        assert check_workspace_access(
            _request(token=_user_token(), db=_member_db("owner")), _WS, "editor"
        ) is None


class TestDatabasePreconditions:
    """Mutants 152, 185, 192 — the guard, in both entry points."""

    def test_no_database_is_a_503_rather_than_an_exception(self):
        """`db is None or ...` mutated to `and` reaches None.is_connected and the
        guard raises AttributeError instead of answering."""
        denial = check_workspace_access(_request(token=_user_token(), db=None), _WS, "viewer")
        assert denial == (503, "Database unavailable")

    def test_no_database_is_a_503_on_the_api_key_path_too(self):
        denial = _check_api_key_access(_request(db=None), "lcw_key", _WS, "viewer")
        assert denial == (503, "Database unavailable")

    def test_no_resolvable_workspace_says_so(self):
        """No requested workspace, none of the caller's own, and no default."""
        db = _member_db()
        db.get_default_workspace_id.return_value = None
        denial = check_workspace_access(_request(token=_user_token(), db=db), None, "viewer")
        assert denial == (400, "No workspace context")


class TestDenialMessages:
    """Mutants 153, 156, 162, 167, 186, 201 — what the caller is actually told.

    A route hands these straight to the client, so a mutated string is a changed
    response rather than a cosmetic detail.
    """

    def test_an_unknown_api_key_is_named_as_such(self):
        db = _key_db()
        db.resolve_workspace_api_key.return_value = None
        assert _check_api_key_access(_request(db=db), "lcw_x", _WS, "viewer") == (
            401, "Invalid or revoked API key"
        )

    def test_a_key_for_another_workspace_is_named_as_such(self):
        """The rule that keeps a key scoped: a requested workspace may be compared
        against the key's own, never substituted for it."""
        assert _check_api_key_access(
            _request(db=_key_db(workspace="ws-other")), "lcw_x", _WS, "viewer"
        ) == (403, "API key is not valid for this workspace")

    def test_an_underpowered_key_names_the_role_it_needs(self):
        assert _check_api_key_access(
            _request(db=_key_db(role="viewer")), "lcw_x", _WS, "owner"
        ) == (403, "API key requires owner role or higher")

    def test_an_underpowered_member_names_the_role_they_need(self):
        assert check_workspace_access(
            _request(token=_user_token(), db=_member_db("viewer")), _WS, "owner"
        ) == (403, "Requires owner role or higher")

    def test_a_non_member_is_named_as_a_non_member(self):
        """BUG-3: None once meant "no role to object to", and let non-members in."""
        assert check_workspace_access(
            _request(token=_user_token(), db=_member_db(None)), _WS, "viewer"
        ) == (403, "Access denied: not a workspace member")


class TestEnforceWorkspaceRole:
    """Mutants 203-210 — the wrapper that turns a denial into an HTTPException."""

    def test_a_denial_becomes_an_exception_carrying_its_message(self):
        """`denial = None`, or an inverted `is None`, stops the refusal happening at
        all and the caller proceeds with no error anywhere."""
        request = _request(token=_user_token(), db=_member_db(None))
        with pytest.raises(HTTPException) as exc_info:
            _enforce_workspace_role(request, _WS, None, "viewer")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["message"] == "Access denied: not a workspace member"

    def test_an_allowed_caller_gets_their_own_identity_back(self):
        """Either half of `claims.get("sub") or "admin"` mutated hands the route a
        different identity than the one that authenticated."""
        result = _enforce_workspace_role(
            _request(token=_user_token(), db=_member_db()), _WS, None, "viewer"
        )
        assert result == _USER

    def test_an_api_key_caller_is_identified_as_the_admin_placeholder(self):
        """The one path that reaches the fallback in `claims.get("sub") or "admin"`.

        An API key carries no bearer claims, so there is no subject to return and
        the literal is what routes receive as the caller's identity. Every test
        using a token has a subject, so the fallback was never exercised — and a
        mutated literal would have silently become the identity instead.
        """
        db = _key_db()
        result = _enforce_workspace_role(
            _request(api_key="lcw_key", db=db), _WS, None, "viewer"
        )
        assert result == "admin"

    def test_claims_are_read_from_the_request_when_none_are_passed(self):
        """`_get_token_claims(credentials) or _claims_from_request(request)` mutated
        to `and` yields None for a direct call, and .get() then raises."""
        assert _enforce_workspace_role(
            _request(token=_user_token(), db=_member_db()), _WS, None, "viewer"
        ) == _USER
