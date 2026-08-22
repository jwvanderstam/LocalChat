"""SEC-2 — token revocation is enforced, not advisory.

`_verify_jti_not_revoked` used to swallow database errors and let the request
through. Revocation that stops applying the moment the database hiccups is not
revocation, and it bought nothing: every workspace-scoped route already answers 503
without a database, so the application is unusable in that state either way. What it
did buy was a window in which a token revoked minutes ago was accepted again.

Now it fails closed, softened by a 60-second cache of recent successful checks so a
blip degrades to slightly-stale-but-enforced rather than to open.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src import security_fastapi as sec

JTI = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _empty_cache():
    """Each test starts with no remembered verdicts — the cache is module state."""
    sec._revocation_cache.clear()
    yield
    sec._revocation_cache.clear()


def _db(*, connected: bool = True, revoked: bool = False, raises: bool = False):
    db = MagicMock()
    db.is_connected = connected
    if raises:
        db.is_token_revoked.side_effect = RuntimeError("connection lost")
    else:
        db.is_token_revoked.return_value = revoked
    return db


@pytest.mark.unit
class TestNormalOperation:
    def test_live_token_passes(self):
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))

    def test_revoked_token_is_refused(self):
        db = _db(revoked=True)
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, db)
        assert exc.value.status_code == 401

    def test_the_refusal_uses_the_error_envelope_the_frontend_reads(self):
        """TQ-3. Renaming the `message` key left every test green, because they all
        assert on `status_code`. `static/js/auth.js` and every caller read
        `data.message`, so the key is part of the contract."""
        db = _db(revoked=True)
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, db)

        assert exc.value.detail == {"message": "Token has been revoked"}

    def test_a_revoked_token_is_never_cached_as_usable(self):
        """A refusal must not leave a verdict that would let it through later."""
        db = _db(revoked=True)
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, db)
        assert JTI not in sec._revocation_cache


@pytest.mark.unit
class TestFailsClosed:
    """The behaviour change. Previously each of these allowed the request."""

    def test_unreachable_database_refuses_an_unseen_token(self):
        db = _db(connected=False)
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, db)
        assert exc.value.status_code == 401

    def test_query_failure_refuses_an_unseen_token(self):
        db = _db(raises=True)
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, db)

    def test_absent_database_refuses_an_unseen_token(self):
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, None)


@pytest.mark.unit
class TestCacheSoftensTheOutage:
    def test_recently_verified_token_survives_a_query_failure(self):
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))   # warm the cache
        sec._verify_jti_not_revoked(JTI, _db(raises=True))     # must not raise

    def test_recently_verified_token_survives_an_unreachable_database(self):
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        sec._verify_jti_not_revoked(JTI, _db(connected=False))

    def test_the_grace_expires(self):
        """Stale-but-enforced has a limit, or a long outage becomes fail-open again."""
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        unreachable = _db(connected=False)
        with patch.object(sec.time, "monotonic",
                          return_value=sec.time.monotonic() + sec._REVOCATION_CACHE_TTL + 1):
            with pytest.raises(HTTPException):
                sec._verify_jti_not_revoked(JTI, unreachable)

    def test_the_cache_does_not_cover_a_different_token(self):
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        unreachable = _db(connected=False)
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked("22222222-2222-2222-2222-222222222222", unreachable)

    def test_a_live_revocation_still_wins_over_a_warm_cache(self):
        """The cache is a fallback for outages, never a shortcut past a working check."""
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        now_revoked = _db(revoked=True)
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, now_revoked)


@pytest.mark.unit
class TestCacheIsBounded:
    def test_it_does_not_grow_without_limit(self):
        """A stream of distinct tokens must not turn this into a memory leak."""
        db = _db(revoked=False)
        for i in range(sec._REVOCATION_CACHE_MAX + 200):
            sec._verify_jti_not_revoked(f"jti-{i}", db)
        assert len(sec._revocation_cache) <= sec._REVOCATION_CACHE_MAX

    def test_the_cache_is_reset_on_the_entry_that_reaches_the_limit(self):
        """TQ-3. `<= MAX` above holds for a cache that evicts one entry late, so
        the off-by-one in `len(...) >= _REVOCATION_CACHE_MAX` was unverified.

        With every entry fresh there is nothing stale to drop, so the limit-th
        insert clears the cache and starts over — leaving exactly one entry.
        """
        db = _db(revoked=False)
        for i in range(sec._REVOCATION_CACHE_MAX + 1):
            sec._verify_jti_not_revoked(f"jti-{i}", db)

        assert len(sec._revocation_cache) == 1

    def test_the_cache_holds_exactly_the_limit_before_that(self):
        """The other side of the boundary: one fewer insert must not reset it."""
        db = _db(revoked=False)
        for i in range(sec._REVOCATION_CACHE_MAX):
            sec._verify_jti_not_revoked(f"jti-{i}", db)

        assert len(sec._revocation_cache) == sec._REVOCATION_CACHE_MAX


@pytest.mark.unit
class TestTheTuningIsWhatTheCommentsPromise:
    """Every other test refers to these symbolically, so changing a constant moves
    the code and the test together and nothing objects. Both values carry a stated
    guarantee in the source, and the guarantee is what is pinned here."""

    def test_the_grace_window_is_a_minute(self):
        """`_REVOCATION_CACHE_TTL`: "a revocation takes effect within a minute even
        during [an outage]". A larger value silently lengthens that window."""
        assert sec._REVOCATION_CACHE_TTL == 60.0

    def test_the_cache_bound_is_the_documented_one(self):
        assert sec._REVOCATION_CACHE_MAX == 4096


@pytest.mark.unit
class TestTheGraceBoundary:
    """`_recently_verified` compares with `<`, so a verdict exactly TTL old has
    expired. `test_the_grace_expires` uses TTL + 1, which passes either way."""

    # The clock is pinned for the *recording* call too. Reading the real clock
    # first makes the gap TTL + however long the call took, which lands on the
    # expired side of both `<` and `<=` and so proves nothing about the boundary.
    RECORDED_AT = 1_000.0

    def _record_then_check_at(self, elapsed: float) -> None:
        with patch.object(sec.time, "monotonic", return_value=self.RECORDED_AT):
            sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        with patch.object(sec.time, "monotonic", return_value=self.RECORDED_AT + elapsed):
            sec._verify_jti_not_revoked(JTI, _db(connected=False))

    def test_a_verdict_exactly_ttl_old_is_no_longer_usable(self):
        with pytest.raises(HTTPException):
            self._record_then_check_at(sec._REVOCATION_CACHE_TTL)

    def test_a_verdict_just_under_ttl_still_is(self):
        self._record_then_check_at(sec._REVOCATION_CACHE_TTL - 0.5)


@pytest.mark.unit
class TestTheConnectedCheckFailsClosed:
    def test_a_database_object_without_is_connected_is_treated_as_down(self):
        """`getattr(db, "is_connected", False)` — the default is the whole point.
        Flipping it to True makes an object that never reports connectivity look
        connected, which is the fail-open shape SEC-2 removed. A MagicMock always
        has the attribute, so only a real object without one exercises it."""

        class DatabaseWithoutTheAttribute:
            def is_token_revoked(self, jti: str) -> bool:
                # Answers "not revoked" rather than raising: raising lands in the
                # `except Exception` fallback, which refuses anyway, so the test
                # would pass with the default flipped. Answering lets the mutant
                # through to the accept path, which is what makes it detectable.
                return False

        db = DatabaseWithoutTheAttribute()
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, db)

        assert exc.value.status_code == 401
