"""P1-2 (M4) — a URL the application is asked to fetch cannot point inward.

Two places retrieve a URL supplied from outside: the web-search result fetcher and
the webhook connector. Both guarded it by inspecting the **hostname string**, so an
IP literal in a private range was refused and a DNS name was waved through — with a
comment in the source admitting the check could not resolve it. A name pointing at
`10.0.0.5`, or a bare compose service name, was fetched by a process sitting on the
same network as the database and the model server.

Neither re-validated redirects, so one public hop was enough to reach anywhere.
"""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from src.utils.safe_fetch import UnsafeUrlError, resolve_and_validate, safe_fetch


def _resolves_to(*addresses: str):
    """Patch DNS so a hostname resolves to exactly *addresses*."""
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 443)) for addr in addresses]
    return patch("src.utils.safe_fetch.socket.getaddrinfo", return_value=infos)


@pytest.mark.unit
class TestANameIsJudgedByWhatItResolvesTo:
    """The heart of M4: the old checks never resolved anything."""

    def test_a_name_resolving_to_a_private_address_is_refused(self):
        with _resolves_to("10.0.0.5"), pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://internal.example.com/doc")

    def test_a_name_resolving_to_loopback_is_refused(self):
        with _resolves_to("127.0.0.1"), pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://sneaky.example.com/doc")

    def test_a_name_resolving_to_the_metadata_address_is_refused(self):
        """169.254.169.254 — the cloud credential endpoint SSRF exists to reach."""
        with _resolves_to("169.254.169.254"), pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://metadata.example.com/latest/meta-data/")

    def test_a_public_name_is_allowed(self):
        """The negative space: refusing everything would satisfy all of the above."""
        with _resolves_to("93.184.216.34"):
            assert resolve_and_validate("https://example.com/doc") == ["93.184.216.34"]

    def test_one_private_answer_among_several_refuses_the_whole_name(self):
        """A round-robin record cannot be retried until the public answer wins."""
        with _resolves_to("93.184.216.34", "10.0.0.5"), pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://mixed.example.com/doc")

    def test_the_refusal_does_not_echo_the_internal_address(self):
        """Otherwise the endpoint maps the caller's network for them."""
        with _resolves_to("10.1.2.3"):
            with pytest.raises(UnsafeUrlError) as exc_info:
                resolve_and_validate("https://internal.example.com/doc")
        assert "10.1.2.3" not in str(exc_info.value)

    def test_a_name_that_does_not_resolve_is_refused(self):
        with patch(
            "src.utils.safe_fetch.socket.getaddrinfo", side_effect=socket.gaierror("nope")
        ), pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://nx.example.com/doc")


@pytest.mark.unit
class TestLiteralsAndSchemes:
    def test_a_private_ip_literal_is_still_refused(self):
        """What the old check did catch; it must keep catching it."""
        with pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://10.0.0.5/doc")

    def test_localhost_is_refused_by_name(self):
        with pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://localhost/doc")

    def test_the_google_metadata_name_is_refused(self):
        with pytest.raises(UnsafeUrlError):
            resolve_and_validate("https://metadata.google.internal/computeMetadata/v1/")

    def test_a_non_http_scheme_is_refused(self):
        """file:// and gopher:// are the classic SSRF escapes."""
        with pytest.raises(UnsafeUrlError):
            resolve_and_validate("file:///etc/passwd")

    def test_http_is_refused_when_https_is_required(self):
        with _resolves_to("93.184.216.34"), pytest.raises(UnsafeUrlError):
            resolve_and_validate("http://example.com/doc", require_https=True)

    def test_http_is_allowed_when_it_is_not(self):
        with _resolves_to("93.184.216.34"):
            assert resolve_and_validate("http://example.com/doc")

    def test_a_url_with_no_hostname_is_refused(self):
        with pytest.raises(UnsafeUrlError):
            resolve_and_validate("https:///doc")


def _response(*, status=200, headers=None, chunks=(b"body",), is_redirect=False):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {"Content-Type": "text/html"}
    resp.is_redirect = is_redirect
    resp.is_permanent_redirect = False
    resp.encoding = "utf-8"
    resp.iter_content.return_value = iter(chunks)
    return resp


@pytest.mark.unit
class TestRedirectsAreRevalidated:
    """A first check that is not repeated at each hop is decorative."""

    def test_a_redirect_into_a_private_address_is_refused(self):
        session = MagicMock()
        session.get.return_value = _response(
            status=302,
            headers={"Location": "http://internal.example.com/secrets"},
            is_redirect=True,
        )

        infos_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        infos_private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]
        with patch(
            "src.utils.safe_fetch.socket.getaddrinfo",
            side_effect=[infos_public, infos_private],
        ), pytest.raises(UnsafeUrlError):
            safe_fetch("https://example.com/start", session=session)

    def test_a_redirect_to_another_public_url_is_followed(self):
        session = MagicMock()
        session.get.side_effect = [
            _response(status=302, headers={"Location": "https://elsewhere.example.com/doc"},
                      is_redirect=True),
            _response(chunks=(b"<p>hi</p>",)),
        ]
        with _resolves_to("93.184.216.34"):
            result = safe_fetch("https://example.com/start", session=session)
        assert "hi" in result.text

    def test_a_redirect_loop_stops(self):
        session = MagicMock()
        session.get.return_value = _response(
            status=302, headers={"Location": "https://example.com/again"}, is_redirect=True
        )
        with _resolves_to("93.184.216.34"), pytest.raises(UnsafeUrlError):
            safe_fetch("https://example.com/start", session=session, max_redirects=2)


@pytest.mark.unit
class TestTheResponseIsBounded:
    def test_a_body_over_the_cap_is_refused(self):
        """There was no cap at all, on either fetch path."""
        session = MagicMock()
        session.get.return_value = _response(chunks=(b"x" * 1024,) * 10)
        with _resolves_to("93.184.216.34"), pytest.raises(UnsafeUrlError):
            safe_fetch("https://example.com/big", session=session, max_bytes=2048)

    def test_a_body_under_the_cap_is_returned(self):
        session = MagicMock()
        session.get.return_value = _response(chunks=(b"small",))
        with _resolves_to("93.184.216.34"):
            assert safe_fetch("https://example.com/ok", session=session).text == "small"

    def test_an_unexpected_content_type_is_refused_when_one_is_required(self):
        session = MagicMock()
        session.get.return_value = _response(headers={"Content-Type": "application/zip"})
        with _resolves_to("93.184.216.34"), pytest.raises(UnsafeUrlError):
            safe_fetch(
                "https://example.com/f",
                session=session,
                allowed_content_types=("text/plain",),
            )


@pytest.mark.unit
class TestTheWebhookSecretIsMandatory:
    """It was optional, and compared with `!=` (audit M4)."""

    def _connector(self, **config):
        from src.connectors.webhook import WebhookConnector

        return WebhookConnector(config)

    def test_a_connector_without_a_secret_is_invalid(self):
        errors = self._connector().validate_config()
        assert errors
        assert "secret" in errors[0]

    def test_an_empty_secret_is_invalid(self):
        assert self._connector(secret="   ").validate_config()

    def test_a_short_secret_is_invalid(self):
        """A guessable secret is the same hole with extra steps."""
        assert self._connector(secret="hunter2").validate_config()

    def test_a_real_secret_is_valid(self):
        assert self._connector(secret="x" * 32).validate_config() == []
