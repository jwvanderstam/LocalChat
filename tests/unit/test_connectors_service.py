"""ConnectorsService and OAuthAccountsService — CONN-1's rules where they now live.

QP-4, aggregate 6. The route tests (``test_connector_routes_unit.py``,
``test_local_folder_least_privilege.py``) prove the rules over HTTP; these prove the
order the service applies them in, that the admin check runs only for an admin-only type,
and that the registry follows the database.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.services.connectors import ConnectorsService, OAuthAccountsService
from src.services.errors import ServiceError

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
SCOPE = "11111111-1111-1111-1111-111111111111"


def _service(valid: bool = True) -> tuple[ConnectorsService, MagicMock, MagicMock]:
    db = MagicMock()
    registry = MagicMock()
    registry.available_types.return_value = ["google_drive", "local_folder"]
    instance = MagicMock()
    instance.validate_config.return_value = [] if valid else ["folder_id is required"]
    instance.display_name = "Drive: f1"
    registry.get_class.return_value = MagicMock(return_value=instance)
    return ConnectorsService(db, registry), db, registry


def _create(service: ConnectorsService, connector_type: str = "google_drive", **overrides):
    args = {"display_name": "", "config": {"folder_id": "f1"}, "sync_interval": 900,
            "workspace_id": SCOPE, "require_admin": MagicMock(), "creator": MagicMock(return_value=USER)}
    args.update(overrides)
    return service.create(
        connector_type, args["display_name"], args["config"], args["sync_interval"], args["workspace_id"],
        require_admin=args["require_admin"], creator=args["creator"],
    ), args


class TestCreate:
    def test_binds_the_creator_and_registers_the_connector_as_theirs(self):
        service, db, registry = _service()
        db.connectors.create.return_value = "new-id"
        db.connectors.get.return_value = {"id": "new-id"}
        connector, args = _create(service)
        assert connector == {"id": "new-id"}
        assert db.connectors.create.call_args.kwargs["created_by"] == USER
        assert registry.add.call_args.kwargs["owner_user_id"] == USER
        args["require_admin"].assert_not_called()

    def test_an_empty_display_name_takes_the_connectors_own(self):
        service, db, _ = _service()
        _create(service)
        assert db.connectors.create.call_args.kwargs["display_name"] == "Drive: f1"

    def test_user_id_in_config_is_refused_before_the_admin_check_or_any_write(self):
        service, db, _ = _service()
        with pytest.raises(ServiceError) as refused:
            _create(service, "local_folder", config={"user_id": "someone-else"})
        assert refused.value.status_code == 400
        db.connectors.create.assert_not_called()

    def test_an_admin_only_type_asks_the_admin_check_and_stops_on_its_refusal(self):
        service, db, _ = _service()
        refuse = MagicMock(side_effect=ServiceError(403, "Admin access required"))
        creator = MagicMock(return_value=USER)
        with pytest.raises(ServiceError) as refused:
            _create(service, "local_folder", require_admin=refuse, creator=creator)
        assert refused.value.status_code == 403
        creator.assert_not_called()
        db.connectors.create.assert_not_called()

    def test_an_invalid_config_writes_nothing(self):
        service, db, registry = _service(valid=False)
        with pytest.raises(ServiceError) as refused:
            _create(service)
        assert (refused.value.status_code, refused.value.message) == (400, "folder_id is required")
        db.connectors.create.assert_not_called()
        registry.add.assert_not_called()

    def test_an_unknown_type_is_refused(self):
        service, db, _ = _service()
        with pytest.raises(ServiceError) as refused:
            _create(service, "ftp")
        assert refused.value.status_code == 400
        db.connectors.create.assert_not_called()

    def test_an_unknown_type_names_the_available_ones(self):
        service, _, _ = _service()
        with pytest.raises(ServiceError) as refused:
            _create(service, "ftp")
        assert refused.value.message == "Unknown connector_type. Available: ['google_drive', 'local_folder']"

    def test_a_missing_type_is_a_400_saying_so(self):
        service, _, _ = _service()
        with pytest.raises(ServiceError) as refused:
            _create(service, "")
        assert (refused.value.status_code, refused.value.message) == (400, "connector_type is required")

    def test_a_type_with_no_class_is_refused_as_unknown(self):
        service, db, registry = _service()
        registry.get_class.return_value = None
        with pytest.raises(ServiceError) as refused:
            _create(service)
        assert (refused.value.status_code, refused.value.message) == (
            400, "Unknown connector_type. Available: ['google_drive', 'local_folder']",
        )
        db.connectors.create.assert_not_called()

    def test_every_config_error_is_reported(self):
        service, _, registry = _service()
        registry.get_class.return_value.return_value.validate_config.return_value = ["a is required", "b is bad"]
        with pytest.raises(ServiceError) as refused:
            _create(service)
        assert refused.value.message == "a is required; b is bad"


class TestUpdate:
    def test_a_config_change_on_an_admin_only_type_asks_the_admin_check(self):
        service, db, _ = _service()
        db.connectors.get.return_value = {"connector_type": "local_folder", "enabled": True, "config": {}}
        refuse = MagicMock(side_effect=ServiceError(403, "Admin access required"))
        with pytest.raises(ServiceError):
            service.update("c1", {"config": {"path": "/etc"}}, SCOPE, require_admin=refuse)
        db.connectors.update.assert_not_called()

    def test_no_such_connector_in_scope_is_none(self):
        service, db, _ = _service()
        db.connectors.get.return_value = None
        assert service.update("c1", {"config": {}}, SCOPE, require_admin=MagicMock()) is None

    def test_disabling_removes_it_from_the_registry(self):
        service, db, registry = _service()
        db.connectors.update.return_value = True
        db.connectors.get.return_value = {"connector_type": "google_drive", "enabled": False}
        service.update("c1", {"enabled": False}, SCOPE, require_admin=MagicMock())
        registry.remove.assert_called_once_with("c1")
        registry.add.assert_not_called()

    def test_a_config_change_is_validated_and_re_registered_with_the_rows_owner(self):
        service, db, registry = _service()
        db.connectors.update.return_value = True
        db.connectors.get.return_value = {"connector_type": "google_drive", "enabled": True,
                                          "config": {"folder_id": "f2"}, "workspace_id": SCOPE,
                                          "created_by": USER}
        service.update("c1", {"config": {"folder_id": "f2"}}, SCOPE, require_admin=MagicMock())
        registry.get_class.return_value.assert_called_once_with({"folder_id": "f2"})
        registry.add.assert_called_once_with("c1", "google_drive", {"folder_id": "f2"},
                                             workspace_id=SCOPE, owner_user_id=USER)


class TestRetire:
    def test_a_retired_connector_leaves_the_registry_and_records_the_caller(self):
        service, db, registry = _service()
        db.connectors.retire.return_value = True
        assert service.retire("c1", USER, SCOPE) is True
        db.connectors.retire.assert_called_once_with("c1", deleted_by=USER, scope=SCOPE)
        registry.remove.assert_called_once_with("c1")

    def test_a_connector_not_found_stays_registered(self):
        service, db, registry = _service()
        db.connectors.retire.return_value = False
        assert service.retire("c1", USER, SCOPE) is False
        registry.remove.assert_not_called()

    @pytest.mark.parametrize("caller", [None, "", "anonymous"])
    def test_no_caller_records_nobody(self, caller):
        service, db, _ = _service()
        service.retire("c1", caller, SCOPE)
        assert db.connectors.retire.call_args.kwargs["deleted_by"] is None


class TestAvailable:
    def test_lists_exactly_the_providers_the_user_has_authorised(self):
        service, db, _ = _service()
        db.is_connected = True
        tokens = {(USER, "google_drive"): {"t": 1}, (USER, "onedrive"): {"t": 2}}
        db.oauth_tokens.get.side_effect = lambda user, provider: tokens.get((user, provider))
        assert service.available(USER) == [
            {"type": "google_drive", "authorized": True},
            {"type": "onedrive", "authorized": True},
        ]
        assert [c.args for c in db.oauth_tokens.get.call_args_list] == [
            (USER, "google_drive"), (USER, "microsoft"), (USER, "onedrive"),
        ]

    @pytest.mark.parametrize(("user", "connected"), [(USER, False), (None, True)])
    def test_nothing_is_probed_without_a_user_or_a_database(self, user, connected):
        service, db, _ = _service()
        db.is_connected = connected
        assert service.available(user) == []
        db.oauth_tokens.get.assert_not_called()

    def test_types_are_the_registrys(self):
        service, _, _ = _service()
        assert service.types() == ["google_drive", "local_folder"]


class TestOAuthAccounts:
    def test_no_token_is_not_connected(self):
        db = MagicMock()
        db.oauth_tokens.get.return_value = None
        assert OAuthAccountsService(db).status(USER, "google") == {"connected": False}
        db.oauth_tokens.is_expired.assert_not_called()

    def test_a_token_reports_its_expiry_and_scopes(self):
        db = MagicMock()
        db.oauth_tokens.get.return_value = {"expires_at": "2099-01-01", "scopes": ["files.read"]}
        db.oauth_tokens.is_expired.return_value = False
        assert OAuthAccountsService(db).status(USER, "microsoft") == {
            "connected": True, "expires_at": "2099-01-01", "expired": False, "scopes": ["files.read"],
        }
