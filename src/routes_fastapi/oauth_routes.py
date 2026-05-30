"""OAuth routes — Microsoft and Google OAuth2 flows."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests as _requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import config
from ..security_fastapi import get_current_user_id
from ..utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter()

_MS_SCOPES = "Files.Read.All Sites.Read.All offline_access"
_MS_AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_MS_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

_GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# In-memory CSRF state store (sufficient for single-process; use Redis for multi-worker)
_oauth_states: dict[str, str] = {}


def _tenant() -> str:
    return config.MICROSOFT_TENANT_ID or "common"


# ---------------------------------------------------------------------------
# Microsoft
# ---------------------------------------------------------------------------

@router.get("/oauth/microsoft/authorize")
def microsoft_authorize(request: Request) -> Response:
    if not config.MICROSOFT_CLIENT_ID:
        return JSONResponse({"success": False, "message": "MICROSOFT_CLIENT_ID is not configured"}, status_code=501)

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = "microsoft"

    params = {
        "client_id": config.MICROSOFT_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.MICROSOFT_REDIRECT_URI,
        "scope": _MS_SCOPES,
        "response_mode": "query",
        "state": state,
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

    stored = _oauth_states.pop(state or "", None)
    if stored is None:
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
    user_id = get_current_user_id(request) or "admin"

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
    user_id = get_current_user_id(request) or "admin"
    db = request.app.state.db
    token = db.get_oauth_token(user_id, "microsoft")
    if not token:
        return JSONResponse({"connected": False})
    expired = db.is_token_expired(user_id, "microsoft")
    return JSONResponse({"connected": True, "expires_at": token.get("expires_at"), "expired": expired, "scopes": token.get("scopes", [])})


@router.delete("/oauth/microsoft/disconnect")
def microsoft_disconnect(request: Request) -> JSONResponse:
    user_id = get_current_user_id(request) or "admin"
    deleted = request.app.state.db.delete_oauth_token(user_id, "microsoft")
    return JSONResponse({"success": True, "removed": deleted})


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

@router.get("/oauth/google/authorize")
def google_authorize(request: Request) -> Response:
    if not config.GOOGLE_CLIENT_ID:
        return JSONResponse({"success": False, "message": "GOOGLE_CLIENT_ID is not configured"}, status_code=501)

    state = secrets.token_urlsafe(16)
    _oauth_states[state] = "google"

    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "scope": _GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
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

    stored = _oauth_states.pop(state or "", None)
    if stored is None:
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
    user_id = get_current_user_id(request) or "admin"

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
    user_id = get_current_user_id(request) or "admin"
    db = request.app.state.db
    token = db.get_oauth_token(user_id, "google")
    if not token:
        return JSONResponse({"connected": False})
    expired = db.is_token_expired(user_id, "google")
    return JSONResponse({"connected": True, "expires_at": token.get("expires_at"), "expired": expired, "scopes": token.get("scopes", [])})


@router.delete("/oauth/google/disconnect")
def google_disconnect(request: Request) -> JSONResponse:
    user_id = get_current_user_id(request) or "admin"
    deleted = request.app.state.db.delete_oauth_token(user_id, "google")
    return JSONResponse({"success": True, "removed": deleted})
