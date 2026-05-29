"""
OAuth Routes
============

OAuth2 authorization-code flows for SharePoint/OneDrive (Microsoft) and
Google Drive connectors.

Microsoft endpoints:
    GET    /api/oauth/microsoft/authorize    redirect to Azure AD consent screen
    GET    /api/oauth/microsoft/callback     exchange code for tokens, store encrypted
    DELETE /api/oauth/microsoft/disconnect   remove stored token for current user
    GET    /api/oauth/microsoft/status       {connected: bool, expires_at}

Google endpoints:
    GET    /api/oauth/google/authorize       redirect to Google consent screen
    GET    /api/oauth/google/callback        exchange code for tokens, store encrypted
    DELETE /api/oauth/google/disconnect      remove stored token for current user
    GET    /api/oauth/google/status          {connected: bool, expires_at}
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, jsonify, redirect, request, session
from flask.typing import ResponseReturnValue

from .. import config
from ..security import get_current_user_id
from ..utils.logging_config import get_logger

logger = get_logger(__name__)

bp = Blueprint('oauth', __name__)

# Microsoft
_MS_SCOPES = 'Files.Read.All Sites.Read.All offline_access'
_MS_AUTH_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize'
_MS_TOKEN_URL = 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token'

# Google
_GOOGLE_SCOPES = 'openid email https://www.googleapis.com/auth/drive.readonly'
_GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
_GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'


def _tenant() -> str:
    return config.MICROSOFT_TENANT_ID or 'common'


# ---------------------------------------------------------------------------
# Authorize — redirect to Azure AD
# ---------------------------------------------------------------------------

@bp.get('/oauth/microsoft/authorize')
def microsoft_authorize() -> ResponseReturnValue:
    """
    Redirect the user to the Microsoft OAuth2 consent screen.
    ---
    tags: [OAuth]
    responses:
      302: {description: Redirect to Azure AD}
      501: {description: Microsoft OAuth not configured}
    """
    if not config.MICROSOFT_CLIENT_ID:
        return jsonify({'success': False, 'message': 'MICROSOFT_CLIENT_ID is not configured'}), 501

    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    params = {
        'client_id': config.MICROSOFT_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': config.MICROSOFT_REDIRECT_URI,
        'scope': _MS_SCOPES,
        'response_mode': 'query',
        'state': state,
    }
    auth_url = _MS_AUTH_URL.format(tenant=_tenant()) + '?' + urlencode(params)
    return redirect(auth_url)


# ---------------------------------------------------------------------------
# Callback — exchange code for tokens
# ---------------------------------------------------------------------------

@bp.get('/oauth/microsoft/callback')
def microsoft_callback() -> ResponseReturnValue:
    """
    Handle Azure AD callback, exchange code for tokens, store encrypted.
    ---
    tags: [OAuth]
    responses:
      200: {description: Connected successfully}
      400: {description: State mismatch or missing code}
      500: {description: Token exchange failed}
    """
    error = request.args.get('error')
    if error:
        desc = request.args.get('error_description', error)
        logger.warning("[OAuth] Microsoft returned an error during authorization")
        return jsonify({'success': False, 'message': desc}), 400

    code = request.args.get('code')
    state = request.args.get('state')
    if not code:
        return jsonify({'success': False, 'message': 'Missing authorization code'}), 400

    # Validate state (CSRF protection)
    stored_state = session.pop('oauth_state', None)
    if stored_state and state != stored_state:
        return jsonify({'success': False, 'message': 'State mismatch — possible CSRF'}), 400

    # Exchange code for tokens
    try:
        resp = requests.post(
            _MS_TOKEN_URL.format(tenant=_tenant()),
            data={
                'grant_type': 'authorization_code',
                'client_id': config.MICROSOFT_CLIENT_ID,
                'client_secret': config.MICROSOFT_CLIENT_SECRET,
                'code': code,
                'redirect_uri': config.MICROSOFT_REDIRECT_URI,
                'scope': _MS_SCOPES,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        logger.error(f"[OAuth] Token exchange failed: {exc}")
        return jsonify({'success': False, 'message': 'Token exchange failed'}), 500

    data = resp.json()
    access_token = data.get('access_token')
    if not access_token:
        return jsonify({'success': False, 'message': 'No access_token in response'}), 500

    expires_in = int(data.get('expires_in', 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

    # Resolve current user — fall back to 'admin' for single-user installs
    user_id = get_current_user_id() or 'admin'

    current_app.db.upsert_oauth_token(
        user_id=user_id,
        provider='microsoft',
        access_token=access_token,
        refresh_token=data.get('refresh_token'),
        expires_at=expires_at,
        scopes=data.get('scope', '').split(),
    )
    logger.info(f"[OAuth] Microsoft token stored for user {user_id}")
    return jsonify({'success': True, 'message': 'Microsoft account connected', 'expires_at': expires_at.isoformat()})


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@bp.get('/oauth/microsoft/status')
def microsoft_status() -> ResponseReturnValue:
    """Return whether the current user has a stored Microsoft token."""
    user_id = get_current_user_id() or 'admin'
    token = current_app.db.get_oauth_token(user_id, 'microsoft')
    if not token:
        return jsonify({'connected': False})
    expired = current_app.db.is_token_expired(user_id, 'microsoft')
    return jsonify({
        'connected': True,
        'expires_at': token.get('expires_at'),
        'expired': expired,
        'scopes': token.get('scopes', []),
    })


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

@bp.delete('/oauth/microsoft/disconnect')
def microsoft_disconnect() -> ResponseReturnValue:
    """Remove the stored Microsoft OAuth token for the current user."""
    user_id = get_current_user_id() or 'admin'
    deleted = current_app.db.delete_oauth_token(user_id, 'microsoft')
    return jsonify({'success': True, 'removed': deleted})


# ===========================================================================
# Google OAuth2
# ===========================================================================

@bp.get('/oauth/google/authorize')
def google_authorize() -> ResponseReturnValue:
    """
    Redirect the user to the Google OAuth2 consent screen.
    ---
    tags: [OAuth]
    responses:
      302: {description: Redirect to Google}
      501: {description: Google OAuth not configured}
    """
    if not config.GOOGLE_CLIENT_ID:
        return jsonify({'success': False, 'message': 'GOOGLE_CLIENT_ID is not configured'}), 501

    state = secrets.token_urlsafe(16)
    session['google_oauth_state'] = state

    params = {
        'client_id': config.GOOGLE_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': config.GOOGLE_REDIRECT_URI,
        'scope': _GOOGLE_SCOPES,
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state,
    }
    return redirect(_GOOGLE_AUTH_URL + '?' + urlencode(params))


@bp.get('/oauth/google/callback')
def google_callback() -> ResponseReturnValue:
    """
    Handle Google callback, exchange code for tokens, store encrypted.
    ---
    tags: [OAuth]
    responses:
      200: {description: Connected successfully}
      400: {description: State mismatch or missing code}
      500: {description: Token exchange failed}
    """
    error = request.args.get('error')
    if error:
        desc = request.args.get('error_description', error)
        logger.warning("[OAuth] Google returned an error during authorization")
        return jsonify({'success': False, 'message': desc}), 400

    code = request.args.get('code')
    state = request.args.get('state')
    if not code:
        return jsonify({'success': False, 'message': 'Missing authorization code'}), 400

    stored_state = session.pop('google_oauth_state', None)
    if stored_state and state != stored_state:
        return jsonify({'success': False, 'message': 'State mismatch — possible CSRF'}), 400

    try:
        resp = requests.post(
            _GOOGLE_TOKEN_URL,
            data={
                'grant_type': 'authorization_code',
                'client_id': config.GOOGLE_CLIENT_ID,
                'client_secret': config.GOOGLE_CLIENT_SECRET,
                'code': code,
                'redirect_uri': config.GOOGLE_REDIRECT_URI,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.HTTPError as exc:
        logger.error(f"[OAuth] Google token exchange failed: {exc}")
        return jsonify({'success': False, 'message': 'Token exchange failed'}), 500

    data = resp.json()
    access_token = data.get('access_token')
    if not access_token:
        return jsonify({'success': False, 'message': 'No access_token in response'}), 500

    expires_in = int(data.get('expires_in', 3600))
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    user_id = get_current_user_id() or 'admin'

    current_app.db.upsert_oauth_token(
        user_id=user_id,
        provider='google',
        access_token=access_token,
        refresh_token=data.get('refresh_token'),
        expires_at=expires_at,
        scopes=data.get('scope', '').split(),
    )
    logger.info(f"[OAuth] Google token stored for user {user_id}")
    return jsonify({'success': True, 'message': 'Google account connected', 'expires_at': expires_at.isoformat()})


@bp.get('/oauth/google/status')
def google_status() -> ResponseReturnValue:
    """Return whether the current user has a stored Google token."""
    user_id = get_current_user_id() or 'admin'
    token = current_app.db.get_oauth_token(user_id, 'google')
    if not token:
        return jsonify({'connected': False})
    expired = current_app.db.is_token_expired(user_id, 'google')
    return jsonify({
        'connected': True,
        'expires_at': token.get('expires_at'),
        'expired': expired,
        'scopes': token.get('scopes', []),
    })


@bp.delete('/oauth/google/disconnect')
def google_disconnect() -> ResponseReturnValue:
    """Remove the stored Google OAuth token for the current user."""
    user_id = get_current_user_id() or 'admin'
    deleted = current_app.db.delete_oauth_token(user_id, 'google')
    return jsonify({'success': True, 'removed': deleted})
