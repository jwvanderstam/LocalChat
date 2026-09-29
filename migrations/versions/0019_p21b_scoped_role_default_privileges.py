"""P2-1b: tables created after 0017 are reachable by the scoped role too.

0017 granted `localchat_scoped` what existed when it ran. Tables are created by
`_ensure_extensions_and_tables()` at every boot, *before* this chain runs, so a table added
in a later release would exist with no grant for the role: readable as the owner and
"permission denied" on the scoped path only — the one path the tests of a new table are
least likely to take. Default privileges make every future table and sequence the
application creates reachable, and the policies, not the grants, decide what is visible.

Default privileges apply to objects created by the role that sets them, which is the
application identity: bootstrap runs both the base schema and this chain on its own
connection. See ADR-5.
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

ROLE = "localchat_scoped"


def upgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM {ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {ROLE}")
