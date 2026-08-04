"""Shared workspace-authorisation helper for route modules.

Wraps ``check_workspace_access`` in the ``{"success": False, "message": ...}`` envelope
the route layer already uses, so the security module stays free of response shaping.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from ..security_fastapi import check_workspace_access


def deny(request: Request, workspace_id: str | None, min_role: str) -> JSONResponse | None:
    """Return an error response when the caller lacks *min_role*, else ``None``.

    Pass ``workspace_id=None`` for header-scoped routes; scope then resolves from
    ``X-Workspace-ID`` (or the ``workspace_id`` query param) and falls back to the
    default workspace. Pass the path value explicitly when the route has one.
    """
    denial = check_workspace_access(request, workspace_id, min_role)
    if denial is None:
        return None
    code, message = denial
    return JSONResponse({"success": False, "message": message}, status_code=code)
