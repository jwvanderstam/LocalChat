"""
Microsoft Graph API — Token Refresh Helper
==========================================

Provides ``get_valid_access_token(user_id, db)`` which returns a fresh access
token, refreshing via the OAuth2 token endpoint if the stored token has expired.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import requests

from .. import config
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

_GRAPH_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"


def get_valid_access_token(user_id: str, db: Any) -> str:
    """Return a valid Microsoft Graph access token for *user_id*.

    Refreshes automatically when the stored token is expired.

    Raises:
        RuntimeError: If no token is stored or refresh fails.
    """
    token = db.get_oauth_token(user_id, 'microsoft')
    if not token:
        raise RuntimeError(f"No Microsoft OAuth token for user {user_id}. Connect via /api/oauth/microsoft/authorize")

    # Check expiry with a 60-second buffer
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

    # Attempt refresh
    refresh_token = token.get('refresh_token')
    if not refresh_token:
        raise RuntimeError("Microsoft token expired and no refresh_token available. Please reconnect.")

    return _refresh_token(user_id, refresh_token, db)


def _refresh_token(user_id: str, refresh_token: str, db: Any) -> str:
    """Exchange a refresh token for a new access token and persist it."""
    tenant = config.MICROSOFT_TENANT_ID or 'common'
    url = _GRAPH_TOKEN_URL.format(tenant=tenant)
    resp = requests.post(url, data={
        'grant_type': 'refresh_token',
        'client_id': config.MICROSOFT_CLIENT_ID,
        'client_secret': config.MICROSOFT_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'scope': 'Files.Read.All Sites.Read.All offline_access',
    }, timeout=15)

    if not resp.ok:
        raise RuntimeError(f"Microsoft token refresh failed: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    access_token = data['access_token']
    new_refresh = data.get('refresh_token', refresh_token)
    expires_in = int(data.get('expires_in', 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    db.upsert_oauth_token(
        user_id=user_id,
        provider='microsoft',
        access_token=access_token,
        refresh_token=new_refresh,
        expires_at=expires_at,
        scopes=data.get('scope', '').split(),
    )
    logger.info(f"[MicrosoftAuth] Refreshed token for user {user_id}")
    return access_token
