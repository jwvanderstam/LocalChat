"""Migrations must not leave the root logger reconfigured.

``migrations/env.py`` calls ``fileConfig(alembic.ini)``. Passing
``disable_existing_loggers=False`` keeps loggers enabled, but ``fileConfig`` still
rewrites the *root* logger — alembic.ini sets ``[logger_root] level = WARN`` and
installs its own handler. Application loggers have no handlers of their own, so they
inherit that level and every INFO line after migrations is dropped.

ERROR still passes a WARN threshold, so the symptom was partial logging: failures
visible, ordinary startup lines gone. ``_preserve_root_logging`` restores level and
handlers around the upgrade call.
"""

from __future__ import annotations

import logging

import pytest

from src.app_bootstrap import _preserve_root_logging


@pytest.fixture
def _root_restored():
    root = logging.getLogger()
    level, handlers = root.level, root.handlers[:]
    yield
    root.setLevel(level)
    root.handlers[:] = handlers


@pytest.mark.unit
def test_level_is_restored_after_the_block(_root_restored):
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    with _preserve_root_logging():
        root.setLevel(logging.WARNING)  # what fileConfig does
    assert root.level == logging.INFO


@pytest.mark.unit
def test_handlers_are_restored_after_the_block(_root_restored):
    root = logging.getLogger()
    original = logging.NullHandler()
    root.handlers[:] = [original]
    with _preserve_root_logging():
        root.handlers[:] = [logging.StreamHandler()]  # what fileConfig does
    assert root.handlers == [original]


@pytest.mark.unit
def test_app_logger_still_emits_info_afterwards(_root_restored):
    """The behaviour that actually broke: INFO from a src.* logger surviving."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    app_logger = logging.getLogger("src.app_bootstrap")
    with _preserve_root_logging():
        root.setLevel(logging.WARNING)
    assert app_logger.isEnabledFor(logging.INFO) is True


@pytest.mark.unit
def test_restores_even_when_the_block_raises(_root_restored):
    """A failed migration must not leave logging broken for the rest of the process."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    with pytest.raises(RuntimeError), _preserve_root_logging():
        root.setLevel(logging.WARNING)
        raise RuntimeError("migration blew up")
    assert root.level == logging.INFO
