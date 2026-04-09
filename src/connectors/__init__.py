"""
Connectors Package
==================

Live document connectors that automatically keep the LocalChat knowledge base
in sync with external sources (local folders, S3, webhooks, etc.).

Public API:
    ConnectorRegistry  — singleton that manages connector lifecycles
    SyncWorker         — background thread that polls enabled connectors
    BaseConnector      — ABC that all connectors implement
"""

from .base import BaseConnector, DocumentEvent, DocumentSource, EventType
from .registry import ConnectorRegistry
from .worker import SyncWorker

__all__ = [
    "BaseConnector",
    "DocumentEvent",
    "DocumentSource",
    "EventType",
    "ConnectorRegistry",
    "SyncWorker",
]
