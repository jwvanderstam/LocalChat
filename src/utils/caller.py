"""The caller of the current request, bound for code the model calls.

A tool runs because the model asked for it, so it has no request to read the caller
from, the same reason the workspace scope is bound in :mod:`src.utils.scope`. The chat
route binds both for the life of its stream. A plugin reads the caller through its
``identity`` handle, and the tool executor checks each tool's minimum role against it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

#: Workspace roles in ascending order, then the global administrator above all of them.
ROLE_LEVELS: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2, "admin": 3}


@dataclass(frozen=True)
class RequestCaller:
    """Who the request was authorised as, and at what role."""

    #: None for a workspace API key, which is not a user.
    user_id: str | None
    #: The role the workspace guard admitted: a workspace role, or ``admin``.
    role: str
    via_api_key: bool = False

    def has_role(self, min_role: str) -> bool:
        """True when this caller's role is at least *min_role*; an unknown role is never met."""
        if min_role not in ROLE_LEVELS:
            return False
        return ROLE_LEVELS.get(self.role, -1) >= ROLE_LEVELS[min_role]


_REQUEST_CALLER: ContextVar[RequestCaller | None] = ContextVar("localchat_request_caller", default=None)


def bind_request_caller(caller: RequestCaller | None) -> Token[RequestCaller | None]:
    return _REQUEST_CALLER.set(caller)


def reset_request_caller(token: Token[RequestCaller | None]) -> None:
    _REQUEST_CALLER.reset(token)


@contextmanager
def request_caller(caller: RequestCaller | None) -> Iterator[None]:
    """Bind *caller* for the duration of the block, then restore the previous one."""
    token = _REQUEST_CALLER.set(caller)
    try:
        yield
    finally:
        _REQUEST_CALLER.reset(token)


def current_request_caller() -> RequestCaller | None:
    """The bound caller, or None outside a request; callers treat None as the lowest role."""
    return _REQUEST_CALLER.get()


def caller_has_role(min_role: str) -> bool:
    """True when the bound caller meets *min_role*. With no caller bound only ``viewer`` is met."""
    caller = _REQUEST_CALLER.get()
    if caller is None:
        return min_role == "viewer"
    return caller.has_role(min_role)
