"""Reddit search: ScrapeCreators when keyed, else the Arctic Shift archive."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from . import _env
from .models import Comment, Post, SiteResult, terms

ARCTIC = "https://arctic-shift.photon-reddit.com/api"
SCRAPECREATORS = "https://api.scrapecreators.com/v1/reddit/search"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")  # Arctic Shift 403s urllib's UA
SPACING = 3.0  # seconds between requests; tests patch to 0
BACKOFF = 15.0  # base retry wait; Arctic 422 is a server-side query timeout ("slow down"), 5s was too short; tests patch to 0
_lock = threading.Lock()
_last = 0.0


class HTTPFail(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


def _fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise HTTPFail(e.code) from None


def _get(url, fetch, headers=None):
    """Spaced, retried GET. Returns parsed JSON; raises HTTPFail or OSError after the retries."""
    global _last
    fetch = fetch or _fetch
    last = None
    for i in range(3):
        with _lock:
            wait = _last + SPACING - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return fetch(url, headers) if headers else fetch(url)
            except HTTPFail as e:
                last = e
            finally:
                _last = time.monotonic()
        if last.status not in (422, 429) or i == 2:
            break
        time.sleep(BACKOFF * (i + 1))
    raise last  # pyright: ignore[reportGeneralTypeIssues]  loop always runs once, so last is set


def _date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else ""


def _err(site, e, url=None):
    return SiteResult(site, "error", [], str(e), url)


def _post(p, site):
    link = p.get("permalink") or ""
    return Post(site, p.get("subreddit") or "", p.get("title") or "", p.get("selftext") or "",
                p.get("score") or 0, p.get("num_comments") or 0, _date(p.get("created_utc")),
                "https://www.reddit.com" + link if link.startswith("/") else (p.get("url") or link),
                p.get("id") or "")


def search(query, subreddit=None, fetch=None):
    key = _env.key("SCRAPECREATORS_API_KEY")
    if key:
        q = f"{query} subreddit:{subreddit}" if subreddit else query
        url = SCRAPECREATORS + "?" + urllib.parse.urlencode(
            {"query": q, "filter": "posts", "sort": "top", "timeframe": "all"})
        try:
            data = _get(url, fetch, {"x-api-key": key})
        except Exception as e:
            return _err("reddit", e, url)
        return SiteResult("reddit", "ok", [_post(p, "reddit") for p in data.get("posts") or []], "", url)
    if not subreddit:
        return SiteResult("reddit", "error", [], "Arctic Shift posts/search needs a subreddit "
                          "(use reddit:<sub>), or set SCRAPECREATORS_API_KEY in dashboard/.env")
    sub = subreddit.removeprefix("r/")
    url = ARCTIC + "/posts/search?" + urllib.parse.urlencode(
        {"subreddit": sub, "query": query, "limit": 100})
    try:
        data = _get(url, fetch)
    except Exception as e:
        return _err("reddit", e, url)
    want = terms(query)
    posts = []
    for p in data.get("data") or []:
        hay = terms((p.get("title") or "") + " " + (p.get("selftext") or ""))
        if all(t in hay for t in want):
            posts.append(_post(p, "reddit"))
    posts.sort(key=lambda p: p.score + 2 * p.num_comments, reverse=True)
    return SiteResult("reddit", "ok", posts, "", url)


def comments(post_id, fetch=None):
    url = ARCTIC + "/comments/search?" + urllib.parse.urlencode(
        {"link_id": post_id, "limit": 100})
    try:
        data = _get(url, fetch).get("data") or []
    except Exception as e:
        return _err("reddit", e, url)
    parent = {c["id"]: c.get("parent_id") or "" for c in data if c.get("id")}

    def depth(cid):  # parent_id is t3_<post> at the top, t1_<comment> below
        d, p = 0, parent.get(cid, "")
        while p.startswith("t1_") and p[3:] in parent and d < 50:
            d, p = d + 1, parent[p[3:]]
        return d

    rows = []
    for c in data:
        body = c.get("body") or ""
        if not body or body in ("[deleted]", "[removed]"):
            continue
        link = c.get("permalink") or ""
        rows.append(Comment(post_id, body, c.get("score") or 0, depth(c.get("id")),
                            _date(c.get("created_utc")),
                            "https://www.reddit.com" + link if link else ""))
    rows.sort(key=lambda c: c.score, reverse=True)
    return SiteResult("reddit", "ok", rows, "", url)
