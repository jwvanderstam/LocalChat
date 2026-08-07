"""Workspace request helper — resolves workspace scope from the current request."""

from __future__ import annotations

from fastapi import Request


def get_workspace_id(request: Request) -> str | None:
    """Return the workspace scope for this request.

    A workspace API key pins the scope: ``check_workspace_access`` records the key's
    own workspace on ``request.state`` and it wins over anything the client sent.
    Without that, a key-authenticated request omitting ``X-Workspace-ID`` would fall
    through to the *default* workspace downstream — the key would authorise against
    one workspace and then read another.
    """
    pinned = getattr(request.state, "api_key_workspace_id", None)
    if pinned:
        return str(pinned)
    return (
        request.headers.get("X-Workspace-ID")
        or request.query_params.get("workspace_id")
        or None
    )
