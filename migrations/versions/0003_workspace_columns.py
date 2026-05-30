"""Workspace columns — adds workspace_id FK to documents, conversations, memories, answer_feedback.

Also backfills existing rows into the Default workspace and creates the
supporting indexes. All statements are idempotent (IF NOT EXISTS / WHERE NULL).

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS workspace_id UUID
                REFERENCES workspaces(id) ON DELETE SET NULL
    """)
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS workspace_id UUID
                REFERENCES workspaces(id) ON DELETE SET NULL
    """)
    op.execute("""
        ALTER TABLE memories
            ADD COLUMN IF NOT EXISTS workspace_id UUID
                REFERENCES workspaces(id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS documents_workspace_idx
            ON documents (workspace_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS conversations_workspace_idx
            ON conversations (workspace_id)
    """)
    # Backfill pre-workspace rows into the Default workspace
    op.execute("""
        UPDATE conversations
        SET workspace_id = (SELECT id FROM workspaces ORDER BY created_at LIMIT 1)
        WHERE workspace_id IS NULL
    """)
    op.execute("""
        UPDATE documents
        SET workspace_id = (SELECT id FROM workspaces ORDER BY created_at LIMIT 1)
        WHERE workspace_id IS NULL
    """)
    op.execute("""
        ALTER TABLE answer_feedback
            ADD COLUMN IF NOT EXISTS workspace_id UUID
                REFERENCES workspaces(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE answer_feedback DROP COLUMN IF EXISTS workspace_id")
    op.execute("DROP INDEX IF EXISTS conversations_workspace_idx")
    op.execute("DROP INDEX IF EXISTS documents_workspace_idx")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS workspace_id")
