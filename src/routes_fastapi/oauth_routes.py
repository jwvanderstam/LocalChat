"""OAuth routes — Microsoft and Google OAuth2 flows."""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests as _requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import config
from ..security_fastapi import require_auth
from ..utils.logging_config import get_logger
from ._authz import require_caller

logger = get_logger(__name__)
router = APIRouter()

_MS_SCOPES = "Files.Read.All Sites.Read.All offline_access"
_MS_AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_MS_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

_GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

#: How long an authorization may stay in flight. Long enough to read a consent
#: screen and pick an account, short enough that an abandoned one does not sit in
#: memory. Entries used to have no expiry at all and were never pruned (audit M3).
_STATE_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class _PendingAuthorization:
    """What /authorize knew and the callback needs.

    ``user_id`` is here because the callback cannot ask the session who is calling:
    it is reached by a redirect *from the provider*, which is a cross-site
    navigation, and the session cookie is ``SameSite=strict``. The old code called
    ``require_caller(request)`` there and got a 401 — after the authorization code
    had already been spent, so the account was never connected and the code could
    not be replayed (audit M3).

    ``code_verifier`` is PKCE. Without it, anyone who intercepts the redirect —
    a shoulder-surfed URL, a leaky proxy, browser history — can exchange the code
    for a token, because the exchange needs only the code and a client secret the
    provider already trusts this client to hold.
    """

    provider: str
    user_id: str
    code_verifier: str
    expires_at: datetime


# Single-process by construction (ADR-1, and UVICORN_WORKERS>1 now aborts the boot),
# so in-memory is correct here rather than merely convenient.
_oauth_states: dict[str, _PendingAuthorization] = {}
_oauth_states_lock = threading.Lock()


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _remember_authorization(provider: str, user_id: str) -> tuple[str, str]:
    """Record a pending authorization; return (state, code_challenge)."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with _oauth_states_lock:
        # Prune here rather than on a timer: this is the only place the store grows.
        for key in [k for k, v in _oauth_states.items() if v.expires_at <= now]:
            del _oauth_states[key]
        _oauth_states[state] = _PendingAuthorization(
            provider=provider,
            user_id=user_id,
            code_verifier=verifier,
            expires_at=now + _STATE_TTL,
        )
    return state, challenge


def _claim_authorization(state: str | None, provider: str) -> _PendingAuthorization | None:
    """Consume *state*, or None when it is unknown, expired or another provider's.

    Single-use: popped whether or not it turns out to be valid, so a state cannot
    be replayed even against the branch that rejects it.
    """
    if not state:
        return None
    with _oauth_states_lock:
        pending = _oauth_states.pop(state, None)
    if pending is None:
        return None
    if pending.expires_at <= datetime.now(UTC):
        logger.warning("[OAuth] Rejected an expired authorization state")
        return None
    if pending.provider != provider:
        # A Google state arriving at the Microsoft callback is not a mix-up to
        # tolerate; the two flows must not be interchangeable.
        logger.warning("[OAuth] Rejected a state issued for a different provider")
        return None
    return pending


def _tenant() -> str:
    return config.MICROSOFT_TENANT_ID or "common"


# ---------------------------------------------------------------------------
# Microsoft
# ---------------------------------------------------------------------------

@router.get("/oauth/microsoft/authorize")
def microsoft_authorize(request: Request) -> Response:
    require_auth(request)
    if not config.MICROSOFT_CLIENT_ID:
        return JSONResponse({"success": False, "message": "MICROSOFT_CLIENT_ID is not configured"}, status_code=501)

    state, challenge = _remember_authorization("microsoft", require_caller(request))

    params = {
        "client_id": config.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.MICROSOFT_REDIRECT_URI,
        "scope": _MS_SCOPES,
        "response_mode": "query",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = _MS_AUTH_URL.format(tenant=_tenant()) + "?" + urlencode(params)
    return RedirectResponse(url=auth_url)


@router.get("/oauth/microsoft/callback")
def microsoft_callback(request: Request) -> JSONResponse:
    error = request.query_params.get("error")
    if error:
        desc = request.query_params.get("error_description", error)
        logger.warning("[OAuth] Microsoft returned an error during authorization")
        return JSONResponse({"success": False, "message": desc}, status_code=400)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        return JSONResponse({"success": False, "message": "Missing authorization code"}, status_code=400)

    pending = _claim_authorization(state, "microsoft")
    if pending is None:
        return JSONResponse({"success": False, "message": "State mismatch — possible CSRF"}, status_code=400)

    try:
        resp = _requests.post(
            _MS_TOKEN_URL.format(tenant=_tenant()),
            data={
                "grant_type": "authorization_code",
                "client_id": config.MICROSOFT_CLIENT_ID,
                "client_secret": config.MICROSOFT_CLIENT_SECRET,
                "code": code,
                "redirect_uri": config.MICROSOFT_REDIRECT_URI,
                "scope": _MS_SCOPES,
                "code_verifier": pending.code_verifier,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except _requests.HTTPError:
        logger.exception("[OAuth] Token exchange failed")
        return JSONResponse({"success": False, "message": "Token exchange failed"}, status_code=500)

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        return JSONResponse({"success": False, "message": "No access_token in response"}, status_code=500)

    expires_in = int(data.get("expires_in", 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    # From the state, not the session: this request is a redirect from the provider,
    # and the SameSite=strict session cookie is not sent on it (audit M3).
    user_id = pending.user_id

    request.app.state.db.upsert_oauth_token(
        user_id=user_id,
        provider="microsoft",
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=data.get("scope", "").split(),
    )
    logger.info("[OAuth] Microsoft token stored for user %s", user_id)
    return JSONResponse({"success": True, "message": "Microsoft account connected", "expires_at": expires_at.isoformat()})


@router.get("/oauth/microsoft/status")
def microsoft_status(request: Request) -> JSONResponse:
    require_auth(request)
    user_id = require_caller(request)
    db = request.app.state.db
    token = db.get_oauth_token(user_id, "microsoft")
    if not token:
        return JSONResponse({"connected": False})
    expired = db.is_token_expired(user_id, "microsoft")
    return JSONResponse({"connected": True, "expires_at": token.get("expires_at"), "expired": expired, "scopes": token.get("scopes", [])})


@router.delete("/oauth/microsoft/disconnect")
def microsoft_disconnect(request: Request) -> JSONResponse:
    require_auth(request)
    user_id = require_caller(request)
    deleted = request.app.state.db.delete_oauth_token(user_id, "microsoft")
    return JSONResponse({"success": True, "removed": deleted})


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

@router.get("/oauth/google/authorize")
def google_authorize(request: Request) -> Response:
    require_auth(request)
    if not config.GOOGLE_CLIENT_ID:
        return JSONResponse({"success": False, "message": "GOOGLE_CLIENT_ID is not configured"}, status_code=501)

    state, challenge = _remember_authorization("google", require_caller(request))

    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse(url=_GOOGLE_AUTH_URL + "?" + urlencode(params))


@router.get("/oauth/google/callback")
def google_callback(request: Request) -> JSONResponse:
    error = request.query_params.get("error")
    if error:
        desc = request.query_params.get("error_description", error)
        logger.warning("[OAuth] Google returned an error during authorization")
        return JSONResponse({"success": False, "message": desc}, status_code=400)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        return JSONResponse({"success": False, "message": "Missing authorization code"}, status_code=400)

    pending = _claim_authorization(state, "google")
    if pending is None:
        return JSONResponse({"success": False, "message": "State mismatch — possible CSRF"}, status_code=400)

    try:
        resp = _requests.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "code": code,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "code_verifier": pending.code_verifier,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except _requests.HTTPError:
        logger.exception("[OAuth] Google token exchange failed")
        return JSONResponse({"success": False, "message": "Token exchange failed"}, status_code=500)

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        return JSONResponse({"success": False, "message": "No access_token in response"}, status_code=500)

    expires_in = int(data.get("expires_in", 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    # From the state, not the session: this request is a redirect from the provider,
    # and the SameSite=strict session cookie is not sent on it (audit M3).
    user_id = pending.user_id

    request.app.state.db.upsert_oauth_token(
        user_id=user_id,
        provider="google",
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
        scopes=data.get("scope", "").split(),
    )
    logger.info("[OAuth] Google token stored for user %s", user_id)
    return JSONResponse({"success": True, "message": "Google account connected", "expires_at": expires_at.isoformat()})


@router.get("/oauth/google/status")
def google_status(request: Request) -> JSONResponse:
    require_auth(request)
    user_id = require_caller(request)
    db = request.app.state.db
    token = db.get_oauth_token(user_id, "google")
    if not token:
        return JSONResponse({"connected": False})
    expired = db.is_token_expired(user_id, "google")
    return JSONResponse({"connected": True, "expires_at": token.get("expires_at"), "expired": expired, "scopes": token.get("scopes", [])})


@router.delete("/oauth/google/disconnect")
def google_disconnect(request: Request) -> JSONResponse:
    require_auth(request)
    user_id = require_caller(request)
    deleted = request.app.state.db.delete_oauth_token(user_id, "google")
    return JSONResponse({"success": True, "removed": deleted})
