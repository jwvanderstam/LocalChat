"""FastAPI providers for the service layer — the one place a route module reads the database.

A handler asks for a service with ``Depends(...)`` and never holds the database, so it
cannot reach a query the service does not offer (ADR-7). One provider per service, added
as each aggregate moves (QP-4).
"""

from __future__ import annotations

from fastapi import Request

from ..services.connectors import ConnectorsService, OAuthAccountsService
from ..services.conversations import ConversationsService
from ..services.documents import DocumentsService
from ..services.memories import MemoriesService
from ..services.users import UsersService
from ..services.workspaces import WorkspacesService


def connectors_service(request: Request) -> ConnectorsService:
    return ConnectorsService(request.app.state.db, request.app.state.connector_registry)


def conversations_service(request: Request) -> ConversationsService:
    return ConversationsService(request.app.state.db)


def documents_service(request: Request) -> DocumentsService:
    return DocumentsService(request.app.state.db)


def memories_service(request: Request) -> MemoriesService:
    return MemoriesService(request.app.state.db)


def oauth_accounts_service(request: Request) -> OAuthAccountsService:
    return OAuthAccountsService(request.app.state.db)


def users_service(request: Request) -> UsersService:
    return UsersService(request.app.state.db)


def workspaces_service(request: Request) -> WorkspacesService:
    return WorkspacesService(request.app.state.db)
