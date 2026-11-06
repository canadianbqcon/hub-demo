"""Viewer CLI: how Claude shows something on the Hub's Viewer page.

  show <path>... [--title T] [--label L ...]   copy files in as one item (several images = versions)
  show --url URL [--title T]                   a web item, with a frame-ability hint
  uploads [--since ISO]                        what he dropped in (web uploads and loose files)

`show` prints the item's Hub link as its last line. Design: docs/specs/2026-10-26-hub-viewer-page-design.md.
"""

from __future__ import annotations

import argparse
import http.client
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from viewer import store  # noqa: E402

HUB_PORT = 5002
BUDGET = 5.0  # seconds for the whole probe
MAX_REDIRECTS = 5


def hub_hosts() -> set[str]:
    return {"localhost", "127.0.0.1", socket.gethostname().lower()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # surface the 3xx so probe() counts the hops itself


_opener = urllib.request.build_opener(_NoRedirect)


def _fetch(url: str, method: str, timeout: float):
    """(status, headers) for one request; headers are read, the body never is."""
    try:
        r = _opener.open(urllib.request.Request(url, method=method), timeout=timeout)
    except urllib.error.HTTPError as e:  # 3xx/4xx/5xx still carry headers
        r = e
    try:
        return r.status or 0, r.headers
    finally:
        r.close()


def _verdict(url: str, headers) -> bool:
    hosts = hub_hosts()
    host = (urlsplit(url).hostname or "").lower()
    xfo = (headers.get("X-Frame-Options") or "").strip().upper()
    if xfo.startswith("DENY") or (xfo.startswith("SAMEORIGIN") and host not in hosts):
        return False
    for csp in headers.get_all("Content-Security-Policy") or []:
        for directive in csp.split(";"):
            parts = directive.split()
            if not parts or parts[0].lower() != "frame-ancestors":
                continue
            ok = False
            for tok in parts[1:]:
                t = re.sub(r"^\w+://", "", tok.strip("'\"")).lower()
                if t == "*" or t in hosts or any(t == f"{h}:{HUB_PORT}" for h in hosts):
                    ok = True
            if not ok:
                return False
    return True


def probe(url: str) -> bool | None:
    """True/False when the page can/cannot be framed in the Hub, None when unknown."""
    end = time.monotonic() + BUDGET
    for method in ("HEAD", "GET"):
        cur, hops = url, 0
        try:
            while True:
                left = end - time.monotonic()
                if left <= 0:
                    return None
                status, headers = _fetch(cur, method, left)
                if status in (301, 302, 303, 307, 308) and headers.get("Location"):
                    hops += 1
                    if hops > MAX_REDIRECTS:
                        return None
                    cur = urljoin(cur, headers["Location"])
                    continue
                break
        except (OSError, ValueError, http.client.HTTPException):  # refused, timeout, DNS, bad URL, garbled reply
            return None
        if method == "HEAD" and status >= 400:
            continue  # many servers refuse HEAD (405); retry as GET
        return _verdict(cur, headers)


def _link(item_id: str) -> str:
    return f"http://localhost:{HUB_PORT}/viewer/?item={item_id}"


def _show(a, p) -> int:
    if a.url:
        if a.paths or a.label:
            p.error("--url takes no paths or labels")
        u = urlsplit(a.url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            p.error("--url must be http(s) with a host and no user:password@")
        title = a.title or u.hostname
        framable = probe(a.url)  # before staging, so nothing is left behind if it fails
        item_id, d = store.stage(title)
        item = store.commit(item_id, d, kind="web", title=title, source="Claude",
                            url=a.url, framable=framable)
    else:
        if not a.paths:
            p.error("give at least one path, or --url")
        if a.label and len(a.label) != len(a.paths):
            p.error(f"{len(a.label)} labels for {len(a.paths)} paths: give one each or none")
        for f in a.paths:
            if not f.is_file():
                p.error(f"not a file: {f}")
        item = store.publish(a.paths, title=a.title, labels=a.label or None)
    print(_link(item["id"]))
    return 0


def _uploads(a) -> int:
    for u in store.uploads(datetime.fromisoformat(a.since) if a.since else None):
        for path in u["paths"]:
            print(f"{u['created']}\t{path}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="viewer/cli.py", description=(__doc__ or "").split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="show files or a URL on the Viewer page")
    s.add_argument("paths", nargs="*", type=Path)
    s.add_argument("--url")
    s.add_argument("--title")
    s.add_argument("--label", action="append")
    u = sub.add_parser("uploads", help="list what he dropped in, with absolute paths")
    u.add_argument("--since", help="ISO date or datetime")
    a = p.parse_args(argv)
    return _show(a, s) if a.cmd == "show" else _uploads(a)


if __name__ == "__main__":
    sys.exit(main())
