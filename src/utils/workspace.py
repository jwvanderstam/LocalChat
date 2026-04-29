"""Workspace request helper."""

from flask import request


def get_workspace_id() -> str | None:
    """Return the workspace ID sent by the client for this request.

    The frontend sends ``X-Workspace-ID`` on every scoped request so that
    each worker reads the value directly from the request rather than from
    any shared server-side state.
    """
    return request.headers.get('X-Workspace-ID') or request.args.get('workspace_id') or None
