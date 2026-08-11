"""Authenticate a test caller for real, instead of switching authorisation off.

Before TQ-1b, tests set ``app.state.testing = True`` and every check short-circuited.
That made the whole suite prove behaviour *without* authorisation — the one condition
the application never runs in. These helpers replace it: a genuine JWT, and an app
state wired so the checks it meets can actually answer.

Three of those wirings are not obvious, and each fails in a way that looks like the
route being tested is broken:

* ``is_token_revoked`` — revocation is fail-closed (SEC-2). A bare ``MagicMock``
  returns a truthy stand-in, so every token reads as revoked and every request 401s.
* ``get_user_workspaces`` — a request without ``X-Workspace-ID`` resolves scope from
  the caller's own workspaces. A truthy stand-in silently becomes the workspace under
  test.
* ``get_workspace_member_role`` — ``None`` means "not a member", which is a 403. It
  has to be set to the role the test intends.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.security_fastapi import create_access_token

#: Stable identities, so a failure names a recognisable subject rather than a UUID.
USER_ID = "33333333-3333-3333-3333-333333333333"
ADMIN_ID = "44444444-4444-4444-4444-444444444444"
WORKSPACE_ID = "11111111-1111-1111-1111-111111111111"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-0000000000ff"


def auth_headers(user_id: str = USER_ID, role: str = "user", **extra: str) -> dict[str, str]:
    """Bearer header carrying a real, signed token for *user_id*."""
    token = create_access_token(user_id, {"role": role})
    return {"Authorization": f"Bearer {token}", **extra}


def admin_headers(user_id: str = ADMIN_ID, **extra: str) -> dict[str, str]:
    return auth_headers(user_id, role="admin", **extra)


def authorise_db(
    db: Any, *, role: str = "user", member_role: str | None = "editor", monkeypatch: Any = None
) -> Any:
    """Make *db* answer the calls the security layer makes.

    Only those calls; anything the test set up itself is left alone. Returns *db* so it
    can be used inline.

    Pass ``monkeypatch`` when *db* is the real singleton rather than a mock — its methods
    are bound and shared between tests, so they must be replaced reversibly. Without it,
    setting ``.return_value`` on a bound method raises AttributeError.
    """
    answers = {
        "is_token_revoked": False,
        "get_workspace_member_role": member_role,
        "get_default_workspace_id": DEFAULT_WORKSPACE_ID,
        "get_user_workspaces": [],
        "resolve_workspace_api_key": None,
        "get_user_by_id": {"id": USER_ID, "role": role},
    }
    if monkeypatch is not None:
        monkeypatch.setattr(db, "is_connected", True, raising=False)
        for name, value in answers.items():
            monkeypatch.setattr(db, name, MagicMock(return_value=value), raising=False)
    else:
        db.is_connected = True
        for name, value in answers.items():
            getattr(db, name).return_value = value
    return db


def authenticated_state(
    *,
    role: str = "user",
    member_role: str | None = "editor",
    workspaces: list[dict[str, Any]] | None = None,
    db: Any = None,
    **attrs: Any,
) -> MagicMock:
    """An ``app.state`` whose database answers the authorisation path.

    ``member_role`` is what ``get_workspace_member_role`` returns — ``None`` makes the
    caller a non-member, which is how a 403 is set up deliberately. Pass ``db`` to keep
    a database the test has already built; its authorisation answers are filled in only
    where the test has not set them.
    """
    state = MagicMock()
    state.db = db if db is not None else MagicMock()
    state.db.is_connected = True
    state.db.is_token_revoked.return_value = False
    state.db.get_workspace_member_role.return_value = member_role
    state.db.get_default_workspace_id.return_value = DEFAULT_WORKSPACE_ID
    state.db.get_user_workspaces.return_value = workspaces if workspaces is not None else []
    state.db.resolve_workspace_api_key.return_value = None
    # Some routes read the role from the record rather than the token — the workspace
    # switcher is one. Keep *role* equal to the role in the header, or the caller is an
    # admin to one check and a plain user to the next.
    state.db.get_user_by_id.return_value = {"id": USER_ID, "role": role}
    for name, value in attrs.items():
        setattr(state, name, value)
    return state
