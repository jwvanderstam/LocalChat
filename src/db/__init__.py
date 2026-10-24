"""
Database Package
================

The ``Database`` connection holds one repository per aggregate and is exposed as the
global singleton ``db``.

Submodules:
    connection    — connection pool, pgvector adapters, schema init
    documents     — document and chunk storage / search
    conversations — persistent chat-memory (conversations and messages)
"""

from ..utils.logging_config import get_logger
from .annotations import AnnotationsRepository
from .connection import (
    DatabaseConnection,
    DatabaseUnavailableError,
    VectorLoader,
)
from .connectors import ConnectorsRepository
from .contributions import ContributionsRepository
from .conversations import ConversationsRepository
from .documents import DocumentsRepository
from .entities import EntitiesRepository
from .feedback import FeedbackRepository
from .memories import MemoriesRepository
from .oauth_tokens import OAuthTokensRepository
from .tokens import RevokedTokensRepository
from .users import UsersRepository
from .workspace_keys import WorkspaceKeysRepository
from .workspaces import WorkspaceMembersRepository, WorkspacesRepository

logger = get_logger(__name__)


class Database(DatabaseConnection):
    """
    PostgreSQL database manager with pgvector support.

    The connection pool, with one repository per aggregate held as an attribute.

    Example:
        >>> from src.db import db
        >>> success, msg = db.initialize()
        >>> if success:
        ...     doc_id = db.documents.insert("file.pdf", "content")
        ...     results = db.documents.search_similar(embedding, top_k=5, scope=workspace_id)

    QP-4 replaced every mixin with a repository; QP-5 removes this class, and
    ``app.state`` then holds services rather than a database.
    """

    def __init__(self) -> None:
        super().__init__()
        self.users = UsersRepository(self)
        self.tokens = RevokedTokensRepository(self)
        self.workspaces = WorkspacesRepository(self)
        self.members = WorkspaceMembersRepository(self)
        self.api_keys = WorkspaceKeysRepository(self)
        self.documents = DocumentsRepository(self)
        self.conversations = ConversationsRepository(self)
        self.memories = MemoriesRepository(self)
        self.connectors = ConnectorsRepository(self)
        self.oauth_tokens = OAuthTokensRepository(self)
        self.feedback = FeedbackRepository(self)
        self.annotations = AnnotationsRepository(self)
        self.entities = EntitiesRepository(self)
        self.contributions = ContributionsRepository(self)


# Global singleton – imported throughout the application
db = Database()

logger.info("Database module loaded")

__all__ = ['Database', 'db', 'DatabaseUnavailableError', 'VectorLoader']
