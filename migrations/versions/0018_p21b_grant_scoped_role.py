"""P2-1b: let the application's own identity switch into the restricted role.

`SET LOCAL ROLE localchat_scoped` succeeds only for a superuser or a member of that role.
Migration 0017 created the role and granted it nothing to anyone, so the stack as shipped
would work only by accident — compose connects as `postgres`, a superuser — and a managed
database, whose application identity is neither, would refuse the switch on its first
scoped transaction.

The grantee is whoever runs the migration, which is the application: bootstrap runs
`alembic upgrade head` on its own connection. The membership a role's creator receives
automatically on PostgreSQL 16 carries ADMIN but not SET, and a GRANT of a membership that
already exists leaves its options unchanged — so the grant says `WITH SET TRUE` explicitly.
It names the user through `format()` because Scaleway's managed PostgreSQL refuses the
`CURRENT_USER` specifier in GRANT. (Until 2026-10-06 this was a plain `GRANT ... TO
CURRENT_USER`, which worked only for a superuser.) Boot re-applies the same grant, so a
database that ran the old form is repaired on its next start. See ADR-5.
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

ROLE = "localchat_scoped"


def upgrade() -> None:
    op.execute(f"DO $$ BEGIN EXECUTE format('GRANT %I TO %I WITH SET TRUE', '{ROLE}', current_user); END $$;")


def downgrade() -> None:
    op.execute(f"DO $$ BEGIN EXECUTE format('REVOKE %I FROM %I', '{ROLE}', current_user); END $$;")
