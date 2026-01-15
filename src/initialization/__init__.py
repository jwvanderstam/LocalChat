"""
Initialization Package
=====================

Application initialization and lifecycle management.

This package contains modules for:
- Flask app creation and configuration (app_setup)
- Application lifecycle management (lifecycle)
- Resource initialization and cleanup

Modules:
    app_setup: Flask application factory
    lifecycle: Startup checks, cleanup, signal handling

Author: LocalChat Team
Created: January 2025
"""

from .app_setup import create_app
from .lifecycle import (
    register_lifecycle_handlers,
    startup_checks,
    cleanup,
    startup_status
)

__all__ = [
    'create_app',
    'register_lifecycle_handlers',
    'startup_checks',
    'cleanup',
    'startup_status'
]
