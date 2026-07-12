"""
Microsoft Graph API Token Refresh Tests
=========================================

Tests for src/connectors/microsoft_auth.py — get_valid_access_token(),
covering the expired/not-expired/refresh-fails branches.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from src.connectors.microsoft_auth import get_valid_access_token

pytestmark = pytest.mark.unit


def _future_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _past_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


class TestGetValidAccessToken:
    def test_raises_when_no_token_stored(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value=None)

        with pytest.raises(RuntimeError, match="No Microsoft OAuth token"):
            get_valid_access_token("user-1", db)

    def test_returns_existing_token_when_not_expired(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'valid-token',
            'refresh_token': 'refresh-1',
            'expires_at': _future_iso(3600),
        })

        result = get_valid_access_token("user-1", db)

        assert result == 'valid-token'
        db.upsert_oauth_token.assert_not_called()

    def test_treats_token_within_60s_buffer_as_expired(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'about-to-expire',
            'refresh_token': 'refresh-1',
            'expires_at': _future_iso(30),
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=True)
            mock_resp.json.return_value = {
                'access_token': 'refreshed-token',
                'expires_in': 3600,
                'scope': 'a b',
            }
            mock_post.return_value = mock_resp

            result = get_valid_access_token("user-1", db)

        assert result == 'refreshed-token'
        mock_post.assert_called_once()

    def test_treats_naive_expires_at_as_utc(self):
        db = Mock()
        naive_future = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None).isoformat()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'valid-token',
            'refresh_token': 'refresh-1',
            'expires_at': naive_future,
        })

        result = get_valid_access_token("user-1", db)

        assert result == 'valid-token'

    def test_treats_unparseable_expires_at_as_needing_refresh(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'stale-token',
            'refresh_token': 'refresh-1',
            'expires_at': 'not-a-date',
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=True)
            mock_resp.json.return_value = {'access_token': 'refreshed', 'expires_in': 3600}
            mock_post.return_value = mock_resp

            result = get_valid_access_token("user-1", db)

        assert result == 'refreshed'

    def test_refreshes_when_expires_at_missing(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'old-token',
            'refresh_token': 'refresh-1',
            'expires_at': None,
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=True)
            mock_resp.json.return_value = {'access_token': 'refreshed', 'expires_in': 3600}
            mock_post.return_value = mock_resp

            result = get_valid_access_token("user-1", db)

        assert result == 'refreshed'

    def test_raises_when_expired_and_no_refresh_token(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': None,
            'expires_at': _past_iso(60),
        })

        with pytest.raises(RuntimeError, match="no refresh_token available"):
            get_valid_access_token("user-1", db)

    def test_raises_when_refresh_request_fails(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': 'refresh-1',
            'expires_at': _past_iso(60),
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=False, status_code=400, text='invalid_grant')
            mock_post.return_value = mock_resp

            with pytest.raises(RuntimeError, match="Microsoft token refresh failed"):
                get_valid_access_token("user-1", db)

    def test_persists_refreshed_token_and_rotates_refresh_token(self):
        """Microsoft may rotate the refresh token — the new one must be persisted."""
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': 'original-refresh',
            'expires_at': _past_iso(60),
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=True)
            mock_resp.json.return_value = {
                'access_token': 'new-access-token',
                'refresh_token': 'rotated-refresh',
                'expires_in': 7200,
                'scope': 'scope1 scope2',
            }
            mock_post.return_value = mock_resp

            result = get_valid_access_token("user-1", db)

        assert result == 'new-access-token'
        db.upsert_oauth_token.assert_called_once()
        _, kwargs = db.upsert_oauth_token.call_args
        assert kwargs['user_id'] == 'user-1'
        assert kwargs['provider'] == 'microsoft'
        assert kwargs['access_token'] == 'new-access-token'
        assert kwargs['refresh_token'] == 'rotated-refresh'
        assert kwargs['scopes'] == ['scope1', 'scope2']

    def test_keeps_original_refresh_token_when_response_omits_it(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': 'original-refresh',
            'expires_at': _past_iso(60),
        })

        with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
            mock_resp = Mock(ok=True)
            mock_resp.json.return_value = {'access_token': 'new-token', 'expires_in': 3600}
            mock_post.return_value = mock_resp

            get_valid_access_token("user-1", db)

        _, kwargs = db.upsert_oauth_token.call_args
        assert kwargs['refresh_token'] == 'original-refresh'

    def test_refresh_request_uses_configured_tenant_and_credentials(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': 'refresh-1',
            'expires_at': _past_iso(60),
        })

        with patch("src.connectors.microsoft_auth.config") as mock_config:
            mock_config.MICROSOFT_TENANT_ID = 'tenant-abc'
            mock_config.MICROSOFT_CLIENT_ID = 'client-id-123'
            mock_config.MICROSOFT_CLIENT_SECRET = 'client-secret-456'
            with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
                mock_resp = Mock(ok=True)
                mock_resp.json.return_value = {'access_token': 'new-token', 'expires_in': 3600}
                mock_post.return_value = mock_resp

                get_valid_access_token("user-1", db)

            args, kwargs = mock_post.call_args
            assert args[0] == "https://login.microsoftonline.com/tenant-abc/oauth2/v2.0/token"
            assert kwargs['data']['client_id'] == 'client-id-123'
            assert kwargs['data']['client_secret'] == 'client-secret-456'
            assert kwargs['timeout'] == 15

    def test_defaults_tenant_to_common_when_not_configured(self):
        db = Mock()
        db.get_oauth_token = Mock(return_value={
            'access_token': 'expired-token',
            'refresh_token': 'refresh-1',
            'expires_at': _past_iso(60),
        })

        with patch("src.connectors.microsoft_auth.config") as mock_config:
            mock_config.MICROSOFT_TENANT_ID = None
            mock_config.MICROSOFT_CLIENT_ID = 'client-id'
            mock_config.MICROSOFT_CLIENT_SECRET = 'secret'
            with patch("src.connectors.microsoft_auth.requests.post") as mock_post:
                mock_resp = Mock(ok=True)
                mock_resp.json.return_value = {'access_token': 'new-token', 'expires_in': 3600}
                mock_post.return_value = mock_resp

                get_valid_access_token("user-1", db)

            args, _ = mock_post.call_args
            assert args[0] == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
