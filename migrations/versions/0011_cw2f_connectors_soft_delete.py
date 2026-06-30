"""CW-2f: add soft-delete columns to connectors."""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_connectors_deleted_at "
        "ON connectors (deleted_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_connectors_deleted_at")
    op.execute("ALTER TABLE connectors DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE connectors DROP COLUMN IF EXISTS deleted_at")
