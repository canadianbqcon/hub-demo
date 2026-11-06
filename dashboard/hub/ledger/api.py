"""Float & Ledger blueprint — routes under /ledger.

A CS2 inventory book: what the skins are worth, what they could actually be
sold for, and whether a move is real or just marking noise. Listed on
/artifacts under Projects like /forge, not as a launcher tile — see this
module's CLAUDE.md.

Server-rendered, and deliberately so. There is no client-side state worth
holding: the page is one read of data/cs2.db through value.book(), which is
milliseconds over a few hundred rows, and every number on it has to arrive
already carrying the basis that produced it. A JSON layer plus a renderer would
be two places for a mark to lose its window label.

Surfaces ship in the order of the build spec. `/ledger/` (the book) is here;
the item page, the sell desk and the index page follow.
"""

from __future__ import annotations

import datetime
import math

from flask import Blueprint, abort, render_template

from . import db, value

bp = Blueprint(
    "ledger",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/ledger",
)


def _usd(cents) -> str:
    return "—" if cents is None else f"${cents / 100:,.2f}"


def _usd0(cents) -> str:
    return "—" if cents is None else f"${cents / 100:,.0f}"


# Chart geometry, in viewBox units. A left gutter for the price scale and a
# bottom strip for the date scale — the first version had neither, so the line
# was a shape with no numbers attached to it.
CHART_W, CHART_H = 1000, 292
PAD_L, PAD_R = 66, 10
PRICE_TOP, PRICE_H = 8, 196
VOL_TOP, VOL_H = 216, 42
AXIS_Y = 282
PLOT_W = CHART_W - PAD_L - PAD_R


def _money(cents: float) -> str:
    """Axis labels: no cents above $10, where the decimals are noise on a tick."""
    if cents >= 1000:
        return f"${cents / 100:,.0f}"
    return f"${cents / 100:,.2f}"


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round tick values inside [lo, hi]. Evenly-spaced ticks off the raw min and
    max give labels like $23.87 that nobody can read a chart against."""
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    # No 2.5 step: on a cent-scale item it lands ticks on half-cents, which the
    # label then rounds, and two ticks come out looking unevenly spaced.
    step = min((1, 2, 5, 10), key=lambda m: abs(m * mag - raw)) * mag
    ticks, v = [], math.ceil(lo / step) * step
    while v <= hi + step * 1e-9:
        ticks.append(v)
        v += step
    return ticks


def chart(history: list[dict]) -> dict | None:
    """Turn the daily series into plain SVG geometry plus its two scales.

    Rejected days get coordinates like every other day: they are drawn greyed,
    never dropped. The price line itself skips them — a discarded print is
    evidence of what the feed said, not a price the item traded at — so the line
    reads as the filtered series while the circles show what was filtered.

    The y-scale spans the KEPT days only. Letting a 9x outlier set the ceiling
    would flatten three years of real movement into a hairline at the bottom of
    its own chart.

    `points` is the same series again, flattened for the hover crosshair. It is
    the geometry the SVG already carries rather than a second copy of the data,
    so the readout can never disagree with the line under it.
    """
    if not history:
        return None
    kept = [h for h in history if not h["rejected"]]
    if not kept:
        return None
    days = [datetime.date.fromisoformat(h["day"]).toordinal() for h in history]
    d0, d1 = min(days), max(days)
    span = max(d1 - d0, 1)
    prices = [h["price_cents"] for h in kept]
    lo, hi = min(prices), max(prices)
    rng = max(hi - lo, 1)
    vmax = max((h["trades"] for h in history), default=1) or 1

    def x_of(ordinal):
        return round(PAD_L + (ordinal - d0) / span * PLOT_W, 1)

    def x(h):
        return x_of(datetime.date.fromisoformat(h["day"]).toordinal())

    def y(cents):
        return round(PRICE_TOP + PRICE_H - (min(max(cents, lo), hi) - lo) / rng * PRICE_H, 1)

    # Year boundaries, thinned to at most ~8 labels so a six-year series does not
    # crowd its own axis.
    y0 = datetime.date.fromordinal(d0).year
    y1 = datetime.date.fromordinal(d1).year
    years = [yr for yr in range(y0, y1 + 1)
             if d0 <= datetime.date(yr, 1, 1).toordinal() <= d1]
    stride = max(1, len(years) // 8 + (1 if len(years) > 8 else 0))
    xticks = [{"x": x_of(datetime.date(yr, 1, 1).toordinal()), "label": str(yr)}
              for i, yr in enumerate(years) if i % stride == 0]

    return {
        "w": CHART_W, "h": CHART_H, "pad_l": PAD_L, "plot_r": CHART_W - PAD_R,
        "price_top": PRICE_TOP, "price_bottom": PRICE_TOP + PRICE_H,
        "vol_top": VOL_TOP, "vol_h": VOL_H, "vol_bottom": VOL_TOP + VOL_H,
        "axis_y": AXIS_Y,
        "line": " ".join(f"{x(h)},{y(h['price_cents'])}" for h in kept),
        "rejected": [{"x": x(h), "y": y(h["price_cents"])} for h in history if h["rejected"]],
        "bars": [{"x": x(h), "h": round(h["trades"] / vmax * VOL_H, 1)}
                 for h in history if h["trades"]],
        "yticks": [{"y": y(t), "label": _money(t)} for t in _nice_ticks(lo, hi)],
        "xticks": xticks,
        "vmax": vmax,
        "lo_cents": lo, "hi_cents": hi,
        "first_day": history[0]["day"], "last_day": history[-1]["day"],
        "days": len(history), "rejected_n": len(history) - len(kept),
        "points": [[x(h), y(h["price_cents"]), h["day"], h["price_cents"],
                    h["trades"], 1 if h["rejected"] else 0, h["reason"] or ""]
                   for h in history],
    }


@bp.route("/")
def book():
    with db._conn() as conn:
        data = value.book(conn)
        delta = value.change(conn)
    return render_template("book.html", b=data, change=delta,
                           usd=_usd, usd0=_usd0,
                           windows=value.WINDOW_ORDER)


@bp.route("/i/<path:name>")
def item(name: str):
    with db._conn() as conn:
        data = value.item(conn, name)
    if data is None:
        abort(404)
    return render_template("item.html", i=data, chart=chart(data["history"]),
                           usd=_usd, depth_target=value.DEPTH_TARGET)
