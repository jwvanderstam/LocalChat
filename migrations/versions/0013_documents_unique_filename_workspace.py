"""Enforce one live document per (filename, workspace_id).

document_exists() previously ignored workspace_id entirely, so two
workspaces uploading a same-named file could read and soft-delete each
other's document. Now that the read is workspace-scoped, this migration
closes the other half: nothing previously stopped duplicate live rows
from existing for the same (filename, workspace_id), including any
already created by the old bug.

A one-time dedup pass keeps the most-recently-created live row per
(filename, workspace_id) group and soft-deletes the rest (recoverable —
same soft-delete convention as everywhere else, chunks untouched), then a
partial unique index makes any future duplicate a loud constraint
violation instead of a silent collision. NULL workspace_id documents are
deduplicated against each other via COALESCE to a sentinel UUID, since a
plain unique index treats every NULL as distinct and would not catch
them.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-26
"""
from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_NULL_WORKSPACE_SENTINEL = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(f"""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY filename, COALESCE(workspace_id, '{_NULL_WORKSPACE_SENTINEL}'::uuid)
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM documents
            WHERE deleted_at IS NULL
        )
        UPDATE documents
        SET deleted_at = NOW()
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """)
    op.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS documents_filename_workspace_uidx
            ON documents (filename, COALESCE(workspace_id, '{_NULL_WORKSPACE_SENTINEL}'::uuid))
            WHERE deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS documents_filename_workspace_uidx")
