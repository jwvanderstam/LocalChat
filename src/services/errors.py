"""The one error a service raises to refuse a request (ADR-7).

A service decides; the route maps the decision to a response. Carrying the status
here keeps that mapping one line per route instead of one ``except`` per reason.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ..db.connection import NotRetiredError


class ServiceError(Exception):
    """A refusal the caller should see. ``message`` is safe to send as-is."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@contextmanager
def purge_refusals(what: str) -> Iterator[None]:
    """A purge of a missing row is a 404; of a live one, a 409 (R-9)."""
    try:
        yield
    except NotRetiredError as exc:
        if exc.missing:
            raise ServiceError(404, f"{what} not found") from exc
        raise ServiceError(409, f"{what} must be retired before it is purged") from exc
