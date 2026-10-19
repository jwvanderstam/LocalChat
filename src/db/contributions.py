"""GKB-2 — the contribution TPs: copy a workspace's documents into the global tier, and
archive them out of it again.

Both run on an unscoped connection, and that is deliberate rather than an omission. Row-
level security lets a scoped transaction *read* the global tier and write none of it
(0019), so writing a global row is only possible as the owner role. Every statement here
therefore names its workspace in the WHERE clause itself — nothing else will.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..utils.logging_config import get_logger
from .connection import DatabaseUnavailableError

if TYPE_CHECKING:
    from .connection import MixinHost
else:
    MixinHost = object

logger = get_logger(__name__)

# Migration 0019's marker, plus not retired.
_LIVE_CONTRIBUTION = (
    "workspace_id IS NULL AND contributed_at IS NOT NULL"
    " AND archived_at IS NULL AND deleted_at IS NULL"
)


class ContributionsMixin(MixinHost):
    """Mixin that adds the global knowledge tier's write side to the Database class."""

    def contribute_documents(
        self, workspace_id: str, document_ids: list[int], contributed_by: str
    ) -> list[dict[str, Any]] | None:
        """Copy live documents of *workspace_id* into the global tier, chunks and embeddings included.

        A document already contributed from this workspace under the same filename is
        updated in place, so its id — and any citation of it — survives; its old chunks
        are retired rather than deleted. All or nothing: returns ``None``, having written
        nothing, when any id is not a live document of *workspace_id*.
        """
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot contribute documents: Database is not connected")

        wanted = sorted(set(document_ids))
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM documents"
                    " WHERE id = ANY(%s) AND workspace_id = %s AND deleted_at IS NULL",
                    (wanted, workspace_id),
                )
                if len(cursor.fetchall()) != len(wanted):
                    return None

                contributed = []
                for document_id in wanted:
                    cursor.execute(
                        f"""
                        INSERT INTO documents
                            (filename, content, metadata, content_hash, doc_type,
                             chunker_version, language, local_only,
                             contributed_at, contributed_by, source_project_id)
                        SELECT filename, content, metadata, content_hash, doc_type,
                               chunker_version, language, local_only,
                               NOW(), %s, workspace_id
                        FROM documents WHERE id = %s
                        ON CONFLICT (filename, source_project_id) WHERE {_LIVE_CONTRIBUTION}
                        DO UPDATE SET
                            content = EXCLUDED.content, metadata = EXCLUDED.metadata,
                            content_hash = EXCLUDED.content_hash, doc_type = EXCLUDED.doc_type,
                            chunker_version = EXCLUDED.chunker_version,
                            language = EXCLUDED.language, local_only = EXCLUDED.local_only,
                            contributed_at = EXCLUDED.contributed_at,
                            contributed_by = EXCLUDED.contributed_by
                        RETURNING id, filename, (xmax = 0) AS inserted
                        """,
                        (contributed_by, document_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise AssertionError("INSERT ... SELECT of a row just read returns it")
                    global_id, filename, inserted = row
                    cursor.execute(
                        "UPDATE document_chunks SET deleted_at = NOW()"
                        " WHERE document_id = %s AND deleted_at IS NULL",
                        (global_id,),
                    )
                    cursor.execute(
                        "INSERT INTO document_chunks"
                        " (document_id, chunk_text, chunk_index, embedding, metadata)"
                        " SELECT %s, chunk_text, chunk_index, embedding, metadata"
                        " FROM document_chunks WHERE document_id = %s AND deleted_at IS NULL",
                        (global_id, document_id),
                    )
                    contributed.append({
                        "document_id": document_id,
                        "global_document_id": global_id,
                        "filename": filename,
                        "chunks": cursor.rowcount,
                        "updated": not inserted,
                    })
            conn.commit()
        # The workspace id comes from the URL path, so it stays out of the log (S5145);
        # contributed_by and source_project_id on the rows are the audit record.
        logger.info(
            "[GKB] contributed %d document(s) as global ids %s",
            len(contributed), [c["global_document_id"] for c in contributed],
        )
        return contributed

    def archive_contributions(self, workspace_id: str, archived_by: str) -> int:
        """Withdraw every live contribution from *workspace_id*; returns how many."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot archive contributions: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE documents SET archived_at = NOW(), archived_by = %s"
                    f" WHERE source_project_id = %s AND {_LIVE_CONTRIBUTION}",
                    (archived_by, workspace_id),
                )
                archived = cursor.rowcount
            conn.commit()
        logger.info("[GKB] archived %d contribution(s)", archived)
        return archived

    def list_contributions(self) -> list[dict[str, Any]]:
        """Every contribution, archived ones included, with its provenance."""
        if not self.is_connected:
            raise DatabaseUnavailableError("Cannot list contributions: Database is not connected")

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT d.id, d.filename, d.source_project_id, w.name,
                           d.contributed_at, u.username, d.archived_at,
                           COUNT(dc.id) AS chunk_count
                    FROM documents d
                    LEFT JOIN workspaces w ON w.id = d.source_project_id
                    LEFT JOIN users u ON u.id = d.contributed_by
                    LEFT JOIN document_chunks dc
                           ON dc.document_id = d.id AND dc.deleted_at IS NULL
                    WHERE d.workspace_id IS NULL AND d.contributed_at IS NOT NULL
                      AND d.deleted_at IS NULL
                    GROUP BY d.id, w.name, u.username
                    ORDER BY d.contributed_at DESC
                """)
                rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "filename": row[1],
                "source_project_id": str(row[2]) if row[2] else None,
                "source_project_name": row[3],
                "contributed_at": row[4].isoformat() if row[4] else None,
                "contributed_by": row[5],
                "archived_at": row[6].isoformat() if row[6] else None,
                "chunk_count": row[7],
            }
            for row in rows
        ]
