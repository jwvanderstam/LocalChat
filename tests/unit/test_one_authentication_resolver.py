"""P0-4 — every guard decides from the same resolver, and from the database.

Three findings, one cause: three guards each answered "who is this?" their own way.

* **H1** — only ``require_auth`` checked revocation. ``check_workspace_access`` (every
  document, chat, memory, feedback, annotation and connector route) and
  ``require_admin_dep`` (31 admin routes) did not, so a revoked token kept working on
  all of them until it expired.
* **H2** — ``check_workspace_access`` read ``role`` from the JWT. That claim is minted
  at login and lives as long as the token, so a demoted administrator kept the global
  short-circuit, and with it owner-equivalent access to every workspace.
* **M1** — the env-var admin was a permanent second credential that no administrator
  could see, demote or disable, and it kept working beside a changed database password.

``resolve_principal`` is now the single answer: decode, refuse if revoked, and read the
role from the database. The token supplies identity and nothing else.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.security_fastapi import (
    AuthError,
    check_workspace_access,
    create_access_token,
    env_admin_is_available,
    require_admin_dep,
    resolve_principal,
    verify_credentials_db,
)

USER = "33333333-3333-3333-3333-333333333333"
WS = "11111111-1111-1111-1111-111111111111"


def _db(*, revoked: bool = False, role: str = "user", live_admins: int = 1) -> MagicMock:
    db = MagicMock()
    db.is_connected = True
    db.is_token_revoked.return_value = revoked
    db.get_user_role.return_value = role
    db.get_workspace_member_role.return_value = "owner"
    db.get_user_workspaces.return_value = [{"id": WS}]
    db.get_default_workspace_id.return_value = WS
    db.resolve_workspace_api_key.return_value = None
    db.count_live_admins.return_value = live_admins
    return db


def _request(db: MagicMock, *, sub: str = USER, claim_role: str = "user") -> MagicMock:
    token = create_access_token(sub, {"role": claim_role})
    req = MagicMock()
    req.headers.get = lambda k, default="": (
        f"Bearer {token}" if k == "Authorization" else default
    )
    req.headers = {"Authorization": f"Bearer {token}"}
    req.cookies = {}
    req.query_params = {}
    req.app.state.db = db
    req.state = MagicMock()
    return req


@pytest.mark.unit
class TestRevocationIsCheckedOnEveryPath:
    """H1 — the check lived in one guard of three."""

    def test_the_resolver_refuses_a_revoked_token(self):
        with pytest.raises(AuthError) as exc_info:
            resolve_principal(_request(_db(revoked=True)))
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.message

    def test_the_workspace_guard_refuses_a_revoked_token(self):
        """Every document, chat, memory, annotation and connector route sits behind this."""
        denial = check_workspace_access(_request(_db(revoked=True)), WS, "viewer")
        assert denial is not None
        assert denial[0] == 401

    def test_the_admin_guard_refuses_a_revoked_token(self):
        """31 admin routes sit behind this one."""
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(_request(_db(revoked=True, role="admin")), credentials=None)
        assert exc_info.value.status_code == 401

    def test_a_live_token_still_passes_each_of_them(self):
        """The negative space: refusing everything would satisfy the three above."""
        assert resolve_principal(_request(_db())).user_id == USER
        assert check_workspace_access(_request(_db()), WS, "viewer") is None
        assert (
            require_admin_dep(_request(_db(role="admin")), credentials=None) == USER
        )


@pytest.mark.unit
class TestTheRoleComesFromTheDatabaseNotTheToken:
    """H2 — a claim minted at login outlives the decision it records."""

    def test_a_demoted_admin_is_no_longer_an_admin(self):
        """Token says admin, database says user."""
        principal = resolve_principal(_request(_db(role="user"), claim_role="admin"))
        assert principal.global_role == "user"
        assert not principal.is_admin

    def test_a_promoted_user_is_an_admin_without_signing_in_again(self):
        """The same property in the direction that helps, and it must also hold."""
        principal = resolve_principal(_request(_db(role="admin"), claim_role="user"))
        assert principal.is_admin

    def test_a_retired_user_loses_the_role_entirely(self):
        """get_user_role filters deleted_at, so a retired admin resolves to None."""
        principal = resolve_principal(_request(_db(role=None), claim_role="admin"))
        assert principal.global_role is None
        assert not principal.is_admin


@pytest.mark.unit
class TestTheEnvVarAdminIsABootstrapCredential:
    """M1 with decision D6 — it creates the first administrator, then stops."""

    def test_available_while_no_administrator_exists(self):
        assert env_admin_is_available(_db(live_admins=0)) is True

    def test_withdrawn_once_one_exists(self):
        assert env_admin_is_available(_db(live_admins=1)) is False

    def test_an_unreadable_database_leaves_the_recovery_path_alone(self):
        """Unknown is not "withdrawn": D6 asked for a credential a real administrator
        supersedes, not for the way back in to be removed. Recorded in SECURITY.md."""
        assert env_admin_is_available(None) is True
        disconnected = _db()
        disconnected.is_connected = False
        assert env_admin_is_available(disconnected) is True

    def test_a_failing_count_leaves_it_alone_too(self):
        db = _db()
        db.count_live_admins.side_effect = RuntimeError("boom")
        assert env_admin_is_available(db) is True

    def test_login_no_longer_falls_back_when_an_administrator_exists(self):
        """The heart of M1: it used to keep working beside a changed database password."""
        db = _db(live_admins=1)
        db.verify_user_password.return_value = None
        assert verify_credentials_db("admin", "the-env-password", db) is None

    def test_a_database_user_still_signs_in_normally(self):
        db = _db(live_admins=1)
        db.verify_user_password.return_value = {"id": "u1", "role": "admin"}
        assert verify_credentials_db("admin", "pw", db) == ("u1", "admin")


@pytest.mark.unit
class TestTheGuardsAgreeBecauseTheyShareTheResolver:
    def test_a_token_that_names_nobody_is_refused(self):
        req = _request(_db(), sub="")
        with pytest.raises(AuthError) as exc_info:
            resolve_principal(req)
        assert exc_info.value.status_code == 401

    def test_an_absent_token_is_a_401_not_a_crash(self):
        req = MagicMock()
        req.headers = {}
        req.cookies = {}
        req.app.state.db = _db()
        with pytest.raises(AuthError) as exc_info:
            resolve_principal(req)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestAppOnlyRoutesThroughOneResolver:
    """The property, so a fourth guard cannot quietly grow its own answer."""

    def test_no_guard_reads_the_role_claim_to_make_a_decision(self):
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2] / "src" / "security_fastapi.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Only the *claims* object. `db_user.get("role", ...)` reads a database row,
        # which is the thing this finding says to read instead.
        claim_names = {"claims", "payload"}
        offenders = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in claim_names
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "role"
            ):
                offenders.append(node.lineno)
        assert not offenders, (
            "security_fastapi.py reads the token's `role` claim at line(s) "
            f"{offenders}. The role is minted at login and outlives a demotion — "
            "read it from the database via resolve_principal (audit H2)."
        )
