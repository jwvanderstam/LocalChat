"""
Base Connector Interface
========================

All live-sync connectors implement ``BaseConnector``.  The interface is
intentionally synchronous so connectors can run inside a normal thread
pool without requiring an async event loop in the main Flask process.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class EventType(enum.StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class DocumentSource:
    """A document visible to a connector."""
    source_id: str          # connector-local unique ID (path, S3 key, item ID…)
    filename: str           # basename used when storing in LocalChat
    content_type: str = "application/octet-stream"
    last_modified: datetime | None = None
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentEvent:
    """A change event emitted by a connector's ``poll()`` method."""
    event_type: EventType
    source: DocumentSource


class BaseConnector(ABC):
    """
    Abstract base for all live-sync connectors.

    Subclasses must implement:
        list_sources() — enumerate all documents visible to this connector
        poll()         — return events since the last poll
        fetch(source)  — download raw bytes for a document

    The ``connector_id`` and ``workspace_id`` attributes are set by
    ``ConnectorRegistry`` after the connector is instantiated, so they
    are available throughout the connector's lifecycle.
    """

    # Set by ConnectorRegistry after instantiation
    connector_id: str = ""
    workspace_id: str | None = None

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Short type string, e.g. 'local_folder', 's3', 'webhook'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the admin UI."""

    @abstractmethod
    def list_sources(self) -> list[DocumentSource]:
        """Return all documents currently visible to this connector."""

    @abstractmethod
    def poll(self) -> list[DocumentEvent]:
        """Return change events since the last call to ``poll()``."""

    @abstractmethod
    def fetch(self, source: DocumentSource) -> bytes:
        """Download and return raw document bytes."""

    def validate_config(self) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        return []
