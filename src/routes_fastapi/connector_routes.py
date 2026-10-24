"""Connector routes — CRUD, sync, history, webhook, available."""

from __future__ import annotations

import hmac
import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..security_fastapi import get_current_user_id, require_admin_dep
from ..services.connectors import ConnectorsService
from ..services.errors import ServiceError
from ..utils.logging_config import get_logger
from ..utils.scope import ALL_WORKSPACES
from ..utils.workspace import get_scope, get_workspace_id
from ._authz import deny as _deny
from ._authz import require_caller
from ._services import connectors_service

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"
_NOT_FOUND = "Connector not found"

Connectors = Annotated[ConnectorsService, Depends(connectors_service)]


def _admin_check(request: Request) -> Callable[[], None]:
    """The global-admin check the service calls for an admin-only connector type.

    Delegates to ``require_admin_dep`` rather than re-deriving the check, so the
    fail-closed behaviour on an unreachable database stays in one place. Passing
    ``credentials=None`` takes its documented fallback: read the bearer token from
    the request, which is also how a cookie session reaches it.
    """

    def check() -> None:
        try:
            require_admin_dep(request, None)
        except HTTPException as exc:
            detail = exc.detail
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
            raise ServiceError(exc.status_code, str(message)) from exc

    return check


def _refused(exc: ServiceError) -> JSONResponse:
    return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)


@router.get("/connectors/available")
def list_available_connectors(request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    return {"success": True, "available": connectors.available(get_current_user_id(request))}


@router.get("/connectors/types")
def list_connector_types(request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    return {"success": True, "types": connectors.types()}


@router.get("/connectors")
def list_connectors(request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    try:
        return {"success": True, "connectors": connectors.list_all(get_scope(request))}
    except Exception:
        logger.exception("[Connectors] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors", status_code=201)
async def create_connector(request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    connector_type = (data.get("connector_type") or "").strip()
    display_name = (data.get("display_name") or "").strip()
    connector_config = data.get("config") or {}
    sync_interval = int(data.get("sync_interval") or 900)

    try:
        connector = connectors.create(
            connector_type,
            display_name,
            connector_config,
            sync_interval,
            get_workspace_id(request),
            require_admin=_admin_check(request),
            creator=lambda: require_caller(request),
        )
        return JSONResponse({"success": True, "connector": connector}, status_code=201)
    except ServiceError as exc:
        return _refused(exc)
    except HTTPException:
        raise  # require_caller's 401 keeps its own response shape
    except Exception:
        logger.exception("[Connectors] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/connectors/{connector_id}")
def get_connector(connector_id: str, request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    try:
        connector = connectors.get(connector_id, get_scope(request))
        if connector is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "connector": connector}
    except Exception:
        logger.exception("[Connectors] get error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/connectors/{connector_id}")
async def update_connector(connector_id: str, request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    data = await request.json() if await request.body() else {}
    allowed = {"display_name", "config", "enabled", "sync_interval"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        connector = connectors.update(
            connector_id, fields, get_scope(request), require_admin=_admin_check(request)
        )
        if connector is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "connector": connector}
    except ServiceError as exc:
        return _refused(exc)
    except Exception:
        logger.exception("[Connectors] update error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/connectors/{connector_id}/purge")
def purge_connector(
    connector_id: str,
    connectors: Connectors,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    try:
        purged = connectors.purge(connector_id)
        if not purged:
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "Connector cannot be purged: it has active synced documents. "
                        "Soft-delete those documents first."
                    ),
                },
                status_code=409,
            )
        return {"success": True}
    except Exception:
        logger.exception("[Connectors] purge error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/connectors/{connector_id}")
def delete_connector(connector_id: str, request: Request, connectors: Connectors) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    try:
        if not connectors.retire(connector_id, get_current_user_id(request), get_scope(request)):
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[Connectors] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors/{connector_id}/sync")
def trigger_sync(connector_id: str, request: Request) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    connector_instance = request.app.state.connector_registry.get(connector_id)
    if connector_instance is None:
        return JSONResponse({"success": False, "message": "Connector not found or not loaded"}, status_code=404)

    sync_worker = getattr(request.app.state, "sync_worker", None)
    if sync_worker is None:
        return JSONResponse({"success": False, "message": "Sync worker not running"}, status_code=503)

    def _run() -> None:
        sync_worker._sync_one(connector_instance)

    threading.Thread(target=_run, daemon=True, name=f"manual-sync-{connector_id[:8]}").start()
    return {"success": True, "message": "Sync triggered"}


@router.get("/connectors/{connector_id}/history")
def sync_history(
    connector_id: str, request: Request, connectors: Connectors, limit: int = 20
) -> Any:
    denied = _deny(request, None, "owner")
    if denied:
        return denied
    limit = min(limit, 100)
    try:
        history = connectors.sync_history(connector_id, limit)
        return {"success": True, "history": history}
    except Exception:
        logger.exception("[Connectors] history error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors/{connector_id}/webhook")
async def receive_webhook(connector_id: str, request: Request, connectors: Connectors) -> Any:
    # No user session here: this is a public receiver, and the connector id plus its
    # secret is the whole credential. ALL_WORKSPACES says that rather than relying on
    # an omitted argument to mean it.
    connector = connectors.get(connector_id, ALL_WORKSPACES)
    if connector is None:
        return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
    if connector.get("connector_type") != "webhook":
        return JSONResponse({"success": False, "message": "Not a webhook connector"}, status_code=400)

    # Mandatory, not "checked when present". This endpoint is public — it has to be,
    # since the caller is an external system with no session — so the secret is the
    # whole credential, and a connector configured without one accepted anything that
    # knew its id (audit M4). compare_digest, not ==, so a secret cannot be recovered
    # a character at a time from response timing.
    secret = (connector.get("config") or {}).get("secret") or ""
    if not secret:
        logger.error(
            "[Webhook] Connector has no secret configured; refusing the delivery. "
            "Set one on the connector."
        )
        return JSONResponse({"success": False, "message": "Forbidden"}, status_code=403)
    provided = request.headers.get("X-LocalChat-Secret", "")
    if not hmac.compare_digest(provided, secret):
        logger.warning("[Webhook] Bad secret for connector")
        return JSONResponse({"success": False, "message": "Forbidden"}, status_code=403)

    instance = request.app.state.connector_registry.get(connector_id)
    if instance is None:
        return JSONResponse({"success": False, "message": "Connector not active"}, status_code=503)

    payload = await request.json() if await request.body() else {}
    errors = instance.push_event(payload)
    if errors:
        return JSONResponse({"success": False, "message": "; ".join(errors)}, status_code=400)

    return {"success": True, "message": "Event queued"}
