"""
Webhook Connector
=================

Receives document push events over HTTP.  Any external system can POST
to ``/api/connectors/<connector_id>/webhook`` to notify LocalChat of a
new, modified, or deleted document.

The connector maintains an in-memory queue of pending events that the
``SyncWorker`` drains on each poll cycle.

Expected POST body:
    {
        "event_type": "added" | "modified" | "deleted",
        "source_id":  "<opaque identifier>",
        "filename":   "<basename used for storage>",
        "content_type": "<mime type>",          // optional
        "fetch_url":  "<URL to download doc>",  // required for added/modified
        "metadata":   {}                         // optional
    }

Config keys:
    secret  (optional) Shared secret — if set the POST must include
                       ``X-LocalChat-Secret: <secret>`` header.
"""

from __future__ import annotations

import ipaddress
import queue
import threading
from typing import Any
from urllib.parse import urlparse

from ..utils.logging_config import get_logger
from .base import BaseConnector, DocumentEvent, DocumentSource, EventType

logger = get_logger(__name__)

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),  # NOSONAR — intentional SSRF block-list
    ipaddress.ip_network("172.16.0.0/12"),  # NOSONAR
    ipaddress.ip_network("192.168.0.0/16"),  # NOSONAR
    ipaddress.ip_network("169.254.0.0/16"),  # NOSONAR — link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_fetch_url(url: str) -> None:
    """Raise ValueError if url is not a safe public https URL."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"fetch_url must use https (got {parsed.scheme!r})")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("fetch_url has no hostname")
    try:
        addr = ipaddress.ip_address(hostname)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                raise ValueError(f"fetch_url resolves to a private/reserved address: {addr}")
    except ValueError as exc:
        if "private" in str(exc) or "reserved" in str(exc):
            raise
        # hostname is a domain name — DNS resolution happens in urlopen;
        # we can't block at this layer without a DNS lookup, but scheme
        # and structural checks cover the most common SSRF vectors.


class WebhookConnector(BaseConnector):
    """Receives push events from external systems."""

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._queue: queue.Queue[DocumentEvent] = queue.Queue()
        self._lock = threading.Lock()

    @property
    def connector_type(self) -> str:
        return "webhook"

    @property
    def display_name(self) -> str:
        return f"Webhook ({self.connector_id or 'unconfigured'})"

    def push_event(self, payload: dict[str, Any]) -> list[str]:
        """Called by the route handler when a POST arrives.

        Returns a list of validation errors (empty = accepted).
        """
        errors = self._validate_payload(payload)
        if errors:
            return errors

        event_type_str = payload.get("event_type", "").lower()
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            return [f"Unknown event_type: {event_type_str!r}"]

        source = DocumentSource(
            source_id=payload["source_id"],
            filename=payload.get("filename") or payload["source_id"],
            content_type=payload.get("content_type", "application/octet-stream"),
            metadata={
                **payload.get("metadata", {}),
                "fetch_url": payload.get("fetch_url", ""),
            },
        )
        self._queue.put(DocumentEvent(event_type, source))
        logger.info(f"[Webhook] Queued {event_type.value} event for {source.filename}")
        return []

    def list_sources(self) -> list[DocumentSource]:
        # Webhooks are push-only — no enumeration.
        return []

    def poll(self) -> list[DocumentEvent]:
        """Drain the event queue and return all pending events."""
        events: list[DocumentEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def fetch(self, source: DocumentSource) -> bytes:
        """Download document bytes from the URL provided in the event payload."""
        fetch_url = source.metadata.get("fetch_url", "")
        if not fetch_url:
            raise ValueError(f"No fetch_url in webhook event for {source.filename}")
        _validate_fetch_url(fetch_url)
        import urllib.request
        with urllib.request.urlopen(fetch_url, timeout=30) as resp:  # noqa: S310
            return resp.read()

    # ------------------------------------------------------------------

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> list[str]:  # noqa: C901
        errors: list[str] = []
        if not payload.get("source_id", "").strip():
            errors.append("'source_id' is required")
        event_type = payload.get("event_type", "")
        if event_type not in ("added", "modified", "deleted"):
            errors.append(f"'event_type' must be added/modified/deleted, got {event_type!r}")
        if event_type in ("added", "modified") and not payload.get("fetch_url", "").strip():
            errors.append("'fetch_url' is required for added/modified events")
        return errors
