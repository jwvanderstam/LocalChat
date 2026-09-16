"""Workspace scope — the value a database query is restricted to.

``workspace_id: str | None`` made "no scope" and "every workspace" the same value,
and the default one. Every query that forgot to pass a workspace silently ran
installation-wide, which is how a workspace-scoped guard came to sit in front of
an unscoped delete (C1/C2). The type here removes that value: a scope is either a
workspace id or :data:`ALL_WORKSPACES`, said out loud.
"""

from __future__ import annotations

from typing import Final


class _AllWorkspaces:
    """Every workspace. Only an explicitly authorised installation-wide path may use it."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "ALL_WORKSPACES"


ALL_WORKSPACES: Final = _AllWorkspaces()

Scope = str | _AllWorkspaces


def scope_predicate(scope: Scope, column: str) -> tuple[str, list[str]]:
    """Return an ``AND``-prefixed SQL fragment and params restricting rows to *scope*.

    *column* is a qualified column name written by the caller, never request data.
    Raises on ``None`` — the whole point is that an unscoped query must not be
    reachable by forgetting an argument.
    """
    if scope is ALL_WORKSPACES:
        return "", []
    if not isinstance(scope, str) or not scope:
        raise ValueError(
            "a workspace scope is required; pass ALL_WORKSPACES for an "
            f"installation-wide operation (got {scope!r})"
        )
    return f" AND {column} = %s", [scope]
