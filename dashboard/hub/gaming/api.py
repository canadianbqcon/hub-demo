from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

from flask import Blueprint, jsonify, render_template

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402
from hub_modules import MODULES as _MODULES

logger = logging.getLogger(__name__)

# Gaming hub: one brand band per game over that game's Hub pages, with live numbers.
bp = Blueprint(
    "gaming", __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/gaming",
)

# id, name, sub, launch, modules. Order is the page order. A module is a Hub page
# for that game; its `stat` is filled from live data in summary().
_GAMES = [
    ("league", "League of Legends", "Item sets, patch notes and champion stats", ["Open Forge", "/forge/"], [
        ("Item Set Forge", "Build and save item sets per champion and role", "/forge/"),
        ("Patch notes", "What changed this patch, item by item", "/forge/patch"),
        ("Champion stats", "Your rank, match history and champion record", "/forge/stats"),
        ("Draft", "Champion select helper with bans and matchups", "/forge/draft"),
        ("Build editor", "Edit a set's items, runes and order", "/forge/edit"),
    ]),
    ("cs2", "Counter-Strike 2", "Inventory book and sell desk", ["Open Float & Ledger", "/ledger/"], [
        ("Float & Ledger", "Marked value of the inventory, sell routes and per-item price history", "/ledger/"),
    ]),
    ("clash", "Clash of Clans", "Builder tracker, profile, war, upgrade plan and layouts", ["Open Tracker", "/clash/"], [
        ("Tracker", "Builders, running upgrades and what finishes next", "/clash/"),
        ("Profile", "Heroes, troops, spells and war stars from the game API", "/clash/profile"),
        ("War", "Current war, attacks and target plan", "/clash/war"),
        ("Plan", "What to upgrade next, with costs and builder time", "/clash/plan"),
        ("Layouts", "Saved base layouts per Town Hall", "/clash/layouts"),
        ("Patch", "Balance changes, blog posts and leaks", "/clash/patch"),
    ]),
]

_DATA = vault_root() / "data"


def _connectors() -> dict:
    """Live connector dots for the shared Hub status strip (same as work)."""
    try:
        import gcal
        import gmail
        from finances import book

        return {
            "gcal": gcal.is_authenticated(),
            "gmail": gmail.is_authenticated(),
            "ynab": book.is_configured(),
        }
    except Exception as e:
        logger.warning("connector ctx unavailable: %s", e)
        return {}


@bp.route("/")
def index():
    return render_template("gaming.html", modules=_MODULES, connectors=_connectors())


def _league_stats() -> dict:
    stats = json.loads((_DATA / "forge-stats.json").read_text(encoding="utf-8"))
    sets = json.loads((_DATA / "forge-sets.json").read_text(encoding="utf-8"))
    # Riot's label (26.22) lives in the baked notes; the stats file carries Data Dragon's (16.22).
    notes = json.loads((_DATA / "forge-patch-notes.json").read_text(encoding="utf-8"))
    return {"patch": notes.get("patch") or stats.get("patch"), "champions": len(stats.get("champions") or {}),
            "sets": len(sets.get("sets") or []), **_safe(_solo_rank)}


def _solo_rank() -> dict:
    """Solo / Duo rank and record from Forge's cached OP.GG profile; the gaming page never calls OP.GG."""
    me = json.loads((_DATA / "forge-me.json").read_text(encoding="utf-8"))
    r = next((r for r in me.get("ranks") or [] if r.get("queue") == "SOLORANKED"), None)
    if not r or not r.get("tier"):
        return {}
    div = f" {r['division']}" if r.get("division") else ""
    return {"rank": f"{r['tier'].title()}{div} {r.get('lp', 0)} LP", "record": f"{r['win']}W {r['lose']}L"}


def _cs2_stats() -> dict:
    from ledger import db, value
    from ledger.api import _usd
    with db._conn() as conn:
        b = value.book(conn)
    return {"mark": _usd(b["mark_cents"]), "items": len(b["rows"])}


def _clash_stats() -> dict:
    """Builders busy of total and the next finish, read-only, for the account updated most recently."""
    import sqlite3
    from datetime import datetime, timezone
    path = _DATA / "clash.db"
    if not path.exists():  # sqlite would create an empty file on connect
        raise FileNotFoundError(path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        acct = c.execute("SELECT tag, builders FROM account ORDER BY updated_at DESC LIMIT 1").fetchone()
        if not acct:
            return {}
        tag, total = acct
        busy, nxt = c.execute("SELECT COUNT(*), MIN(finishes_at) FROM upgrade WHERE tag=? AND facility='builder' "
                              "AND finishes_at > ?", (tag, now)).fetchone()
    finally:
        c.close()
    return {"busy": busy, "total": total, "next": nxt}


def _until(iso: str) -> str:
    from datetime import datetime, timezone
    secs = int((datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                - datetime.now(timezone.utc)).total_seconds())
    d, r = divmod(max(secs, 0), 86400)
    h, r = divmod(r, 3600)
    return f"{d}d {h}h" if d else (f"{h}h {r // 60}m" if h else f"{r // 60}m")


def _safe(fn) -> dict:
    try:
        return fn() or {}
    except Exception as e:  # a missing or half-written source blanks its numbers, never the page
        logger.warning("gaming stats %s: %s", fn.__name__, e)
        return {}


def _stat(url: str, league: dict, cs2: dict, clash: dict | None = None) -> str:
    if url == "/forge/" and "sets" in league:
        return f"{league['sets']} saved sets"
    if url == "/forge/patch" and league.get("patch"):
        return f"Patch {league['patch']}"
    if url == "/forge/stats" and league.get("record"):
        return league["record"]
    if url == "/ledger/" and cs2:
        return f"{cs2['mark']} across {cs2['items']} items"
    if url == "/clash/" and clash:
        nxt = f", next in {_until(clash['next'])}" if clash.get("next") else ""
        return f"{clash['busy']} of {clash['total']} builders busy{nxt}"
    return ""


def _headline(gid: str, league: dict, cs2: dict, clash: dict | None = None) -> dict | None:
    if gid == "league" and league.get("rank"):
        return {"label": "Solo / Duo", "value": league["rank"]}
    if gid == "league" and league.get("patch"):
        return {"label": "Patch", "value": str(league["patch"])}
    if gid == "cs2" and cs2:
        return {"label": "Inventory", "value": cs2["mark"]}
    if gid == "clash" and clash:
        return {"label": "Builders busy", "value": f"{clash['busy']} of {clash['total']}"}
    return None


def summary() -> dict:
    league, cs2, clash = _safe(_league_stats), _safe(_cs2_stats), _safe(_clash_stats)
    games = []
    for gid, name, sub, launch, mods in _GAMES:
        modules = [{"title": t, "desc": d, "url": u, "stat": _stat(u, league, cs2, clash)} for t, d, u in mods]
        games.append({"id": gid, "name": name, "sub": sub, "launch": launch, "modules": modules,
                      "count": len(modules), "headline": _headline(gid, league, cs2, clash)})
    return {"games": games}


@bp.route("/api/summary")
def api_summary():
    return jsonify(summary())
