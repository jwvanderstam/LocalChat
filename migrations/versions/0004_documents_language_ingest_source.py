"""v1.1/v1.5 documents columns — language, last_ingested_at, source_id.

Adds:
  documents.language (v1.1 — multilingual detection)
  documents.last_ingested_at (v1.1 — scheduled re-ingest tracking) + backfill
  documents.source_id (v1.5 — multi-source connector ID) + index

All statements are idempotent (IF NOT EXISTS).

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS language VARCHAR(10)
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS last_ingested_at TIMESTAMPTZ
    """)
    op.execute("""
        UPDATE documents
        SET last_ingested_at = created_at
        WHERE last_ingested_at IS NULL
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS source_id VARCHAR(255)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_source_id
            ON documents (source_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_source_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS source_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS last_ingested_at")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS language")
