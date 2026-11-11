"""Profile and war pages: read views over api_cache plus the who-hits-whom plan (routes join api.bp)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from flask import jsonify, request

from . import coc_api, db, gamedata
from .api import _err, _shell, _tag, bp

_GROUPS = (("heroes", "heroes"), ("troops", "troops"), ("spells", "spells"), ("equipment", "heroEquipment"))
_NAMES: dict[str, int] = {}


@bp.route("/profile")
def profile_page():
    return _shell("profile")


@bp.route("/war")
def war_page():
    return _shell("war")


def _age(ok_at):
    try:
        return max(0, int((datetime.now(timezone.utc) - db.parse(ok_at)).total_seconds()))
    except (TypeError, ValueError):
        return None


def _banner(c, tag):
    """Banner kind from the stored state; the refresh answer carries the live IP, so ip stays None here."""
    if coc_api._key() is None:
        return {"kind": "no_key", "ip": None}
    r = c.execute("SELECT last_status, last_error FROM api_cache WHERE path=?", (f"/players/{quote(tag, safe='')}",)).fetchone()
    if r and r["last_status"] == 403:
        return {"kind": "invalid_ip" if r["last_error"] == "accessDenied.invalidIp" else "refused", "ip": None}
    return None


def _name_id():
    if not _NAMES:
        for d in gamedata._index().values():
            _NAMES.setdefault(d["name"], d["dataId"])
    return _NAMES


def _items(player):
    th = player.get("townHallLevel", 1)
    out = {}
    for key, src in _GROUPS:
        rows = []
        for it in player.get(src) or []:
            if it.get("village", "home") != "home":
                continue
            did = _name_id().get(it["name"])
            if did is None and key == "troops":  # super troops: not in the game data, never upgraded on their own
                continue
            cap = gamedata.max_level(did, th) if did is not None else 0
            rows.append({"name": it["name"], "level": it["level"], "max": cap or it.get("maxLevel", it["level"]),
                         "icon": gamedata.icon(did) if did is not None else None})
        out[key] = rows
    return out


@bp.route("/api/profile")
def api_profile():
    with db.conn() as c:
        acct = _tag(c, request.args.get("tag"))
        out = {"account": dict(acct) if acct else None, "accounts": db.accounts(c), "player": None, "items": None,
               "ok_at": None, "age_secs": None, "error": None, "banner": None}
        if not acct:
            return jsonify(out)
        body, ok_at, error = coc_api.cached(c, f"/players/{quote(acct['tag'], safe='')}")
        out.update(ok_at=ok_at, age_secs=_age(ok_at), error=error, banner=_banner(c, acct["tag"]))
        if body:
            out["player"] = {k: body.get(k) for k in ("name", "tag", "townHallLevel", "expLevel", "trophies", "bestTrophies",
                                                      "warStars", "attackWins", "donations", "clan", "league")}
            out["items"] = _items(body)
        return jsonify(out)


@bp.route("/api/refresh", methods=["POST"])
def api_refresh():
    with db.conn() as c:
        tag = request.args.get("tag", "")
        if not c.execute("SELECT 1 FROM account WHERE tag=?", (tag,)).fetchone():
            return _err("Unknown account", 404)
        return jsonify(coc_api.refresh(c, tag))


def _sides(body, clan_tag):
    us, them = body.get("clan") or {}, body.get("opponent") or {}
    return (them, us) if clan_tag and them.get("tag") == clan_tag and us.get("tag") != clan_tag else (us, them)


def _view(body, clan_tag, key, plans):
    us, them = _sides(body, clan_tag)
    roster = {m["tag"]: m for m in them.get("members", [])}
    members = []
    for m in sorted(us.get("members", []), key=lambda m: m.get("mapPosition", 0)):
        atk = m.get("attacks") or []
        p = plans.get(m["tag"])
        plan = None
        if p:
            t = roster.get(p["target_tag"])
            plan = {**p, "gone": t is None}
            if t:
                plan.update(target_name=t["name"], target_pos=t.get("mapPosition"))
        members.append({"tag": m["tag"], "name": m["name"], "pos": m.get("mapPosition"), "th": m.get("townhallLevel"),
                        "stars": sum(a.get("stars", 0) for a in atk), "attacks_used": len(atk),
                        "attacks_left": max(0, body.get("attacksPerMember", 2) - len(atk)), "plan": plan})
    return {"key": key, "state": body.get("state"), "us": {k: us.get(k) for k in ("tag", "name", "stars", "destructionPercentage")},
            "them": {k: them.get(k) for k in ("tag", "name", "stars", "destructionPercentage")},
            "members": members,
            "targets": [{"tag": t["tag"], "name": t["name"], "pos": t.get("mapPosition"), "th": t.get("townhallLevel")}
                        for t in sorted(roster.values(), key=lambda t: t.get("mapPosition", 0))]}


def _plans(c, key):
    return {r["attacker_tag"]: {"target_tag": r["target_tag"], "note": r["note"]}
            for r in c.execute("SELECT attacker_tag, target_tag, note FROM war_plan WHERE war_key=?", (key,))}


def _status(body, error):
    if body and body.get("state") != "notInWar":
        return "ok"
    if error == "not_in_war" or (body and body.get("state") == "notInWar"):
        return "not_in_war"
    return "error" if error else "no_data"


@bp.route("/api/war")
def api_war():
    with db.conn() as c:
        acct = _tag(c, request.args.get("tag"))
        out = {"account": dict(acct) if acct else None, "accounts": db.accounts(c), "status": "no_data", "current": None,
               "cwl": [], "log": [], "log_status": "no_data", "ok_at": None, "age_secs": None, "error": None, "banner": None}
        if not acct:
            return jsonify(out)
        clan = acct["clan_tag"]
        out["banner"] = _banner(c, acct["tag"])
        if not clan:
            out["status"] = "no_clan"
            return jsonify(out)
        ce = quote(clan, safe="")
        body, ok_at, error = coc_api.cached(c, f"/clans/{ce}/currentwar")
        out.update(ok_at=ok_at, age_secs=_age(ok_at), error=error, status=_status(body, error))
        if out["status"] == "ok":
            us, them = _sides(body, clan)
            key = f"{us.get('tag')}:{them.get('tag')}:{body.get('preparationStartTime')}"
            out["current"] = _view(body, clan, key, _plans(c, key))
        group, _, _ = coc_api.cached(c, f"/clans/{ce}/currentwar/leaguegroup")
        for i, rnd in enumerate((group or {}).get("rounds", []), 1):
            for wt in rnd.get("warTags", []):
                wb, _, _ = coc_api.cached(c, f"/clanwarleagues/wars/{quote(wt, safe='')}")
                if wb and clan in ((wb.get("clan") or {}).get("tag"), (wb.get("opponent") or {}).get("tag")):
                    out["cwl"].append({"round": i, "war_tag": wt, **_view(wb, clan, wt, _plans(c, wt))})
        log, _, log_err = coc_api.cached(c, f"/clans/{ce}/warlog")
        if log:
            out["log_status"] = "ok"
            out["log"] = [{"result": w.get("result"), "end": w.get("endTime"), "size": w.get("teamSize"),
                           "us": (w.get("clan") or {}).get("stars"), "them": (w.get("opponent") or {}).get("stars"),
                           "opponent": (w.get("opponent") or {}).get("name")} for w in log.get("items", [])[:10]]
        elif log_err:
            out["log_status"] = "private" if log_err == "not_in_war" else "error"
        return jsonify(out)


@bp.route("/api/war-plan", methods=["PUT"])
def api_war_plan():
    b = request.get_json(silent=True) or {}
    key, att, tgt = b.get("war_key"), b.get("attacker_tag"), b.get("target_tag")
    pos, note = b.get("target_pos"), b.get("note", "")
    if not (isinstance(key, str) and key and isinstance(att, str) and att):
        return _err("war_key and attacker_tag are required", 400)
    if tgt is not None and not isinstance(tgt, str):
        return _err("target_tag must be a tag or null", 400)
    if not isinstance(note, str) or (pos is not None and (not isinstance(pos, int) or isinstance(pos, bool))):
        return _err("note must be text and target_pos a whole number", 400)
    with db.conn() as c:
        if not c.execute("SELECT 1 FROM account WHERE tag=?", (att,)).fetchone():
            return _err("Unknown account", 404)
        if not tgt:  # clearing the pick
            c.execute("DELETE FROM war_plan WHERE war_key=? AND attacker_tag=?", (key, att))
            return jsonify({"war_key": key, "attacker_tag": att, "target_tag": None})
        c.execute("INSERT INTO war_plan (war_key, attacker_tag, target_tag, target_pos, note) VALUES (?,?,?,?,?) "
                  "ON CONFLICT(war_key, attacker_tag) DO UPDATE SET target_tag=excluded.target_tag, "
                  "target_pos=excluded.target_pos, note=excluded.note", (key, att, tgt, pos, note))
    return jsonify({"war_key": key, "attacker_tag": att, "target_tag": tgt, "target_pos": pos, "note": note})
