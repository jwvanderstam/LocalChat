"""Baseline — marks the initial schema created by _ensure_extensions_and_tables().

All tables exist at this point. Subsequent migrations add columns
and indexes that were previously applied inline in _ensure_extensions_and_tables().

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""
from __future__ import annotations

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
