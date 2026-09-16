"""Fetch a URL the application was asked to fetch, without reaching inward.

Two places take a URL from outside and retrieve it: the web-search result fetcher
and the webhook connector. Both guarded it by *looking at the hostname string* —
an IP literal in a private range was refused, and a DNS name was waved through with
a comment saying the check could not resolve it. So `http://internal.example.com`
pointing at `10.0.0.5`, or a bare compose service name like `http://db:5432`, went
straight past both (audit M4), from a process sitting on the same network as the
database and the model server.

What this adds, in the order it matters:

* **Resolution before decision.** Every address a name resolves to is checked, not
  the name. One private address anywhere in the record set refuses the fetch, so a
  round-robin record that mixes public and private answers cannot be retried until
  it wins.
* **Redirects are re-validated.** A public URL that 302s to `http://169.254.169.254`
  was previously followed without a second look, which makes the first check
  decorative.
* **Caps on bytes and time**, so a slow or endless response cannot hold a worker or
  exhaust memory.

**Residual, stated rather than hidden:** the connection is made by name after the
name resolves, so a DNS entry that answers differently between the check and the
connection (rebinding) is not defeated. Closing that means pinning the connection
to the validated address, which for HTTPS means taking over certificate
verification. Recorded in SECURITY.md with the trigger that would justify it.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from .logging_config import get_logger

logger = get_logger(__name__)

#: Hostnames that name something internal without resolving to an obvious range.
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.goog",
})

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 10
DEFAULT_MAX_REDIRECTS = 3


class UnsafeUrlError(ValueError):
    """The URL names something this application must not reach."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content_type: str
    text: str


def _address_is_reachable_externally(addr: str) -> bool:
    """False for anything that is not a public unicast address.

    Deliberately a whole-category refusal rather than a block-list of ranges: a
    list needs extending every time a new one matters, and the AWS metadata
    endpoint at 169.254.169.254 is only the famous member of link-local.
    """
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        parsed.is_private
        or parsed.is_loopback
        or parsed.is_link_local
        or parsed.is_reserved
        or parsed.is_multicast
        or parsed.is_unspecified
    )


def resolve_and_validate(url: str, *, require_https: bool = False) -> list[str]:
    """Return the addresses *url* resolves to, or raise :class:`UnsafeUrlError`.

    Raises when the scheme is wrong, the host names something internal, the name
    does not resolve, or **any** address it resolves to is not publicly routable.
    """
    parsed = urlparse(url)
    allowed_schemes = ("https",) if require_https else ("http", "https")
    if parsed.scheme not in allowed_schemes:
        raise UnsafeUrlError(f"scheme must be one of {allowed_schemes}, got {parsed.scheme!r}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise UnsafeUrlError("URL has no hostname")
    if hostname in _BLOCKED_HOSTNAMES:
        raise UnsafeUrlError(f"refusing to fetch {hostname}")

    try:
        infos = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve {hostname}") from exc

    addresses = sorted({str(info[4][0]) for info in infos})
    if not addresses:
        raise UnsafeUrlError(f"could not resolve {hostname}")

    for address in addresses:
        if not _address_is_reachable_externally(address):
            # The address is not echoed back: it is a fact about the caller's
            # network that the caller supplied a name to discover.
            raise UnsafeUrlError(f"{hostname} resolves to a non-public address")
    return addresses


def safe_fetch(
    url: str,
    *,
    require_https: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allowed_content_types: tuple[str, ...] | None = None,
    session: requests.Session | None = None,
) -> FetchResult:
    """Fetch *url*, refusing anything that points inward at any hop."""
    http = session or requests
    current = url

    for _ in range(max_redirects + 1):
        resolve_and_validate(current, require_https=require_https)
        response = http.get(
            current,
            timeout=timeout,
            # Followed here instead, so each hop is validated before it is taken.
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise UnsafeUrlError("redirect without a Location header")
                current = requests.compat.urljoin(current, location)  # type: ignore[attr-defined]
                continue

            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if allowed_content_types and content_type not in allowed_content_types:
                raise UnsafeUrlError(f"unexpected content type {content_type!r}")

            body = bytearray()
            for chunk in response.iter_content(8192):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise UnsafeUrlError(f"response exceeded {max_bytes} bytes")

            return FetchResult(
                url=current,
                status_code=response.status_code,
                content_type=content_type,
                text=body.decode(response.encoding or "utf-8", errors="replace"),
            )
        finally:
            response.close()

    raise UnsafeUrlError(f"more than {max_redirects} redirects")
