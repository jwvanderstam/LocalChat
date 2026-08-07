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
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, _db(revoked=True))
        assert exc.value.status_code == 401

    def test_a_revoked_token_is_never_cached_as_usable(self):
        """A refusal must not leave a verdict that would let it through later."""
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, _db(revoked=True))
        assert JTI not in sec._revocation_cache


@pytest.mark.unit
class TestFailsClosed:
    """The behaviour change. Previously each of these allowed the request."""

    def test_unreachable_database_refuses_an_unseen_token(self):
        with pytest.raises(HTTPException) as exc:
            sec._verify_jti_not_revoked(JTI, _db(connected=False))
        assert exc.value.status_code == 401

    def test_query_failure_refuses_an_unseen_token(self):
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, _db(raises=True))

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
        with patch.object(sec.time, "monotonic",
                          return_value=sec.time.monotonic() + sec._REVOCATION_CACHE_TTL + 1):
            with pytest.raises(HTTPException):
                sec._verify_jti_not_revoked(JTI, _db(connected=False))

    def test_the_cache_does_not_cover_a_different_token(self):
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked("22222222-2222-2222-2222-222222222222",
                                        _db(connected=False))

    def test_a_live_revocation_still_wins_over_a_warm_cache(self):
        """The cache is a fallback for outages, never a shortcut past a working check."""
        sec._verify_jti_not_revoked(JTI, _db(revoked=False))
        with pytest.raises(HTTPException):
            sec._verify_jti_not_revoked(JTI, _db(revoked=True))


@pytest.mark.unit
class TestCacheIsBounded:
    def test_it_does_not_grow_without_limit(self):
        """A stream of distinct tokens must not turn this into a memory leak."""
        db = _db(revoked=False)
        for i in range(sec._REVOCATION_CACHE_MAX + 200):
            sec._verify_jti_not_revoked(f"jti-{i}", db)
        assert len(sec._revocation_cache) <= sec._REVOCATION_CACHE_MAX
