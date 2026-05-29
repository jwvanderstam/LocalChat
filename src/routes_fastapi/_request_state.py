"""Thread-local request state — replaces Flask's ``g`` for sync handlers."""

import threading

_local = threading.local()


class _G:
    """Proxy to thread-local storage, mimicking Flask g."""

    def __getattr__(self, name: str):
        return getattr(_local, name, None)

    def __setattr__(self, name: str, value) -> None:
        setattr(_local, name, value)

    def get(self, name: str, default=None):
        return getattr(_local, name, default)


g = _G()
