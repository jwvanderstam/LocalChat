"""P2-1b: row-level security on the workspace-owned tables, as defence in depth.

The audit's C1 and C2 were one property, not a list of bugs: `workspace_id=None` meant
"every workspace", and enforcement was per-route convention. P0-1 made the scope a
mandatory value (`src/utils/scope.py`) and `test_object_authorization_matrix.py` fails any
call that omits it. This is the second half — the database refusing on its own, so a query
that reaches it without a scope returns nothing rather than everything.

Three decisions are load-bearing, and each was established by running it
(`tests/integration/test_set_local_scope_mechanism.py`) rather than by reading:

* **`set_config('app.workspace_id', %s, true)`, never `SET LOCAL app.workspace_id = %s`.**
  `SET` is a utility statement and takes no bind parameter, so writing it means
  interpolating the id into SQL — an injection site on the one value that decides what the
  caller can see. `set_config` means the same thing and takes a parameter.

* **A restricted role.** RLS does not apply to a superuser or to the table's owner, and the
  application connects as the owner. Without a role to switch into, every policy below is
  inert while every test of it passes. The role is `NOLOGIN`: it is reached only by
  `SET LOCAL ROLE` from a connection that already authenticated, never by connecting.

* **Transaction-local, both of them.** `SET LOCAL ROLE` and `set_config(..., true)` revert
  at commit or rollback, so a pooled connection cannot carry one request's scope into the
  next. A session-level `SET` could, and that is the failure mode this whole approach
  exists to prevent — see `_warn_if_ef_search_did_not_stick` in `src/db/connection.py` for
  what a session GUC costs behind a pooler.

Rows whose `workspace_id` is NULL become invisible to a scoped transaction. That is correct
today: migration 0003 backfilled every existing row. It is a decision to revisit for GKB-1,
whose global knowledge base is specified as `workspace_id IS NULL` — those rows will need
either an explicit `OR workspace_id IS NULL` here or a separate policy.
"""
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

#: Reached only through SET LOCAL ROLE, never by connecting. See the module docstring.
ROLE = "localchat_scoped"

POLICY = "localchat_workspace_isolation"

#: The scope as SQL. NULLIF turns an unset GUC into NULL, and `workspace_id = NULL` is
#: never true — which is what makes "no scope" mean "no rows" instead of "every row".
_SCOPE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"

#: Tables carrying workspace_id, read from information_schema against a fully migrated
#: database rather than from the DDL — `chunk_stats` looks like one and is not.
DIRECT = (
    "documents",
    "conversations",
    "memories",
    "answer_feedback",
    "connectors",
    "workspace_api_keys",
    "workspace_members",
)

#: Tables with no workspace of their own, which borrow their parent's.
#: (table, parent table, the child's foreign key to it)
INHERITED = (
    ("document_chunks", "documents", "document_id"),
    ("conversation_messages", "conversations", "conversation_id"),
    ("annotations", "document_chunks", "chunk_id"),
)


def upgrade() -> None:
    # Idempotent: CREATE ROLE has no IF NOT EXISTS, so it is guarded.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END $$;
        """
    )
    # The role runs the whole application, so it needs the same reach on every table; the
    # policies below are what narrow it. Sequences included or an INSERT cannot get an id.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")

    for table in DIRECT:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING (workspace_id = {_SCOPE})"
        )

    for table, parent, fk in INHERITED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        # The parent's own policy also applies inside this subquery, so the predicate is
        # belt and braces — and it is what keeps the child correct if the parent's policy
        # is ever bypassed by an owner-role transaction.
        parent_scope = (
            f"p.workspace_id = {_SCOPE}"
            if parent in DIRECT
            else f"EXISTS (SELECT 1 FROM documents d WHERE d.id = p.document_id"
                 f" AND d.workspace_id = {_SCOPE})"
        )
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ("
            f"  EXISTS (SELECT 1 FROM {parent} p WHERE p.id = {table}.{fk} AND {parent_scope})"
            f")"
        )


def downgrade() -> None:
    for table in [t for t, _, _ in INHERITED] + list(DIRECT):
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")
