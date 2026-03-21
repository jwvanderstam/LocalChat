# -*- coding: utf-8 -*-

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

from flask import Flask
from typing import Any, Dict, Optional


class LocalChatApp(Flask):
    """Flask subclass with LocalChat-specific attributes declared for type checkers."""

    db: Any
    ollama_client: Any
    doc_processor: Any
    startup_status: Dict[str, bool]
    embedding_cache: Optional[Any]
    query_cache: Optional[Any]
    security_enabled: bool
    swagger: Any
    plugin_loader: Any
