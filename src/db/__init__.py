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
from .annotations import AnnotationsMixin
from .connection import (
    DatabaseConnection,
    DatabaseUnavailableError,
    VectorLoader,
)
from .connectors import ConnectorsMixin
from .contributions import ContributionsMixin
from .conversations import ConversationsMixin
from .documents import DocumentsMixin
from .entities import EntitiesMixin
from .feedback import FeedbackMixin
from .memories import MemoriesMixin
from .oauth_tokens import OAuthTokensMixin
from .tokens import RevokedTokensRepository
from .users import UsersRepository
from .workspace_keys import WorkspaceKeysRepository
from .workspaces import WorkspaceMembersRepository, WorkspacesRepository

logger = get_logger(__name__)


class Database(DocumentsMixin, ContributionsMixin, ConversationsMixin, MemoriesMixin, EntitiesMixin, FeedbackMixin, OAuthTokensMixin, ConnectorsMixin, AnnotationsMixin, DatabaseConnection):
    """
    PostgreSQL database manager with pgvector support.

    Combines connection management, document/chunk operations, and
    conversation persistence into a single injectable service object.

    Example:
        >>> from src.db import db
        >>> success, msg = db.initialize()
        >>> if success:
        ...     doc_id = db.insert_document("file.pdf", "content")
        ...     results = db.search_similar_chunks(embedding, top_k=5, scope=workspace_id)

    The users, revoked-tokens, workspaces, memberships and API-key aggregates are
    repositories held as attributes, not mixins (QP-4); the remaining mixins move the
    same way, one aggregate per PR, and QP-5 removes this class.
    """

    def __init__(self) -> None:
        super().__init__()
        self.users = UsersRepository(self)
        self.tokens = RevokedTokensRepository(self)
        self.workspaces = WorkspacesRepository(self)
        self.members = WorkspaceMembersRepository(self)
        self.api_keys = WorkspaceKeysRepository(self)


# Global singleton – imported throughout the application
db = Database()

logger.info("Database module loaded")

__all__ = ['Database', 'db', 'DatabaseUnavailableError', 'VectorLoader']
