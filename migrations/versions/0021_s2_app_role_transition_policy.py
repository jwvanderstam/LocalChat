"""QP-2 S2 (B2): a transition policy, so the application can stop being the database owner.

Until S2 the application connected as the identity that owns every table, a superuser in
the shipped compose, and row-level security bound only scoped transactions (0017), which
switch into `localchat_scoped`. S2 moves requests to `localchat_app`: a login that owns
nothing, so 0017's policies apply to it, and an unscoped transaction sees no rows at all.
49 database methods read or write these tables without a scope, among them every insert,
the API-key lookup and the membership check that authorises a request.

ADR-5's amendment (2026-10-23) records where this ends: each of those paths names its
scope, or an explicit all-workspaces flag, and nothing else passes (option B). Getting
there method by method is QP-4's work, one aggregate per PR, so this policy keeps today's
behaviour in the meantime: `localchat_app` itself reads and writes every row, exactly as
the owner did. A scoped transaction runs as `localchat_scoped`, which this policy does not
match, so workspace isolation is unchanged. QP-5 drops this policy.

The role is matched by name, as `current_user = 'localchat_app'`, not with
`TO localchat_app`. A `TO` clause references the role by OID, and a dump restored into a
cluster where the role does not exist yet fails to recreate the policy, which would leave
the application seeing nothing (the trap `_apply_scoped_role` records for the role
itself). A name compared as text survives that, and the boot creates the role.
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

POLICY = "localchat_app_transition"
APP_ROLE = "localchat_app"

#: Every table 0017 put under row-level security, direct and inherited.
TABLES = (
    "documents",
    "conversations",
    "memories",
    "answer_feedback",
    "connectors",
    "workspace_api_keys",
    "workspace_members",
    "document_chunks",
    "conversation_messages",
    "annotations",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table}"
            f" USING (current_user = '{APP_ROLE}')"
            f" WITH CHECK (current_user = '{APP_ROLE}')"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
