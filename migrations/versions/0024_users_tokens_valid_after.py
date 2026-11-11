"""SECURITY.md item 13: a password change ends the account's sessions issued before it.

``users.tokens_valid_after`` is written when a password is set, and the guard refuses a
token whose ``iat`` is earlier. ``NULL`` means no change has happened, so every token
issued so far stays valid. ``users`` is not under row-level security, so no scope flag.
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tokens_valid_after TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tokens_valid_after")
