"""Auth routes — user management (admin) + self-service password change."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..security_fastapi import (
    decode_token_for_revocation,
    extract_bearer_token,
    get_current_user_id,
    require_admin_dep,
)
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_NOT_FOUND = "User not found"
_ERR_INTERNAL = "Internal server error"


def _public(user: dict) -> dict:
    return {k: v for k, v in user.items() if k != "hashed_password"}


@router.post("/users", status_code=201)
async def create_user(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..db.users import hash_user_password

    data = await request.json() if await request.body() else {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    email = (data.get("email") or "").strip() or None
    role = data.get("role", "user")

    if not username:
        return JSONResponse({"success": False, "message": "username is required"}, status_code=400)
    if not password:
        return JSONResponse({"success": False, "message": "password is required"}, status_code=400)
    if role not in ("admin", "user"):
        return JSONResponse({"success": False, "message": "role must be 'admin' or 'user'"}, status_code=400)

    try:
        db = request.app.state.db
        user_id = db.create_user(username=username, hashed_password=hash_user_password(password), email=email, role=role)
        user = db.get_user_by_id(user_id)
        return JSONResponse({"success": True, "user": _public(user)}, status_code=201)
    except Exception as exc:
        if "unique" in str(exc).lower():
            return JSONResponse({"success": False, "message": "Username or email already exists"}, status_code=409)
        logger.exception("[Users] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/users")
def list_users(request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        users = request.app.state.db.list_users()
        return {"success": True, "users": [_public(u) for u in users]}
    except Exception:
        logger.exception("[Users] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/users/{user_id}")
def get_user(user_id: str, request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        user = request.app.state.db.get_user_by_id(user_id)
        if user is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "user": _public(user)}
    except Exception:
        logger.exception("[Users] get error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/users/{user_id}")
async def update_user(user_id: str, request: Request, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    from ..db.users import hash_user_password

    data = await request.json() if await request.body() else {}
    allowed = {"email", "role", "is_active"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if "password" in data:
        fields["hashed_password"] = hash_user_password(data["password"])
    if not fields:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        db = request.app.state.db
        updated = db.update_user(user_id, **fields)
        if not updated:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "user": _public(db.get_user_by_id(user_id))}
    except Exception:
        logger.exception("[Users] update error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/users/{user_id}/purge")
def purge_user(user_id: str, request: Request, admin_user_id: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        purged = request.app.state.db.purge_user(user_id)
        if not purged:
            return JSONResponse(
                {
                    "success": False,
                    "message": (
                        "User cannot be purged: active workspace memberships exist. "
                        "Remove the user from all workspaces first."
                    ),
                },
                status_code=409,
            )
        return {"success": True}
    except Exception:
        logger.exception("[Users] purge error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request, admin_user_id: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        deleted = request.app.state.db.delete_user(user_id, deleted_by=admin_user_id)
        if not deleted:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True}
    except Exception:
        logger.exception("[Users] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/users/me/password")
async def change_own_password(request: Request) -> Any:
    from ..db.users import hash_user_password

    user_id = get_current_user_id(request)
    if not user_id or user_id == "anonymous":
        return JSONResponse({"success": False, "message": "Authentication required"}, status_code=401)

    data = await request.json() if await request.body() else {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if not current_password or not new_password:
        return JSONResponse({"success": False, "message": "current_password and new_password required"}, status_code=400)

    db = request.app.state.db
    user = db.get_user_by_id(user_id)
    if not user:
        return JSONResponse({"success": False, "message": "User not found"}, status_code=404)

    if not db.verify_user_password(user["username"], current_password):
        return JSONResponse({"success": False, "message": "Current password is incorrect"}, status_code=401)

    db.update_user(user_id, hashed_password=hash_user_password(new_password))
    return {"success": True}


@router.post("/logout")
async def logout(request: Request) -> Any:
    """Revoke the caller's current JWT so it cannot be reused."""
    token = extract_bearer_token(request)
    if not token:
        return JSONResponse({"success": False, "message": "No token provided"}, status_code=400)
    payload = decode_token_for_revocation(token)
    if payload is None:
        return JSONResponse({"success": False, "message": "Invalid token"}, status_code=400)

    jti = payload.get("jti")
    if not jti:
        # Token predates jti support — nothing to revoke, still report success.
        return {"success": True}

    exp_ts = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp_ts, tz=UTC) if exp_ts else datetime.now(UTC)

    db = getattr(request.app.state, "db", None)
    if db is None or not getattr(db, "is_connected", False):
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)

    try:
        db.revoke_token(jti, expires_at)
    except Exception:
        logger.exception("[Auth] logout revoke error")
        return JSONResponse({"success": False, "message": "Failed to revoke token"}, status_code=500)

    return {"success": True}
