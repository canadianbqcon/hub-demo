from __future__ import annotations
from datetime import date, timedelta
from flask import Blueprint, jsonify, render_template
import logging

# Single source of truth for the launcher list — see hub_modules.py. (Used to be
# a hand-synced local copy that drifted: it was missing finances + capabilities
# and had checklists in the wrong tier.)
from hub_modules import MODULES as _MODULES

logger = logging.getLogger(__name__)

# Work portal: J&Co's home page. A branded band with the headline numbers over
# coming-up shifts, paid shifts and the board's sections, all from /work/api/summary.
bp = Blueprint(
    "work", __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/work",
)

def _connectors() -> dict:
    """Live connector dots for the shared Hub status strip — the same cheap
    is_authenticated()/is_configured() token-presence checks home and purchases
    use. Without this the work page never sets window.CONNECTORS, so the global
    footer's gcal/gmail/ynab pips render permanently-disconnected and the gmail
    reconnect link never clears even after a successful re-auth."""
    try:
        import gcal  # top-level modules in dashboard/, already on sys.path
        import gmail
        from finances import book

        return {
            "gcal": gcal.is_authenticated(),
            "gmail": gmail.is_authenticated(),
            "ynab": book.is_configured(),
        }
    except Exception as e:  # chrome still renders with empty/dim connector dots
        logger.warning("connector ctx unavailable: %s", e)
        return {}


@bp.route("/")
def index():
    return render_template("work.html", modules=_MODULES, connectors=_connectors())


JC = "juniper-and-co"


def _hours(start: str, end: str) -> float:
    """Shift length from HH:MM clock times; an end at or before the start ran past midnight."""
    a, b = (int(t[:2]) * 60 + int(t[3:5]) for t in (start, end))
    return round(((b - a) % 1440 or 1440) / 60, 2)


def summary(today: str | None = None) -> dict:
    """J&Co at a glance for the Work page: the next two weeks of shifts, the last
    stub, the year's gross, the last paid shifts, and what each board section holds.
    Reads earnings.db and work.db through their own modules' connections; both
    are read only here."""
    from finances import db as fdb  # ponytail: both modules own these dbs; work only reads
    from batch_prep import db as wdb

    today = today or date.today().isoformat()
    until = (date.fromisoformat(today) + timedelta(days=13)).isoformat()
    with fdb._conn() as e:
        up = [
            {"date": d, "start": s, "end": t, "hours": _hours(s, t)}
            for d, s, t in e.execute(
                "SELECT shift_date, start_at, end_at FROM earnings_scheduled_shifts"
                " WHERE source = ? AND shift_date BETWEEN ? AND ?"
                " AND start_at IS NOT NULL AND end_at IS NOT NULL ORDER BY shift_date, start_at",
                (JC, today, until),
            )
        ]
        last = e.execute(
            "SELECT period_start, period_end, net, gross, hours FROM earnings"
            " WHERE source = ? ORDER BY period_end DESC LIMIT 1", (JC,)
        ).fetchone()
        ytd = e.execute(
            "SELECT COALESCE(SUM(gross), 0), COALESCE(SUM(net), 0), COUNT(*) FROM earnings"
            " WHERE source = ? AND substr(period_end, 1, 4) = ?", (JC, today[:4])
        ).fetchone()
        paid = [
            {"date": d, "hours": h, "total": t}
            for d, h, t in e.execute(
                "SELECT s.shift_date, s.hours, s.shift_total FROM earnings_shifts s"
                " JOIN earnings x ON x.id = s.earnings_id WHERE x.source = ?"
                " ORDER BY s.shift_date DESC LIMIT 6", (JC,)
            )
        ]
    with wdb._conn() as w:
        items = dict(w.execute(
            "SELECT t.key, COUNT(i.id) FROM checklist_template t"
            " LEFT JOIN checklist_template_item i ON i.template_id = t.id GROUP BY t.key"
        ).fetchall())
        rec = dict(w.execute("SELECT kind, COUNT(*) FROM recipes GROUP BY kind").fetchall())
        n_items = w.execute("SELECT COUNT(*) FROM storage_item").fetchone()[0]
        n_areas = w.execute("SELECT COUNT(*) FROM storage_area").fetchone()[0]
    tools = [
        ["Open", f"{items.get('opening_barback', 0)} tasks before doors"],
        ["Close", f"{items.get('closing_barback', 0)} tasks at last call"],
        ["Batch prep", f"{rec.get('batch', 0)} batches, {rec.get('prep', 0)} preps"],
        ["Cocktails", f"{rec.get('cocktail', 0)} specs"],
        ["Map", f"{n_items} items in {n_areas} areas"],
        ["Stock", f"Low boy fill, {items.get('lowboy_fill', 0)} items"],
    ]
    return {
        "today": today,
        "up": up,
        "last_pay": dict(zip(("start", "end", "net", "gross", "hours"), last)) if last else None,
        "ytd": {"gross": round(ytd[0], 2), "net": round(ytd[1], 2), "stubs": ytd[2]},
        "paid": paid,
        "tools": tools,
    }


@bp.route("/api/summary")
def api_summary():
    return jsonify(summary())
