"""TQ-3 — the observable contract of the auth layer, written where mutants survived.

The mutation gate reported 77 survivors in ``security_fastapi.py``: changes to the
source that no test objected to. These tests are written against the specific
mutations, so each one names the change it refuses rather than exercising a line
and hoping.

Three groups, and the reason each is worth pinning:

* **What is extracted from a token.** Mutating ``payload.get("jti")`` to ``None``
  skips revocation entirely and every existing test still passed — the token was
  still valid, so the request still succeeded. Silence is the whole failure mode.
* **The response envelope.** Mutating the ``"message"`` key leaves a well-formed
  401 that no client can read. Status-code assertions cannot see it.
* **The database preconditions.** Fail-closed only fails closed if the condition
  is the one intended; ``and``/``or`` and a flipped default both survive a test
  that only ever supplies a healthy database.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.security_fastapi import (
    _ERR_AUTH_REQUIRED,
    _remember_not_revoked,
    _revocation_cache,
    create_access_token,
    require_admin_dep,
    require_auth,
)

pytestmark = pytest.mark.unit

_USER = "77777777-7777-7777-7777-777777777777"


_MISSING = object()


def _healthy_db(*, revoked: bool = False, role: str = "admin") -> MagicMock:
    db = MagicMock()
    db.is_connected = True
    db.is_token_revoked.return_value = revoked
    db.get_user_role.return_value = role
    return db


def _request(token: str | None = None, *, db: object = _MISSING) -> MagicMock:
    """A request carrying *token* as a bearer header, with *db* on app.state.

    The database defaults to a healthy one rather than to None: revocation fails
    closed (SEC-2), so a request with no database is refused before it reaches the
    behaviour most of these tests are about. Pass ``db=None`` to mean it.
    """
    req = MagicMock()
    header = f"Bearer {token}" if token else ""
    req.headers.get = lambda k, default="": (header if k == "Authorization" else default)
    req.cookies = {}
    req.app.state.db = _healthy_db() if db is _MISSING else db
    return req


class TestWhatRequireAuthExtracts:
    """Mutants 95, 96, 98: the claim names the token is read with."""

    def test_the_subject_is_returned_not_some_other_claim(self):
        """`return payload["sub"]` mutated to another key raises KeyError; mutated
        to a literal returns the wrong user. Both look like success from outside."""
        token = create_access_token(_USER, {"role": "user"})
        assert require_auth(_request(token), credentials=None) == _USER

    def test_a_revoked_token_is_refused(self):
        """The jti is what revocation is keyed on. Read it from the wrong claim and
        it comes back None, the check is skipped, and a revoked token is accepted --
        with no error anywhere, because the token itself is still valid."""
        token = create_access_token(_USER, {"role": "user"})
        db = _healthy_db(revoked=True)

        request = _request(token, db=db)
        with pytest.raises(HTTPException) as exc_info:
            require_auth(request, credentials=None)
        assert exc_info.value.status_code == 401

    def test_the_revocation_check_is_actually_reached(self):
        """Complements the case above: proves the jti arrived, rather than the
        request having been refused for some unrelated reason."""
        token = create_access_token(_USER, {"role": "user"})
        db = _healthy_db(revoked=False)

        require_auth(_request(token, db=db), credentials=None)
        assert db.is_token_revoked.called, "revocation was never consulted"

    def test_the_jti_from_the_token_is_the_one_checked(self):
        """Pins the value, not just the call: a mutant that passes a constant, or
        the wrong claim, still 'consults' revocation."""
        from src.security_fastapi import _decode_token

        token = create_access_token(_USER, {"role": "user"})
        expected_jti = _decode_token(token)["jti"]
        db = _healthy_db(revoked=False)

        require_auth(_request(token, db=db), credentials=None)
        assert db.is_token_revoked.call_args[0][0] == expected_jti


class TestCredentialsObjectIsPreferred:
    """Mutants 54, 87: the attribute the bearer token is read off `credentials`."""

    def test_a_credentials_object_authenticates_without_a_header(self):
        """Read the wrong attribute and this falls through to the header, which is
        absent here -- so the caller is refused despite presenting a valid token."""
        token = create_access_token(_USER, {"role": "user"})
        credentials = MagicMock()
        credentials.credentials = token

        assert require_auth(_request(), credentials=credentials) == _USER

    def test_an_unresolved_depends_sentinel_falls_back_to_the_header(self):
        """require_auth is called directly as well as via Depends. The sentinel is
        truthy but has no .credentials, which is why this uses getattr rather than
        truthiness -- `if not credentials` once rejected every valid caller."""
        token = create_access_token(_USER, {"role": "user"})
        sentinel = object()  # truthy, no .credentials

        assert require_auth(_request(token), credentials=sentinel) == _USER


class TestErrorEnvelope:
    """Mutants 91, 93, 94, 129, 130, 133, 134: the shape clients actually read.

    A mutated key leaves a perfectly well-formed 401 that no client can parse.
    Asserting the status code alone cannot see the difference.
    """

    def test_a_missing_token_reports_under_the_message_key(self):
        request = _request()
        with pytest.raises(HTTPException) as exc_info:
            require_auth(request, credentials=None)
        assert exc_info.value.detail["message"] == _ERR_AUTH_REQUIRED

    def test_a_malformed_token_says_so(self):
        request = _request("not-a-jwt")
        with pytest.raises(HTTPException) as exc_info:
            require_auth(request, credentials=None)
        assert exc_info.value.detail["message"] == "Invalid or expired token"

    def test_a_non_admin_is_told_admin_access_is_required(self):
        token = create_access_token(_USER, {"role": "admin"})
        db = _healthy_db(role="user")

        request = _request(token, db=db)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.detail["message"] == "Admin access required"

    def test_an_unverifiable_role_names_the_database(self):
        """503 and 403 mean different things to an operator; so do their messages."""
        token = create_access_token(_USER, {"role": "admin"})
        db = _healthy_db()
        db.is_connected = False

        request = _request(token, db=db)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["message"] == (
            "Cannot verify administrator role: database unavailable"
        )


class TestDatabasePreconditions:
    """Mutants 110, 111, 112, 126, 152: the conditions that make failure closed.

    Each of these survives a suite that only ever supplies a healthy database.
    """

    def _admin_token(self) -> str:
        return create_access_token(_USER, {"role": "admin"})

    def test_no_database_at_all_is_refused(self):
        """`db is None or ...` mutated to `and` reaches getattr(None, ...) and the
        guard stops refusing."""
        request = _request(self._admin_token(), db=None)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 503

    def test_a_disconnected_database_is_refused(self):
        """The default in getattr(db, "is_connected", False) flipped to True makes a
        database that never reports its state look healthy."""
        db = _healthy_db()
        db.is_connected = False

        request = _request(self._admin_token(), db=db)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 503

    def test_a_database_missing_the_attribute_entirely_is_refused(self):
        """Precisely what the getattr default is for -- an object that is not the
        database this code expects must not be read as a connected one."""
        db = MagicMock(spec=[])  # no is_connected, no methods

        request = _request(self._admin_token(), db=db)
        with pytest.raises(HTTPException) as exc_info:
            require_admin_dep(request, credentials=None)
        assert exc_info.value.status_code == 503

    def test_a_healthy_database_still_lets_an_admin_through(self):
        """Guard against over-correction: the refusals above must not be the only
        outcome the guard can produce."""
        db = _healthy_db(role="admin")
        assert require_admin_dep(self._request_admin(db), credentials=None) == _USER

    def _request_admin(self, db):
        return _request(self._admin_token(), db=db)


class TestRevocationCacheEviction:
    """Mutants 67, 69: the arithmetic and the boundary of stale-first eviction.

    `monotonic() - TTL` mutated to `+` puts the cutoff in the future, so every entry
    counts as stale and the cache is emptied on every overflow -- the bound still
    holds, which is why nothing objected.
    """

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        _revocation_cache.clear()
        yield
        _revocation_cache.clear()

    def test_overflow_drops_stale_entries_and_keeps_fresh_ones(self):
        from src.security_fastapi import _REVOCATION_CACHE_MAX, _REVOCATION_CACHE_TTL

        now = time.monotonic()
        # One clearly stale entry, and a cache filled to the eviction trigger.
        _revocation_cache["stale"] = now - (_REVOCATION_CACHE_TTL * 2)
        for i in range(_REVOCATION_CACHE_MAX - 1):
            _revocation_cache[f"fresh-{i}"] = now

        _remember_not_revoked("new-one")

        assert "stale" not in _revocation_cache, "a stale entry was not evicted"
        assert "new-one" in _revocation_cache
        assert "fresh-0" in _revocation_cache, (
            "a fresh entry was evicted — the cutoff is on the wrong side of now"
        )

    def test_the_cache_stays_bounded(self):
        from src.security_fastapi import _REVOCATION_CACHE_MAX

        for i in range(_REVOCATION_CACHE_MAX + 50):
            _remember_not_revoked(f"jti-{i}")
        assert len(_revocation_cache) <= _REVOCATION_CACHE_MAX


class TestCurrentGlobalRoleGuards:
    """Mutants 110, 111, 112 — reachable only by calling this directly.

    require_admin_dep refuses with 503 before this function runs, so a test that
    goes through the dependency never exercises its own precondition. The mutants
    live here regardless, and this is where they become visible: each of the cases
    below returns a role instead of None once the condition is flipped.
    """

    def _request_with(self, db) -> MagicMock:
        req = MagicMock()
        req.app.state.db = db
        return req

    def _claims(self) -> dict:
        return {"sub": _USER, "role": "admin"}

    def test_no_database_yields_no_role(self):
        from src.security_fastapi import _current_global_role

        assert _current_global_role(self._request_with(None), self._claims()) is None

    def test_a_disconnected_database_yields_no_role_even_though_it_would_answer(self):
        """`db is None or not connected` mutated to `and` falls through to the query.

        The database here *would* return "admin" -- the point is that a connection
        it does not vouch for must not be trusted to answer, so the role must come
        back None rather than from a database reporting itself down.
        """
        from src.security_fastapi import _current_global_role

        db = MagicMock()
        db.is_connected = False
        db.get_user_role.return_value = "admin"

        assert _current_global_role(self._request_with(db), self._claims()) is None
        assert not db.get_user_role.called, "a disconnected database was queried"

    def test_an_object_without_is_connected_yields_no_role(self):
        """The getattr default: flipped to True, anything with a get_user_role
        becomes an authority on who is an administrator."""
        from src.security_fastapi import _current_global_role

        db = MagicMock(spec=["get_user_role"])
        db.get_user_role.return_value = "admin"

        assert _current_global_role(self._request_with(db), self._claims()) is None

    def test_a_connected_database_answers(self):
        """Guard against over-correction: the refusals above must not be the only
        outcome this function can produce."""
        from src.security_fastapi import _current_global_role

        db = MagicMock()
        db.is_connected = True
        db.get_user_role.return_value = "admin"

        assert _current_global_role(self._request_with(db), self._claims()) == "admin"

    def test_the_env_var_admin_needs_no_database(self):
        """That account has no row; it is the way back in when the database is empty."""
        from src.security_fastapi import _current_global_role

        role = _current_global_role(self._request_with(None), {"sub": "admin"})
        assert role == "admin"


class TestGetCurrentUserIdReadsCredentials:
    """Mutant 54 — the same getattr, in the other function.

    `require_auth` and `get_current_user_id` each read the bearer token off the
    credentials object, and a test of one says nothing about the other.
    """

    def test_a_credentials_object_identifies_the_caller_without_a_header(self):
        from src.security_fastapi import get_current_user_id

        token = create_access_token(_USER, {"role": "user"})
        credentials = MagicMock()
        credentials.credentials = token

        assert get_current_user_id(_request(), credentials=credentials) == _USER

    def test_no_token_anywhere_is_nobody_rather_than_an_error(self):
        """Unlike require_auth, this one answers None instead of refusing."""
        from src.security_fastapi import get_current_user_id

        assert get_current_user_id(_request(), credentials=None) is None


class TestEvictionBoundary:
    """Mutant 69 — `seen < cutoff` against `seen <= cutoff`.

    An entry aged exactly TTL is the only input the two disagree about, so the
    clock has to be controlled rather than approximated: a test using "clearly
    stale" and "clearly fresh" values passes under both.

    The fill matters as much as the clock. Filling with nothing evictable leaves
    the cache at its maximum, which trips the clear-everything fallback and wipes
    the boundary entry whichever comparison is in force. One genuinely stale entry
    is included so eviction drops the size below the trigger, and the boundary
    entry's fate is then decided by the comparison alone.
    """

    @pytest.fixture(autouse=True)
    def _clean_cache(self):
        _revocation_cache.clear()
        yield
        _revocation_cache.clear()

    def _fill(self, sec, now: float, *, extra: dict[str, float]) -> None:
        _revocation_cache.clear()
        _revocation_cache["definitely-stale"] = now - (sec._REVOCATION_CACHE_TTL * 10)
        _revocation_cache.update(extra)
        for i in range(sec._REVOCATION_CACHE_MAX - len(_revocation_cache)):
            _revocation_cache[f"fresh-{i}"] = now

    def test_an_entry_aged_exactly_the_ttl_is_kept(self, monkeypatch):
        import src.security_fastapi as sec

        now = 1_000_000.0
        monkeypatch.setattr(sec.time, "monotonic", lambda: now)
        # cutoff is now - TTL; this entry sits precisely on it.
        self._fill(sec, now, extra={"boundary": now - sec._REVOCATION_CACHE_TTL})

        sec._remember_not_revoked("trigger")

        assert "definitely-stale" not in _revocation_cache, "eviction did not run"
        assert "boundary" in _revocation_cache, (
            "an entry exactly at the cutoff was evicted — the comparison is inclusive"
        )

    def test_an_entry_one_tick_older_than_the_ttl_is_dropped(self, monkeypatch):
        """The other side of the same boundary, so the test above cannot pass by
        eviction simply never running."""
        import src.security_fastapi as sec

        now = 1_000_000.0
        monkeypatch.setattr(sec.time, "monotonic", lambda: now)
        self._fill(sec, now, extra={"just-stale": now - sec._REVOCATION_CACHE_TTL - 0.001})

        sec._remember_not_revoked("trigger")

        assert "just-stale" not in _revocation_cache
