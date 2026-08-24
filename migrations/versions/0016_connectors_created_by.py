"""BUG-4: bind a connector to the user whose OAuth token it may use."""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE connectors ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id)")


def downgrade() -> None:
    op.execute("ALTER TABLE connectors DROP COLUMN IF EXISTS created_by")
