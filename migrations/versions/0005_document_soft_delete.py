"""CW-1: soft-delete columns for documents and document_chunks.

Adds:
  documents.deleted_at   (TIMESTAMPTZ) — set on soft-delete; NULL = live
  documents.deleted_by   (UUID FK → users.id) — who triggered the retirement
  document_chunks.deleted_at (TIMESTAMPTZ) — reserved for per-chunk retirement

All statements are idempotent (IF NOT EXISTS / IF EXISTS).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-27
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)
    """)
    op.execute("""
        ALTER TABLE document_chunks
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_deleted_at
            ON documents (deleted_at)
            WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_deleted_at")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at")
