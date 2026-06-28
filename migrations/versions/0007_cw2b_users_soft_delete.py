"""CW-2b: soft-delete columns for users.

Adds:
  users.deleted_at  (TIMESTAMPTZ) — set on soft-delete; NULL = live
  users.deleted_by  (UUID FK → users.id, self-referential) — admin who retired the account

All statements are idempotent (IF NOT EXISTS).

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
    """)
    op.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_users_deleted_at
            ON users (deleted_at)
            WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_deleted_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS deleted_at")
