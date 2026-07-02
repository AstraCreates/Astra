"""
URL-safety guard against SSRF (Server-Side Request Forgery).

Apply this wherever the backend fetches a URL that isn't a hardcoded, trusted
API endpoint — e.g. a URL discovered via web search, returned by an LLM, or
otherwise derived from external/agent-controlled input. It blocks requests to
internal infrastructure (cloud metadata endpoint, docker-internal service
names, loopback, private/reserved ranges) while leaving normal public URLs
(news sites, competitor pages, third-party APIs) untouched.

Deliberately minimal — this is not a hardened SSRF-proofing framework, just
enough to close the "agent fetches http://169.254.169.254/, http://localhost/
or http://redis:6379/" hole.

Known residual gap: this re-validates the hostname/IP at check time and at
each redirect hop, which closes the obvious cases including basic DNS
rebinding-via-redirect. It does NOT pin the TCP connection to the exact IP
that was validated (i.e. a DNS record that changes between our `getaddrinfo`
call and the underlying library's own connect a few milliseconds later could
in theory slip through). That level of protection would require a custom
transport/adapter per HTTP client library; not worth the complexity for the
threat model here (this closes the "obvious internal-network access hole,"
it does not defend against a sophisticated, actively-racing DNS-rebinding
attacker).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Docker-compose service names used in this repo (see docker-compose.yml).
# Blocked by name in addition to IP-range checks, since within the docker
# network these hostnames resolve to addresses that would also be caught by
# the private-range check below — this is just defense in depth / a faster,
# clearer rejection than waiting on DNS.
_BLOCKED_HOSTNAMES = {
    "redis", "backend", "frontend", "nginx", "certbot", "windmill-server", "windmill-db",
    "localhost", "metadata", "metadata.google.internal",
}

_ALLOWED_SCHEMES = {"http", "https"}

MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """Raised when a URL fails the SSRF safety check."""


def _is_ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> treat as unsafe
    return (
        ip.is_private       # RFC1918 (10/8, 172.16/12, 192.168/16) + others
        or ip.is_loopback   # 127.0.0.0/8, ::1
        or ip.is_link_local # 169.254.0.0/16 -> blocks cloud metadata endpoint
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_url(url: str) -> bool:
    """Return True if `url` is safe to fetch (public http/https host)."""
    try:
        validate_url(url)
        return True
    except UnsafeURLError:
        return False


def validate_url(url: str) -> str:
    """Raise UnsafeURLError if `url` targets internal/private infrastructure.
    Returns the url unchanged on success so it can be chained inline."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError(f"Blocked unsafe URL: {url!r}")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"Blocked unsafe URL (scheme not allowed): {url}")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise UnsafeURLError(f"Blocked unsafe URL (no hostname): {url}")

    if hostname in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Blocked unsafe URL (internal service hostname): {url}")

    # Resolve DNS ourselves rather than trusting the hostname string, and
    # reject if ANY resolved address is private/loopback/link-local/reserved.
    # This is what catches http://169.254.169.254/, http://10.0.0.5/, etc.,
    # and also catches "attacker-owned-domain.com that resolves to 127.0.0.1".
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Blocked unsafe URL (DNS resolution failed): {url}") from e

    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        raise UnsafeURLError(f"Blocked unsafe URL (no addresses resolved): {url}")

    for ip_str in resolved_ips:
        if _is_ip_blocked(ip_str):
            raise UnsafeURLError(
                f"Blocked unsafe URL (resolves to private/internal address {ip_str}): {url}"
            )

    return url


def safe_get(url: str, *, max_redirects: int = MAX_REDIRECTS, **kwargs):
    """requests.get() with the SSRF guard applied to the initial URL AND to
    every redirect hop.

    `allow_redirects` is intentionally disabled and redirects are followed
    manually (bounded to `max_redirects` hops) so a URL that passes the
    initial check can't 302 its way to an internal address — this is the
    fix for the `requests.get(url, allow_redirects=True)` SSRF pattern.
    """
    import requests

    kwargs.pop("allow_redirects", None)
    current = url
    for _ in range(max_redirects + 1):
        validate_url(current)
        resp = requests.get(current, allow_redirects=False, **kwargs)
        if resp.is_redirect or resp.is_permanent_redirect:
            location = resp.headers.get("Location")
            if not location:
                return resp
            current = urljoin(current, location)
            continue
        return resp
    raise UnsafeURLError(f"Blocked unsafe URL (too many redirects): {url}")


if __name__ == "__main__":
    # Minimal self-check — not a full pytest suite, just enough to confirm
    # the guard behaves sanely against a mix of safe and unsafe URLs.
    _CASES = [
        ("https://example.com", True),
        ("http://example.com", True),
        ("https://www.google.com", True),
        ("http://169.254.169.254/latest/meta-data/", False),   # cloud metadata
        ("http://localhost/", False),
        ("http://localhost:8000/admin/", False),
        ("http://127.0.0.1/", False),
        ("http://10.0.0.5/", False),
        ("http://172.16.0.1/", False),
        ("http://192.168.1.1/", False),
        ("http://redis:6379/", False),
        ("http://backend:8000/", False),
        ("ftp://example.com/file", False),                     # bad scheme
        ("file:///etc/passwd", False),                         # bad scheme
        ("not a url", False),
    ]
    failures = 0
    for test_url, expected_safe in _CASES:
        actual_safe = is_safe_url(test_url)
        status = "OK" if actual_safe == expected_safe else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"[{status}] is_safe_url({test_url!r}) = {actual_safe} (expected {expected_safe})")
    if failures:
        print(f"\n{failures} check(s) failed.")
        raise SystemExit(1)
    print(f"\nAll {len(_CASES)} checks passed.")
