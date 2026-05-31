"""Isolated outbound-HTTP helpers.

Every network call in the package funnels through here so the one known gotcha — a
corporate TLS-intercepting proxy that breaks naive HTTPS — is fixable with two env vars
in a single place rather than scattered across sources.

Honors:
  HTTPS_PROXY / HTTP_PROXY     standard proxy URLs
  CA_BUNDLE / REQUESTS_CA_BUNDLE / SSL_CERT_FILE   path to a CA bundle (e.g. corp root CA)

Verification is never disabled by default.
"""

from __future__ import annotations

import os
import ssl
import urllib.request
from urllib.error import HTTPError, URLError

DEFAULT_UA = "ai-radar/0.1 (+https://github.com/cdblake1/cc-plugins)"
DEFAULT_TIMEOUT = 30


def proxy_url() -> str | None:
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = os.environ.get(var)
        if val:
            return val
    return None


def ca_bundle_path() -> str | None:
    for var in ("CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        val = os.environ.get(var)
        if val and os.path.exists(val):
            return val
    return None


def ssl_context() -> ssl.SSLContext:
    """Build an SSL context, trusting a custom CA bundle when configured."""
    ca = ca_bundle_path()
    if ca:
        return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def _opener() -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPSHandler(context=ssl_context())
    ]
    proxy = proxy_url()
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def get(url: str, timeout: int = DEFAULT_TIMEOUT, headers: dict | None = None) -> bytes:
    """GET a URL and return raw bytes, honoring proxy + CA settings.

    Raises urllib's HTTPError / URLError on failure; callers decide whether to skip.
    """
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA, **(headers or {})})
    with _opener().open(req, timeout=timeout) as resp:
        return resp.read()


__all__ = [
    "proxy_url",
    "ca_bundle_path",
    "ssl_context",
    "get",
    "HTTPError",
    "URLError",
    "DEFAULT_TIMEOUT",
]
