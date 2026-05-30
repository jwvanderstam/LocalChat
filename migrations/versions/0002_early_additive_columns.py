"""Early additive columns — conversations, documents, conversation_messages.

Adds columns that were introduced during initial feature development:
  conversations.document_ids
  documents.content_hash, doc_type, chunker_version, local_only
  conversation_messages.plan_json
  conversations.memory_extracted_at

All statements use IF NOT EXISTS so this migration is idempotent.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS document_ids JSONB DEFAULT '[]'::jsonb
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64)
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS doc_type VARCHAR(20)
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS chunker_version VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS local_only BOOLEAN DEFAULT TRUE
    """)
    op.execute("""
        ALTER TABLE conversation_messages
            ADD COLUMN IF NOT EXISTS plan_json JSONB
    """)
    op.execute("""
        ALTER TABLE conversations
            ADD COLUMN IF NOT EXISTS memory_extracted_at TIMESTAMP
    """)


def downgrade() -> None:
    # Downgrade drops columns only when safe (no data loss concern in dev).
    # In production, prefer a new migration instead of rolling back.
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS memory_extracted_at")
    op.execute("ALTER TABLE conversation_messages DROP COLUMN IF EXISTS plan_json")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS local_only")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS chunker_version")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS doc_type")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS content_hash")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS document_ids")
