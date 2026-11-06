"""Store search backends (Constructor.io, Algolia, Searchspring, Bloomreach) plus discovery."""

import json
import os
import pathlib
import re
import urllib.error
import urllib.parse as up
import urllib.request

from . import _browser
from .models import Listing, SiteResult

REGISTRY = pathlib.Path(__file__).with_name("stores.json")
HOSTS = ("cnstrc.com", "algolia.net", "algolianet.com", "searchspring.io", "dxpapi.com")
UA = {"User-Agent": "Mozilla/5.0"}


def _fetch(url, headers=None, body=None):
    req = urllib.request.Request(url, data=body, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _price(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v)  # pyright: ignore[reportArgumentType]  None is caught by the except TypeError below
    except (TypeError, ValueError):
        return None


def _on(host, domain):
    return host == domain or host.endswith("." + domain)


def _safe(*vals):
    """Discovered ids go into hostnames and paths; a page could plant anything there."""
    return all(v and re.fullmatch(r"[A-Za-z0-9_.-]+", v) for v in vals)


def _q(**kw):
    return up.urlencode(kw)


def _constructor(p, q, fetch):
    d = fetch(f"https://ac.cnstrc.com/search/{up.quote(q, safe='')}?" + _q(key=p["key"], num_results_per_page=40))
    return [(r.get("value"), r["data"].get("price_min"), r["data"].get("url"))
            for r in d["response"]["results"]]


def _algolia(p, q, fetch):
    url = f"https://{p['app_id']}-dsn.algolia.net/1/indexes/{up.quote(p['index'], safe='')}/query"
    hdr = {"X-Algolia-Application-Id": p["app_id"], "X-Algolia-API-Key": p["key"],
           "Content-Type": "application/json"}
    d = fetch(url, hdr, json.dumps({"params": _q(query=q, hitsPerPage=40)}).encode())
    return [(h.get("name") or h.get("title"), h.get("price"), h.get("url")) for h in d["hits"]]


def _searchspring(p, q, fetch):
    d = fetch(f"https://{p['site_id']}.a.searchspring.io/api/search/search.json?"
              + _q(siteId=p["site_id"], q=q, resultsPerPage=40))
    return [(r.get("name"), r.get("price"), r.get("url")) for r in d["results"]]


def _bloomreach(p, q, fetch):
    d = fetch("https://core.dxpapi.com/api/v1/core/?" + _q(
        account_id=p["account_id"], domain_key=p["domain_key"], request_type="search",
        search_type="keyword", q=q, fl="pid,title,price,sale_price,url", rows=40, start=0,
        url="", ref_url="", request_id="0"))
    return [(x.get("title"), x.get("sale_price", x.get("price")), x.get("url"))
            for x in d["response"]["docs"]]


BACKENDS = {"constructor": _constructor, "algolia": _algolia,
            "searchspring": _searchspring, "bloomreach": _bloomreach}


def _load():
    return json.loads(REGISTRY.read_text())


def names() -> list[str]:
    return sorted(_load())


def search(store, query, max_price=None, fetch=None) -> SiteResult:
    entry = _load().get(store)
    if not entry:
        return SiteResult(store, "error", [], f"unknown store {store}; run discover {store} <search url with ?q=>")
    if entry["backend"] == "headless":
        url = entry["params"]["search_url"]
        return SiteResult(store, "blocked", [], "no search API found; open the page by hand", url)
    try:
        raw = BACKENDS[entry["backend"]](entry["params"], query, fetch or _fetch)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return SiteResult(store, "error", [], f"HTTP {e.code}: key rotated? re-run discover {store} <search url>")
        return SiteResult(store, "error", [], f"HTTP {e.code}")
    except Exception as e:  # never raise out of an adapter
        return SiteResult(store, "error", [], f"{type(e).__name__}: {e}")
    rows = []
    for title, price, url in raw:
        price = _price(price)
        if not title or (max_price is not None and (price is None or price > max_price)):
            continue
        rows.append(Listing(store, title, price, "USD", "new", url or "", {}))
    rows.sort(key=lambda r: (r.price is None, r.price))
    return SiteResult(store, "ok", rows, f"{len(rows)} results")


def extract(request_urls, headers=None) -> dict | None:
    """First recognised backend in captured request URLs. Algolia credentials are read from
    query params or from `headers`; header-only credentials are invisible to _browser.load,
    which captures URLs only, so those stores fall back to headless."""
    h = {k.lower(): v for k, v in (headers or {}).items()}
    for u in request_urls:
        pu = up.urlparse(u)
        qs = {k.lower(): v[0] for k, v in up.parse_qs(pu.query).items()}
        host = pu.hostname or ""
        if _on(host, "cnstrc.com") and qs.get("key"):
            return {"backend": "constructor", "params": {"key": qs["key"]}}
        if _on(host, "algolia.net") or _on(host, "algolianet.com"):
            app = qs.get("x-algolia-application-id") or h.get("x-algolia-application-id") \
                or host.split("-dsn")[0].split(".")[0].upper()
            key = qs.get("x-algolia-api-key") or h.get("x-algolia-api-key")
            parts = pu.path.split("/")
            idx = up.unquote(parts[3]) if len(parts) > 3 and parts[2] == "indexes" else None
            if _safe(app, idx) and key and idx != "*":
                return {"backend": "algolia", "params": {"app_id": app, "key": key, "index": idx}}
        if _on(host, "searchspring.io"):
            site = qs.get("siteid") or host.split(".")[0]
            if _safe(site):
                return {"backend": "searchspring", "params": {"site_id": site}}
        if _on(host, "dxpapi.com") and _safe(qs.get("account_id"), qs.get("domain_key")):
            return {"backend": "bloomreach",
                    "params": {"account_id": qs["account_id"], "domain_key": qs["domain_key"]}}
    return None


def discover(store, search_url, load=None) -> dict:
    if not up.urlparse(search_url).query:
        raise ValueError("search_url needs a query string, e.g. https://store.com/search?q=jacket")
    # wait_for="body": busy storefronts never reach networkidle, so the default wait times out
    _, urls = (load or _browser.load)(search_url, wait_for="body", capture_hosts=HOSTS)
    entry = extract(urls) or {"backend": "headless", "params": {"search_url": search_url}}
    reg = _load()
    reg[store] = entry
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2) + "\n")
    os.replace(tmp, REGISTRY)  # atomic: the alert job may be reading it
    return entry
