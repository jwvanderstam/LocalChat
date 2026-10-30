"""Unit tests for connector route exception handlers."""

from unittest.mock import MagicMock


class TestConnectorRoutesErrors:
    """Trigger the except-block paths that return 500 with _ERR_INTERNAL."""

    def test_list_connectors_db_error_returns_500(self, client, app):
        app.state.db.connectors.list_all = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_get_connector_db_error_returns_500(self, client, app):
        app.state.db.connectors.get = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors/some-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_update_connector_db_error_returns_500(self, client, app):
        app.state.db.connectors.update = MagicMock(side_effect=Exception("db gone"))
        resp = client.put(
            '/api/connectors/some-id',
            json={'display_name': 'new name'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_delete_connector_db_error_returns_500(self, client, app):
        app.state.db.connectors.retire = MagicMock(side_effect=Exception("db gone"))
        resp = client.delete('/api/connectors/some-id')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_sync_history_db_error_returns_500(self, client, app):
        app.state.db.connectors.sync_history = MagicMock(side_effect=Exception("db gone"))
        resp = client.get('/api/connectors/some-id/history')
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_create_connector_db_error_returns_500(self, client, app):
        """DB error after config validation should return 500."""
        app.state.db.connectors.create = MagicMock(side_effect=Exception("db gone"))

        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.validate_config.return_value = []
        mock_instance.display_name = 'Test'
        mock_cls.return_value = mock_instance
        mock_reg = MagicMock()
        mock_reg.available_types.return_value = ['webhook']
        mock_reg.get_class.return_value = mock_cls
        app.state.connector_registry = mock_reg

        resp = client.post(
            '/api/connectors',
            json={'connector_type': 'webhook', 'config': {}},
            headers={'X-Workspace-ID': 'ws-1'},
        )
        assert resp.status_code == 500
        assert resp.json()['message'] == 'Internal server error'

    def test_create_connector_instantiation_error_returns_400(self, client, app):
        """Constructor raising should return 400 via logger.warning path."""
        mock_cls = MagicMock(side_effect=ValueError("bad config"))
        mock_reg = MagicMock()
        mock_reg.available_types.return_value = ['webhook']
        mock_reg.get_class.return_value = mock_cls
        app.state.connector_registry = mock_reg

        resp = client.post(
            '/api/connectors',
            json={'connector_type': 'webhook', 'config': {}},
        )
        assert resp.status_code == 400
        assert resp.json()['message'] == 'Invalid connector configuration'


class TestAConnectorOutsideTheScopeIsNotFound:
    """R-7 (QP-9 review) — history and manual sync resolve the connector in the scope.

    Both took the id alone: the sync log has no workspace and no row-level security, and
    the registry holds every workspace's connectors, so the owner of any workspace could
    read another's sync errors and spend its owner's OAuth token on a sync.
    """

    def test_history_of_a_foreign_connector_is_not_found(self, client, app):
        app.state.db.connectors.get = MagicMock(return_value=None)
        app.state.db.connectors.sync_history = MagicMock(return_value=[{"id": 1}])
        resp = client.get('/api/connectors/foreign/history', headers={'X-Workspace-ID': 'ws-a'})
        assert resp.status_code == 404
        app.state.db.connectors.sync_history.assert_not_called()

    def test_history_looks_the_connector_up_in_the_authorised_scope(self, client, app):
        app.state.db.connectors.get = MagicMock(return_value={'id': 'own'})
        app.state.db.connectors.sync_history = MagicMock(return_value=[{"id": 1}])
        resp = client.get('/api/connectors/own/history', headers={'X-Workspace-ID': 'ws-a'})
        assert resp.json()['history'] == [{"id": 1}]
        assert app.state.db.connectors.get.call_args.kwargs['scope'] == 'ws-a'

    def test_a_foreign_connector_is_not_synced(self, client, app):
        app.state.db.connectors.get = MagicMock(return_value=None)
        app.state.connector_registry = MagicMock()
        app.state.sync_worker = MagicMock()
        resp = client.post('/api/connectors/foreign/sync', headers={'X-Workspace-ID': 'ws-a'})
        assert resp.status_code == 404
        app.state.connector_registry.get.assert_not_called()

    def test_the_callers_own_connector_is_synced(self, client, app):
        app.state.db.connectors.get = MagicMock(return_value={'id': 'own'})
        app.state.connector_registry = MagicMock()
        app.state.sync_worker = MagicMock()
        resp = client.post('/api/connectors/own/sync', headers={'X-Workspace-ID': 'ws-a'})
        assert resp.status_code == 200
        assert app.state.db.connectors.get.call_args.kwargs['scope'] == 'ws-a'


class TestConnectorOwnerBinding:
    """BUG-4 — a connector spends its creator's OAuth token, nobody else's."""

    @staticmethod
    def _registry(app) -> MagicMock:
        instance = MagicMock()
        instance.validate_config.return_value = []
        instance.display_name = 'Test'
        cls = MagicMock(return_value=instance)
        registry = MagicMock()
        registry.available_types.return_value = ['google_drive']
        registry.get_class.return_value = cls
        app.state.connector_registry = registry
        return registry

    def test_create_rejects_a_client_supplied_owner(self, client, app):
        self._registry(app)
        app.state.db.connectors.create = MagicMock(return_value='new-id')

        resp = client.post(
            '/api/connectors',
            json={'connector_type': 'google_drive', 'config': {'user_id': 'someone-else'}},
        )

        assert resp.status_code == 400
        assert 'user_id' in resp.json()['message']
        app.state.db.connectors.create.assert_not_called()

    def test_an_admin_naming_no_workspace_is_refused_and_nothing_is_created(self, client, app):
        """A global admin passes the guard without naming a workspace, so the connector
        had none: it was inserted and registered, then the read-back refused the missing
        scope and the caller got a 500 for a connector that now existed."""
        registry = self._registry(app)
        app.state.db.connectors.create = MagicMock(return_value='new-id')

        resp = client.post(
            '/api/connectors',
            json={'connector_type': 'google_drive', 'config': {'folder_id': 'f1'}},
        )

        assert (resp.status_code, resp.json()['message']) == (
            400, 'Select a workspace for the connector'
        )
        app.state.db.connectors.create.assert_not_called()
        registry.add.assert_not_called()

    def test_create_binds_the_caller_as_owner(self, client, app):
        registry = self._registry(app)
        app.state.db.connectors.create = MagicMock(return_value='new-id')
        app.state.db.connectors.get = MagicMock(return_value={'id': 'new-id'})

        resp = client.post(
            '/api/connectors',
            json={'connector_type': 'google_drive', 'config': {'folder_id': 'f1'}},
            headers={'X-Workspace-ID': 'ws-1'},
        )

        assert resp.status_code == 201
        created_by = app.state.db.connectors.create.call_args.kwargs['created_by']
        assert created_by
        assert registry.add.call_args.kwargs['owner_user_id'] == created_by

    def test_update_rejects_a_client_supplied_owner(self, client, app):
        app.state.db.connectors.update = MagicMock(return_value=True)

        resp = client.put(
            '/api/connectors/some-id',
            json={'config': {'user_id': 'someone-else'}},
        )

        assert resp.status_code == 400
        assert 'user_id' in resp.json()['message']
        app.state.db.connectors.update.assert_not_called()

    def test_reregistration_after_update_carries_the_stored_owner(self, client, app):
        registry = self._registry(app)
        app.state.db.connectors.update = MagicMock(return_value=True)
        app.state.db.connectors.get = MagicMock(return_value={
            'id': 'some-id', 'connector_type': 'google_drive', 'config': {},
            'enabled': True, 'workspace_id': 'ws-1', 'created_by': 'creator',
        })

        resp = client.put('/api/connectors/some-id', json={'enabled': True})

        assert resp.status_code == 200
        assert registry.add.call_args.kwargs['owner_user_id'] == 'creator'
