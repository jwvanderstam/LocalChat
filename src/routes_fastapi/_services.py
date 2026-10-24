"""FastAPI providers for the service layer — the one place a route module reads the database.

A handler asks for a service with ``Depends(...)`` and never holds the database, so it
cannot reach a query the service does not offer (ADR-7). One provider per service, added
as each aggregate moves (QP-4).
"""

from __future__ import annotations

from fastapi import Request

from ..services.users import UsersService


def users_service(request: Request) -> UsersService:
    return UsersService(request.app.state.db)
