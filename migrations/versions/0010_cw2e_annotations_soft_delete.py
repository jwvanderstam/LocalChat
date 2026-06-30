"""CW-2e: add soft-delete columns to annotations."""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE annotations ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE annotations ADD COLUMN IF NOT EXISTS deleted_by UUID REFERENCES users(id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_annotations_deleted_at "
        "ON annotations (deleted_at) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_annotations_deleted_at")
    op.execute("ALTER TABLE annotations DROP COLUMN IF EXISTS deleted_by")
    op.execute("ALTER TABLE annotations DROP COLUMN IF EXISTS deleted_at")
