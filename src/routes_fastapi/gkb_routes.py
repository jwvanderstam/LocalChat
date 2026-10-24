"""Global knowledge routes (GKB-2) — contribute a workspace's documents, withdraw them, list them."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..models import ContributionRequest
from ..security_fastapi import require_admin_dep
from ..services.contributions import ContributionsService
from ..services.errors import ServiceError
from ..utils.logging_config import get_logger
from ._authz import deny as _deny
from ._authz import require_caller
from ._services import contributions_service

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"

Contributions = Annotated[ContributionsService, Depends(contributions_service)]


@router.post("/workspaces/{workspace_id}/contribute")
async def contribute(
    workspace_id: str,
    request: Request,
    contributions: Contributions,
    admin_id: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    # Admin, not ws:owner: any user can create a workspace and own it, so an owner-only
    # guard would let anyone publish into the tier every workspace reads (decided
    # 2026-10-19, the reasoning of D3). An admin passes the owner check anyway.
    data = await request.json() if await request.body() else {}
    try:
        payload = ContributionRequest(**data)
    except (ValidationError, TypeError):
        return JSONResponse(
            {"success": False, "message": "document_ids must be a list of 1 to 100 document ids"},
            status_code=400,
        )
    try:
        contributed = contributions.contribute(workspace_id, payload.document_ids, admin_id)
        return {"success": True, "contributed": contributed}
    except ServiceError as exc:
        return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)
    except Exception:
        logger.exception("[GKB] contribute error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/workspaces/{workspace_id}/contributions")
def archive_contributions(workspace_id: str, request: Request, contributions: Contributions) -> Any:
    # Withdrawing only narrows what every workspace reads, so the owner may do it alone.
    denied = _deny(request, workspace_id, "owner")
    if denied:
        return denied
    caller = require_caller(request)
    try:
        archived = contributions.archive(workspace_id, caller)
        return {"success": True, "archived": archived}
    except Exception:
        logger.exception("[GKB] archive error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/gkb/documents")
def list_contributions(
    contributions: Contributions,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    try:
        return {"success": True, "documents": contributions.list_all()}
    except Exception:
        logger.exception("[GKB] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)
