"""Workspace request helper — resolves workspace scope from the current request."""

from __future__ import annotations

from fastapi import Request


def get_workspace_id(request: Request) -> str | None:
    """Return the workspace ID sent by the client for this request."""
    return (
        request.headers.get("X-Workspace-ID")
        or request.query_params.get("workspace_id")
        or None
    )
