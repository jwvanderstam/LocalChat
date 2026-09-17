"""P0-5 — a caller cannot choose its own rate-limit key behind the bundled nginx.

Audit finding H3. Two settings combined into a bypass:

* `nginx/nginx.conf` set ``X-Forwarded-For`` with ``$proxy_add_x_forwarded_for``, which
  **appends** the peer to whatever the caller already sent.
* `docker-compose.nginx.yml` set ``TRUSTED_PROXY_IPS: "*"``, and with that uvicorn's
  ``ProxyHeadersMiddleware`` trusts every peer and takes the **leftmost** entry.

So a request carrying its own ``X-Forwarded-For: 9.9.9.9`` arrived as
``9.9.9.9, <real address>`` and the application keyed on ``9.9.9.9``. Login brute force
was unthrottled on the one path that faces the internet, and `RATELIMIT_LOGIN` counted
whatever bucket the attacker named.

These tests drive the real middleware rather than reading the config files, because the
bypass lived in how uvicorn interprets the values, not in the values looking wrong. The
two config assertions at the end exist only to keep the deployed files and the behaviour
described here from drifting apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
#: The subnet docker-compose.nginx.yml pins the frontend network to.
PROXY_SUBNET = "172.31.240.0/24"
PROXY_ADDRESS = "172.31.240.2"
REAL_CLIENT = "203.0.113.9"
FORGED = "9.9.9.9"


def _client_host_seen_by_the_app(
    *, trusted: str, peer: str, forwarded_for: str | None
) -> str | None:
    """Run ProxyHeadersMiddleware as uvicorn does and report the resulting client."""
    import asyncio

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    seen: dict[str, str | None] = {}

    async def app(scope, receive, send):
        client = scope.get("client")
        seen["host"] = client[0] if client else None

    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))

    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 54321),
        "scheme": "http",
    }
    asyncio.run(ProxyHeadersMiddleware(app, trusted_hosts=trusted)(scope, None, None))
    return seen["host"]


@pytest.mark.unit
class TestTheWildcardWasTheBypass:
    """Kept as the measurement: the fix is only meaningful against the bug."""

    def test_a_wildcard_lets_the_caller_pick_its_own_address(self):
        """What the shipped overlay did. nginx appends, so the forged entry is first."""
        assert (
            _client_host_seen_by_the_app(
                trusted="*", peer=PROXY_ADDRESS, forwarded_for=f"{FORGED}, {REAL_CLIENT}"
            )
            == FORGED
        )

    def test_naming_the_subnet_reaches_the_address_nginx_observed(self):
        """Uvicorn walks the list from the right and stops at the first untrusted host."""
        assert (
            _client_host_seen_by_the_app(
                trusted=PROXY_SUBNET,
                peer=PROXY_ADDRESS,
                forwarded_for=f"{FORGED}, {REAL_CLIENT}",
            )
            == REAL_CLIENT
        )


@pytest.mark.unit
class TestTheDeployedCombinationCannotBeForged:
    """nginx replaces the header, so only one entry ever arrives."""

    def test_a_forged_header_is_discarded_before_it_reaches_the_app(self):
        """What the fixed nginx sends: X-Forwarded-For is exactly the peer it saw."""
        assert (
            _client_host_seen_by_the_app(
                trusted=PROXY_SUBNET, peer=PROXY_ADDRESS, forwarded_for=REAL_CLIENT
            )
            == REAL_CLIENT
        )

    def test_two_callers_forging_the_same_value_still_key_separately(self):
        """The point of the finding: the rate-limit key must not be caller-chosen."""
        first = _client_host_seen_by_the_app(
            trusted=PROXY_SUBNET, peer=PROXY_ADDRESS, forwarded_for="198.51.100.1"
        )
        second = _client_host_seen_by_the_app(
            trusted=PROXY_SUBNET, peer=PROXY_ADDRESS, forwarded_for="198.51.100.2"
        )
        assert first != second

    def test_an_untrusted_peer_is_not_believed_at_all(self):
        """Anything reaching the app directly keeps its own address, header or not."""
        assert (
            _client_host_seen_by_the_app(
                trusted=PROXY_SUBNET, peer="10.9.9.9", forwarded_for=FORGED
            )
            == "10.9.9.9"
        )

    def test_a_request_with_no_header_keeps_the_peer_address(self):
        assert (
            _client_host_seen_by_the_app(
                trusted=PROXY_SUBNET, peer=PROXY_ADDRESS, forwarded_for=None
            )
            == PROXY_ADDRESS
        )


@pytest.mark.unit
class TestTheShippedOverlayMatchesWhatIsTestedHere:
    """The behaviour above is only true of the deployment if these still hold."""

    def _overlay(self) -> dict:
        # Compose has its own tags (`!reset`) that safe_load refuses. Their meaning
        # does not matter here, so they resolve to None rather than stopping the read.
        class _ComposeLoader(yaml.SafeLoader):
            pass

        _ComposeLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
        return yaml.load(  # noqa: S506 - SafeLoader subclass, not the unsafe loader
            (_ROOT / "docker-compose.nginx.yml").read_text(encoding="utf-8"),
            Loader=_ComposeLoader,
        )

    def test_the_overlay_does_not_wildcard_proxy_trust(self):
        trusted = self._overlay()["services"]["app"]["environment"]["TRUSTED_PROXY_IPS"]
        assert trusted != "*"
        assert trusted == PROXY_SUBNET

    def test_the_frontend_network_pins_that_subnet(self):
        """Docker assigns bridge subnets dynamically; an unpinned one cannot be trusted."""
        subnets = [
            entry["subnet"]
            for entry in self._overlay()["networks"]["frontend"]["ipam"]["config"]
        ]
        assert PROXY_SUBNET in subnets

    def test_nginx_shares_a_network_with_the_app(self):
        """It joined the implicit default network, where `proxy_pass http://app:5000`
        cannot resolve — the overlay never reached the application at all."""
        assert "frontend" in self._overlay()["services"]["nginx"]["networks"]

    def test_nginx_sets_the_headers_its_own_responses_need(self):
        """A 413 or a 502 is answered by nginx and never reaches the app middleware."""
        conf = (_ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        for header in (
            "X-Content-Type-Options",
            "Referrer-Policy",
            "X-Frame-Options",
            "Strict-Transport-Security",
        ):
            directive = next(
                (line.strip() for line in conf.splitlines()
                 if line.strip().startswith("add_header") and header in line),
                None,
            )
            assert directive is not None, f"nginx sets no {header}"
            # Without `always` it applies to 2xx/3xx only — not to the error
            # responses that are the reason for setting it here at all.
            assert directive.endswith("always;"), directive

    def test_nginx_caps_the_body_size_to_match_the_application(self):
        """Its own default is 1 MB, so it silently overrides a larger app limit."""
        conf = (_ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        assert "client_max_body_size 16m;" in conf

    def test_nginx_replaces_the_forwarded_header_rather_than_appending(self):
        conf = (_ROOT / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        # Directives only. The file explains the old value in a comment, and a
        # substring search over the whole text would match that explanation.
        directives = [
            line.strip()
            for line in conf.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        forwarded = [d for d in directives if "X-Forwarded-For" in d]
        assert forwarded == ["proxy_set_header   X-Forwarded-For   $remote_addr;"]
        assert not any("$proxy_add_x_forwarded_for" in d for d in directives)
