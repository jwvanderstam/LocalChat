"""Add full-text search column and GIN index for the independent lexical
retrieval arm (fixes hybrid search only ever reordering vector search's
own candidates instead of running a genuine second retrieval path)."""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS chunk_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', chunk_text)) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS document_chunks_tsv_gin_idx "
        "ON document_chunks USING GIN (chunk_tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS document_chunks_tsv_gin_idx")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS chunk_tsv")
