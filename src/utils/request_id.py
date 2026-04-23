"""
Request ID Middleware
====================

Assigns a unique ``request_id`` to every incoming HTTP request and stores it
on ``flask.g`` so that it can be:

  * Injected into every log record via ``RequestIdFilter``
  * Echoed back in the ``X-Request-ID`` response header
  * Propagated to downstream services via the outgoing ``X-Request-ID`` header

The middleware accepts an ``X-Request-ID`` header from an upstream proxy
(e.g., Nginx, Traefik) so that end-to-end tracing works without changes to
client code.

Usage::

    from src.utils.request_id import init_request_id
    init_request_id(app)

"""

import logging
import time
import uuid

from flask import Flask, g, request

from .logging_config import sanitize_log_value as _slv

_HEADER = "X-Request-ID"
_access_logger = logging.getLogger("access")


def _get_or_generate() -> str:
    """Return the incoming request-id header or generate a fresh UUID4."""
    incoming = request.headers.get(_HEADER)
    if incoming and len(incoming) <= 128:  # basic sanity-check on length
        return incoming
    return str(uuid.uuid4())


def init_request_id(app: Flask) -> None:
    """
    Register before/after request hooks that manage ``g.request_id``.

    Args:
        app: Flask application instance.

    After calling this function every request will have:
      - ``flask.g.request_id`` set (UUID4 or value from upstream header)
      - ``X-Request-ID`` echoed in the response headers
    """

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = _get_or_generate()
        g.request_start_time = time.perf_counter()

    @app.after_request
    def _echo_request_id(response):
        response.headers[_HEADER] = getattr(g, "request_id", "")
        duration_ms = round(
            (time.perf_counter() - getattr(g, "request_start_time", time.perf_counter())) * 1000, 1
        )
        _access_logger.info(
            "%s %s %d",
            request.method, _slv(request.path), response.status_code,
            extra={
                "method": request.method,
                "path": _slv(request.path),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "model": getattr(g, "model", None),
                "chunks_retrieved": getattr(g, "chunks_retrieved", None),
            },
        )
        return response
