"""QP-2 S2 — the decisions around the application's own role, against a scripted cursor.

`tests/integration/test_app_role_is_not_owner.py` proves the result on a real Postgres.
This pins the parts a real database would not make visible: that the password never
travels as plain interpolated SQL, that a role carrying superuser-like attributes stops the
boot instead of being used, and that the switch happens only when it is configured.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from psycopg import sql

from src import config
from src.db.connection import APP_ROLE, SCOPED_ROLE, _apply_app_role

pytestmark = pytest.mark.unit

_PASSWORD = "a-secret-app-password"


def _cursor(attributes: tuple[bool, bool, bool, bool] = (False, False, False, False)) -> MagicMock:
    cursor = MagicMock()
    cursor.fetchone.return_value = attributes
    return cursor


def _statements(cursor: MagicMock) -> list[object]:
    return [c.args[0] for c in cursor.execute.call_args_list]


class TestApplyingTheAppRole:
    def test_the_password_never_appears_in_a_plain_string_statement(self):
        cursor = _cursor()
        _apply_app_role(cursor, _PASSWORD)
        plain = [s for s in _statements(cursor) if isinstance(s, str)]
        assert [s for s in plain if _PASSWORD in s] == []

    def test_the_password_is_set_through_a_composed_literal(self):
        cursor = _cursor()
        _apply_app_role(cursor, _PASSWORD)
        composed = [s for s in _statements(cursor) if isinstance(s, sql.Composed)]
        assert any(sql.Literal(_PASSWORD) in list(s) for s in composed)

    def test_the_app_role_may_switch_into_the_scoped_role(self):
        """Without SET TRUE every scoped query is refused on PostgreSQL 16."""
        cursor = _cursor()
        _apply_app_role(cursor, _PASSWORD)
        assert f"GRANT {SCOPED_ROLE} TO {APP_ROLE} WITH SET TRUE" in _statements(cursor)

    @pytest.mark.parametrize("attributes", [
        (True, False, False, False), (False, True, False, False),
        (False, False, True, False), (False, False, False, True),
    ], ids=["superuser", "bypassrls", "createrole", "createdb"])
    def test_a_role_with_owner_powers_stops_the_boot_before_any_grant(self, attributes):
        cursor = _cursor(attributes)
        with pytest.raises(RuntimeError):
            _apply_app_role(cursor, _PASSWORD)
        assert [s for s in _statements(cursor) if isinstance(s, str) and s.startswith("GRANT")] == []


class TestTheBootSwitch:
    def test_unset_it_keeps_the_single_identity_and_says_so(self, monkeypatch, caplog):
        from src import app_bootstrap

        monkeypatch.setattr(config, "PG_APP_PASSWORD", "")
        db = MagicMock()
        app_bootstrap._drop_to_app_identity(db)
        assert (db.method_calls, "PG_APP_PASSWORD is not set" in caplog.text) == ([], True)

    def test_set_it_creates_the_role_and_then_switches_to_it(self, monkeypatch):
        from src import app_bootstrap

        monkeypatch.setattr(config, "PG_APP_PASSWORD", _PASSWORD)
        db = MagicMock()
        app_bootstrap._drop_to_app_identity(db)
        assert db.method_calls == [call.ensure_app_role(), call.use_app_identity()]
