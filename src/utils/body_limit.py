"""A ceiling on how many bytes a request body may carry (audit S5).

Every JSON route reads its body whole with ``await request.json()``, so a large enough
body was a way to exhaust memory. The upload route is exempt: it may carry several
files, each held to ``MAX_CONTENT_LENGTH`` while it streams to disk, so a total cap
equal to one file's limit would refuse a legitimate multi-file upload.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.responses import JSONResponse

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Answer 413 when a body exceeds *max_bytes*, declared or as it arrives.

    Both checks matter: a client can declare a small Content-Length and send more,
    or send chunked with no length at all.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, exempt_paths: frozenset[str]) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        if self._declared_length(scope) > self.max_bytes:
            await self._refuse(scope, receive, send)
            return

        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if started:
                raise
            await self._refuse(scope, receive, send)

    @staticmethod
    def _declared_length(scope: Scope) -> int:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return 0  # malformed: the server's own parser refuses it
        return 0

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"success": False, "message": f"Request body larger than {self.max_bytes} bytes"},
            status_code=413,
        )
        await response(scope, receive, send)
