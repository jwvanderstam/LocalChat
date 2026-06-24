"""Unit tests for auth route exception handlers."""

from unittest.mock import MagicMock


class TestAuthRoutesErrors:
    """Trigger the except-block paths that return 500 with _ERR_INTERNAL.

    Requires testing=True (require_admin bypass) from the conftest app fixture.
    """

    def test_create_user_db_error_returns_500(self, client, app):
        app.state.db.create_user = MagicMock(side_effect=Exception("db gone"))
        resp = client.post(
            '/api/users',
            json={'username': 'u', 'email': 'u@example.com', 'password': 'pw'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_create_user_duplicate_returns_409(self, client, app):
        app.state.db.create_user = MagicMock(side_effect=Exception("unique constraint violated"))
        resp = client.post(
            '/api/users',
            json={'username': 'u', 'email': 'u@example.com', 'password': 'pw'},
        )
        assert resp.status_code == 409

    def test_list_users_db_error_returns_500(self, client, app):
        app.state.db.list_users = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/users')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_get_user_db_error_returns_500(self, client, app):
        app.state.db.get_user_by_id = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/users/nonexistent-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_update_user_db_error_returns_500(self, client, app):
        app.state.db.update_user = MagicMock(side_effect=Exception("db gone"))
        resp = client.put(
            '/api/users/some-id',
            json={'email': 'new@example.com'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_delete_user_db_error_returns_500(self, client, app):
        app.state.db.delete_user = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete('/api/users/some-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

