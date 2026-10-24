"""WorkspacesService — the decisions that depend on who is asking (QP-4, aggregate 2).

The route's ``deny()`` decides whether the caller may act at all; these are what the
service decides after that: which workspaces a caller is shown, who owns a workspace
they create, whose name a retirement or revocation records, and the last-owner refusal.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.workspaces import LastOwnerError
from src.services.errors import ServiceError
from src.services.workspaces import WorkspacesService

pytestmark = pytest.mark.unit

USER = "33333333-3333-3333-3333-333333333333"
ALL = [{"id": "ws-a"}, {"id": "ws-b"}]
OWN = [{"id": "ws-a", "role": "editor"}]


def _service(role: str | None = "user") -> tuple[WorkspacesService, MagicMock]:
    db = MagicMock()
    db.workspaces.list_all.return_value = ALL
    db.members.for_user.return_value = OWN
    db.users.get_by_id.return_value = {"id": USER, "role": role} if role else None
    return WorkspacesService(db), db


class TestVisibleTo:
    def test_a_member_sees_only_their_own_workspaces(self):
        service, db = _service("user")
        assert service.visible_to(USER) == OWN
        db.members.for_user.assert_called_once_with(USER)

    def test_an_admin_sees_every_workspace(self):
        service, _ = _service("admin")
        assert service.visible_to(USER) == ALL

    def test_the_role_comes_from_the_database_not_the_token(self):
        """A demoted admin's record says user, so they are narrowed at once."""
        service, db = _service("user")
        service.visible_to(USER)
        db.workspaces.list_all.assert_not_called()

    def test_a_caller_with_no_live_record_sees_only_memberships(self):
        service, _ = _service(None)
        assert service.visible_to(USER) == OWN

    @pytest.mark.parametrize("caller", [None, "", "anonymous"])
    def test_no_caller_sees_every_workspace_rather_than_an_empty_switcher(self, caller):
        service, db = _service("user")
        assert service.visible_to(caller) == ALL
        db.users.get_by_id.assert_not_called()


class TestCallerIsRecorded:
    def test_the_creator_becomes_the_owner(self):
        service, db = _service()
        db.workspaces.create.return_value = "ws-new"
        db.workspaces.get.return_value = {"id": "ws-new"}
        assert service.create("Acme", "", "", None, creator=USER) == {"id": "ws-new"}
        assert db.workspaces.create.call_args.kwargs["owner_id"] == USER

    def test_anonymous_creates_an_unowned_workspace(self):
        service, db = _service()
        service.create("Acme", "", "", None, creator="anonymous")
        assert db.workspaces.create.call_args.kwargs["owner_id"] is None

    def test_retire_records_who_retired_it(self):
        service, db = _service()
        db.workspaces.retire.return_value = True
        assert service.retire("ws-a", actor=USER) is True
        db.workspaces.retire.assert_called_once_with("ws-a", deleted_by=USER)

    def test_revoke_key_records_who_revoked_it_and_names_the_workspace(self):
        service, db = _service()
        service.revoke_key("ws-a", "key-1", actor=USER)
        db.api_keys.revoke.assert_called_once_with(key_id="key-1", workspace_id="ws-a", revoked_by=USER)

    def test_create_key_records_the_creator(self):
        service, db = _service()
        db.api_keys.create.return_value = ("lcw_x", {"id": "key-1"})
        assert service.create_key("ws-a", "bot", "viewer", creator=USER) == ("lcw_x", {"id": "key-1"})
        assert db.api_keys.create.call_args.kwargs["created_by"] == USER


class TestUpdate:
    def test_returns_the_workspace_as_it_now_is(self):
        service, db = _service()
        db.workspaces.update.return_value = True
        db.workspaces.get.return_value = {"id": "ws-a", "name": "New"}
        assert service.update("ws-a", {"name": "New"}) == {"id": "ws-a", "name": "New"}
        db.workspaces.update.assert_called_once_with("ws-a", name="New")

    def test_no_such_workspace_is_none(self):
        service, db = _service()
        db.workspaces.update.return_value = False
        assert service.update("ws-a", {"name": "New"}) is None
        db.workspaces.get.assert_not_called()


class TestRemoveMember:
    def test_the_last_owner_is_a_409_with_a_constant_message(self):
        service, db = _service()
        db.members.remove.side_effect = LastOwnerError("internal detail")
        with pytest.raises(ServiceError) as refused:
            service.remove_member("ws-a", USER)
        assert (refused.value.status_code, refused.value.message) == (
            409,
            "Cannot remove the last owner of a workspace",
        )

    def test_any_other_error_is_not_turned_into_a_refusal(self):
        service, db = _service()
        db.members.remove.side_effect = ValueError("bad uuid")
        with pytest.raises(ValueError):
            service.remove_member("ws-a", USER)

    def test_a_removed_member_is_true(self):
        service, db = _service()
        db.members.remove.return_value = True
        assert service.remove_member("ws-a", USER) is True
