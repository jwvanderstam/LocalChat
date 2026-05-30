"""
FastAPI Security — JWT auth, rate limiting, CORS, admin guards.

Uses:
  - python-jose for JWT encode/decode
  - slowapi for rate limiting
  - FastAPI dependency injection for auth guards
  - Starlette CORSMiddleware for CORS

Public API
----------
require_auth        — FastAPI dependency; returns user_id str
require_admin_dep   — FastAPI dependency; raises 403 if not admin
get_current_user_id — util returning user_id or None (no exception)
create_access_token — create a JWT for a user
verify_credentials  — check username/password; returns (sub, role) or None
limiter             — slowapi Limiter instance (attach to FastAPI app)
setup_cors          — adds CORSMiddleware to a FastAPI app
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .utils.logging_config import get_logger

logger = get_logger(__name__)

# ── JWT ────────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"

_ADMIN_PASSWORD_RAW: str = config.ADMIN_PASSWORD
_ADMIN_PASSWORD_SALT: bytes = os.urandom(32)
_ADMIN_PASSWORD_HASH: bytes = hashlib.pbkdf2_hmac(
    "sha256", _ADMIN_PASSWORD_RAW.encode(), _ADMIN_PASSWORD_SALT, 100_000
)

_ROLE_LEVELS: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}

_bearer = HTTPBearer(auto_error=False)


def create_access_token(identity: str, additional_claims: dict[str, Any] | None = None) -> str:
    """Return a signed JWT for *identity*."""
    from jose import jwt

    payload: dict[str, Any] = {
        "sub": identity,
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(UTC) + timedelta(seconds=config.JWT_ACCESS_TOKEN_EXPIRES),
        "iat": datetime.now(UTC),
    }
    payload.update(additional_claims or {})
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=_ALGORITHM)


def _decode_token(token: str) -> dict[str, Any]:
    from jose import jwt
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=[_ALGORITHM])


def verify_credentials(username: str, password: str) -> tuple[str, str] | None:
    """Return *(user_sub, user_role)* on success, ``None`` on failure."""
    # Try DB-backed users first (injected via app state at call site).
    # Fall back to the legacy env-var admin account.
    if username != "admin" or not _ADMIN_PASSWORD_RAW:
        return None
    provided_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), _ADMIN_PASSWORD_SALT, 100_000
    )
    if not hmac.compare_digest(provided_hash, _ADMIN_PASSWORD_HASH):
        return None
    return "admin", "admin"


def verify_credentials_db(username: str, password: str, db: Any) -> tuple[str, str] | None:
    """Try DB-backed auth, then fall back to env-var admin."""
    if db is not None and getattr(db, "is_connected", False):
        db_user = db.verify_user_password(username, password)
        if db_user:
            return str(db_user["id"]), db_user.get("role", "user")
    return verify_credentials(username, password)


# ── Auth dependencies ──────────────────────────────────────────────────────────

def _is_testing(request: Request) -> bool:
    return getattr(request.app.state, "testing", False)


def _is_rbac_bypassed(request: Request) -> bool:
    return (
        not _ADMIN_PASSWORD_RAW
        or config.DEMO_MODE
        or _is_testing(request)
    )


def _extract_bearer_token(request: Request) -> str | None:
    """Extract Bearer token from Authorization header without DI."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> str | None:
    """Return the JWT sub claim or None when no valid token is present.

    Safe to call both as a FastAPI Depends and directly with just request.
    """
    if _is_testing(request) or config.DEMO_MODE:
        return None
    token = credentials.credentials if credentials else _extract_bearer_token(request)
    if not token:
        return None
    try:
        payload = _decode_token(token)
        return payload.get("sub")
    except Exception:
        return None


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> str:
    """FastAPI dependency — return user_id or raise 401."""
    if _is_rbac_bypassed(request):
        return "anonymous"
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Authentication required"})
    try:
        payload = _decode_token(credentials.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Invalid or expired token"}) from None
    jti = payload.get("jti")
    if jti:
        db = getattr(request.app.state, "db", None)
        if db is not None and getattr(db, "is_connected", False):
            try:
                if db.is_token_revoked(jti):
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Token has been revoked"})
            except HTTPException:
                raise
            except Exception:
                pass  # DB unavailable — fail open rather than locking out users
    return payload["sub"]


def _get_token_claims(credentials: HTTPAuthorizationCredentials | None) -> dict[str, Any]:
    if not credentials:
        return {}
    try:
        return _decode_token(credentials.credentials)
    except Exception:
        return {}


def require_admin_dep(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> str:
    """FastAPI dependency — require admin role or raise 403."""
    if _is_rbac_bypassed(request):
        return "anonymous"
    claims = _get_token_claims(credentials)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Authentication required"})
    if claims.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": "Admin access required"})
    return claims.get("sub", "admin")


def require_workspace_role_dep(min_role: str):
    """Return a FastAPI dependency that enforces workspace membership."""

    def _dep(
        request: Request,
        workspace_id: str | None = None,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
    ) -> str:
        if _is_rbac_bypassed(request):
            return "anonymous"
        claims = _get_token_claims(credentials)
        if not claims:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Authentication required"})
        user_id = claims.get("sub")
        if claims.get("role") == "admin":
            return user_id or "admin"
        # Resolve workspace_id from header when not in query
        ws_id = workspace_id or request.headers.get("X-Workspace-ID")
        if not ws_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"message": "No workspace context"})
        db = getattr(request.app.state, "db", None)
        if db is None or not db.is_connected:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail={"message": "Database unavailable"})
        role = db.get_workspace_member_role(ws_id, user_id)
        if role is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": "Access denied: not a workspace member"})
        if _ROLE_LEVELS.get(role, -1) < _ROLE_LEVELS.get(min_role, 0):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": f"Requires {min_role} role or higher"})
        return user_id or ""

    return _dep


# ── Rate limiting ──────────────────────────────────────────────────────────────

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, enabled=config.RATELIMIT_ENABLED)


# ── CORS ──────────────────────────────────────────────────────────────────────

def setup_cors(app: Any) -> None:
    """Add CORSMiddleware to a FastAPI app when CORS is enabled."""
    if not config.CORS_ENABLED:
        return
    origins = config.CORS_ORIGINS or ["*"]
    if origins == ["*"] or origins == "*":
        logger.warning(
            "CORS is enabled with wildcard origin ('*'). "
            "Any domain can make cross-origin requests. "
            "Set CORS_ORIGINS to specific domains for non-localhost deployments."
        )
    from starlette.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS enabled for origins: %s", origins)
