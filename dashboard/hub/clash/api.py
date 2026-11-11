"""Clash Hub blueprint, routes under /clash: the tracker page and its JSON API."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from flask import Blueprint, jsonify, render_template, request

from . import coc_api, db, export, gamedata, notify_glue, unlock

bp = Blueprint(
    "clash",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/clash",
)


_MAX_BODY = 12 * 1024 * 1024  # layout images cap at 10 MB; an export is well under 1 MB


@bp.before_request
def _same_origin_writes():
    """Another site's page can post a text/plain or multipart body here with no
    CORS preflight (a forged paste would overwrite the village), so writes take
    same-origin callers only, and an oversized body is refused before it is read."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.headers.get("Sec-Fetch-Site", "none") not in ("same-origin", "none"):
        return jsonify({"error": "Cross-site writes are refused"}), 403
    if (request.content_length or 0) > _MAX_BODY:
        return jsonify({"error": "Body too large"}), 413
    return None


# page -> (title suffix, stylesheets, scripts); one shell template serves all five
_PAGES = {
    "clash": ("", ["clash.css"], ["wp-common.jsx", "clash.jsx"]),
    "profile": ("Profile", ["war.css"], ["wp-common.jsx", "profile.jsx"]),
    "war": ("War", ["war.css"], ["wp-common.jsx", "war.jsx"]),
    "plan": ("", ["clash.css", "plan.css"], ["wp-common.jsx", "plan.jsx"]),
    "layouts": ("", ["clash.css", "plan.css"], ["wp-common.jsx", "layouts.jsx"]),
    "patch": ("Patch", ["war.css", "patch.css"], ["wp-common.jsx", "patch.jsx"]),
}


def _shell(page: str):
    # Same shell context as the gaming page (topbar menu and status dots).
    modules, connectors = [], {}
    try:
        from gaming.api import _connectors
        from hub_modules import MODULES as modules
        connectors = _connectors()
    except Exception:  # shell context is cosmetic; the page still works without it
        pass
    title, css, js = _PAGES[page]
    return render_template("clash.html", modules=modules, connectors=connectors, title=title, css=css, js=js)


@bp.route("/")
def index():
    return _shell("clash")


_FACILITY = {"troop": "lab", "spell": "lab", "siege-machine": "lab", "pet": "pet_house"}
_NO_TIMER = {"hero-equipment", "guardian", "crafted-defense", "wall"}  # forge, crafting, wall work: not tracked here


def _err(msg: str, code: int):
    return jsonify({"error": msg}), code


def _tag(c, tag):
    """Requested tag if it exists, else the first account, else None."""
    if tag:
        r = c.execute("SELECT * FROM account WHERE tag=?", (tag,)).fetchone()
        if r:
            return r
    return c.execute("SELECT * FROM account ORDER BY name COLLATE NOCASE, tag LIMIT 1").fetchone()


def _acct(c, tag):
    """Exact account for a write: an unknown tag must never land on another account."""
    return c.execute("SELECT * FROM account WHERE tag=?", (tag,)).fetchone() if tag else None


def _iso(v):
    """Client ISO time -> normalized UTC string, or None when unparseable."""
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).strftime(db.FMT)


def _step(data_id, from_level):
    """Level row that the upgrade from from_level builds, or None."""
    for lv in gamedata.entity(data_id)["levels"]:
        if lv["level"] == from_level + 1:
            return lv
    return None


def _next(data_id, level):
    """Next level's cost, resource, time and the Town Hall that unlocks it; None when none exists."""
    s = _step(data_id, level)
    return s and {"cost": s["buildCost"], "resource": s["buildCostResource"], "secs": s["buildTime"],
                  "th": gamedata.unlock_th(data_id, level + 1)}


_HELPER_FAC = {"builders-apprentice": "builder", "lab-assistant": "lab"}
# The package tags Prospector 93000002 and Alchemist with no id, but his export has 93000002 at level 5
# and Prospector has 1 level: 93000002 is the Alchemist (release order), so ids map by hand.
_HELPER_IDS = {93000000: "builders-apprentice", 93000001: "lab-assistant", 93000002: "alchemist",
               93000003: "prospector"}


@lru_cache(maxsize=None)
def _helper_data(slug):
    f = gamedata.GAMEDATA / "home/other/helpers" / f"{slug}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _helpers(c, tag):
    out = []
    for r in c.execute("SELECT * FROM helper WHERE tag=? ORDER BY data_id", (tag,)):
        slug = _HELPER_IDS.get(r["data_id"])
        d = _helper_data(slug) if slug else None
        if not d:
            continue
        lv = next((x for x in d.get("levels", []) if x["level"] == r["level"]), {})
        out.append({"data_id": r["data_id"], "name": d["name"], "level": r["level"], "ready_at": r["ready_at"],
                    "icon": gamedata.icon_file(f"i-{slug}.png"), "facility": _HELPER_FAC.get(d["id"]),
                    "work_rate": lv.get("workRate"), "max": len(d.get("levels", []))})
    return out


# kind -> (facility, speed multiplier) for one hour; sources in the clash CLAUDE.md
BOOSTS = {"builder_potion": ("builder", 10), "builder_bite": ("builder", 2), "research_potion": ("lab", 24),
          "study_soup": ("lab", 4), "pet_potion": ("pet_house", 24)}


@bp.route("/api/boost", methods=["POST"])
def boost():
    b = request.get_json(silent=True)
    if not isinstance(b, dict) or not isinstance(b.get("tag"), str) or not isinstance(b.get("kind"), str) \
            or b["kind"] not in BOOSTS:
        return _err("kind must be one of " + ", ".join(BOOSTS), 400)
    fac, rate = BOOSTS[b["kind"]]
    with db.conn() as c:
        acct = _acct(c, b.get("tag"))
        if not acct:
            return _err("Unknown account", 404)
        db._begin(c)
        n = db.boost(c, acct["tag"], fac, rate, db.now(), kind=b["kind"])
    return jsonify({"moved": n})


@bp.route("/api/helper", methods=["POST"])
def helper_use():
    """Put the Builder's Apprentice or Lab Assistant on one running upgrade for its hour."""
    b = request.get_json(silent=True)
    if not isinstance(b, dict) or not isinstance(b.get("tag"), str) or not all(
            isinstance(b.get(k), int) and not isinstance(b.get(k), bool) and 0 < b[k] < 2**62 for k in ("data_id", "upgrade_id")):
        return _err("tag, data_id and upgrade_id are required", 400)
    now = db.now()
    with db.conn() as c:
        db._begin(c)  # the ready check and the ready_at write are one unit: a double click cannot apply it twice
        acct = _acct(c, b.get("tag"))
        if not acct:
            return _err("Unknown account", 404)
        h = next((x for x in _helpers(c, acct["tag"]) if x["data_id"] == b["data_id"]), None)
        if not h or not h["facility"] or not h["work_rate"]:
            return _err("No such helper", 404)
        if h["ready_at"] and h["ready_at"] > now:
            return _err("Helper is resting until " + h["ready_at"], 409)
        u = c.execute("SELECT * FROM upgrade WHERE id=? AND tag=?", (b["upgrade_id"], acct["tag"])).fetchone()
        if not u or u["facility"] != h["facility"] or u["finishes_at"] <= now:
            return _err("That upgrade is not running in the helper's building", 409)
        fin = db.speed_up(c, u["id"], h["work_rate"] + 1, now, kind="helper")
        # ponytail: helpers reset once a day; step the known reset forward, else assume 24h from now
        t = db.parse(h["ready_at"]) if h["ready_at"] else db.parse(now)
        while t <= db.parse(now):
            t += timedelta(days=1)
        ready = t.strftime(db.FMT)
        c.execute("UPDATE helper SET ready_at=? WHERE tag=? AND data_id=?", (ready, acct["tag"], h["data_id"]))
    return jsonify({"finishes_at": fin, "ready_at": ready})


@bp.route("/api/village")
def village():
    with db.conn() as c:
        db.apply_due(c, db.now())
        # release the write lock before the 1-3 s read: holding it made overlapping polls fail with
        # "database is locked" past the 5 s busy timeout (34 times on 2026-11-10)
        c.commit()
        acct = _tag(c, request.args.get("tag"))
        accounts = db.accounts(c)
        # village switcher cards (2026-11-11 Workbench pick): each village's own builders, so idle ones show without switching
        run = {r["tag"]: r for r in c.execute(
            "SELECT a.tag, a.builders, COUNT(u.id) AS busy, MIN(u.finishes_at) AS next_at FROM account a "
            "LEFT JOIN upgrade u ON u.tag = a.tag AND u.facility = 'builder' GROUP BY a.tag")}
        for a in accounts:
            r = run[a["tag"]]
            a.update(builders=r["builders"], busy=r["busy"], next_at=r["next_at"])
        out ={"account": dict(acct) if acct else None, "accounts": accounts, "structures": [], "upgrades": [],
               "builders": acct["builders"] if acct else 0, "notify_on": notify_glue.available(),
               "data_version": gamedata.version(), "now": db.now()}
        if not acct:
            return jsonify(out)
        th = acct["th_level"]
        for r in c.execute("SELECT data_id, level, cnt, predicted FROM structure WHERE tag=? ORDER BY data_id, level DESC", (acct["tag"],)):
            try:
                e = gamedata.entity(r["data_id"])
            except KeyError:
                continue  # unknown id kept in the store, not drawn
            out["structures"].append({
                "data_id": r["data_id"], "name": e["name"], "icon": gamedata.icon(r["data_id"]), "category": e["category"],
                "level": r["level"], "cnt": r["cnt"], "max": max(gamedata.max_level(r["data_id"], th), r["level"]), "predicted": r["predicted"],
                "facility": None if e["category"] in _NO_TIMER else _FACILITY.get(e["category"], "builder"),
                "next": _next(r["data_id"], r["level"]), "order": unlock.order(e["name"])})
        for r in c.execute("SELECT * FROM upgrade WHERE tag=? ORDER BY finishes_at", (acct["tag"],)):
            try:
                name = gamedata.entity(r["data_id"])["name"]
                step = _step(r["data_id"], r["from_level"])
            except KeyError:
                continue
            out["upgrades"].append({**dict(r), "name": name, "icon": gamedata.icon(r["data_id"]),
                                    "total_secs": step["buildTime"] if step else 0,
                                    "resource": step["buildCostResource"] if step else None})
        out["helpers"] = _helpers(c, acct["tag"])
        out["queue"] = _queue(c, acct, out["upgrades"])
        for x in out["structures"] + out["upgrades"] + out["queue"]:
            x["sc_base"] = gamedata.sc_base(x["data_id"])  # supercharge split for the level label
    _remind(out["queue"])
    return jsonify(out)


def _queue(c, acct, upgrades=None):
    """The village's queue placed on lanes, reminders re-posted at each item's planned start.
    An item whose level no longer has a copy (a paste or a finished timer moved it) is dropped."""
    if upgrades is None:
        upgrades = [dict(r) for r in c.execute("SELECT * FROM upgrade WHERE tag=?", (acct["tag"],))]
    items = []
    for r in c.execute("SELECT q.* FROM queue_item q WHERE q.tag=? ORDER BY q.position, q.id", (acct["tag"],)).fetchall():
        have = c.execute("SELECT 1 FROM structure WHERE tag=? AND data_id=? AND level=?",
                         (acct["tag"], r["data_id"], r["from_level"])).fetchone()
        try:
            e, step = gamedata.entity(r["data_id"]), _step(r["data_id"], r["from_level"])
        except KeyError:
            e = step = None
        if not have or not step:
            c.execute("DELETE FROM queue_item WHERE id=?", (r["id"],))
            notify_glue.unqueued(r["id"])
            continue
        items.append({**dict(r), "name": e["name"], "icon": gamedata.icon(r["data_id"]), "secs": step["buildTime"],
                      "resource": step["buildCostResource"], "cost": step["buildCost"]})
    return db.schedule(items, upgrades, acct["builders"], db.now())


def _remind(queue):
    """Post reminders after the clash transaction commits: notify.db writes are slow on /mnt/c, and holding
    clash.db's write lock through them made concurrent page polls fail with "database is locked" (2026-11-10)."""
    for q in queue:
        notify_glue.queued(q)


def _body_ints(b, *keys):
    return isinstance(b, dict) and all(isinstance(b.get(k), int) and not isinstance(b.get(k), bool)
                                       and 0 <= b[k] < 2**62 for k in keys)


@bp.route("/api/queue", methods=["POST"])
def queue_add():
    """Queue an upgrade for when its facility frees: {tag, data_id, from_level}."""
    b = request.get_json(silent=True)
    if not _body_ints(b, "data_id", "from_level") or not isinstance(b.get("tag"), str):
        return _err("tag, data_id and from_level are required", 400)
    try:
        e, step = gamedata.entity(b["data_id"]), _step(b["data_id"], b["from_level"])
    except KeyError:
        return _err("data_id and from_level must name a known structure", 400)
    if step is None or e["category"] in _NO_TIMER:
        return _err("No next level to queue", 400)
    with db.conn() as c:
        db._begin(c)
        acct = _acct(c, b["tag"])
        if acct is None:
            return _err("Unknown account", 404)
        key = (acct["tag"], b["data_id"], b["from_level"])
        have = c.execute("SELECT cnt FROM structure WHERE tag=? AND data_id=? AND level=?", key).fetchone()
        used = c.execute("SELECT COUNT(*) FROM upgrade WHERE tag=? AND data_id=? AND from_level=?", key).fetchone()[0] \
            + c.execute("SELECT COUNT(*) FROM queue_item WHERE tag=? AND data_id=? AND from_level=?", key).fetchone()[0]
        if not have or used >= have[0]:
            return _err("Every copy at that level is already upgrading or queued", 409)
        qid = c.execute("INSERT INTO queue_item (tag, data_id, from_level, facility, position) VALUES "
                        "(?,?,?,?,(SELECT COALESCE(MAX(position), 0) + 1 FROM queue_item WHERE tag=?))",
                        (*key, _FACILITY.get(e["category"], "builder"), acct["tag"])).lastrowid
        q = _queue(c, acct)
    _remind(q)
    return jsonify({"id": qid, "queue": q})


@bp.route("/api/queue/remove", methods=["POST"])
def queue_remove():
    b = request.get_json(silent=True)
    if not _body_ints(b, "id"):
        return _err("id is required", 400)
    with db.conn() as c:
        c.execute("DELETE FROM queue_item WHERE id=?", (b["id"],))
    notify_glue.unqueued(b["id"])
    return jsonify({"id": b["id"]})


@bp.route("/api/queue/order", methods=["PUT"])
def queue_order():
    """Reorder one village's queue: {tag, ids: [every queued id, in the new order]}."""
    b = request.get_json(silent=True)
    ids = b.get("ids") if isinstance(b, dict) else None
    if not isinstance(b, dict) or not isinstance(b.get("tag"), str) or not isinstance(ids, list) \
            or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids) or len(set(ids)) != len(ids):
        return _err("tag and ids (distinct queued ids) are required", 400)
    with db.conn() as c:
        db._begin(c)
        acct = _acct(c, b["tag"])
        if acct is None:
            return _err("Unknown account", 404)
        if set(ids) != {r["id"] for r in c.execute("SELECT id FROM queue_item WHERE tag=?", (acct["tag"],))}:
            return _err("ids must list every queued item exactly once", 409)
        c.executemany("UPDATE queue_item SET position=? WHERE id=?", [(i + 1, q) for i, q in enumerate(ids)])
        q = _queue(c, acct)
    _remind(q)
    return jsonify({"queue": q})


@bp.route("/api/start", methods=["POST"])
def start():
    b = request.get_json(silent=True) or {}
    try:
        data_id, frm = int(b["data_id"]), int(b["from_level"])
        e = gamedata.entity(data_id)
        step = _step(data_id, frm)
    except (KeyError, TypeError, ValueError):
        return _err("data_id and from_level must name a known structure", 400)
    if step is None or e["category"] in _NO_TIMER:
        return _err("No next level to start", 400)
    fin = _iso(b["finishes_at"]) if b.get("finishes_at") else (
        (datetime.now(timezone.utc) + timedelta(seconds=step["buildTime"])).strftime(db.FMT))
    if fin is None:
        return _err("finishes_at is not a time", 400)
    with db.conn() as c:
        acct = _acct(c, b.get("tag"))
        if acct is None:
            return _err("Unknown account", 404)
        have = c.execute("SELECT cnt FROM structure WHERE tag=? AND data_id=? AND level=?", (acct["tag"], data_id, frm)).fetchone()
        if not have:
            return _err("No copy at that level", 400)
        running = c.execute("SELECT COUNT(*) FROM upgrade WHERE tag=? AND data_id=? AND from_level=?",
                            (acct["tag"], data_id, frm)).fetchone()[0]
        if running >= have[0]:
            return _err("Every copy at that level is already upgrading", 409)
        try:
            uid = db.start_upgrade(c, acct["tag"], data_id, frm, _FACILITY.get(e["category"], "builder"), fin)
        except db.FacilityFull as ex:
            return _err(str(ex), 409)
        except sqlite3.IntegrityError:
            return _err("That upgrade is already running", 409)
        qid = b.get("queue_id")
        if isinstance(qid, int) and not isinstance(qid, bool):  # a queued item he started: it leaves the queue
            c.execute("DELETE FROM queue_item WHERE id=? AND tag=?", (qid, acct["tag"]))
            notify_glue.unqueued(qid)
    return jsonify({"id": uid, "finishes_at": fin})


@bp.route("/api/finish", methods=["POST"])
def finish():
    b = request.get_json(silent=True) or {}
    fin = _iso(b.get("finishes_at"))
    if fin is None or not isinstance(b.get("id"), int):
        return _err("id and finishes_at are required", 400)
    with db.conn() as c:
        try:
            db.edit_finish(c, b["id"], fin)
        except LookupError:
            return _err("No such upgrade", 404)
        except sqlite3.IntegrityError:
            return _err("An identical upgrade already exists", 409)
    return jsonify({"id": b["id"], "finishes_at": fin})


@bp.route("/api/undo", methods=["POST"])
def undo():
    b = request.get_json(silent=True) or {}
    if not isinstance(b.get("id"), int):
        return _err("id is required", 400)
    with db.conn() as c:
        db.undo_upgrade(c, b["id"])
    return jsonify({"id": b["id"]})


@bp.route("/api/builders", methods=["PUT"])
def builders():
    b = request.get_json(silent=True) or {}
    n = b.get("builders")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 8:
        return _err("builders must be a whole number from 1 to 8", 400)
    with db.conn() as c:
        cur = c.execute("UPDATE account SET builders=? WHERE tag=?", (n, b.get("tag")))
        if cur.rowcount == 0:
            return _err("Unknown account", 404)
    return jsonify({"builders": n})


@bp.route("/api/order", methods=["PUT"])
def order():
    """Reorder the village tabs: {tags: [every tracked tag, in the new order]}."""
    b = request.get_json(silent=True)
    tags = b.get("tags") if isinstance(b, dict) else None
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags) or len(set(tags)) != len(tags):
        return _err("tags must be a list of distinct village tags", 400)
    with db.conn() as c:
        db._begin(c)
        if set(tags) != {r["tag"] for r in c.execute("SELECT tag FROM account")}:
            return _err("tags must list every village exactly once", 409)
        c.executemany("UPDATE account SET position=? WHERE tag=?", [(i + 1, t) for i, t in enumerate(tags)])
    return jsonify({"tags": tags})


@bp.route("/api/paste", methods=["POST"])
def paste():
    body = request.get_json(silent=True)
    text = body.get("text") if isinstance(body, dict) else request.get_data(as_text=True)
    with db.conn() as c:
        res = export.apply(c, text if isinstance(text, str) else "", datetime.now(timezone.utc))
        # An export carries the tag but not the player name, so a village added by paste showed as
        # its tag until a war page happened to refresh it (2026-11-10, samrivera). Fetch it now.
        row = c.execute("SELECT name FROM account WHERE tag=?", (res["tag"],)).fetchone() if res["status"] != "rejected" else None
        if row is not None and not row["name"]:
            try:
                coc_api.refresh(c, res["tag"])
            except Exception:  # the name is cosmetic; the paste already landed
                pass
    return jsonify(res), (400 if res["status"] == "rejected" else 200)


from . import patch_pages, plan_pages, war_pages  # noqa: E402,F401  routes for /plan, /layouts, /profile, /war, /patch
