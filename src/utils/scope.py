"""Workspace scope — the value a database query is restricted to.

``workspace_id: str | None`` made "no scope" and "every workspace" the same value,
and the default one. Every query that forgot to pass a workspace silently ran
installation-wide, which is how a workspace-scoped guard came to sit in front of
an unscoped delete (C1/C2). The type here removes that value: a scope is either a
workspace id or :data:`ALL_WORKSPACES`, said out loud.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
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


# ── Request-scoped ambient scope ──────────────────────────────────────────────
#
# LLM tools are called by the model mid-answer, through a registry that knows
# nothing about the request. Threading a workspace argument through every tool
# signature would put it on tools that have no use for it, so the request sets it
# once and the retrieval tools read it. Reading it when nothing set it raises:
# an unscoped retrieval is the defect, not the default.

_REQUEST_SCOPE: ContextVar[Scope | None] = ContextVar("localchat_request_scope", default=None)


class ScopeUnavailableError(RuntimeError):
    """Raised when a scoped operation runs outside a request that set one."""


@contextmanager
def request_scope(scope: Scope) -> Iterator[None]:
    """Bind *scope* for the duration of the block, then restore the previous one."""
    token = _REQUEST_SCOPE.set(scope)
    try:
        yield
    finally:
        _REQUEST_SCOPE.reset(token)


def current_request_scope() -> Scope:
    """The scope the current request was authorised for.

    Raises rather than returning None: every caller of this is about to query
    documents, and "no scope" used to mean "every workspace" (audit C3).
    """
    scope = _REQUEST_SCOPE.get()
    if scope is None:
        raise ScopeUnavailableError(
            "no workspace scope is bound to this request — a retrieval tool ran "
            "outside request_scope(), which would otherwise search every workspace"
        )
    return scope


def bind_request_scope(scope: Scope) -> Token[Scope | None]:
    """Bind *scope* and return the token needed to undo it.

    The token form exists for the SSE generator, whose body cannot be wrapped in a
    ``with`` block without reindenting it — it binds here and resets in the
    ``finally`` it already has.
    """
    return _REQUEST_SCOPE.set(scope)


def reset_request_scope(token: Token[Scope | None]) -> None:
    """Undo the binding *token* came from."""
    _REQUEST_SCOPE.reset(token)
