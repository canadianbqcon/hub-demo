#!/usr/bin/env python3
"""The valuation engine: a pure function over what collect.py stored.

Nothing here touches the network. Everything is derived from `item_price`,
`holding` and `daily_sale`, which is what lets the basis change and be re-run
across the whole stored history — the methodology took two adversarial reviews
and will take more, and re-pricing must not mean re-fetching.

The one thing this module exists to prevent: a number without the basis that
produced it. The same inventory prices $810 to $1,400 across defensible
statistics, so every figure below travels with its window, its trade count and
its confidence.

    python value.py              # print the book
    python value.py --selfcheck  # asserts, no database
"""

from __future__ import annotations

import argparse
import datetime
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlite_helpers import connect  # noqa: E402
from vault_path import vault_root  # noqa: E402

# Shortest first. The adaptive window is the first one deep enough to trust.
WINDOW_ORDER = ("24h", "7d", "30d", "90d")
# Both reviewers rejected a fixed 30-day window: at 7,401 trades/month it throws
# away price discovery, and at 16 trades/month it lags a Valve patch by weeks.
DEPTH_TARGET = 30
# A window this short with DEPTH_TARGET behind it is a real price, not an estimate.
SOLID_WINDOWS = ("24h", "7d")

# Seller fee per venue. Only the three with free bulk feeds are routable here;
# Buff163 (2.5%) is login-gated and Steam (15%) is not a cash-out.
FEES = {"csfloat": 0.02, "waxpeer": 0.06, "skinport": 0.12}
# Skinport halves its fee above EUR1000. Nothing in this book is close, but the
# rule is cheap to honour and wrong the moment a knife appreciates into it.
SKINPORT_HIGH_VALUE_CENTS = 100_000
SKINPORT_HIGH_VALUE_FEE = 0.06
# Withdrawal + payment processor + FX, on top of the seller fee. Never folded
# into it: "net after fee" is not cash in hand.
FRICTION = (0.02, 0.05)

TREND_SMOOTH_DAYS = 7


def _fee(source: str, price_cents: int | None) -> float:
    if source == "skinport" and price_cents and price_cents >= SKINPORT_HIGH_VALUE_CENTS:
        return SKINPORT_HIGH_VALUE_FEE
    return FEES.get(source, 0.0)


# --- reading the store -----------------------------------------------------

def _latest_ok(conn, source: str, offset: int = 0) -> int | None:
    """The id of the `offset`-th most recent successful run of one source."""
    r = conn.execute(
        "SELECT id FROM snapshot WHERE source=? AND ok=1"
        " ORDER BY id DESC LIMIT 1 OFFSET ?", (source, offset)).fetchone()
    return r["id"] if r else None


def _sales(conn, snapshot_id: int) -> dict:
    out: dict = {}
    for r in conn.execute(
            "SELECT market_hash_name, window, price_cents, volume FROM item_price"
            " WHERE snapshot_id=? AND basis='sale'", (snapshot_id,)):
        out.setdefault(r["market_hash_name"], {})[r["window"]] = (
            r["price_cents"], r["volume"] or 0)
    return out


def _listings(conn) -> dict:
    """Latest listing floor + depth per (item, venue), each venue from its own
    most recent successful run — a venue that failed today keeps yesterday's
    board rather than vanishing from it."""
    out: dict = {}
    for source in ("skinport", "csfloat", "waxpeer"):
        sid = _latest_ok(conn, f"{source}_listings")
        if sid is None:
            continue
        for r in conn.execute(
                "SELECT market_hash_name, price_cents, depth FROM item_price"
                " WHERE snapshot_id=? AND basis='listing'", (sid,)):
            out.setdefault(r["market_hash_name"], {})[source] = (
                r["price_cents"], r["depth"])
    return out


def _carried_mark(conn, name: str, before_id: int) -> tuple[int, str] | None:
    """The most recent sale price this item ever had, for an item that has not
    traded inside any window. Stale carries its last mark; it is never zeroed."""
    r = conn.execute(
        "SELECT p.price_cents, s.taken_at FROM item_price p JOIN snapshot s ON s.id=p.snapshot_id"
        " WHERE p.market_hash_name=? AND p.basis='sale' AND p.price_cents IS NOT NULL"
        "   AND p.snapshot_id <= ?"
        " ORDER BY p.snapshot_id DESC LIMIT 1", (name, before_id)).fetchone()
    return (r["price_cents"], r["taken_at"][:10]) if r else None


# --- the per-item verdict --------------------------------------------------

def price_item(windows: dict) -> tuple[str | None, int | None, int]:
    """Pick the adaptive window: the SHORTEST one carrying DEPTH_TARGET trades.

    Falls through to the deepest window that priced at all when none qualifies,
    which is how the 59 thin items get a number instead of a hole. Returns
    (window, price_cents, volume); window is None when nothing traded.
    """
    priced = [(w, *windows[w]) for w in WINDOW_ORDER
              if w in windows and windows[w][0] is not None]
    if not priced:
        return None, None, 0
    for window, price, volume in priced:
        if volume >= DEPTH_TARGET:
            return window, price, volume
    return max(priced, key=lambda r: r[2])


def confidence(window: str | None, volume: int, marketable: bool, carried: bool) -> str:
    """The chip. Computed, never decorative, and never suppressed for compactness:
    a $252.34 row with `thin` and a depth of 16 is telling the truth about a knife,
    and the same row without the chip is not."""
    if not marketable:
        return "n/a"
    if carried or window is None:
        return "stale"
    if window in SOLID_WINDOWS and volume >= DEPTH_TARGET:
        return "solid"
    return "thin"


def _routes(name: str, listings: dict) -> list[dict]:
    """Every venue that could actually ticket this item, ranked by net.

    Nothing is averaged across venues — a blended price exists on zero
    exchanges. The floor is what you would have to meet to clear, so the net
    column is the only one that ranks.
    """
    out = []
    for source, (floor, depth) in sorted(listings.get(name, {}).items()):
        if not floor:
            continue
        fee = _fee(source, floor)
        out.append({"venue": source, "floor_cents": floor, "depth": depth,
                    "fee": fee, "net_cents": round(floor * (1 - fee))})
    return sorted(out, key=lambda r: -r["net_cents"])


# --- trend, from the real daily series only --------------------------------

def _trends(conn, names) -> dict:
    """30d and 90d price change per item, from `daily_sale` and nothing else.

    Deliberately blank for items with no stored series rather than falling back
    to a 30d-vs-90d median comparison. That fallback would be a different
    quantity in the same column, which is exactly the dishonesty the confidence
    chip exists to prevent. Per-item history covers 95% of the book by value,
    so the rows that carry the money all carry a trend.
    """
    series: dict = {}
    for r in conn.execute(
            "SELECT market_hash_name, day, avg_price_cents FROM daily_sale"
            " WHERE rejected=0 ORDER BY day"):
        if r["market_hash_name"] in names:
            series.setdefault(r["market_hash_name"], []).append(
                (r["day"], r["avg_price_cents"]))

    def band(rows, end_day, days):
        lo = (end_day - datetime.timedelta(days=days)).isoformat()
        hi = (end_day - datetime.timedelta(days=days - TREND_SMOOTH_DAYS)).isoformat()
        vals = [p for d, p in rows if lo <= d <= hi]
        return statistics.median(vals) if vals else None

    out: dict = {}
    for name, rows in series.items():
        end = datetime.date.fromisoformat(rows[-1][0])
        now = band(rows, end, TREND_SMOOTH_DAYS - 1)
        out[name] = {}
        for days in (30, 90):
            then = band(rows, end, days)
            out[name][f"d{days}"] = (
                round((now / then - 1) * 100, 1) if now and then else None)
    return out


# --- the book --------------------------------------------------------------

def book(conn, offset: int = 0) -> dict:
    """The whole marketable-inventory mark, priced off the `offset`-th most
    recent sale snapshot. offset=1 is what the change figure compares against."""
    sale_sid = _latest_ok(conn, "skinport_sales", offset)
    if sale_sid is None:
        return {"rows": [], "mark_cents": 0, "taken_at": None}
    taken_at = conn.execute("SELECT taken_at FROM snapshot WHERE id=?",
                            (sale_sid,)).fetchone()["taken_at"]
    sales = _sales(conn, sale_sid)
    listings = _listings(conn)
    holdings = conn.execute(
        "SELECT * FROM holding WHERE qty > 0 ORDER BY market_hash_name").fetchall()
    trends = _trends(conn, {h["market_hash_name"] for h in holdings})

    rows = []
    for h in holdings:
        name = h["market_hash_name"]
        window, price, volume = price_item(sales.get(name, {}))
        carried_on = None
        if price is None and h["marketable"]:
            carried = _carried_mark(conn, name, sale_sid)
            if carried:
                price, carried_on = carried
        chip = confidence(window, volume, bool(h["marketable"]), carried_on is not None)
        depth30 = (sales.get(name, {}).get("30d") or (None, 0))[1]
        routes = _routes(name, listings)
        rows.append({
            "name": name, "qty": h["qty"], "type": h["item_type"],
            "exterior": h["exterior"], "rarity": h["rarity"],
            "marketable": bool(h["marketable"]),
            "window": window, "unit_cents": price, "volume": volume,
            "depth_30d": depth30, "confidence": chip, "carried_on": carried_on,
            "mark_cents": (price or 0) * h["qty"] if h["marketable"] else 0,
            "trend_30d": trends.get(name, {}).get("d30"),
            "trend_90d": trends.get(name, {}).get("d90"),
            "routes": routes,
            "best_route": routes[0]["venue"] if routes else None,
            "windows": {w: sales.get(name, {}).get(w) for w in WINDOW_ORDER},
        })
    rows.sort(key=lambda r: -r["mark_cents"])
    priced = [r for r in rows if r["marketable"] and r["unit_cents"]]

    return {
        "taken_at": taken_at,
        "snapshot_id": sale_sid,
        "rows": rows,
        "mark_cents": sum(r["mark_cents"] for r in rows),
        "priced_items": len(priced),
        "total_items": sum(1 for r in rows if r["marketable"]),
        "unmarketable_items": sum(1 for r in rows if not r["marketable"]),
        "window_mix": {w: sum(1 for r in priced if r["window"] == w) for w in WINDOW_ORDER},
        "noise_band_cents": noise_band(rows),
        "executable": executable_range(rows, listings),
        "concentration": concentration(rows),
    }


def noise_band(rows) -> int:
    """How much the mark moves from nothing but which window it landed on.

    Each item's windows disagree by some amount; half that spread is what its
    contribution to the mark could shift without a single trade changing hands.
    Combined in quadrature rather than summed, because the windows do not all
    shift the same way on the same day and a straight sum would make the band so
    wide it could never be cleared.

    This is the number the change figure has to beat before it is allowed to
    call a move real. Sampling error on the mark is only about ±$3 — the
    uncertainty that matters here is model choice, not sample size.
    """
    total = 0.0
    for r in rows:
        vals = [v[0] for v in r["windows"].values() if v and v[0] is not None]
        if len(vals) < 2:
            continue
        total += ((max(vals) - min(vals)) / 2 * r["qty"]) ** 2
    return round(math.sqrt(total))


def executable_range(rows, listings) -> dict:
    """Conservative to optimistic net cash, batched to one venue.

    Batching is the default because routing per item means three balances, three
    withdrawal fees and three counterparty exposures, and that friction usually
    eats the theoretical gain. Both ends are net of the seller fee AND of
    withdrawal/processor/FX friction, which stay two separate lines everywhere
    they are shown. No midpoint is reported — the spread IS the answer.

    Each end takes the WORSE (resp. better) of the venue's listing floor and the
    item's own sale mark, rather than assuming the floor is always the pessimistic
    one. On this book it is not: Waxpeer's floors sit ~9% above what things
    actually sell for, so "list at the floor" there is the optimistic case, and
    hard-coding floor-as-conservative produced a low end above its own high end.

    Venues are ranked by net RATE, not by total, because coverage differs — Waxpeer
    lists 95 of the 109 marketable items and Skinport 109, so comparing absolute
    totals would reward the venue for the items it cannot ticket at all. What that
    venue cannot sell is reported as `uncovered_mark_cents` rather than being
    quietly folded in.
    """
    best = None
    for venue in FEES:
        low_gross = high_gross = covered_mark = uncovered = 0
        covered = 0
        for r in rows:
            if not r["marketable"] or not r["unit_cents"]:
                continue
            floor, _ = (listings.get(r["name"], {}).get(venue) or (None, None))
            if not floor:
                uncovered += r["mark_cents"]
                continue
            covered += 1
            mark = r["unit_cents"]
            low_gross += min(floor, mark) * r["qty"] * (1 - _fee(venue, min(floor, mark)))
            high_gross += max(floor, mark) * r["qty"] * (1 - _fee(venue, max(floor, mark)))
            covered_mark += mark * r["qty"]
        if not covered_mark:
            continue
        low = low_gross * (1 - FRICTION[1])
        high = high_gross * (1 - FRICTION[0])
        rate = low / covered_mark
        if best is None or rate > best["rate"]:
            best = {"venue": venue, "covered": covered, "rate": rate,
                    "covered_mark_cents": round(covered_mark),
                    "uncovered_mark_cents": round(uncovered),
                    "seller_fee_pct": FEES[venue] * 100,
                    "friction_pct": [FRICTION[0] * 100, FRICTION[1] * 100],
                    "low_cents": round(low), "high_cents": round(high)}
    return best or {}


def concentration(rows) -> dict:
    """Top five as a share of the book. 56% at last count, which is the fact the
    hairline rule under row five is there to state without a paragraph."""
    marks = [r["mark_cents"] for r in rows if r["marketable"]]
    total = sum(marks)
    return {"top5_cents": sum(marks[:5]),
            "top5_share": round(sum(marks[:5]) / total * 100, 1) if total else 0}


def change(conn) -> dict:
    """This mark against the previous snapshot's, with a verdict.

    The page must be willing to print "not distinguishable from marking noise",
    and this is what makes it willing: a daily diff of a rolling median
    manufactures performance out of window churn, so the move has to clear the
    band before it is called real.
    """
    now, prev = book(conn), book(conn, offset=1)
    if not prev["rows"]:
        return {"verdict": "first snapshot", "delta_cents": None}
    delta = now["mark_cents"] - prev["mark_cents"]
    band = max(now["noise_band_cents"], prev["noise_band_cents"])
    return {
        "delta_cents": delta, "band_cents": band,
        "prev_taken_at": prev["taken_at"], "prev_mark_cents": prev["mark_cents"],
        "verdict": "real move" if abs(delta) > band else "not distinguishable from marking noise",
    }


def item(conn, name: str) -> dict | None:
    """Everything the item page needs to defend one mark.

    Four blocks in the order a doubt arrives: the working behind the chosen
    window, the daily history including the days the filter threw out, the venue
    board, and the float block that renders its own absence.
    """
    h = conn.execute("SELECT * FROM holding WHERE market_hash_name=?", (name,)).fetchone()
    if h is None:
        return None
    sale_sid = _latest_ok(conn, "skinport_sales")
    windows = _sales(conn, sale_sid).get(name, {}) if sale_sid else {}
    spread = {}
    if sale_sid:
        for r in conn.execute(
                "SELECT window, low_cents, high_cents FROM item_price"
                " WHERE snapshot_id=? AND market_hash_name=? AND basis='sale'",
                (sale_sid, name)):
            spread[r["window"]] = (r["low_cents"], r["high_cents"])
    chosen, price, volume = price_item(windows)

    working = []
    for w in WINDOW_ORDER:
        med, vol = windows.get(w, (None, 0))
        low, high = spread.get(w, (None, None))
        working.append({"window": w, "median_cents": med, "volume": vol,
                        "low_cents": low, "high_cents": high, "chosen": w == chosen})

    return {
        "name": name, "qty": h["qty"], "item_type": h["item_type"],
        "rarity": h["rarity"], "exterior": h["exterior"],
        "marketable": bool(h["marketable"]),
        "float_value": h["float_value"], "paint_seed": h["paint_seed"],
        "window": chosen, "unit_cents": price, "volume": volume,
        "mark_cents": (price or 0) * h["qty"] if h["marketable"] else 0,
        "confidence": confidence(chosen, volume, bool(h["marketable"]), False),
        "working": working,
        "history": history(conn, name),
        "board": venue_board(conn, name, windows),
    }


def history(conn, name: str) -> list[dict]:
    """The stored daily series, rejected days included and labelled with WHY.

    Kept, not deleted, and drawn greyed on the page: a filter that hides its own
    discards cannot be checked by the person relying on it, and the discards are
    exactly where a $23.52 seven-cent item would have shown up.
    """
    rows = [(r["day"], r["avg_price_cents"], r["trade_count"], r["rejected"])
            for r in conn.execute(
                "SELECT day, avg_price_cents, trade_count, rejected FROM daily_sale"
                " WHERE market_hash_name=? ORDER BY day", (name,))]
    out = []
    for i, (day, price, count, rejected) in enumerate(rows):
        reason = None
        if rejected:
            cutoff = (datetime.date.fromisoformat(day)
                      - datetime.timedelta(days=30)).isoformat()
            prior = [p for d, p, _, _ in rows[:i] if d >= cutoff]
            if prior:
                med = statistics.median(prior)
                reason = (f"${price / 100:,.2f} against a ${med / 100:,.2f} trailing "
                          f"30-day median, on {count} trade{'s' if count != 1 else ''}")
        out.append({"day": day, "price_cents": price, "trades": count,
                    "rejected": bool(rejected), "reason": reason})
    return out


def venue_board(conn, name: str, windows: dict) -> list[dict]:
    """Per venue: listing floor, depth, fee, net. Nothing is averaged across them.

    Sale median and volume come from Skinport's sales feed and are attributed to
    Skinport alone rather than being spread across the row, because they are
    Skinport's trades. CSFloat and Waxpeer expose listings only on a free feed,
    and pretending otherwise would be the venue blending this board exists to
    refuse.
    """
    listings = _listings(conn).get(name, {})
    med, vol = (windows.get("30d") or (None, 0))
    out = []
    for venue in FEES:
        floor, depth = listings.get(venue, (None, None))
        fee = _fee(venue, floor)
        out.append({
            "venue": venue, "floor_cents": floor, "depth": depth, "fee_pct": fee * 100,
            "net_cents": round(floor * (1 - fee)) if floor else None,
            "sale_median_cents": med if venue == "skinport" else None,
            "sale_volume": vol if venue == "skinport" else None,
        })
    return sorted(out, key=lambda r: (r["net_cents"] is None, -(r["net_cents"] or 0)))


def _usd(cents) -> str:
    return "—" if cents is None else f"${cents / 100:,.2f}"


def selfcheck() -> None:
    # The adaptive window takes the shortest window that is deep enough...
    assert price_item({"24h": (100, 5), "7d": (110, 40), "30d": (120, 900)}) == ("7d", 110, 40)
    # ...and 24h wins outright when 24h is already deep.
    assert price_item({"24h": (100, 50), "7d": (110, 400)}) == ("24h", 100, 50)
    # Nothing deep enough: fall through to the deepest window that priced at all,
    # which is how a 16-trade-a-month knife gets a number instead of a hole.
    assert price_item({"24h": (100, 1), "90d": (120, 16)}) == ("90d", 120, 16)
    assert price_item({}) == (None, None, 0)
    # A null price is not a zero price.
    assert price_item({"24h": (None, 0), "30d": (250, 31)}) == ("30d", 250, 31)

    assert confidence("7d", 40, True, False) == "solid"
    assert confidence("7d", 12, True, False) == "thin", "a short window on 12 trades is not solid"
    assert confidence("30d", 900, True, False) == "thin", "depth cannot promote a stretched window"
    assert confidence(None, 0, True, True) == "stale"
    assert confidence("7d", 400, False, False) == "n/a", "untradable outranks everything"

    # Quadrature, not a straight sum: two items disagreeing by $2 each do not
    # add up to a $2 band on the pair.
    rows = [{"qty": 1, "windows": {"24h": (100, 1), "90d": (300, 9)}},
            {"qty": 1, "windows": {"24h": (100, 1), "90d": (300, 9)}}]
    assert noise_band(rows) == round(math.sqrt(2) * 100)
    # One window means nothing to disagree with, so it contributes no band.
    assert noise_band([{"qty": 9, "windows": {"30d": (500, 40)}}]) == 0

    # A venue whose floor sits ABOVE the mark must not produce a low end above
    # its own high end — the inversion that floor-is-always-conservative caused.
    rows = [{"marketable": True, "unit_cents": 1000, "qty": 1, "mark_cents": 1000,
             "name": "x"}]
    e = executable_range(rows, {"x": {"waxpeer": (1200, 9)}})
    assert e["low_cents"] < e["high_cents"], "conservative end must stay below optimistic"
    assert e["low_cents"] == round(1000 * 0.94 * 0.95)
    assert e["high_cents"] == round(1200 * 0.94 * 0.98)
    # Value a venue cannot ticket is reported, never folded into its total.
    rows.append({"marketable": True, "unit_cents": 500, "qty": 2, "mark_cents": 1000,
                 "name": "y"})
    e = executable_range(rows, {"x": {"waxpeer": (1200, 9)}})
    assert e["uncovered_mark_cents"] == 1000 and e["covered"] == 1

    r = _routes("x", {"x": {"skinport": (1000, 5), "csfloat": (950, 900)}})
    assert [v["venue"] for v in r] == ["csfloat", "skinport"], \
        "a lower floor at a 2% fee still nets more than a higher one at 12%"
    assert r[0]["net_cents"] == 931
    # The Skinport high-value break applies where it applies and nowhere else.
    assert _fee("skinport", 99_999) == 0.12 and _fee("skinport", 100_000) == 0.06
    print("selfcheck ok")


def main() -> None:
    with connect(vault_root() / "data" / "cs2.db", "ledger.value") as conn:
        b = book(conn)
        c = change(conn)
    print(f"marketable inventory  {_usd(b['mark_cents'])}   "
          f"({b['priced_items']}/{b['total_items']} priced, "
          f"{b['unmarketable_items']} untradable excluded)   as of {b['taken_at']}")
    print("  window mix: " + ", ".join(f"{n} on {w}" for w, n in b["window_mix"].items() if n))
    e = b["executable"]
    if e:
        print(f"  executable  {_usd(e['low_cents'])} – {_usd(e['high_cents'])}   "
              f"batched to {e['venue']} ({e['covered']} items), seller fee "
              f"{e['seller_fee_pct']:.1f}% + {e['friction_pct'][0]:.0f}–"
              f"{e['friction_pct'][1]:.0f}% friction, {_usd(e['uncovered_mark_cents'])} "
              f"of mark not listed there")
    print(f"  change      {_usd(c.get('delta_cents'))}  ({c['verdict']}, "
          f"band {_usd(c.get('band_cents'))})")
    print(f"  top 5 = {b['concentration']['top5_share']}% of the book\n")
    print(f"  {'qty':>3}  {'mark':>10}  {'win':>4} {'depth':>6}  {'chip':<6} "
          f"{'30d':>7} {'90d':>7}  {'route':<9} name")
    def t(v):
        return "—" if v is None else f"{v:+.1f}%"
    for r in b["rows"][:20]:
        print(f"  {r['qty']:>3}  {_usd(r['mark_cents']):>10}  {r['window'] or '—':>4} "
              f"{r['depth_30d'] or 0:>6}  {r['confidence']:<6} "
              f"{t(r['trend_30d']):>7} {t(r['trend_90d']):>7}  "
              f"{r['best_route'] or '—':<9} {r['name'][:44]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    selfcheck() if a.selfcheck else main()
