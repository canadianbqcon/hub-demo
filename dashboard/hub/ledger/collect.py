#!/usr/bin/env python3
"""Nightly collector for the /ledger CS2 inventory book.

Writes snapshots into data/cs2.db and interprets nothing. Every number here is
what a source said and when it said it; the adaptive window, the outlier
verdict, the fee model and the confidence chip all live in value.py, so the
valuation basis can change and be re-run across the whole stored history
without touching the network. That separation is the point — see
docs/archive/specs/2026-08-25-ledger-hub-module-design.md.

Six sources, each in its own snapshot row and its own try block: a Waxpeer 500
marks that source ok=0 and the run continues on the sources that answered.

    python collect.py                     # full run
    python collect.py --steam-json FILE   # seed holdings from a saved inventory dump
    python collect.py --selfcheck         # outlier filter only, no network

The one Steam caveat: the public inventory endpoint rate-limits an IP hard once
it has seen a portfolio sweep, and stays 429 for a long while. --steam-json
reads a dump captured from a browser instead; without it a throttled run just
prices the holdings already on file.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import statistics
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlite_helpers import connect  # noqa: E402
from vault_path import vault_root  # noqa: E402

STEAM_ID = "76561198148470135"
STEAM_URL = f"https://steamcommunity.com/inventory/{STEAM_ID}/730/2?l=english&count=2000"
SKINPORT_SALES = "https://api.skinport.com/v1/sales/history?app_id=730&currency=USD"
SKINPORT_ITEMS = "https://api.skinport.com/v1/items?app_id=730&currency=USD"
CSFLOAT_PRICES = "https://csfloat.com/api/v1/listings/price-list"
CSFLOAT_GRAPH = "https://csfloat.com/api/v1/history/{}/graph"
WAXPEER_PRICES = "https://api.waxpeer.com/v1/prices?game=csgo&minified=0"

SALE_WINDOWS = {"last_24_hours": "24h", "last_7_days": "7d",
                "last_30_days": "30d", "last_90_days": "90d"}

# CSFloat's own docs ask for a gap between calls; 0.8s survived a 122-item sweep.
CSFLOAT_DELAY = 0.8
# Reject a daily average this many times above its own trailing median.
OUTLIER_FACTOR = 3.0
OUTLIER_LOOKBACK_DAYS = 30
# Fewer prior days than this inside the lookback and there is nothing to judge against.
OUTLIER_MIN_SAMPLE = 5


def _get(url: str, timeout: int = 120):
    """One HTTP GET as parsed JSON.

    ponytail: curl, not urllib — Skinport serves brotli and 406s on anything
    else, and the stdlib has no brotli decoder. curl links one in already.
    """
    p = subprocess.run(
        [shutil.which("curl") or "curl", "-sS", "--compressed", "--max-time", str(timeout),
         "-H", "User-Agent: Mozilla/5.0", "-H", "Accept: application/json",
         "-w", "%{http_code}", url],
        capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl failed: {p.stderr.strip()[:200]}")
    body, code = p.stdout[:-3], p.stdout[-3:]
    if code != "200":
        raise RuntimeError(f"HTTP {code}: {body.strip()[:200]}")
    return json.loads(body)


def _cents(value) -> int | None:
    """USD units (Skinport) to cents. None stays None — a missing price is not zero."""
    return None if value is None else round(float(value) * 100)


def _snapshot(conn, source: str) -> int:
    return conn.execute("INSERT INTO snapshot(source) VALUES (?)", (source,)).lastrowid


def _finish(conn, sid: int, ok: int, note: str) -> None:
    conn.execute("UPDATE snapshot SET ok=?, note=? WHERE id=?", (ok, note[:500], sid))
    conn.commit()


def _held(conn) -> set[str]:
    return {r["market_hash_name"] for r in
            conn.execute("SELECT market_hash_name FROM holding WHERE qty > 0")}


# --- sources ---------------------------------------------------------------

def collect_steam(conn, cached: Path | None) -> None:
    """Current inventory into `holding`. Names that vanish go to qty 0 rather than
    being deleted, so a sale is visible as a change instead of a hole."""
    sid = _snapshot(conn, "steam")
    try:
        inv = json.loads(cached.read_text()) if cached else _get(STEAM_URL)
        if not inv or not inv.get("assets"):
            raise RuntimeError("no assets in response (Steam throttles portfolio sweeps)")
        desc = {(d["classid"], d["instanceid"]): d for d in inv["descriptions"]}
        counts: collections.Counter = collections.Counter()
        meta = {}
        for a in inv["assets"]:
            d = desc.get((a["classid"], a["instanceid"]))
            if not d:
                continue
            counts[d["market_hash_name"]] += int(a.get("amount", 1))
            meta[d["market_hash_name"]] = d
        for name, qty in counts.items():
            d = meta[name]
            tags = {t.get("category"): t.get("localized_tag_name") for t in d.get("tags", [])}
            conn.execute(
                "INSERT INTO holding(market_hash_name, qty, tradable, marketable,"
                " item_type, rarity, exterior) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(market_hash_name) DO UPDATE SET"
                " qty=excluded.qty, last_seen=datetime('now'),"
                " tradable=excluded.tradable, marketable=excluded.marketable,"
                " item_type=excluded.item_type, rarity=excluded.rarity,"
                " exterior=excluded.exterior",
                (name, qty, int(d.get("tradable", 0)), int(d.get("marketable", 0)),
                 tags.get("Type") or "", tags.get("Rarity") or "", tags.get("Exterior") or ""))
        gone = [n for n in _held(conn) if n not in counts]
        for name in gone:
            conn.execute("UPDATE holding SET qty=0, last_seen=datetime('now')"
                         " WHERE market_hash_name=?", (name,))
        _finish(conn, sid, 1, f"{sum(counts.values())} assets, {len(counts)} unique,"
                              f" {len(gone)} no longer held")
    except Exception as exc:
        _finish(conn, sid, 0, str(exc))


def _write_prices(conn, sid: int, rows) -> int:
    """Rows are (name, source, basis, window, price_cents, volume, depth,
    low_cents, high_cents). The last two are the spread inside a sale window and
    stay NULL for listings, which have no window to take a min/max over."""
    conn.executemany(
        "INSERT OR REPLACE INTO item_price(snapshot_id, market_hash_name, source,"
        " basis, window, price_cents, volume, depth, low_cents, high_cents)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(sid, *r) for r in rows])
    return len(rows)


def collect_skinport_sales(conn, names: set[str]) -> None:
    """The backbone: real sale min/max/avg/median plus volume at four windows,
    36k items in one unauthenticated call."""
    sid = _snapshot(conn, "skinport_sales")
    try:
        rows = []
        for item in _get(SKINPORT_SALES):
            name = item["market_hash_name"]
            if name not in names:
                continue
            for key, window in SALE_WINDOWS.items():
                w = item.get(key) or {}
                if not w.get("volume"):
                    continue
                rows.append((name, "skinport", "sale", window,
                             _cents(w.get("median")), int(w["volume"]), None,
                             _cents(w.get("min")), _cents(w.get("max"))))
        _finish(conn, sid, 1, f"{_write_prices(conn, sid, rows)} rows,"
                              f" {len({r[0] for r in rows})} items")
    except Exception as exc:
        _finish(conn, sid, 0, str(exc))


def _collect_listings(conn, source: str, url: str, names: set[str], parse) -> None:
    """Listing floor + depth from a bulk venue feed. `parse` yields
    (name, price_cents, depth) so the three venues differ by one lambda."""
    sid = _snapshot(conn, source)
    try:
        payload = _get(url)
        rows = [(name, source.replace("_listings", ""), "listing", "live", cents,
                 None, depth, None, None)
                for name, cents, depth in parse(payload) if name in names]
        _finish(conn, sid, 1, f"{_write_prices(conn, sid, rows)} items")
    except Exception as exc:
        _finish(conn, sid, 0, str(exc))


def collect_skinport_listings(conn, names: set[str]) -> None:
    _collect_listings(conn, "skinport_listings", SKINPORT_ITEMS, names, lambda d: (
        (i["market_hash_name"], _cents(i.get("min_price")), i.get("quantity")) for i in d))


def collect_csfloat_listings(conn, names: set[str]) -> None:
    # CSFloat quotes cents already.
    _collect_listings(conn, "csfloat_listings", CSFLOAT_PRICES, names, lambda d: (
        (i["market_hash_name"], i.get("min_price"), i.get("quantity")) for i in d))


def collect_waxpeer_listings(conn, names: set[str]) -> None:
    # Waxpeer quotes mills (1/1000 USD): 38150 is $38.15.
    _collect_listings(conn, "waxpeer_listings", WAXPEER_PRICES, names, lambda d: (
        (i["name"], round(i["min"] / 10) if i.get("min") else None, i.get("count"))
        for i in d.get("items", [])))


# --- CSFloat daily series + the outlier filter -----------------------------

def flag_outliers(series):
    """[(day, avg_cents, count)] ascending -> same with a rejected flag appended.

    A day is rejected when its average sits above OUTLIER_FACTOR times the median
    of the *trailing 30 calendar days*. Trailing, never whole-history: CSFloat
    publishes an average rather than a median, so a 2-trade day on a cheap item
    reads 9x high — but an item that genuinely appreciated (P250 See Ya Later,
    $3 lifetime median against $99 today) would be rejected outright by a
    lifetime comparison. The rejected row is kept and drawn greyed; a filter
    that deletes its own discards cannot be checked.
    """
    out = []
    for i, (day, price, count) in enumerate(series):
        cutoff = datetime.date.fromisoformat(day) - datetime.timedelta(days=OUTLIER_LOOKBACK_DAYS)
        prior = [p for d, p, _ in series[:i] if datetime.date.fromisoformat(d) >= cutoff]
        rejected = 0
        if len(prior) >= OUTLIER_MIN_SAMPLE:
            med = statistics.median(prior)
            if med > 0 and price > OUTLIER_FACTOR * med:
                rejected = 1
        out.append((day, price, count, rejected))
    return out


def _history_targets(conn, names: set[str], share: float, cap: int) -> list[str]:
    """The holdings carrying `share` of the book by latest sale mark, biggest first.
    Per-item history is the only non-bulk call in the run, so it is spent where the
    value is; everything else still prices off the bulk sale feed."""
    ranked = conn.execute(
        "SELECT h.market_hash_name AS name, h.qty * ("
        "  SELECT p.price_cents FROM item_price p"
        "  WHERE p.market_hash_name = h.market_hash_name AND p.basis='sale'"
        "    AND p.price_cents IS NOT NULL"
        "  ORDER BY p.snapshot_id DESC, p.volume DESC LIMIT 1) AS mark"
        " FROM holding h WHERE h.qty > 0 AND h.marketable = 1"
        " ORDER BY mark DESC NULLS LAST").fetchall()
    ranked = [(r["name"], r["mark"]) for r in ranked if r["mark"] and r["name"] in names]
    total = sum(m for _, m in ranked)
    picked, running = [], 0
    for name, mark in ranked:
        picked.append(name)
        running += mark
        if total and running / total >= share:
            break
    return picked[:cap]


def collect_csfloat_history(conn, targets: list[str]) -> None:
    """Daily sale average + trade count per item, up to ~4 years deep."""
    import time
    sid = _snapshot(conn, "csfloat_history")
    got = days = failed = 0
    try:
        for name in targets:
            try:
                graph = _get(CSFLOAT_GRAPH.format(urllib.parse.quote(name)), timeout=45)
            except Exception:
                failed += 1
                time.sleep(CSFLOAT_DELAY)
                continue
            series = sorted(((g["day"][:10], round(g["avg_price"]), int(g.get("count") or 0))
                             for g in graph or []), key=lambda r: r[0])
            if series:
                conn.executemany(
                    "INSERT INTO daily_sale(market_hash_name, day, avg_price_cents,"
                    " trade_count, rejected) VALUES (?,?,?,?,?)"
                    " ON CONFLICT(market_hash_name, day) DO UPDATE SET"
                    " avg_price_cents=excluded.avg_price_cents,"
                    " trade_count=excluded.trade_count, rejected=excluded.rejected",
                    [(name, d, p, c, rej) for d, p, c, rej in flag_outliers(series)])
                conn.commit()
                got += 1
                days += len(series)
            time.sleep(CSFLOAT_DELAY)
        _finish(conn, sid, 1 if got else 0,
                f"{got}/{len(targets)} items, {days} days, {failed} failed")
    except Exception as exc:
        _finish(conn, sid, 0, f"{exc} (after {got} items)")


# --- entry point -----------------------------------------------------------

def run(steam_json: Path | None, share: float, cap: int, skip_history: bool) -> None:
    with connect(vault_root() / "data" / "cs2.db", "ledger.collect") as conn:
        collect_steam(conn, steam_json)
        names = _held(conn)
        if not names:
            print("no holdings on file and Steam gave nothing — nothing to price")
            return
        collect_skinport_sales(conn, names)
        collect_skinport_listings(conn, names)
        collect_csfloat_listings(conn, names)
        collect_waxpeer_listings(conn, names)
        if not skip_history:
            collect_csfloat_history(conn, _history_targets(conn, names, share, cap))
        for r in conn.execute("SELECT source, ok, note FROM snapshot"
                              " WHERE taken_at >= datetime('now','-1 hour')"
                              " ORDER BY id"):
            print(f"  {'ok ' if r['ok'] else 'FAIL'}  {r['source']:<18} {r['note']}")


def selfcheck() -> None:
    spike = [("2026-01-%02d" % d, 100, 5) for d in range(1, 11)]
    spike.append(("2026-01-11", 900, 2))
    flagged = flag_outliers(spike)
    assert flagged[-1][3] == 1, "a 9x day on 2 trades must be rejected"
    assert all(r[3] == 0 for r in flagged[:-1]), "flat days must survive"

    # Steady appreciation: 2% a day for 200 days never trips the trailing window,
    # though it ends far enough above its own lifetime median that a whole-history
    # comparison at the same 3x factor would reject the current price outright.
    climb = [((datetime.date(2026, 1, 1) + datetime.timedelta(days=i)).isoformat(),
              round(100 * 1.02 ** i), 8) for i in range(200)]
    assert all(r[3] == 0 for r in flag_outliers(climb)), "appreciation is not contamination"
    assert flag_outliers(climb)[-1][1] > OUTLIER_FACTOR * statistics.median(
        [p for _, p, _ in climb]), "the whole-history trap this filter avoids"

    # Too little history to judge against: nothing is rejected on day one.
    assert flag_outliers([("2026-01-01", 100, 1), ("2026-01-02", 9000, 1)])[-1][3] == 0

    # A gap longer than the lookback resets the baseline rather than comparing
    # against prices from years ago.
    stale = [("2020-01-%02d" % d, 100, 5) for d in range(1, 11)] + [("2026-01-01", 900, 5)]
    assert flag_outliers(stale)[-1][3] == 0, "an old baseline must not judge today"
    print("selfcheck ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steam-json", type=Path,
                    help="saved Steam inventory JSON, for when the endpoint is throttled")
    ap.add_argument("--history-share", type=float, default=0.95,
                    help="fraction of book value to pull per-item history for (default 0.95)")
    ap.add_argument("--history-cap", type=int, default=40,
                    help="hard ceiling on per-item history calls (default 40)")
    ap.add_argument("--no-history", action="store_true", help="skip the per-item CSFloat calls")
    ap.add_argument("--selfcheck", action="store_true", help="run the outlier-filter asserts")
    a = ap.parse_args()
    selfcheck() if a.selfcheck else run(a.steam_json, a.history_share, a.history_cap, a.no_history)
