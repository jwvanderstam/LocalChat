"""GKB-1: a global knowledge tier, readable from every workspace and writable from none.

A document is global when it has no workspace **and** was contributed, and has not been
archived. The workspace alone cannot be the marker: `documents.workspace_id` is
`ON DELETE SET NULL`, so purging a workspace leaves its retired documents with no
workspace too — they must never surface as global knowledge. `contributed_at` is set only
by the contribution TP (GKB-2), and the CHECK keeps the two halves of the marker from
disagreeing: a document with a workspace cannot also claim to be contributed.

The columns are on `documents`, not on `document_chunks` as the ticket first said: a chunk
has no workspace of its own (0017 gives it its document's), and a contribution is chosen
document by document.

0017's policies hide every row whose workspace is NULL, which its docstring left for this
migration to decide. The decision (2026-10-09): global rows are **read-only** to a scoped
transaction. Each table gets a second, `FOR SELECT` policy; permissive policies are OR-ed,
so a scoped read sees its own workspace plus the global tier, while UPDATE and DELETE still
pass only 0017's `workspace_id = scope` — no workspace can change or archive what another
contributed. Only an unscoped, explicitly authorised TP writes the tier.

Both new policies also require the scope to be set, so 0017's "no scope means no rows"
still holds with global documents present.
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

POLICY = "localchat_global_read"

#: Mirrors 0017: an unset GUC becomes NULL, and NULL IS NOT NULL is false.
_SCOPE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"

#: The global marker, over a row of `documents` aliased *alias*.
def _is_global(alias: str) -> str:
    return (
        f"{alias}.workspace_id IS NULL AND {alias}.contributed_at IS NOT NULL"
        f" AND {alias}.archived_at IS NULL"
    )


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS contributed_at    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS contributed_by    UUID REFERENCES users(id),
            ADD COLUMN IF NOT EXISTS archived_at       TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS source_project_id UUID
                REFERENCES workspaces(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS outcome           VARCHAR(32),
            ADD COLUMN IF NOT EXISTS sector            VARCHAR(128)
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'documents_contributed_is_global'
            ) THEN
                ALTER TABLE documents ADD CONSTRAINT documents_contributed_is_global
                    CHECK (contributed_at IS NULL OR workspace_id IS NULL);
            END IF;
        END $$;
    """)
    op.execute(f"""
        CREATE INDEX IF NOT EXISTS documents_global_idx ON documents (id)
        WHERE {_is_global("documents")}
    """)

    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON documents")
    op.execute(
        f"CREATE POLICY {POLICY} ON documents FOR SELECT"
        f" USING ({_SCOPE} IS NOT NULL AND {_is_global('documents')})"
    )
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON document_chunks")
    op.execute(
        f"CREATE POLICY {POLICY} ON document_chunks FOR SELECT USING ("
        f"  {_SCOPE} IS NOT NULL AND EXISTS (SELECT 1 FROM documents p"
        f"   WHERE p.id = document_chunks.document_id AND {_is_global('p')})"
        f")"
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON document_chunks")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON documents")
    op.execute("DROP INDEX IF EXISTS documents_global_idx")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_contributed_is_global")
    for column in ("sector", "outcome", "source_project_id", "archived_at",
                   "contributed_by", "contributed_at"):
        op.execute(f"ALTER TABLE documents DROP COLUMN IF EXISTS {column}")
