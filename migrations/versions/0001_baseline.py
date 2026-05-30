"""Baseline — marks the initial schema created by _init_schema().

All tables exist at this point. Subsequent migrations add columns
and indexes that were previously applied inline in _init_schema().

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
