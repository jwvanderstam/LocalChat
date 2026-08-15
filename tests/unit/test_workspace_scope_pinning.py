"""A request must read from the workspace it was authorised against.

Found by browsing as a viewer: `GET /api/documents/list` with no `X-Workspace-ID`
returned 26 documents — every workspace on the instance — while the same call with
the viewer's own workspace header returned 20. Authorisation resolved to a workspace
they belonged to; the query behind it then ran with `workspace_id=None` and scoped to
nothing.

The fix is the one already applied to API keys: whatever `check_workspace_access`
authorised against is pinned on the request, and `get_workspace_id()` returns it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import Request

from src.security_fastapi import check_workspace_access, create_access_token
from src.utils.workspace import get_workspace_id

OWN_WS = "11111111-1111-1111-1111-111111111111"
OTHER_WS = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"


def _request(headers: dict[str, str], *, member_of: list[str], default_ws: str,
             query_string: bytes = b""):
    db = MagicMock()
    db.is_connected = True
    db.resolve_workspace_api_key.return_value = None
    db.get_default_workspace_id.return_value = default_ws
    db.get_user_workspaces.return_value = [{"id": w} for w in member_of]
    db.get_workspace_member_role.side_effect = (
        lambda ws, uid: "viewer" if ws in member_of else None
    )
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": query_string, "path": "/api/documents/list", "method": "GET",
        "app": MagicMock(),
    }
    req = Request(scope)
    req.scope["app"].state.db = db
    return req


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(USER, {'role': 'user'})}"}


@pytest.mark.unit
class TestScopeIsPinnedForUsers:
    def test_omitted_header_still_yields_a_concrete_workspace(self):
        """The leak: get_workspace_id() returned None, so the query scoped to nothing."""
        req = _request(_auth(), member_of=[OWN_WS], default_ws=OTHER_WS)
        assert check_workspace_access(req, None, "viewer") is None
        assert get_workspace_id(req) == OWN_WS

    def test_the_pinned_workspace_is_the_one_authorised_against(self):
        req = _request(_auth(), member_of=[OWN_WS], default_ws=OTHER_WS)
        check_workspace_access(req, None, "viewer")
        checked = req.scope["app"].state.db.get_workspace_member_role.call_args[0][0]
        assert get_workspace_id(req) == checked

    def test_an_explicit_header_is_still_honoured(self):
        req = _request({**_auth(), "X-Workspace-ID": OWN_WS},
                       member_of=[OWN_WS, OTHER_WS], default_ws=OTHER_WS)
        assert check_workspace_access(req, None, "viewer") is None
        assert get_workspace_id(req) == OWN_WS

    def test_a_refused_request_pins_nothing(self):
        """Nothing to scope by if the caller was not allowed in."""
        req = _request(_auth(), member_of=[], default_ws=OTHER_WS)
        denial = check_workspace_access(req, None, "viewer")
        assert denial is not None
        assert get_workspace_id(req) is None


@pytest.mark.unit
class TestTheQueryParameterFallback:
    """TQ-3. Mutating the `workspace_id` query-parameter name to garbage killed no
    test: every case above sends the header or nothing, so the documented
    query-parameter form of the same scope was never read by a test at all."""

    def test_the_query_parameter_scopes_the_request_when_no_header_is_sent(self):
        req = _request(_auth(), member_of=[OWN_WS], default_ws=OTHER_WS,
                       query_string=f"workspace_id={OWN_WS}".encode())
        assert get_workspace_id(req) == OWN_WS

    def test_a_query_parameter_naming_a_foreign_workspace_is_refused(self):
        """The query parameter is scope, not a shortcut around membership: it selects
        the workspace authorisation runs against, so naming someone else's is a 403
        rather than a widened read."""
        req = _request(_auth(), member_of=[OWN_WS], default_ws=OTHER_WS,
                       query_string=f"workspace_id={OTHER_WS}".encode())
        assert check_workspace_access(req, None, "viewer") == (
            403, "Access denied: not a workspace member"
        )
