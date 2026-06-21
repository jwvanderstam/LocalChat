"""Request ID middleware for FastAPI.

Assigns a unique request ID to every incoming request, stores it in a
ContextVar for log injection, and echoes it in the X-Request-ID response header.
Accepts an X-Request-ID header from an upstream proxy (Nginx, Traefik) so that
end-to-end tracing works without changes to client code.
"""

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging_config import sanitize_log_value as _slv

_HEADER = "X-Request-ID"
_access_logger = logging.getLogger("access")

#: ContextVar holding the request ID for the current async context.
#: Read by RequestIdFilter in logging_config.py to inject into every log record.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request ID to every incoming HTTP request.

    Reads X-Request-ID from the upstream proxy if present (and ≤128 chars),
    generates a UUID4 otherwise. Stores the ID in request_id_var so that
    every log record in this async context carries it, and echoes it in
    the X-Request-ID response header. Also logs a structured access record
    to the 'access' logger after each request completes.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(_HEADER, "")
        request_id = incoming if incoming and len(incoming) <= 128 else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[_HEADER] = request_id
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            _access_logger.info(
                "%s %s %d",
                _slv(request.method),
                _slv(request.url.path),
                response.status_code,
                extra={
                    "method": _slv(request.method),
                    "path": _slv(request.url.path),
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            request_id_var.reset(token)
