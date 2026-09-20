"""P2-6 — the JWT library swap, held to its two acceptance conditions.

`python-jose` was replaced by `PyJWT` to get `ecdsa` out of the image (SECURITY.md §2).
The swap is only safe if it is invisible to tokens already in the wild, and only
worth doing if the dependency actually left. Each of those is one test below.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: A real token minted by `python-jose` 3.5.0 before the swap, HS256 over the secret
#: below, expiring in 2099. It is the only evidence available that the new library
#: verifies what the old one signed — once jose is uninstalled it cannot be re-made.
_JOSE_SIGNED_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJ1c2VyLWxlZ2FjeS1hYmMiLCJqdGkiOiIxMTExMTExMS0yMjIyLTMzMzMtNDQ0NC01"
    "NTU1NTU1NTU1NTUiLCJyb2xlIjoiYWRtaW4iLCJpYXQiOjE3ODk4NjI0MDAsImV4cCI6NDA3MDkw"
    "ODgwMH0."
    "dTrS3874VxDwAqjWpuEP9IQe3EAeypooX-1H0iHtA2E"
)
_JOSE_SIGNING_SECRET = "p2-6-fixture-secret-do-not-use-in-production"


class TestTokensIssuedBeforeTheSwapStillVerify:
    """The upgrade has to be survivable without logging every session out."""

    def test_a_jose_signed_token_decodes_under_pyjwt(self, monkeypatch):
        from src import config
        from src.security_fastapi import _decode_token

        monkeypatch.setattr(config, "JWT_SECRET_KEY", _JOSE_SIGNING_SECRET)

        claims = _decode_token(_JOSE_SIGNED_TOKEN)

        assert claims["sub"] == "user-legacy-abc"
        assert claims["jti"] == "11111111-2222-3333-4444-555555555555"
        assert claims["role"] == "admin"

    def test_the_same_token_under_a_different_secret_is_refused(self, monkeypatch):
        """Without this the test above passes against a decoder that verifies nothing."""
        import jwt

        from src import config
        from src.security_fastapi import _decode_token

        monkeypatch.setattr(config, "JWT_SECRET_KEY", _JOSE_SIGNING_SECRET + "x")

        with pytest.raises(jwt.InvalidSignatureError):
            _decode_token(_JOSE_SIGNED_TOKEN)


class TestTheDependencyActuallyLeft:
    """The point of the swap. A future bump that reintroduces jose fails here."""

    @pytest.mark.parametrize("lock", ["requirements.txt", "requirements-dev.txt"])
    @pytest.mark.parametrize("banned", ["python-jose", "ecdsa"])
    def test_no_lock_pins_it(self, lock, banned):
        pins = {
            m.group(1).lower()
            for m in (
                re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==", line.strip())
                for line in (_REPO_ROOT / lock).read_text(encoding="utf-8").splitlines()
            )
            if m
        }
        assert banned not in pins, f"{lock} still pins {banned}"

    def test_no_module_imports_jose(self):
        offenders = [
            path.relative_to(_REPO_ROOT).as_posix()
            for path in (_REPO_ROOT / "src").rglob("*.py")
            if re.search(r"^\s*(from jose\b|import jose\b)", path.read_text(encoding="utf-8"), re.M)
        ]
        assert offenders == []
