"""QP-5 step 3: option B is reached — drop 0021's transition policy and FORCE row-level security.

Since QP-5 step 2 every repository path names a workspace or the explicit all-workspaces
flag (0022), and a ratchet holds the count of unscoped ones at zero. So the policy that let
``localchat_app`` read and write every row without either goes, and nothing passes the ten
protected tables without a scope any more.

``FORCE`` makes the policies bind the tables' owner too. Until now the owner bypassed them,
which mattered for a deployment without ``PG_APP_PASSWORD``, where every request runs as the
owner. A superuser still bypasses row-level security whatever this says; that is Postgres,
and the reason ADR-5's amendment moves requests off the owner in the first place.

A future migration that writes to one of these tables as the owner must now set the flag
first: ``SELECT set_config('app.all_workspaces', 'on', true)``.
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

TRANSITION_POLICY = "localchat_app_transition"
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
        op.execute(f"DROP POLICY IF EXISTS {TRANSITION_POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {TRANSITION_POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {TRANSITION_POLICY} ON {table}"
            f" USING (current_user = '{APP_ROLE}')"
            f" WITH CHECK (current_user = '{APP_ROLE}')"
        )
