"""
Google OAuth2 — Token Refresh Helper
=====================================

Provides ``get_valid_google_access_token(user_id, db)`` which returns a fresh
access token, refreshing via the OAuth2 token endpoint if expired.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_valid_google_access_token(user_id: str, db: Any) -> str:
    """Return a valid Google access token for *user_id*, refreshing if expired.

    Raises:
        RuntimeError: If no token is stored or refresh fails.
    """
    token = db.get_oauth_token(user_id, 'google')
    if not token:
        raise RuntimeError(
            f"No Google OAuth token for user {user_id}. "
            "Connect via /api/oauth/google/authorize"
        )

    expires_at_str = token.get('expires_at')
    needs_refresh = True
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            needs_refresh = datetime.now(UTC) >= (expires_at - timedelta(seconds=60))
        except Exception:
            needs_refresh = True

    if not needs_refresh:
        return token['access_token']

    refresh_token = token.get('refresh_token')
    if not refresh_token:
        raise RuntimeError("Google token expired and no refresh_token available. Please reconnect.")

    return _refresh_google_token(user_id, refresh_token, db)


def _refresh_google_token(user_id: str, refresh_token: str, db: Any) -> str:
    """Exchange a Google refresh token for a new access token and persist it."""
    resp = requests.post(_GOOGLE_TOKEN_URL, data={
        'grant_type': 'refresh_token',
        'client_id': config.GOOGLE_CLIENT_ID,
        'client_secret': config.GOOGLE_CLIENT_SECRET,
        'refresh_token': refresh_token,
    }, timeout=15)

    if not resp.ok:
        raise RuntimeError(f"Google token refresh failed: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    access_token = data['access_token']
    expires_in = int(data.get('expires_in', 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    # Google does not rotate refresh tokens on every refresh
    db.upsert_oauth_token(
        user_id=user_id,
        provider='google',
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=data.get('scope', '').split(),
    )
    logger.info(f"[GoogleAuth] Refreshed token for user {user_id}")
    return access_token
