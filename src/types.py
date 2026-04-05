
"""
Custom Type Definitions
=======================

Typed Flask subclass that declares the custom attributes set on the
application object by the factory (``app_factory.py``).  Importing and
using ``LocalChatApp`` instead of plain ``Flask`` in type annotations
silences Pyright / Pylance ``reportAttributeAccessIssue`` warnings
without adding ``# type: ignore`` comments everywhere.

Author: LocalChat Team
Created: 2025-01-27
"""

from typing import Any, Dict, Optional

from flask import Flask


class LocalChatApp(Flask):
    """Flask subclass with LocalChat-specific attributes declared for type checkers."""

    db: Any
    ollama_client: Any
    doc_processor: Any
    startup_status: dict[str, bool]
    embedding_cache: Any | None
    query_cache: Any | None
    security_enabled: bool
    swagger: Any
    plugin_loader: Any
