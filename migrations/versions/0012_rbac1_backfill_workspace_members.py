"""RBAC-1 prerequisite: backfill workspace_members so nobody is locked out.

Membership was never written on the creation path, so on an existing instance no
user is a member of any workspace. Once RBAC-1 enforces membership, that state
denies everyone everything. This backfill establishes the starting membership.

Two rules, per the decisions recorded in docs/ROADMAP.md (RBAC-1):

* every global admin becomes ``owner`` of every live workspace — admins already
  short-circuit workspace checks, so this grants no access they lacked; it makes
  ownership explicit and guarantees no workspace is left unmanageable.
* every other live user becomes ``editor`` on the default workspace, which is
  exactly what they can do today (upload, delete, manage conversations), so the
  upgrade is behaviour-neutral rather than a silent removal of upload rights.

``ON CONFLICT DO NOTHING`` throughout: an explicitly assigned role always wins over
a backfilled one, so re-running this can never demote or promote anybody.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT w.id, u.id, 'owner'
          FROM workspaces w
          CROSS JOIN users u
         WHERE w.deleted_at IS NULL
           AND u.deleted_at IS NULL
           AND u.role = 'admin'
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """
    )
    # The default workspace is the oldest live one — the same rule
    # WorkspacesMixin.get_default_workspace_id() uses. Matching on name = 'Default'
    # would miss instances where it has been renamed.
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT d.id, u.id, 'editor'
          FROM (
                SELECT id FROM workspaces
                 WHERE deleted_at IS NULL
                 ORDER BY created_at
                 LIMIT 1
               ) d
          CROSS JOIN users u
         WHERE u.deleted_at IS NULL
           AND u.role <> 'admin'
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """No-op by design.

    This migration inserts data, and ``ON CONFLICT DO NOTHING`` means an inserted row
    is indistinguishable afterwards from one a user assigned deliberately. Deleting
    by rule on the way down would therefore revoke real, hand-granted memberships.
    Leaving the rows is the non-destructive choice, consistent with the repo's
    additive-migration rule.
    """
