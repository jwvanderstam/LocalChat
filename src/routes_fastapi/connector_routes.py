"""Connector routes — CRUD, sync, history, webhook, available."""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..connectors.registry import connector_registry
from ..security_fastapi import get_current_user_id
from ..utils.logging_config import get_logger
from ..utils.workspace import get_workspace_id

logger = get_logger(__name__)
router = APIRouter()

_ERR_INTERNAL = "Internal server error"
_NOT_FOUND = "Connector not found"


@router.get("/connectors/available")
def list_available_connectors(request: Request) -> Any:
    user_id = get_current_user_id(request)
    available = []
    for provider in ("google_drive", "microsoft", "onedrive"):
        try:
            db = request.app.state.db
            token = db.get_oauth_token(user_id or "", provider) if user_id and db.is_connected else None
            if token:
                available.append({"type": provider, "authorized": True})
        except Exception:
            pass
    return {"success": True, "available": available}


@router.get("/connectors/types")
def list_connector_types(request: Request) -> Any:
    return {"success": True, "types": connector_registry.available_types()}


@router.get("/connectors")
def list_connectors(request: Request) -> Any:
    workspace_id = get_workspace_id(request)
    try:
        connectors = request.app.state.db.list_connectors(workspace_id=workspace_id)
        return {"success": True, "connectors": connectors}
    except Exception:
        logger.exception("[Connectors] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors", status_code=201)
async def create_connector(request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    connector_type = (data.get("connector_type") or "").strip()
    display_name = (data.get("display_name") or "").strip()
    connector_config = data.get("config") or {}
    sync_interval = int(data.get("sync_interval") or 900)

    if not connector_type:
        return JSONResponse({"success": False, "message": "connector_type is required"}, status_code=400)
    if connector_type not in connector_registry.available_types():
        return JSONResponse(
            {"success": False, "message": f"Unknown connector_type. Available: {connector_registry.available_types()}"},
            status_code=400,
        )

    workspace_id = get_workspace_id(request)
    cls = connector_registry.get_class(connector_type)
    try:
        tmp_instance = cls(connector_config)
    except Exception as exc:
        logger.warning("Connector config instantiation failed: %s", exc)
        return JSONResponse({"success": False, "message": "Invalid connector configuration"}, status_code=400)

    errors = tmp_instance.validate_config()
    if errors:
        return JSONResponse({"success": False, "message": "; ".join(errors)}, status_code=400)

    if not display_name:
        display_name = tmp_instance.display_name

    try:
        db = request.app.state.db
        connector_id = db.create_connector(
            connector_type=connector_type,
            display_name=display_name,
            config=connector_config,
            workspace_id=workspace_id,
            sync_interval=sync_interval,
        )
        connector_registry.add(connector_id, connector_type, connector_config, workspace_id=workspace_id)
        connector = db.get_connector(connector_id)
        return JSONResponse({"success": True, "connector": connector}, status_code=201)
    except Exception:
        logger.exception("[Connectors] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/connectors/{connector_id}")
def get_connector(connector_id: str, request: Request) -> Any:
    try:
        connector = request.app.state.db.get_connector(connector_id)
        if connector is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "connector": connector}
    except Exception:
        logger.exception("[Connectors] get error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/connectors/{connector_id}")
async def update_connector(connector_id: str, request: Request) -> Any:
    data = await request.json() if await request.body() else {}
    allowed = {"display_name", "config", "enabled", "sync_interval"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        db = request.app.state.db
        updated = db.update_connector(connector_id, **fields)
        if not updated:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        if "config" in fields or "enabled" in fields:
            row = db.get_connector(connector_id)
            if row and row.get("enabled"):
                connector_registry.add(connector_id, row["connector_type"], row["config"], workspace_id=row.get("workspace_id"))
            else:
                connector_registry.remove(connector_id)
        return {"success": True, "connector": db.get_connector(connector_id)}
    except Exception:
        logger.exception("[Connectors] update error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/connectors/{connector_id}")
def delete_connector(connector_id: str, request: Request) -> Any:
    try:
        deleted = request.app.state.db.delete_connector(connector_id)
        if not deleted:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        connector_registry.remove(connector_id)
        return {"success": True}
    except Exception:
        logger.exception("[Connectors] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors/{connector_id}/sync")
def trigger_sync(connector_id: str, request: Request) -> Any:
    connector_instance = connector_registry.get(connector_id)
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
def sync_history(connector_id: str, request: Request, limit: int = 20) -> Any:
    limit = min(limit, 100)
    try:
        history = request.app.state.db.get_connector_sync_history(connector_id, limit=limit)
        return {"success": True, "history": history}
    except Exception:
        logger.exception("[Connectors] history error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/connectors/{connector_id}/webhook")
async def receive_webhook(connector_id: str, request: Request) -> Any:
    db = request.app.state.db
    connector = db.get_connector(connector_id)
    if connector is None:
        return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
    if connector.get("connector_type") != "webhook":
        return JSONResponse({"success": False, "message": "Not a webhook connector"}, status_code=400)

    secret = connector.get("config", {}).get("secret")
    if secret:
        provided = request.headers.get("X-LocalChat-Secret", "")
        if provided != secret:
            logger.warning("[Webhook] Bad secret for connector")
            return JSONResponse({"success": False, "message": "Forbidden"}, status_code=403)

    instance = connector_registry.get(connector_id)
    if instance is None:
        return JSONResponse({"success": False, "message": "Connector not active"}, status_code=503)

    payload = await request.json() if await request.body() else {}
    errors = instance.push_event(payload)
    if errors:
        return JSONResponse({"success": False, "message": "; ".join(errors)}, status_code=400)

    return {"success": True, "message": "Event queued"}
