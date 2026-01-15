"""
Initialization Package
=====================

Application initialization and lifecycle management.

This package contains modules for:
- Flask app creation and configuration
- Application lifecycle (startup, cleanup, signals)
- Resource initialization

Author: LocalChat Team
Created: January 2025
"""

from .app_setup import create_app
from .lifecycle import register_lifecycle_handlers, startup_checks, cleanup

__all__ = [
    'create_app',
    'register_lifecycle_handlers',
    'startup_checks',
    'cleanup'
]
