"""eBay Browse API adapter (client-credentials token). Never raises."""

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import _env
from .models import Listing, SiteResult

_API = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_token = {"value": None, "exp": 0.0}


def _http(url, headers, data=None):
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def _get_token(cid, secret):
    if _token["value"] and time.time() < _token["exp"]:
        return _token["value"]
    auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    d = _http(_TOKEN_URL, {"Authorization": f"Basic {auth}",
                           "Content-Type": "application/x-www-form-urlencoded"},
              b"grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope")
    _token.update(value=d["access_token"], exp=time.time() + int(d.get("expires_in", 7200)) - 60)
    return _token["value"]


def _web_url(query):
    return "https://www.ebay.com/sch/i.html?_nkw=" + urllib.parse.quote_plus(query)


def _filter(max_price, min_price, condition, buy_it_now):
    f = []
    if max_price is not None or min_price is not None:
        lo = "" if min_price is None else min_price
        hi = "" if max_price is None else max_price
        f += [f"price:[{lo}..{hi}]", "priceCurrency:USD"]
    if condition:
        f.append("conditions:{%s}" % condition.upper())
    if buy_it_now:
        f.append("buyingOptions:{FIXED_PRICE}")
    return ",".join(f)


def parse(data) -> list[Listing]:
    rows = []
    for it in data.get("itemSummaries", []):
        p = it.get("price") or {}
        rows.append(Listing("ebay", it.get("title", ""), float(p["value"]) if p.get("value") else None,
                            p.get("currency", "USD"), it.get("condition", ""), it.get("itemWebUrl", ""),
                            {"id": it.get("itemId"), "buying": it.get("buyingOptions", [])}))
    return rows


def search(query, max_price=None, min_price=None, condition=None, buy_it_now=False, newest=False, fetch=None) -> SiteResult:
    url = _web_url(query)
    cid, secret = _env.key("EBAY_CLIENT_ID"), _env.key("EBAY_CLIENT_SECRET")
    missing = [n for n, v in (("EBAY_CLIENT_ID", cid), ("EBAY_CLIENT_SECRET", secret)) if not v]
    if missing and fetch is None:
        return SiteResult("ebay", "no_key", [], f"{' and '.join(missing)} not set in dashboard/.env", url)
    try:
        qs = {"q": query, "limit": "50"}
        if newest:  # alerts: best-match top 50 reshuffles and would re-push old listings as new
            qs["sort"] = "newlyListed"
        flt = _filter(max_price, min_price, condition, buy_it_now)
        if flt:
            qs["filter"] = flt
        full = _API + "?" + urllib.parse.urlencode(qs, safe=":[]{},.")
        get = fetch or (lambda u: _http(u, {"Authorization": "Bearer " + _get_token(cid, secret)}))
        try:
            data = get(full)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2)  # ponytail: one fixed backoff, per spec
            data = get(full)
        return SiteResult("ebay", "ok", parse(data), "", url)
    except Exception as e:
        return SiteResult("ebay", "error", [], f"{type(e).__name__}: {e}", url)


def sold(query) -> SiteResult:
    url = _web_url(query) + "&LH_Sold=1&LH_Complete=1"
    return SiteResult("ebay_sold", "blocked", [], "eBay sold data has no free route; open the URL by hand", url)
