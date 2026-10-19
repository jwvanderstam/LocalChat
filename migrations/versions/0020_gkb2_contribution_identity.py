"""GKB-2: a contribution is identified by its filename and the project it came from.

0013 allowed one live document per filename among *all* NULL-workspace rows, so two
projects could not both contribute `retro.md`. Decided 2026-10-10: a live contribution is
unique per `(filename, source_project_id)`, and re-contributing the same file from the
same project updates it in place. The identity is the project's id, not its name, so a
renamed workspace still updates its own contribution rather than adding a second copy.

0013's index keeps guarding every document that is *not* a contribution, unchanged. The
new one covers live contributions only: an archived contribution leaves it, so the same
file can be contributed again after a withdrawal. `source_project_id` is
`ON DELETE SET NULL`, and a unique index treats NULLs as distinct, so purging a project
that contributed can never collide with another project's orphaned contribution.

`archived_by` gives archiving the same audit pair every other retirement has
(`deleted_at` + `deleted_by`).

The downgrade restores 0013's index, which fails if two projects have live
contributions sharing a filename. That is the state this migration exists to allow, so
archive one of them before downgrading.
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_NULL_WORKSPACE_SENTINEL = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS archived_by UUID REFERENCES users(id)"
    )
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS documents_contribution_filename_uidx
            ON documents (filename, source_project_id)
            WHERE deleted_at IS NULL AND contributed_at IS NOT NULL AND archived_at IS NULL
    """)
    op.execute("DROP INDEX IF EXISTS documents_filename_workspace_uidx")
    op.execute(f"""
        CREATE UNIQUE INDEX documents_filename_workspace_uidx
            ON documents (filename, COALESCE(workspace_id, '{_NULL_WORKSPACE_SENTINEL}'::uuid))
            WHERE deleted_at IS NULL AND contributed_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS documents_filename_workspace_uidx")
    op.execute(f"""
        CREATE UNIQUE INDEX documents_filename_workspace_uidx
            ON documents (filename, COALESCE(workspace_id, '{_NULL_WORKSPACE_SENTINEL}'::uuid))
            WHERE deleted_at IS NULL
    """)
    op.execute("DROP INDEX IF EXISTS documents_contribution_filename_uidx")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS archived_by")
