"""Workspace API keys — programmatic access to one workspace, no user attached."""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_api_keys (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name         TEXT NOT NULL,
            key_prefix   TEXT NOT NULL,
            key_hash     TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'viewer',
            created_at   TIMESTAMPTZ DEFAULT NOW(),
            created_by   UUID REFERENCES users(id),
            last_used_at TIMESTAMPTZ,
            deleted_at   TIMESTAMPTZ,
            revoked_at   TIMESTAMPTZ,
            revoked_by   UUID REFERENCES users(id)
        )
    """)
    # Partial index: lookup is always by prefix among live keys.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_api_keys_prefix "
        "ON workspace_api_keys (key_prefix) WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    """No-op: dropping the table would destroy the audit trail of revoked keys."""
