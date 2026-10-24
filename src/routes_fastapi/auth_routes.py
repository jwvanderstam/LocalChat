"""Auth routes — login/logout, user management (admin), self-service password change."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .. import config
from ..models import ChangePasswordRequest, LoginRequest
from ..security_fastapi import (
    SESSION_COOKIE,
    AuthError,
    check_workspace_access,
    create_access_token,
    decode_token_for_revocation,
    extract_bearer_token,
    limiter,
    require_admin_dep,
    resolve_principal,
)
from ..services.errors import ServiceError
from ..services.users import UsersService
from ..utils.logging_config import get_logger
from ..utils.workspace import get_workspace_id
from ._services import users_service

logger = get_logger(__name__)
router = APIRouter()
Users = Annotated[UsersService, Depends(users_service)]

_NOT_FOUND = "User not found"
_ERR_INTERNAL = "Internal server error"
_PASSWORD_RULES = (
    f"Give your current password and a new one of at least "
    f"{config.USER_PASSWORD_MIN_LENGTH} characters"
)
_PASSWORD_TOO_SHORT = f"password must be at least {config.USER_PASSWORD_MIN_LENGTH} characters"


def _is_acceptable_password(value: Any) -> bool:
    """The one rule every way of setting a password applies (audit S7)."""
    return isinstance(value, str) and len(value) >= config.USER_PASSWORD_MIN_LENGTH


def _refused(exc: ServiceError) -> JSONResponse:
    return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)


#: One message for "no such user" and "wrong password" alike — distinguishing them
#: turns the login form into a username oracle.
_ERR_BAD_CREDENTIALS = "Invalid username or password"


def _set_session_cookie(response: JSONResponse, token: str, request: Request) -> None:
    """Attach the session JWT as an httpOnly cookie.

    httpOnly so JavaScript cannot read it: this app renders LLM output into the DOM,
    which is the one place an XSS is most likely to appear, and a readable token there
    would be exfiltrable. SameSite=strict is sufficient CSRF protection because the UI
    and API share an origin and nothing posts into this app cross-site.
    """
    # Secure would make the cookie undeliverable over plain http, which is how the
    # app is reached on a developer machine. Loopback is already a trusted transport.
    is_loopback = (request.url.hostname or "") in ("localhost", "127.0.0.1", "::1")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.JWT_ACCESS_TOKEN_EXPIRES,
        httponly=True,
        samesite="strict",
        secure=not is_loopback,
        path="/",
    )


@router.post("/auth/login")
@limiter.limit(config.RATELIMIT_LOGIN)
async def login(request: Request, users: Users) -> Any:
    """Verify credentials and issue a session JWT as an httpOnly cookie.

    Rate-limited because this is the one endpoint where guessing is the attack.
    """
    data = await request.json() if await request.body() else {}
    try:
        creds = LoginRequest(**data)
    except (ValidationError, TypeError):
        return JSONResponse({"success": False, "message": _ERR_BAD_CREDENTIALS}, status_code=401)

    result = users.authenticate(creds.username, creds.password)
    if result is None:
        # Deliberately no username in the log: failed logins are the one place a
        # log becomes a list of attempted accounts.
        logger.warning("[Auth] Failed login attempt")
        return JSONResponse({"success": False, "message": _ERR_BAD_CREDENTIALS}, status_code=401)

    user_id, role = result
    token = create_access_token(user_id, {"role": role})
    response = JSONResponse({
        "success": True,
        "user_id": user_id,
        "role": role,
        "username": creds.username,
    })
    _set_session_cookie(response, token, request)
    logger.info("[Auth] Login succeeded for user %s", user_id)
    return response


@router.post("/users", status_code=201)
async def create_user(
    request: Request, users: Users, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    data = await request.json() if await request.body() else {}
    username = (data.get("username") or "").strip()
    # Never stripped: login, password change and reset take the password as typed,
    # so a stripped one here is a password its owner cannot sign in with (defect 2).
    password = data.get("password") or ""
    email = (data.get("email") or "").strip() or None
    role = data.get("role", "user")

    if not username:
        return JSONResponse({"success": False, "message": "username is required"}, status_code=400)
    if not password:
        return JSONResponse({"success": False, "message": "password is required"}, status_code=400)
    if not _is_acceptable_password(password):
        return JSONResponse({"success": False, "message": _PASSWORD_TOO_SHORT}, status_code=400)
    if role not in ("admin", "user"):
        return JSONResponse({"success": False, "message": "role must be 'admin' or 'user'"}, status_code=400)

    # Membership is granted in the same request, not as a follow-up call; see
    # UsersService.create_user for why.
    workspace_id = (data.get("workspace_id") or "").strip() or None
    workspace_role = data.get("workspace_role", "editor")
    if workspace_role not in ("viewer", "editor", "owner"):
        return JSONResponse(
            {"success": False, "message": "workspace_role must be viewer, editor or owner"},
            status_code=400,
        )

    try:
        user = users.create_user(username, password, email, role, workspace_id, workspace_role)
        return JSONResponse({"success": True, "user": user}, status_code=201)
    except ServiceError as exc:
        return _refused(exc)
    except Exception:
        logger.exception("[Users] create error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/users")
def list_users(
    users: Users,
    _admin: Annotated[str, Depends(require_admin_dep)],
    include_retired: bool = False,
) -> Any:
    try:
        return {"success": True, "users": users.list_users(include_retired)}
    except Exception:
        logger.exception("[Users] list error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/users/me")
def get_own_identity(request: Request, users: Users) -> Any:
    """Return the caller's identity and whether they may write in the active workspace.

    ``can_write`` is decided by the same ``check_workspace_access`` the routes
    themselves call, so the UI never reimplements the role hierarchy — a second
    copy of that rule is exactly what let the member routes drift (BUG-3).
    """
    # Through resolve_principal, not get_current_user_id: a revoked token decodes
    # fine, and answering it with an id and roles is what the public allowlist
    # promises this route never does. A refused token reads as anonymous.
    try:
        user_id: str | None = resolve_principal(request).user_id
    except AuthError:
        user_id = None
    workspace_id = get_workspace_id(request)
    global_role, workspace_role = users.identity(user_id, workspace_id)

    return {
        "success": True,
        "user_id": user_id,
        "role": global_role,
        "workspace_id": workspace_id,
        "workspace_role": workspace_role,
        "can_write": check_workspace_access(request, None, "editor") is None,
        # GKB-2's two guards, answered here for the same reason as can_write:
        # contributing is require_admin_dep, withdrawing is ws:owner.
        "can_contribute": global_role == "admin",
        "can_withdraw": check_workspace_access(request, None, "owner") is None,
    }


@router.get("/users/{user_id}/workspaces")
def list_user_workspaces(
    user_id: str,
    users: Users,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    """Which workspaces this user belongs to, and at what role."""
    try:
        return {"success": True, "workspaces": users.user_workspaces(user_id)}
    except Exception:
        logger.exception("[Users] list user workspaces error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/users/{user_id}/workspaces")
async def grant_user_workspace(
    user_id: str,
    request: Request,
    users: Users,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    """Grant or change this user's role in a workspace."""
    data = await request.json() if await request.body() else {}
    workspace_id = (data.get("workspace_id") or "").strip()
    role = data.get("role", "editor")
    if not workspace_id:
        return JSONResponse({"success": False, "message": "workspace_id is required"}, status_code=400)
    if role not in ("viewer", "editor", "owner"):
        return JSONResponse({"success": False, "message": "role must be viewer, editor or owner"}, status_code=400)
    try:
        users.grant_workspace(user_id, workspace_id, role)
        return {"success": True}
    except Exception:
        logger.exception("[Users] grant workspace error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/users/{user_id}/workspaces/{workspace_id}")
def revoke_user_workspace(
    user_id: str,
    workspace_id: str,
    users: Users,
    _admin: Annotated[str, Depends(require_admin_dep)],
) -> Any:
    """Remove this user from a workspace. Refuses to remove its last owner."""
    try:
        if not users.revoke_workspace(user_id, workspace_id):
            return JSONResponse({"success": False, "message": "Membership not found"}, status_code=404)
        return {"success": True}
    except ServiceError as exc:
        return _refused(exc)
    except Exception:
        logger.exception("[Users] revoke workspace error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.get("/users/{user_id}")
def get_user(user_id: str, users: Users, _admin: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        user = users.get_user(user_id)
        if user is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "user": user}
    except Exception:
        logger.exception("[Users] get error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.put("/users/{user_id}")
async def update_user(
    user_id: str, request: Request, users: Users, _admin: Annotated[str, Depends(require_admin_dep)]
) -> Any:
    data = await request.json() if await request.body() else {}
    allowed = {"email", "role", "is_active"}
    fields = {k: v for k, v in data.items() if k in allowed}
    password = data.get("password") if "password" in data else None
    if "password" in data and not _is_acceptable_password(password):
        return JSONResponse({"success": False, "message": _PASSWORD_TOO_SHORT}, status_code=400)
    if not fields and password is None:
        return JSONResponse({"success": False, "message": "No valid fields provided"}, status_code=400)
    try:
        user = users.update_user(user_id, fields, password)
        if user is None:
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True, "user": user}
    except ServiceError as exc:
        return _refused(exc)
    except Exception:
        logger.exception("[Users] update error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.delete("/users/{user_id}/purge")
def purge_user(user_id: str, users: Users, admin_user_id: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        if not users.purge_user(user_id):
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
def delete_user(user_id: str, users: Users, admin_user_id: Annotated[str, Depends(require_admin_dep)]) -> Any:
    try:
        if not users.retire_user(user_id, actor=admin_user_id):
            return JSONResponse({"success": False, "message": _NOT_FOUND}, status_code=404)
        return {"success": True}
    except ServiceError as exc:
        return _refused(exc)
    except Exception:
        logger.exception("[Users] delete error")
        return JSONResponse({"success": False, "message": _ERR_INTERNAL}, status_code=500)


@router.post("/users/me/password")
@limiter.limit(config.RATELIMIT_LOGIN)
async def change_own_password(request: Request, users: Users) -> Any:
    """Change the caller's own password, given the current one.

    Rate-limited like login: knowing the current password is the whole proof, so this
    is a second place to guess it.
    """
    try:
        principal = resolve_principal(request, database_required="Database unavailable")
    except AuthError as exc:
        return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status_code)

    data = await request.json() if await request.body() else {}
    try:
        body = ChangePasswordRequest(**data)
    except (ValidationError, TypeError):
        return JSONResponse({"success": False, "message": _PASSWORD_RULES}, status_code=400)

    try:
        users.change_own_password(principal.user_id, body.current_password, body.new_password)
    except ServiceError as exc:
        return _refused(exc)
    return {"success": True}


@router.post("/logout")
async def logout(request: Request, users: Users) -> Any:
    """Revoke the caller's current JWT so it cannot be reused."""
    token = extract_bearer_token(request)
    if not token:
        # Nothing to revoke, but still clear the cookie: a caller asking to log out
        # must end up logged out, not told their request was malformed.
        cleared = JSONResponse({"success": True})
        cleared.delete_cookie(SESSION_COOKIE, path="/")
        return cleared
    payload = decode_token_for_revocation(token)
    if payload is None:
        # Still clear it. The token is unusable either way, and leaving a known-bad
        # cookie in the browser serves nobody — the status stays 400 because the
        # caller did send something invalid.
        invalid = JSONResponse({"success": False, "message": "Invalid token"}, status_code=400)
        invalid.delete_cookie(SESSION_COOKIE, path="/")
        return invalid

    jti = payload.get("jti")
    if not jti:
        # Token predates jti support — nothing to revoke, still end the session.
        cleared = JSONResponse({"success": True})
        cleared.delete_cookie(SESSION_COOKIE, path="/")
        return cleared

    exp_ts = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp_ts, tz=UTC) if exp_ts else datetime.now(UTC)

    if not users.available:
        return JSONResponse({"success": False, "message": "Database unavailable"}, status_code=503)

    try:
        users.revoke_session(jti, expires_at)
    except Exception:
        logger.exception("[Auth] logout revoke error")
        return JSONResponse({"success": False, "message": "Failed to revoke token"}, status_code=500)

    response = JSONResponse({"success": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
