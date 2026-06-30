"""CW-2c: add soft-delete columns to workspaces."""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspaces_deleted_at "
        "ON workspaces (deleted_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workspaces_deleted_at")
    op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS deleted_at")
