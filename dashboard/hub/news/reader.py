"""In-app article reading, behind an SSRF guard.

Eligible items (reporting/primary lane, free, on their own outlet's domain,
never a Google News redirect link) get fetched and run through trafilatura;
everything else is a link-out. Every hop -- the item's own URL and any
redirect it returns -- is resolved and address-checked before it is fetched,
so a URL that redirects into the Hub's own tailnet is refused mid-chain, not
just at the first hop.

fetch_article() is the pure core: it takes a fetcher and a resolver as
arguments and never touches the database, so tests drive it directly with
fakes and never hit the network. read() is the thin DB-aware wrapper that
looks the item up, checks eligibility, and caches a successful extraction.
"""

from __future__ import annotations

import http.client
import ipaddress
import logging
import socket
import ssl
import time
import urllib.parse
from datetime import datetime, timezone

import trafilatura

from news import db

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; VaultNewsReader/1.0; +https://github.com/)"
FETCH_TIMEOUT = 10
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 3 * 1024 * 1024
TOTAL_DEADLINE = 15  # seconds, the whole fetch_article() call across every hop
_REDIRECT_CODES = (301, 302, 303, 307, 308)
_ALLOWED_PORTS = {"http": 80, "https": 443}

# ponytail: one hard-coded host, not a pattern. Every Google News link in the
# seed is the news.google.com redirect shape; add a pattern if a second host
# shows up.
_GOOGLE_NEWS_HOSTS = {"news.google.com"}


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower()


def _site(host: str) -> str:
    """Approximate registrable domain: last two labels, three under a
    co.uk-shaped suffix. Feeds often live on a sibling subdomain of the
    articles (rss.dw.com -> www.dw.com, feeds.npr.org -> www.npr.org).

    ponytail: short suffix list, no public-suffix-list dependency; add a
    real PSL if a seeded outlet sits under a suffix this misses.
    """
    labels = host.split(".")
    n = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-n:])


_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac"}


def _same_registrable(item_host: str, source_host: str) -> bool:
    """`item_host` on the same registrable domain as `source_host`."""
    if not item_host or not source_host:
        return False
    return _site(item_host) == _site(source_host)


def eligible(item: dict, source: dict) -> bool:
    """Reporting/primary lane, not paywalled, on the outlet's own domain, and
    not a Google News redirect link."""
    if source.get("lane") not in ("reporting", "primary"):
        return False
    if source.get("paywall"):
        return False
    item_host = _host(item.get("url", ""))
    if item_host in _GOOGLE_NEWS_HOSTS:
        return False
    if not _same_registrable(item_host, _host(source.get("url", ""))):
        return False
    return True


def _default_resolve(host: str) -> list[str]:
    """Every address `host` resolves to. Empty list on a lookup failure."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return [info[4][0] for info in infos]  # pyright: ignore[reportReturnType]  getaddrinfo tuple slot 0 is a str for AF_INET/AF_INET6 / hostname checked upstream


def _resolve_vetted_ip(host: str, resolve) -> str | None:
    """One address to connect to for `host`, or None if it fails to resolve or
    any resolved address is non-global. `ip.is_global` already excludes
    loopback, RFC 1918 private, link-local, and the 100.64.0.0/10
    CGNAT/Tailscale range in one flag -- Python's ipaddress module treats all
    four as non-global, so a single check covers what the plan spells out as
    three named ranges.

    Returning the actual address (not a bool) lets the caller connect to the
    EXACT address that was just checked -- see _default_fetch()'s docstring
    for why a second, independent resolution at connect time is the bug this
    closes (DNS rebinding: the name could answer differently between a check
    and a later, separate lookup).
    """
    if not host:
        return None
    addrs = resolve(host)
    if not addrs:
        return None
    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return None
        if not ip.is_global:
            return None
    return addrs[0]


_READ_CHUNK_BYTES = 65536


def _read_capped(resp, deadline: float | None) -> bytes:
    """Read `resp` in chunks, capped at MAX_BODY_BYTES and cut off at
    `deadline` (a time.monotonic() timestamp) when one is given.

    resp.read(MAX_BODY_BYTES + 1) in one call only bounds *how much* comes
    back, not how long it takes -- a server that dribbles a few bytes at a
    time, each individual recv well inside FETCH_TIMEOUT, could hold the
    thread for minutes without ever tripping the byte cap or a socket
    timeout. Checking the deadline between chunks bounds that too.
    """
    chunks = []
    total = 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError("response read past the fetch deadline")
        chunk = resp.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise ValueError(f"response exceeded the {MAX_BODY_BYTES}-byte read cap")
    return b"".join(chunks)


def _default_fetch(url: str, ip: str, deadline: float | None = None) -> tuple[int, dict, bytes]:
    """One hop, GET, no automatic redirect-follow. Returns (status, headers, body).

    Connects to `ip` -- the address fetch_article() already vetted -- never
    re-resolving the hostname itself, which is what closes the DNS-rebinding
    gap (see _resolve_vetted_ip). The Host header (http) or SNI + certificate
    hostname (https) still carry the real hostname, so name-based routing and
    TLS validation are unaffected.

    http.client never auto-follows a 3xx, so a redirect comes back as an
    ordinary response with a Location header -- fetch_article() walks it by
    hand, address-checking each hop the same way as the first. `deadline`
    (fetch_article()'s TOTAL_DEADLINE, across every hop) and MAX_BODY_BYTES
    both bound the body read -- see _read_capped.
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"no hostname in {url!r}")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    if parsed.scheme == "https":
        raw = socket.create_connection((ip, parsed.port or 443), timeout=FETCH_TIMEOUT)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        conn = http.client.HTTPSConnection(host, timeout=FETCH_TIMEOUT)
        conn.sock = sock
        conn.putrequest("GET", path)
    else:
        conn = http.client.HTTPConnection(ip, parsed.port or 80, timeout=FETCH_TIMEOUT)
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host)
    try:
        conn.putheader("User-Agent", USER_AGENT)
        conn.endheaders()
        resp = conn.getresponse()
        body = _read_capped(resp, deadline)
        return resp.status, dict(resp.getheaders()), body
    finally:
        conn.close()


def _extract_paragraphs(html, url: str) -> list[str] | None:
    text = trafilatura.extract(html, url=url)
    if not text:
        return None
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return paragraphs or None


def fetch_article(url: str, fetch=_default_fetch, resolve=_default_resolve) -> dict:
    """Follow up to MAX_REDIRECTS hops, SSRF-checking every one, then extract
    readable text. No DB access -- the pure core, driven directly in tests.

    Any failure along the way (bad host, bad scheme/port, oversize response,
    a redirect loop, non-200, empty extraction, a raised exception, or the
    whole call running past TOTAL_DEADLINE) fails closed to a link-out result
    -- the reader never shows a broken page, only headline + link out.
    """
    start = time.monotonic()
    deadline = start + TOTAL_DEADLINE
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if time.monotonic() > deadline:
            return {"status": "link", "url": url}
        parsed = urllib.parse.urlparse(current)
        default_port = _ALLOWED_PORTS.get(parsed.scheme)
        try:
            port = parsed.port  # raises ValueError on a malformed/out-of-range port
        except ValueError:
            return {"status": "link", "url": url}
        if default_port is None or port not in (None, default_port):
            return {"status": "link", "url": url}
        ip = _resolve_vetted_ip(parsed.hostname or "", resolve)
        if ip is None:
            return {"status": "link", "url": url}
        logger.info("news reader fetching %s", current)
        try:
            if fetch is _default_fetch:
                status, headers, body = fetch(current, ip, deadline)
            else:
                status, headers, body = fetch(current, ip)
        except Exception:
            logger.exception("news reader fetch failed for %s", current)
            return {"status": "link", "url": url}
        if status in _REDIRECT_CODES:
            location = headers.get("Location") or headers.get("location")
            if not location:
                return {"status": "link", "url": url}
            current = urllib.parse.urljoin(current, location)
            continue
        if status != 200:
            return {"status": "link", "url": url}
        paragraphs = _extract_paragraphs(body, current)
        if not paragraphs:
            return {"status": "link", "url": url}
        return {"status": "ok", "paragraphs": paragraphs}
    return {"status": "link", "url": url}


def _safe_url(url: str | None) -> str | None:
    """`url` unchanged if it's http(s), else None. A feed entry's link is
    untrusted data (poll.py stores whatever a source's feed hands it); a
    `javascript:`-scheme item url handed straight to the frontend's <a href>
    would run in the page, not just link out."""
    if not url:
        return None
    return url if urllib.parse.urlparse(url).scheme in _ALLOWED_PORTS else None


def read(item_id: int, fetch=_default_fetch, resolve=_default_resolve) -> dict:
    """The item's readable text, cached in `articles` on a successful
    extraction, or a link-out result. A failed fetch is never cached --
    ponytail: no retry backoff, a transient failure just refetches on the
    next click; add a failure cache if repeated dead fetches show up live."""
    with db._cache() as conn:
        item_row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if item_row is None:
            return {"status": "link", "url": None}
        item = dict(item_row)
        cached = conn.execute(
            "SELECT text FROM articles WHERE item_id = ? AND status = 'ok'", (item_id,)
        ).fetchone()
        if cached is not None:
            return {"status": "ok", "paragraphs": cached["text"].split("\n")}

    sources = {s["id"]: s for s in db.list_sources()}
    source = sources.get(item["source_id"], {})

    if not eligible(item, source):
        return {"status": "link", "url": _safe_url(item["url"])}

    result = fetch_article(item["url"], fetch=fetch, resolve=resolve)
    if result.get("status") == "link":
        result["url"] = _safe_url(result.get("url"))

    if result["status"] == "ok":
        with db._cache() as conn:
            conn.execute(
                """INSERT INTO articles (item_id, text, fetched_at, status)
                   VALUES (?, ?, ?, 'ok')
                   ON CONFLICT(item_id) DO UPDATE SET
                     text = excluded.text, fetched_at = excluded.fetched_at, status = 'ok'""",
                (item_id, "\n".join(result["paragraphs"]), datetime.now(timezone.utc).isoformat()),
            )

    return result
