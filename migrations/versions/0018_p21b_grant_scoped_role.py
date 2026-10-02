"""P2-1b: let the application's own identity switch into the restricted role.

`SET LOCAL ROLE localchat_scoped` succeeds only for a superuser or a member of that role.
Migration 0017 created the role and granted it nothing to anyone, so the stack as shipped
would work only by accident — compose connects as `postgres`, a superuser — and a managed
database, whose application identity is neither, would refuse the switch on its first
scoped transaction.

`CURRENT_USER` here is whoever runs the migration, which is the application: bootstrap runs
`alembic upgrade head` on its own connection. On PostgreSQL 16 a plain `GRANT role TO user`
carries `SET TRUE`, which is the option `SET ROLE` needs; the membership a role's creator
receives automatically does not. See ADR-5.
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

ROLE = "localchat_scoped"


def upgrade() -> None:
    op.execute(f"GRANT {ROLE} TO CURRENT_USER")


def downgrade() -> None:
    op.execute(f"REVOKE {ROLE} FROM CURRENT_USER")
