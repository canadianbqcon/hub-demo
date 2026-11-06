"""Amazon adapter: Keepa with a key, else headless Chrome. Never raises."""

import html as _html
import json
import re
import urllib.parse
import urllib.request

from . import _browser, _env
from .models import Listing, SiteResult

_ROOT = "https://www.amazon.com"


def _fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def _keepa(query, max_price, key, fetch):
    url = ("https://api.keepa.com/search?" +
           urllib.parse.urlencode({"key": key, "domain": 1, "type": "product", "term": query, "stats": 90}))
    shown = f"{_ROOT}/s?k=" + urllib.parse.quote_plus(query)
    rows = []
    for p in (fetch or _fetch_json)(url).get("products", []):
        st = p.get("stats") or {}
        cur = st.get("current") or []
        mn = st.get("minInInterval") or []
        # csv type 0 = Amazon price, 1 = marketplace new; -1 = none; values are cents
        price = next((cur[i] for i in (0, 1) if len(cur) > i and cur[i] > 0), None)
        low = next((mn[i][1] for i in (0, 1) if len(mn) > i and mn[i] and mn[i][1] > 0), None)  # Keepa sends null for no data
        if price is None or (max_price is not None and price / 100 > max_price):
            continue
        rows.append(Listing("amazon", p.get("title", ""), price / 100, "USD", "New",
                            f"{_ROOT}/dp/{p.get('asin')}",
                            {"low_90d": low / 100 if low else None, "asin": p.get("asin")}))
    return SiteResult("amazon", "ok", rows, "", shown)


def parse(html: str, url: str | None = None) -> SiteResult:
    if "/errors/validateCaptcha" in html:
        return SiteResult("amazon", "blocked", [], "Amazon served a captcha; open the URL by hand", url)
    blocks = re.split(r'(?=data-component-type="s-search-result")', html)[1:]
    if not blocks:
        if "No results for" in html:
            return SiteResult("amazon", "ok", [], "no results", url)
        return SiteResult("amazon", "blocked", [], "Amazon served a bot shell (no results, no captcha); open the URL by hand", url)
    rows = []
    for b in blocks:
        t = re.search(r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>', b, re.S)
        h = re.search(r'<a[^>]*href="([^"]+)"', b)
        pr = re.search(r'a-offscreen">\s*\$([\d,]+(?:\.\d+)?)', b)
        rows.append(Listing("amazon", _html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip() if t else "",
                            float(pr.group(1).replace(",", "")) if pr else None, "USD", "New",
                            _ROOT + _html.unescape(h.group(1)) if h else "", {}))
    return SiteResult("amazon", "ok", rows, "", url)


def search(query, max_price=None, fetch=None, load=None) -> SiteResult:
    url = f"{_ROOT}/s?k=" + urllib.parse.quote_plus(query)
    try:
        k = _env.key("KEEPA_KEY")
        if k:
            return _keepa(query, max_price, k, fetch)
        res = parse((load or _browser.load)(url)[0], url)
        if max_price is not None:
            res.rows = [r for r in res.rows if r.price is not None and r.price <= max_price]
        return res
    except Exception as e:
        return SiteResult("amazon", "error", [], f"{type(e).__name__}: {e}", url)
