"""The one error a service raises to refuse a request (ADR-7).

A service decides; the route maps the decision to a response. Carrying the status
here keeps that mapping one line per route instead of one ``except`` per reason.
"""

from __future__ import annotations


class ServiceError(Exception):
    """A refusal the caller should see. ``message`` is safe to send as-is."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
