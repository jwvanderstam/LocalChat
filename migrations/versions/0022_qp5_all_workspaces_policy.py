"""QP-5 step 1: the explicit all-workspaces flag that option B needs (ADR-5's amendment).

A path that legitimately reads or writes across workspaces — the API-key lookup, the
membership check that authorises a request, an admin's totals, a purge, the connector
worker — will open its transaction with ``get_connection(scope=ALL_WORKSPACES)``, which
sets ``app.all_workspaces`` to ``on`` for that transaction only. This policy admits such a
transaction on the ten tables 0017 protects. Everything else must name a workspace.

It changes nothing yet: 0021's transition policy already admits ``localchat_app``
unconditionally, and permissive policies are OR'd. Once every path names its scope or
this flag (QP-5 step 2), a later migration drops 0021 and adds ``FORCE``.

Two choices, both recorded in ADR-5:

* The policy is not tied to ``localchat_app`` by name, as 0021 is. Under ``FORCE`` the owner
  is bound too, and a deployment without ``PG_APP_PASSWORD`` runs every request as the
  owner, so a name-restricted policy would leave that mode seeing nothing.
* It refuses ``localchat_scoped``. A transaction scoped to one workspace switches into that
  role, and must never also count as all workspaces, whatever else was set in it.
"""

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

POLICY = "localchat_all_workspaces"
SCOPED_ROLE = "localchat_scoped"
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
_PREDICATE = (
    f"current_setting('app.all_workspaces', true) = 'on'"
    f" AND current_user <> '{SCOPED_ROLE}'"
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table}"
            f" USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
