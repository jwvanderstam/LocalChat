"""Unit tests for auth route exception handlers."""

from unittest.mock import MagicMock

from werkzeug.security import check_password_hash


class TestPasswordsAreTakenAsTyped:
    """Defect 2: creating a user stripped the password, while login, change and
    reset did not, so " correct horse " was stored as "correct horse" and the
    password its owner typed never worked."""

    def test_create_user_hashes_the_password_including_its_spaces(self, client, app, monkeypatch):
        create = MagicMock(return_value="u-1")
        monkeypatch.setattr(app.state.db.users, "create", create)
        monkeypatch.setattr(app.state.db.users, "get_by_id", MagicMock(return_value={"id": "u-1"}))
        resp = client.post("/api/users", json={"username": "u", "password": " correct horse "})
        assert resp.status_code == 201
        stored = create.call_args.kwargs["hashed_password"]
        assert (check_password_hash(stored, " correct horse "),
                check_password_hash(stored, "correct horse")) == (True, False)


class TestAuthRoutesErrors:
    """Trigger the except-block paths that return 500 with _ERR_INTERNAL.

    Requires testing=True (require_admin bypass) from the conftest app fixture.
    """

    def test_create_user_db_error_returns_500(self, client, app):
        app.state.db.users.create = MagicMock(side_effect=Exception("db gone"))
        resp = client.post(
            '/api/users',
            json={'username': 'u', 'email': 'u@example.com', 'password': 'a-long-enough-pw'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_create_user_duplicate_returns_409(self, client, app):
        app.state.db.users.create = MagicMock(side_effect=Exception("unique constraint violated"))
        resp = client.post(
            '/api/users',
            json={'username': 'u', 'email': 'u@example.com', 'password': 'a-long-enough-pw'},
        )
        assert resp.status_code == 409

    def test_list_users_db_error_returns_500(self, client, app):
        app.state.db.users.list_all = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/users')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_get_user_db_error_returns_500(self, client, app):
        app.state.db.users.get_by_id = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/users/nonexistent-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_update_user_db_error_returns_500(self, client, app):
        app.state.db.users.update = MagicMock(side_effect=Exception("db gone"))
        resp = client.put(
            '/api/users/some-id',
            json={'email': 'new@example.com'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_delete_user_db_error_returns_500(self, client, app):
        app.state.db.users.retire = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete('/api/users/some-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

