"""Web routes — serve the SPA and favicon."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

router = APIRouter()


def _templates(request: Request) -> Jinja2Templates:
    return Jinja2Templates(directory=request.app.state.template_folder)


@router.get("/favicon.ico", include_in_schema=False)
def favicon(request: Request) -> Response:
    path = Path(request.app.state.static_folder) / "favicon.ico"
    if path.exists():
        return FileResponse(str(path))
    return Response(status_code=204)


@router.get("/", include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "chat.html")


@router.get("/chat", include_in_schema=False)
def chat(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "chat.html")


@router.get("/documents", include_in_schema=False)
def documents(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "documents.html")


@router.get("/models", include_in_schema=False)
def models(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "models.html")


@router.get("/overview", include_in_schema=False)
def overview(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "overview.html")


@router.get("/settings", include_in_schema=False)
def settings(request: Request) -> HTMLResponse:
    try:
        from .settings_routes import gather_admin_stats
        stats = gather_admin_stats(request.app.state)
    except Exception:
        stats = {}
    return _templates(request).TemplateResponse(request, "settings.html", {"stats": stats})
