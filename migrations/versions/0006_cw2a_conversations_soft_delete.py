"""CW-2a: soft-delete columns for conversations.

Adds:
  conversations.deleted_at  (TIMESTAMPTZ) — set on soft-delete; NULL = live
  conversations.deleted_by  (UUID FK → users.id) — who triggered the retirement

All statements are idempotent (IF NOT EXISTS).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
    """)
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_conversations_deleted_at
            ON conversations (deleted_at)
            WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversations_deleted_at")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS deleted_at")
