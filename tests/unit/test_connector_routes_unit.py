"""Unit tests for connector route exception handlers."""

from unittest.mock import MagicMock


class TestConnectorRoutesErrors:
    """Trigger the except-block paths that return 500 with _ERR_INTERNAL."""

    def test_list_connectors_db_error_returns_500(self, client, app):
        app.db.list_connectors = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors')
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_get_connector_db_error_returns_500(self, client, app):
        app.db.get_connector = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors/some-id')
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_update_connector_db_error_returns_500(self, client, app):
        app.db.update_connector = MagicMock(side_effect=Exception("db gone"))
        import json
        resp = client.put(
            '/api/connectors/some-id',
            data=json.dumps({'display_name': 'new name'}),
            content_type='application/json',
        )
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_delete_connector_db_error_returns_500(self, client, app):
        app.db.delete_connector = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete('/api/connectors/some-id')
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_sync_history_db_error_returns_500(self, client, app):
        app.db.get_connector_sync_history = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors/some-id/history')
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_create_connector_db_error_returns_500(self, client, app):
        """DB error after config validation should return 500."""
        import json
        from unittest.mock import patch

        app.db.create_connector = MagicMock(side_effect=Exception("db gone"))
        with patch('src.routes.connector_routes.connector_registry') as reg:
            mock_cls = MagicMock()
            mock_instance = MagicMock()
            mock_instance.validate_config.return_value = []
            mock_instance.display_name = 'Test'
            mock_cls.return_value = mock_instance
            reg.available_types.return_value = ['webhook']
            reg.get_class.return_value = mock_cls

            resp = client.post(
                '/api/connectors',
                data=json.dumps({'connector_type': 'webhook', 'config': {}}),
                content_type='application/json',
            )
        assert resp.status_code == 500
        assert resp.get_json()['message'] == 'Internal server error'

    def test_create_connector_instantiation_error_returns_400(self, client, app):
        """Constructor raising should return 400 via logger.warning path."""
        import json
        from unittest.mock import patch

        with patch('src.routes.connector_routes.connector_registry') as reg:
            mock_cls = MagicMock(side_effect=ValueError("bad config"))
            reg.available_types.return_value = ['webhook']
            reg.get_class.return_value = mock_cls

            resp = client.post(
                '/api/connectors',
                data=json.dumps({'connector_type': 'webhook', 'config': {}}),
                content_type='application/json',
            )
        assert resp.status_code == 400
        assert resp.get_json()['message'] == 'Invalid connector configuration'
