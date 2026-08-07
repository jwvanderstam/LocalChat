"""Workspace request helper — resolves workspace scope from the current request."""

from __future__ import annotations

from fastapi import Request


def get_workspace_id(request: Request) -> str | None:
    """Return the workspace scope for this request.

    ``check_workspace_access`` records the workspace it authorised against on
    ``request.state``, and that wins over anything the client sent. Two cases need it:

    * An API key names its own workspace, and a client-supplied one must never widen it.
    * A user request that omits ``X-Workspace-ID`` resolves to one of their workspaces.
      Without pinning, the check passes against that workspace while this function
      still returns ``None`` — and a query scoped by ``None`` runs unscoped, so a
      viewer saw documents from workspaces they are not a member of.
    """
    pinned = getattr(request.state, "resolved_workspace_id", None)
    if pinned:
        return str(pinned)
    return (
        request.headers.get("X-Workspace-ID")
        or request.query_params.get("workspace_id")
        or None
    )
