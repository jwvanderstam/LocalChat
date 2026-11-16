"""The core-to-plugin event surface (PC-2): a hook bus and the scheduler that ticks it.

Core code announces an event with ``hook_bus.emit(hook, payload)``; whoever subscribed
reacts. The core never depends on there being a subscriber, and a subscriber that raises
is logged and skipped, so the operation that emitted completes as if it had none.

``emit`` is synchronous and runs every subscriber in the emitting thread. Async code
calls it through ``asyncio.to_thread`` so a slow subscriber cannot stall the event loop.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime

from ..utils.logging_config import get_logger

logger = get_logger(__name__)

#: The hooks the core fires. ``on_route_mount`` is deferred until a plugin needs one:
#: plugins load after the app is assembled, so a router they contribute needs a later mount.
HOOKS = ("on_document_ingested", "on_scheduler_tick", "on_tool_invocation")

Payload = dict[str, object]
Subscriber = Callable[[Payload], None]


class HookBus:
    """Subscribers per hook, each tagged with its owner so a plugin's can be removed together."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[tuple[str, Subscriber]]] = {h: [] for h in HOOKS}

    def subscribe(self, hook: str, owner: str, subscriber: Subscriber) -> None:
        if hook not in HOOKS:
            raise ValueError(f"unknown hook {hook!r}")
        with self._lock:
            self._subscribers[hook].append((owner, subscriber))

    def unsubscribe(self, owner: str) -> None:
        with self._lock:
            for hook in HOOKS:
                self._subscribers[hook] = [s for s in self._subscribers[hook] if s[0] != owner]

    def subscribers(self, hook: str) -> list[str]:
        """The owners subscribed to *hook*, in the order they are called."""
        with self._lock:
            return [owner for owner, _ in self._subscribers[hook]]

    def emit(self, hook: str, payload: Payload) -> None:
        if hook not in HOOKS:
            raise ValueError(f"unknown hook {hook!r}")
        with self._lock:
            subscribers = list(self._subscribers[hook])
        for owner, subscriber in subscribers:
            try:
                # Each gets its own copy: one subscriber mutating the payload must not
                # change what the next one sees.
                subscriber(dict(payload))
            except Exception:  # noqa: BLE001 — a subscriber is best-effort; the core operation completes without it
                logger.exception("[HOOKS] %s subscriber '%s' raised; skipped", hook, owner)


class Scheduler:
    """One daemon thread emitting ``on_scheduler_tick`` every *interval* seconds."""

    def __init__(self, bus: HookBus, interval: float) -> None:
        self._bus = bus
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="core-scheduler", daemon=True)
        self._thread.start()
        logger.info("[HOOKS] Scheduler ticking every %ss", self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)

    def _run(self) -> None:
        tick = 0
        while not self._stop.wait(self._interval):
            tick += 1
            self._bus.emit("on_scheduler_tick", {"tick": tick, "at": datetime.now(UTC).isoformat()})


hook_bus = HookBus()
