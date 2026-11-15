"""An id that cannot exist is refused as the caller's mistake, never a 500.

A path parameter typed ``str`` reached Postgres as text, a ``UUID`` column refused
``not-a-uuid`` with ``invalid_text_representation``, and the route's own broad ``except``
answered 500. Nothing leaked, but a 500 pages someone and says the server is broken when
the request is. A UUID path id is now typed ``UuidId`` and refused with a 422, as an ``int``
one always was; a malformed ``X-Workspace-ID`` is a 400 from the workspace guard.

Driven over HTTP as an admin, so every guard admits the request and it reaches the
database. The routes come from the same derivation as the object-authorisation matrix.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.slow]

httpx = pytest.importorskip("httpx", reason="driven over HTTP")

from tests.e2e.conftest import (  # noqa: E402,F401
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    live_server,
)
from tests.integration.test_object_authorization_over_the_wire import (  # noqa: E402
    _BODIES,
    _PARAM_RE,
    _login,
    _server_errors,
    _status,
    object_routes,
    server_env,  # noqa: F401
)

#: Not a UUID, and past bigint: between them every id column type refuses one.
_MALFORMED = ("not-a-uuid", "99999999999999999999")


@pytest.fixture(scope="module")
def admin(live_server: str) -> httpx.Client:
    return _login(live_server, ADMIN_USERNAME, ADMIN_PASSWORD)


def _probe(admin: httpx.Client, method: str, path: str, value: str, **kwargs: Any) -> int | str:
    url = _PARAM_RE.sub(value, path)
    body = _BODIES.get((method, path), {}) if method in {"POST", "PUT", "PATCH"} else None
    return _status(admin, method, url, json=body, **kwargs)


def test_a_malformed_id_in_the_path_is_never_a_server_error(admin: httpx.Client) -> None:
    errors = {
        f"{method} {path} [{value}]": status
        for method, path in object_routes()
        for value in _MALFORMED
        if not isinstance(status := _probe(admin, method, path, value), int) or status >= 500
    }
    assert errors == {}, _server_errors(admin)


def test_a_malformed_id_is_refused_at_the_boundary_and_a_well_formed_one_is_not(
    admin: httpx.Client,
) -> None:
    """A malformed UUID is a 422; a well-formed one nobody holds still reaches the database."""
    absent = "00000000-0000-0000-0000-000000000000"
    statuses = [
        _probe(admin, "DELETE", "/api/users/{user_id}", "not-a-uuid"),
        _probe(admin, "GET", "/api/conversations/{conversation_id}", "not-a-uuid"),
        _probe(admin, "DELETE", "/api/users/{user_id}", absent),
        _probe(admin, "GET", "/api/conversations/{conversation_id}", absent),
        _probe(admin, "DELETE", "/api/documents/{doc_id}", "99999999999999999999"),
    ]
    assert statuses == [422, 422, 404, 404, 404], _server_errors(admin)


#: ``uuid.UUID`` accepts the urn form; Postgres does not.
_MALFORMED_WORKSPACES = ("not-a-uuid", "urn:uuid:00000000-0000-0000-0000-000000000000")


@pytest.mark.parametrize("value", _MALFORMED_WORKSPACES)
@pytest.mark.parametrize(
    "method,path",
    [("GET", "/api/documents/list"), ("GET", "/api/workspaces/active")],
)
def test_a_malformed_workspace_header_is_a_400(
    admin: httpx.Client, method: str, path: str, value: str
) -> None:
    """``/workspaces/active`` hands the header to the guard itself; the others leave it to the guard."""
    status = _status(admin, method, path, headers={"X-Workspace-ID": value})
    assert status == 400, _server_errors(admin)


@pytest.mark.parametrize("value", _MALFORMED_WORKSPACES)
def test_a_malformed_workspace_in_a_body_is_a_400(admin: httpx.Client, value: str) -> None:
    status = _status(admin, "POST", "/api/workspaces/switch", json={"workspace_id": value})
    assert status == 400, _server_errors(admin)


def test_the_callers_own_workspace_is_still_admitted(admin: httpx.Client) -> None:
    """The control: without it, a guard refusing every workspace would pass the tests above."""
    own = admin.get("/api/workspaces").json()["workspaces"][0]["id"]
    statuses = [
        _status(admin, "GET", "/api/documents/list", headers={"X-Workspace-ID": own}),
        _status(admin, "GET", "/api/workspaces/active", headers={"X-Workspace-ID": own}),
        _status(admin, "POST", "/api/workspaces/switch", json={"workspace_id": own}),
    ]
    assert statuses == [200, 200, 200], _server_errors(admin)
