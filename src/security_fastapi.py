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
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .utils.logging_config import get_logger
from .utils.workspace import get_workspace_id

logger = get_logger(__name__)

# ── JWT ────────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"

_ADMIN_PASSWORD_RAW: str = config.ADMIN_PASSWORD
_ADMIN_PASSWORD_SALT: bytes = os.urandom(32)
_ADMIN_PASSWORD_HASH: bytes = hashlib.pbkdf2_hmac(
    "sha256", _ADMIN_PASSWORD_RAW.encode(), _ADMIN_PASSWORD_SALT, 100_000
)

_ROLE_LEVELS: dict[str, int] = {"viewer": 0, "editor": 1, "owner": 2}
_ERR_AUTH_REQUIRED = "Authentication required"

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
    """The last remaining authorisation bypass, and it is test-only.

    SEC-1 removed the other two. ``not _ADMIN_PASSWORD_RAW`` went because an admin
    account is now always seeded, so an empty password no longer means "no way in";
    ``DEMO_MODE`` went because it disabled authorisation rather than reachability —
    a safety flag implemented at the wrong layer, which made it the risk it was
    meant to reduce.

    ``app.state.testing`` survives only until TQ-1 replaces it with route tests that
    authenticate for real. At that point this function has no branch left and goes.
    """
    return _is_testing(request)


#: Name of the httpOnly cookie the browser session uses. Not configurable —
#: a renamed cookie would silently log everyone out with no other symptom.
SESSION_COOKIE = "localchat_session"


def _extract_bearer_token(request: Request) -> str | None:
    """Return the caller's JWT from the Authorization header, else the session cookie.

    Header first so API clients, tests and any curl/n8n integration keep working
    exactly as before; the cookie exists for the browser, which must not be able to
    read its own token (AUTH-1: httpOnly, so an XSS in rendered LLM output cannot
    exfiltrate it).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(SESSION_COOKIE) or None


def extract_bearer_token(request: Request) -> str | None:
    """Public: extract Bearer token from Authorization header."""
    return _extract_bearer_token(request)


def decode_token_for_revocation(token: str) -> dict[str, Any] | None:
    """Decode a JWT for revocation — returns claims dict or None on any failure."""
    try:
        return _decode_token(token)
    except Exception:
        return None


def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> str | None:
    """Return the JWT sub claim or None when no valid token is present.

    Safe to call both as a FastAPI Depends and directly with just request.
    """
    if _is_testing(request):
        return None
    # getattr, not truthiness: called directly rather than via Depends, *credentials*
    # is the unresolved Depends sentinel — truthy, but with no .credentials attribute.
    token = getattr(credentials, "credentials", None) or _extract_bearer_token(request)
    if not token:
        return None
    try:
        payload = _decode_token(token)
        return payload.get("sub")
    except Exception:
        return None


#: How long a successful "not revoked" answer stays usable when the database cannot be
#: reached. Long enough to ride out a restart or a brief blip, short enough that a
#: revocation takes effect within a minute even during one.
_REVOCATION_CACHE_TTL = 60.0
#: Bounded so a stream of distinct tokens cannot grow this without limit.
_REVOCATION_CACHE_MAX = 4096

_revocation_cache: dict[str, float] = {}
_revocation_cache_lock = threading.Lock()


def _remember_not_revoked(jti: str) -> None:
    with _revocation_cache_lock:
        if len(_revocation_cache) >= _REVOCATION_CACHE_MAX:
            cutoff = time.monotonic() - _REVOCATION_CACHE_TTL
            for key in [k for k, seen in _revocation_cache.items() if seen < cutoff]:
                del _revocation_cache[key]
            if len(_revocation_cache) >= _REVOCATION_CACHE_MAX:
                _revocation_cache.clear()  # nothing stale to drop; start over
        _revocation_cache[jti] = time.monotonic()


def _recently_verified(jti: str) -> bool:
    with _revocation_cache_lock:
        seen = _revocation_cache.get(jti)
    return seen is not None and (time.monotonic() - seen) < _REVOCATION_CACHE_TTL


def _verify_jti_not_revoked(jti: str, db: Any) -> None:
    """Raise 401 unless this token is known not to be revoked.

    Fail-closed (SEC-2). Revocation that stops applying the moment the database
    hiccups is advisory, not revocation — and it bought nothing: every
    workspace-scoped route already answers 503 without a database, so the
    application is unusable in that state either way. The old behaviour left a
    window in which a token revoked minutes ago was accepted again.

    The cache keeps that from being brittle: a token verified within the last
    minute stays usable through a blip, so an outage degrades to
    slightly-stale-but-enforced instead of to open. Anything not recently verified
    is refused. In-process is the right place for it under ADR-1 — one node, one
    process.
    """
    if db is not None and getattr(db, "is_connected", False):
        try:
            if db.is_token_revoked(jti):
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED, detail={"message": "Token has been revoked"}
                )
            _remember_not_revoked(jti)
            return
        except HTTPException:
            raise
        except Exception:
            logger.warning("[Auth] Revocation check failed; falling back to cache")

    if _recently_verified(jti):
        return

    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail={"message": "Could not verify token status"},
    )


def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
) -> str:
    """FastAPI dependency — return user_id or raise 401.

    Safe to call directly with just a request, like ``get_current_user_id``.
    """
    if _is_rbac_bypassed(request):
        return "anonymous"
    # getattr, not truthiness: called directly rather than via Depends, *credentials*
    # is the unresolved Depends sentinel — truthy, but with no .credentials attribute.
    # Left as `if not credentials` this rejected every caller, valid token included.
    token = getattr(credentials, "credentials", None) or _extract_bearer_token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": _ERR_AUTH_REQUIRED})
    try:
        payload = _decode_token(token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": "Invalid or expired token"}) from None
    jti = payload.get("jti")
    if jti:
        _verify_jti_not_revoked(jti, getattr(request.app.state, "db", None))
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
    # Falls back to the request so a browser session (httpOnly cookie, no
    # Authorization header) reaches admin routes too. Without the fallback every
    # admin route 401s for a correctly authenticated cookie session.
    claims = _get_token_claims(credentials) or _claims_from_request(request)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"message": _ERR_AUTH_REQUIRED})
    if claims.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"message": "Admin access required"})
    return claims.get("sub", "admin")


def _claims_from_request(request: Request) -> dict[str, Any]:
    """Return JWT claims from the request's Authorization header, or ``{}``."""
    token = _extract_bearer_token(request)
    if not token:
        return {}
    try:
        return _decode_token(token)
    except Exception:
        return {}


def _extract_api_key(request: Request) -> str | None:
    """Return a workspace API key from ``X-API-Key`` or a ``Bearer lcw_...`` header.

    Accepting it as a Bearer token as well means an HTTP client that only offers an
    Authorization field — n8n, most webhook tools — needs no special handling. The
    ``lcw_`` prefix is what distinguishes it from a JWT, so the two never collide.
    """
    from .db.workspace_keys import KEY_PREFIX

    header = request.headers.get("X-API-Key", "").strip()
    if header.startswith(KEY_PREFIX):
        return header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        candidate = auth[7:].strip()
        if candidate.startswith(KEY_PREFIX):
            return candidate
    return None


def _check_api_key_access(
    request: Request,
    api_key: str,
    workspace_id: str | None,
    min_role: str,
) -> tuple[int, str] | None:
    """Authorise a workspace API key.

    The key's own workspace is authoritative. A caller-supplied workspace — path
    parameter, ``X-Workspace-ID`` header, query string — is only ever compared
    against it, never substituted for it. Without that rule a key issued for one
    workspace could read any other simply by changing a header, which would make
    the key a credential for the whole installation rather than for one workspace.

    A key also never receives the global-admin short-circuit: it is scoped to a
    workspace by construction, and nothing about it should be able to escape that.
    """
    db = getattr(request.app.state, "db", None)
    if db is None or not db.is_connected:
        return (status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable")

    resolved = db.resolve_workspace_api_key(api_key)
    if resolved is None:
        return (status.HTTP_401_UNAUTHORIZED, "Invalid or revoked API key")
    key_workspace, key_role = resolved

    requested = workspace_id or get_workspace_id(request)
    if requested and requested != key_workspace:
        return (status.HTTP_403_FORBIDDEN, "API key is not valid for this workspace")

    if _ROLE_LEVELS.get(key_role, -1) < _ROLE_LEVELS.get(min_role, 0):
        return (status.HTTP_403_FORBIDDEN, f"API key requires {min_role} role or higher")

    # Pin the scope for everything downstream. get_workspace_id() prefers this over
    # the header, so a request that omits X-Workspace-ID cannot fall through to the
    # default workspace after authorising against the key's.
    request.state.api_key_workspace_id = key_workspace
    return None


def check_workspace_access(
    request: Request,
    workspace_id: str | None,
    min_role: str,
) -> tuple[int, str] | None:
    """Return ``(status, message)`` when the caller may not act at *min_role* here, else ``None``.

    Safe to call directly with just a request — it reads the bearer token from the
    Authorization header rather than requiring a Depends-injected credential, so a
    route with ``workspace_id`` as a *path* parameter can pass that value explicitly.
    That matters: a dependency declaring its own ``workspace_id`` would have it bound
    as a query parameter, silently authorising against the wrong workspace.

    Pass ``workspace_id=None`` for a header-scoped route; scope then resolves via
    ``get_workspace_id`` and falls back to the default workspace.
    """
    if _is_rbac_bypassed(request):
        return None

    # A workspace API key is a principal in its own right, checked before user
    # claims because it is not a user and must not fall through to user handling.
    api_key = _extract_api_key(request)
    if api_key:
        return _check_api_key_access(request, api_key, workspace_id, min_role)

    claims = _claims_from_request(request)
    if not claims:
        return (status.HTTP_401_UNAUTHORIZED, _ERR_AUTH_REQUIRED)
    if claims.get("role") == "admin":
        return None
    ws_id = workspace_id or get_workspace_id(request)
    db = getattr(request.app.state, "db", None)
    if db is None or not db.is_connected:
        return (status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable")
    if not ws_id:
        # X-Workspace-ID is optional and the frontend omits it until localStorage
        # holds an active workspace, so a fresh session sends none. Falling back to
        # the default workspace keeps those requests working exactly as they did
        # before this check existed; erroring here would break them on first load.
        ws_id = db.get_default_workspace_id()
    if not ws_id:
        return (status.HTTP_400_BAD_REQUEST, "No workspace context")
    role = db.get_workspace_member_role(ws_id, claims.get("sub"))
    # A non-member gets None here. Denying is the whole point: treating None as
    # "no role to object to" is what let non-members through (BUG-3).
    if role is None:
        return (status.HTTP_403_FORBIDDEN, "Access denied: not a workspace member")
    if _ROLE_LEVELS.get(role, -1) < _ROLE_LEVELS.get(min_role, 0):
        return (status.HTTP_403_FORBIDDEN, f"Requires {min_role} role or higher")
    return None


def _enforce_workspace_role(
    request: Request,
    workspace_id: str | None,
    credentials: HTTPAuthorizationCredentials | None,
    min_role: str,
) -> str:
    """Enforce workspace membership; returns user_id or raises 4xx."""
    if _is_rbac_bypassed(request):
        return "anonymous"
    denial = check_workspace_access(request, workspace_id, min_role)
    if denial is not None:
        code, message = denial
        raise HTTPException(code, detail={"message": message})
    claims = _get_token_claims(credentials) or _claims_from_request(request)
    return claims.get("sub") or "admin"


def require_workspace_role_dep(min_role: str):
    """Return a FastAPI dependency that enforces workspace membership."""

    def _dep(
        request: Request,
        workspace_id: str | None = None,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),  # noqa: B008
    ) -> str:
        return _enforce_workspace_role(request, workspace_id, credentials, min_role)

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
