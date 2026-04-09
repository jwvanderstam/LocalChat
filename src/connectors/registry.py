"""
Connector Registry
==================

Singleton that maps connector types to implementation classes, and manages
the in-process lifecycle (create, enable, disable) of connector instances.

The persistent state (connector configs, sync timestamps) lives in the
``connectors`` DB table via ``ConnectorsMixin``.  This registry holds the
live Python instances in memory and is the single source of truth for
which connectors are currently active.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Type

from ..utils.logging_config import get_logger
from .base import BaseConnector
from .local_folder import LocalFolderConnector
from .s3_connector import S3Connector
from .webhook import WebhookConnector

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_CONNECTOR_CLASSES: dict[str, type[BaseConnector]] = {
    "local_folder": LocalFolderConnector,
    "s3": S3Connector,
    "webhook": WebhookConnector,
}


class ConnectorRegistry:
    """Thread-safe registry of live connector instances."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._instances: dict[str, BaseConnector] = {}  # connector_id → instance

    # ------------------------------------------------------------------
    # Type registry
    # ------------------------------------------------------------------

    @staticmethod
    def available_types() -> list[str]:
        """Return the list of connector type strings supported by this build."""
        return list(_CONNECTOR_CLASSES.keys())

    @staticmethod
    def get_class(connector_type: str) -> type[BaseConnector] | None:
        return _CONNECTOR_CLASSES.get(connector_type)

    # ------------------------------------------------------------------
    # Instance management
    # ------------------------------------------------------------------

    def load_from_db(self, db) -> None:
        """Instantiate all enabled connectors from the database on startup."""
        if not db.is_connected:
            return
        rows = db.list_connectors(enabled_only=True)
        for row in rows:
            self._load_row(row)
        logger.info(f"[Connectors] Loaded {len(self._instances)} connector(s) from DB")

    def _load_row(self, row: dict[str, Any]) -> BaseConnector | None:
        connector_id = row["id"]
        connector_type = row["connector_type"]
        cls = _CONNECTOR_CLASSES.get(connector_type)
        if cls is None:
            logger.warning(f"[Connectors] Unknown type {connector_type!r} for id={connector_id}")
            return None
        try:
            instance = cls(row.get("config") or {})
            instance.connector_id = connector_id
            instance.workspace_id = row.get("workspace_id")
            with self._lock:
                self._instances[connector_id] = instance
            return instance
        except Exception as exc:
            logger.warning(f"[Connectors] Failed to instantiate {connector_type}: {exc}")
            return None

    def add(self, connector_id: str, connector_type: str, config: dict[str, Any],
            workspace_id: str | None = None) -> BaseConnector:
        """Create and register a new connector instance."""
        cls = _CONNECTOR_CLASSES.get(connector_type)
        if cls is None:
            raise ValueError(f"Unknown connector type: {connector_type!r}")
        instance = cls(config)
        instance.connector_id = connector_id
        instance.workspace_id = workspace_id
        with self._lock:
            self._instances[connector_id] = instance
        return instance

    def remove(self, connector_id: str) -> None:
        with self._lock:
            self._instances.pop(connector_id, None)

    def get(self, connector_id: str) -> BaseConnector | None:
        return self._instances.get(connector_id)

    def all_instances(self) -> list[BaseConnector]:
        with self._lock:
            return list(self._instances.values())


# Global singleton — imported by app_factory and connector_routes
connector_registry = ConnectorRegistry()
