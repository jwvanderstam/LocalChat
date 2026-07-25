"""Repo-docs routes — serves the in-app documentation catalogue (src/docs/service.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import exceptions
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
def list_docs(request: Request) -> Any:
    return request.app.state.docs_service.list_docs()


@router.get("/{slug}")
def get_doc(slug: str, request: Request) -> Any:
    entry = request.app.state.docs_service.get_doc(slug)
    if entry is None:
        exc = exceptions.DocNotFoundError(f"Unknown doc slug: {slug}", details={"slug": slug})
        return JSONResponse(exc.to_dict(), status_code=exceptions.get_status_code(exc))
    return {"slug": entry.slug, "title": entry.title, "html": entry.html, "mtime": entry.mtime}


@router.get("/{slug}/fragments/{fragment_slug}")
def get_fragment(slug: str, fragment_slug: str, request: Request) -> Any:
    html = request.app.state.docs_service.get_fragment(slug, fragment_slug)
    if html is None:
        exc = exceptions.DocNotFoundError(
            f"Unknown fragment: {slug}/{fragment_slug}",
            details={"slug": slug, "fragment_slug": fragment_slug},
        )
        return JSONResponse(exc.to_dict(), status_code=exceptions.get_status_code(exc))
    return {"html": html}
