"""Stocks Hub blueprint — routes under /stocks. Read-only watchlist + detail
view over data/stocks.db; the `/stock` skill is the only writer (see this
module's CLAUDE.md). Chrome wiring mirrors the current vanilla-page pattern
(jobs/trips/finances/checklists/vault_map/etc.): the module launcher is the
one canonical list in hub_modules.py, served to every page via the
/hub-modules.js route (app.py) — no per-page copy of the list here. No
VaultReader either — this module has no node-lookup surface to expose.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, redirect

from . import db

logger = logging.getLogger(__name__)

bp = Blueprint(
    "stocks",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/stocks",
)

# A row's analysis is stale once it's this many days old, independent of the
# next_earnings check below.
_STALE_DAYS = 30


@bp.route("/")
def index():
    # stocks now lives as a tab inside the finances umbrella (/finances#stocks).
    # This blueprint keeps serving the /stocks/api/* data the finances page reads;
    # the standalone page route just forwards to its new home so old links work.
    return redirect("/finances/#stocks", code=302)


# ── Watchlist (live price refresh) ────────────────────────────────────────────


def _fetch_prices(tickers: list[str]) -> tuple[dict[str, float], bool]:
    """One batched yfinance call for every ticker on the watchlist — never one
    request per ticker. Returns (ticker -> last close, fetch_failed); on any
    failure the dict is empty and fetch_failed is True, so callers fall back
    to each row's own latest_price and flag it stale."""
    if not tickers:
        return {}, False
    try:
        import yfinance as yf

        data = yf.download(" ".join(tickers), period="1d", progress=False, group_by="ticker")
        if data is None or data.empty:
            logger.warning("yfinance returned no rows for %d ticker(s)", len(tickers))
            return {}, True
        prices: dict[str, float] = {}
        for t in tickers:
            try:
                # pandas-stubs types this __getitem__ chain as possibly-ndarray, which
                # has no .dropna(); at runtime yfinance always hands back a Series here.
                close = data[t]["Close"].dropna()  # type: ignore[union-attr]
                prices[t] = float(close.iloc[-1])
            except Exception:
                # This ticker's close wasn't in the batch response. Callers fall back
                # to latest_price and flag price_stale, so it is not fatal — but it is
                # logged, because a silent skip hides a broken batch fetch entirely.
                logger.debug("no close price in batch response for %s", t, exc_info=True)
        return prices, False
    except Exception:
        logger.exception("batched price fetch failed")
        return {}, True


# The batched yfinance call above is a live round trip to Yahoo and it was costing
# 2.5 s on EVERY load of the finances page — the single slowest thing on the Hub, paid
# by the reader while the panel sat empty. Prices are served from this cache instead and
# the refresh happens off the request: a visit never waits on Yahoo, it just gets prices
# that are at most _PRICE_TTL old. Before the first successful fetch the cache is empty,
# which is the path that already existed — each row falls back to its stored
# latest_price and renders with the `*` stale marker until the refresh lands.
# ponytail: one module-level tuple and a non-blocking lock, no eviction — there is one
# watchlist. Swap for a scheduled refresher if the page ever wants sub-minute prices.
_PRICE_TTL = 300
_price_cache: tuple[float, dict[str, float], bool] | None = None
_price_lock = threading.Lock()


def _cached_prices(tickers: list[str]) -> tuple[dict[str, float], bool]:
    """Last known prices now; a refresh in the background if they have aged out."""
    global _price_cache
    cached = _price_cache
    if not cached or time.monotonic() - cached[0] >= _PRICE_TTL:
        if _price_lock.acquire(blocking=False):
            threading.Thread(target=_refresh_prices, args=(tickers,), daemon=True).start()
    return (cached[1], cached[2]) if cached else ({}, True)


def _refresh_prices(tickers: list[str]) -> None:
    global _price_cache
    try:
        prices, failed = _fetch_prices(tickers)
        if not failed:
            _price_cache = (time.monotonic(), prices, failed)
    finally:
        _price_lock.release()


def _distance_to_entry_pct(current: float | None, entry: float | None) -> float | None:
    """% distance of the current price from the analysis's trade entry price.
    None when either side is missing (no entry called, or no live/last price)."""
    if not current or not entry:
        return None
    return round((current / entry - 1) * 100, 2)


def _is_stale(last_analyzed: str | None, next_earnings: str | None, now: datetime) -> bool:
    """A row is stale once its last analysis is _STALE_DAYS+ old, OR its
    next_earnings (a unix-timestamp string on the latest analysis) has
    already passed — either way the game plan predates known-changed facts."""
    if last_analyzed:
        try:
            last_dt = datetime.fromisoformat(last_analyzed.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            if (now - last_dt).days >= _STALE_DAYS:
                return True
        except ValueError:
            pass
    if next_earnings:
        try:
            earnings_dt = datetime.fromtimestamp(float(next_earnings), tz=timezone.utc)
            if earnings_dt < now:
                return True
        except (TypeError, ValueError):
            pass  # next_earnings wasn't a parseable unix timestamp
    return False


def _watchlist() -> list[dict]:
    rows = db.list_stocks()
    prices, price_fetch_failed = _cached_prices([r["ticker"] for r in rows])
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        r = dict(r)
        cur = prices.get(r["ticker"])
        r["price_stale"] = price_fetch_failed or cur is None
        if cur is None:
            cur = r.get("latest_price")
        r["current_price"] = cur
        r["distance_to_entry_pct"] = _distance_to_entry_pct(cur, r.get("trade_entry_num"))
        r["stale"] = _is_stale(r.get("last_analyzed"), r.get("next_earnings"), now)
        out.append(r)
    return out


@bp.route("/api/stocks")
def api_stocks():
    return jsonify(_watchlist())


@bp.route("/api/stocks/<ticker>")
def api_stock(ticker):
    row = db.get_stock(ticker.upper())
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)
