"""Parse a pasted village export into the store. Three outcomes: rejected, applied, kept (unknown ids)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from . import db, gamedata, notify_glue

# category -> facility for its timers (None: no timers expected, a stray one is ignored)
STORED = {"buildings": "builder", "traps": "builder", "heroes": "builder", "units": "lab", "spells": "lab",
          "siege_machines": "lab", "pets": "pet_house", "equipment": None}
COSMETIC = {"decos", "obstacles", "house_parts", "skins", "sceneries"}
UNUSED = {"helper_recurrent", "guardians", "boosts", "buildings2", "traps2", "heroes2", "units2", "decos2",
          "obstacles2", "skins2", "sceneries2"}
META = {"tag", "timestamp"}


class Reject(Exception):
    pass


def _iso(ts) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime(db.FMT)


def _int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise Reject(f"{what} is not a whole number: {v!r}")
    return v


def classify(d: dict, th: int | None = None) -> dict:
    """Sort every record: applied (structures, validated), unused, cosmetic, skipped (unknown)."""
    out = {"applied": [], "helpers": 0, "unused": 0, "cosmetic": 0, "skipped": [], "records": 0}
    for cat, val in d.items():
        if cat in META:
            continue
        recs = val if isinstance(val, list) else [val]
        out["records"] += len(recs)
        if cat == "helpers":  # stored by _helpers into the helper table
            out["helpers"] += len(recs)
        elif cat in COSMETIC:
            out["cosmetic"] += len(recs)
        elif cat in UNUSED:
            out["unused"] += len(recs)
        elif cat not in STORED or not isinstance(val, list):
            out["skipped"] += [f"{cat}:{r.get('data') if isinstance(r, dict) else '?'}" for r in recs]
        else:
            for r in recs:
                if not isinstance(r, dict) or "data" not in r:
                    raise Reject(f"{cat}: record without data id")
                did = _int(r["data"], f"{cat} data id")
                if "types" in r:  # Crafting Station: each crafted defense's modules level on their own dataIds
                    mods = [m for t in r["types"] if isinstance(t, dict) for m in t.get("modules") or [] if isinstance(m, dict)]
                    for m in mods:
                        if "data" not in m:
                            raise Reject(f"{cat}: crafting module without data id")
                        mid = _int(m["data"], f"{cat} module data id")
                        if mid in gamedata._index():
                            out["applied"].append((cat, mid, m))
                        else:
                            out["skipped"].append(f"{cat}:{mid}")
                    continue
                if r.get("supercharge"):
                    # ponytail: key name unverified (no export with a supercharge seen yet, 2026-11-11); tiers sit above lvl
                    r = {**r, "lvl": _int(r.get("lvl"), f"{cat} {did} level") + _int(r["supercharge"], f"{cat} {did} supercharge")}
                try:
                    gamedata.entity(did)
                except KeyError:
                    out["skipped"].append(f"{cat}:{did}")
                    continue
                out["applied"].append((cat, did, r))
    return out


def _parse(text: str):
    try:
        d = json.loads(text)
    except (TypeError, ValueError):
        raise Reject("not JSON")
    if not isinstance(d, dict):
        raise Reject("not a village export")
    tag = d.get("tag")
    if not isinstance(tag, str) or not tag.strip("# "):
        raise Reject("no player tag")
    tag = "#" + tag.strip().lstrip("#").upper()
    ts = d.get("timestamp")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or ts <= 0:
        raise Reject("no export timestamp")
    return d, tag, int(ts)


def _build(d: dict, ts: int):
    """-> (th, skipped, structures {(did, level): cnt}, upgrades {(did, from_level, finishes_at): facility})."""
    th = next((r["lvl"] for r in d.get("buildings", []) if isinstance(r, dict) and r.get("data") == 1000001), None)
    cl = classify(d)
    if th is None:
        th = 1
    structs: dict = {}
    ups: dict = {}
    for cat, did, r in cl["applied"]:
        lvl = _int(r.get("lvl"), f"{cat} {did} level")
        cnt = _int(r.get("cnt", 1), f"{cat} {did} count")
        timer = _int(r.get("timer", 0), f"{cat} {did} timer")
        if lvl < 1:  # no upper check: the game writes the export, so a level above the bundled cap is real
            raise Reject(f"{gamedata.entity(did)['name']} level {lvl} is below 1")
        if cnt < 1:
            raise Reject(f"{gamedata.entity(did)['name']} count {cnt} is not positive")
        if timer < 0:
            raise Reject(f"{gamedata.entity(did)['name']} timer {timer} is negative")
        structs[(did, lvl)] = structs.get((did, lvl), 0) + cnt  # a gear_up copy sits at its own level
        if timer and STORED[cat]:
            ups[(did, lvl, _iso(ts + timer))] = STORED[cat]
    return th, cl["skipped"], structs, ups


def _helpers(d: dict, ts: int) -> list[tuple]:
    """-> [(data_id, level, ready_at|None)]; a malformed helper record is dropped, never a reject."""
    out = []
    for r in d.get("helpers") or []:
        if not isinstance(r, dict):
            continue
        did, lvl, cd = r.get("data"), r.get("lvl"), r.get("helper_cooldown")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (did, lvl)) or lvl < 1:
            continue
        ok = isinstance(cd, int) and not isinstance(cd, bool) and cd >= 0 and cd <= 7 * 86400  # a helper rests a day at most
        out.append((did, lvl, _iso(ts + cd) if ok else None))
    return out


def apply(c, text: str, now) -> dict:
    now = now if isinstance(now, str) else now.astimezone(timezone.utc).strftime(db.FMT)
    res = {"status": "rejected", "reason": None, "tag": "", "added": 0, "changed": 0, "kept_unknown": 0, "skipped": []}
    try:
        d, tag, ts = _parse(text)
        res["tag"] = tag
        th, skipped, structs, ups = _build(d, ts)
        acct = c.execute("SELECT last_export_ts FROM account WHERE tag=?", (tag,)).fetchone()
        if acct and acct["last_export_ts"] and _iso(ts) < acct["last_export_ts"]:
            raise Reject(f"export is older than the last one ({acct['last_export_ts']})")
    except Reject as e:
        res["reason"] = str(e)
        return res

    unknown_ids = {int(s.split(":")[1]) for s in skipped if s.split(":")[1].isdigit()}
    seen = {did for did, _ in structs}
    drop, post = [], []
    db._begin(c)
    try:
        nb = sum(1 for f in ups.values() if f == "builder")
        c.execute("INSERT OR IGNORE INTO account (tag, builders) VALUES (?, ?)", (tag, max(nb, 2)))
        c.execute("UPDATE account SET th_level=?, last_export_ts=?, "
                  "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE tag=?", (th, _iso(ts), tag))
        old = {(r["data_id"], r["level"]): r for r in
               c.execute("SELECT * FROM structure WHERE tag=?", (tag,)) if r["data_id"] in seen}
        for k, r in old.items():
            if k not in structs:
                c.execute("DELETE FROM structure WHERE tag=? AND data_id=? AND level=?", (tag, *k))
                res["changed"] += 1
        for (did, lvl), cnt in structs.items():
            o = old.get((did, lvl))
            if o is None:
                res["added"] += 1
            elif o["cnt"] != cnt:
                res["changed"] += 1
            elif not o["predicted"]:
                continue
            c.execute("INSERT INTO structure (tag, data_id, level, cnt, predicted) VALUES (?,?,?,?,0) "
                      "ON CONFLICT(tag, data_id, level) DO UPDATE SET cnt=excluded.cnt, predicted=0, "
                      "observed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')", (tag, did, lvl, cnt))
        have = {(r["data_id"], r["from_level"], r["finishes_at"]): r for r in
                c.execute("SELECT * FROM upgrade WHERE tag=?", (tag,)) if r["data_id"] not in unknown_ids}
        for k, r in have.items():
            if k not in ups:
                c.execute("DELETE FROM upgrade WHERE id=?", (r["id"],))
                drop.append(dict(r))
        for (did, lvl, fin), fac in ups.items():
            if (did, lvl, fin) not in have:
                c.execute("INSERT INTO upgrade (tag, data_id, from_level, facility, finishes_at, source) "
                          "VALUES (?,?,?,?,?, 'export')", (tag, did, lvl, fac, fin))
                post.append({"tag": tag, "data_id": did, "from_level": lvl, "finishes_at": fin})
        for did, lvl, ready in _helpers(d, ts):
            c.execute("INSERT INTO helper (tag, data_id, level, ready_at) VALUES (?,?,?,?) ON CONFLICT(tag, data_id) "
                      "DO UPDATE SET level=excluded.level, ready_at=excluded.ready_at", (tag, did, lvl, ready))
        c.execute("INSERT INTO import_run (tag, pasted_at, export_ts, added, changed, kept_unknown, skipped_json, "
                  "data_version) VALUES (?,?,?,?,?,?,?,?)",
                  (tag, now, _iso(ts), res["added"], res["changed"], len(skipped), json.dumps(skipped),
                   gamedata.version()))
        c.commit()
    except Exception:
        c.rollback()
        raise
    for r in drop:
        notify_glue.dropped(r)
    for r in post:
        notify_glue.scheduled(r)
    res.update(status="applied", kept_unknown=len(skipped), skipped=skipped)
    return res
