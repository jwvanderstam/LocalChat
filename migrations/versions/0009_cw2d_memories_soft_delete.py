"""CW-2d: add soft-delete columns to memories."""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE memories ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_deleted_at "
        "ON memories (deleted_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memories_deleted_at")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE memories DROP COLUMN IF EXISTS deleted_at")
