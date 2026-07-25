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


_SETTING_DOC_SLUGS = [
    "retrieval-candidates-top_k_results",
    "chunks-sent-to-llm-rerank_top_k",
    "diversity-threshold-diversity_threshold",
    "semantic-weight-semantic_weight",
]


@router.get("/settings", include_in_schema=False)
def settings(request: Request) -> HTMLResponse:
    try:
        from .settings_routes import gather_admin_stats
        stats = gather_admin_stats(request.app.state)
    except Exception:
        stats = {}
    docs_service = request.app.state.docs_service
    setting_docs = {
        slug: (docs_service.get_fragment("docs-settings", slug) or "")
        for slug in _SETTING_DOC_SLUGS
    }
    return _templates(request).TemplateResponse(
        request, "settings.html", {"stats": stats, "setting_docs": setting_docs}
    )


@router.get("/docs", include_in_schema=False)
def docs(request: Request) -> HTMLResponse:
    return _templates(request).TemplateResponse(request, "docs.html")
