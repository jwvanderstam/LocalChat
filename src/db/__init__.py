"""
Database Package
================

Composes the Database class from domain-specific mixins and exposes the
global singleton ``db`` with the same public API as the former ``db.py``.

Submodules:
    connection    — connection pool, pgvector adapters, schema init
    documents     — document and chunk storage / search
    conversations — persistent chat-memory (conversations and messages)
"""

from ..utils.logging_config import get_logger
from .connection import (
    DatabaseConnection,
    DatabaseUnavailableError,
    VectorLoader,
    register_vector_types,
)
from .conversations import ConversationsMixin
from .documents import DocumentsMixin
from .entities import EntitiesMixin
from .feedback import FeedbackMixin
from .memories import MemoriesMixin

logger = get_logger(__name__)


class Database(DocumentsMixin, ConversationsMixin, MemoriesMixin, EntitiesMixin, FeedbackMixin, DatabaseConnection):
    """
    PostgreSQL database manager with pgvector support.

    Combines connection management, document/chunk operations, and
    conversation persistence into a single injectable service object.

    Example:
        >>> from src.db import db
        >>> success, msg = db.initialize()
        >>> if success:
        ...     doc_id = db.insert_document("file.pdf", "content")
        ...     results = db.search_similar_chunks(embedding, top_k=5)
    """


# Global singleton – imported throughout the application
db = Database()

logger.info("Database module loaded")

__all__ = ['Database', 'db', 'DatabaseUnavailableError', 'VectorLoader']
