"""Workspace request helper — works with Flask and FastAPI request objects."""

from __future__ import annotations

from typing import Any


def get_workspace_id(request: Any = None) -> str | None:
    """Return the workspace ID sent by the client for this request.

    Accepts either a FastAPI Request object (explicit arg) or falls back to
    Flask's thread-local request proxy when called without arguments.
    """
    if request is None:
        from flask import request as flask_request
        req = flask_request
        header = req.headers.get("X-Workspace-ID")
        param = req.args.get("workspace_id")
    else:
        # FastAPI Request: headers is a dict-like, query_params is a dict-like
        header = request.headers.get("X-Workspace-ID")
        params = getattr(request, "query_params", None) or getattr(request, "args", {})
        param = params.get("workspace_id")

    return header or param or None
