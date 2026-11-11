"""Static Clash of Clans game data (npm clash-of-clans-data, home village), read from gamedata/home/**."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

GAMEDATA = Path(__file__).resolve().parent / "gamedata"
ICONS = Path(__file__).resolve().parent / "frontend" / "static" / "icons"

# Each category stores a level's cost and time under its own keys; first present wins.
_COST = (("buildCost", "buildCostResource", "buildTime"),
         ("upgradeCost", "upgradeCostResource", "upgradeTime"),
         ("researchCost", "researchCostResource", "researchTime"))


def _secs(t) -> int:
    t = t or {}
    return t.get("days", 0) * 86400 + t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)


def _level(raw: dict) -> dict:
    cost, res, secs = 0, None, 0
    for ck, rk, tk in _COST:
        if ck in raw or tk in raw:
            cost, res, secs = raw.get(ck, 0), raw.get(rk), _secs(raw.get(tk))
            break
    return {"level": raw["level"], "buildCost": cost, "buildCostResource": res, "buildTime": secs,
            "townHallLevel": raw.get("townHallRequired")}


def _camel(s: str) -> str:
    a = s.split("-")
    return a[0] + "".join(w.title() for w in a[1:])


CRAFTED_TH = 18  # Crafting Station's Town Hall (crafting-station.json availablePerTownHall); modules carry none


def _supercharge(d: dict) -> None:
    """Supercharge tiers come after the max as levels 1, 2 flagged supercharge: renumber them max+1, max+2 so
    timers, queue, caps and plan run on one level line. `sc_base` (the last normal level) is the label's split."""
    lv = d.get("levels") or []
    base = max((l["level"] for l in lv if not l.get("supercharge")), default=0)
    if base and any(l.get("supercharge") for l in lv):
        d["sc_base"] = base
        d["levels"] = [l if not l.get("supercharge") else {**l, "level": base + l["level"]} for l in lv]


def _modules(d: dict) -> list:
    """A crafted defense's three modules as entities of their own: the export levels each module by its dataId."""
    return [{"dataId": m["dataId"], "id": d["id"], "name": f"{d['name']} {m['name']}", "category": "crafted-module",
             "levels": [{**u, "townHallRequired": CRAFTED_TH} for u in m.get("upgrades", [])]}
            for m in d.get("modules") or [] if isinstance(m.get("dataId"), int)]


@lru_cache(maxsize=None)
def _index(root: str = str(GAMEDATA)) -> dict:
    out = {}
    for f in Path(root, "home").rglob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            continue
        for m in _modules(d):
            out[m["dataId"]] = m
        if d.get("dataId") is not None:
            _supercharge(d)
            out[d["dataId"]] = d
    return out


def sc_base(data_id: int) -> int | None:
    """Last normal level when the structure has supercharge tiers above it, else None."""
    d = _index().get(int(data_id))
    return d.get("sc_base") if d else None


def reload() -> None:
    _index.cache_clear()
    _icons.cache_clear()
    version.cache_clear()
    reload_api()


def entity(data_id: int) -> dict:
    d = _index()[int(data_id)]
    return {"data_id": d["dataId"], "id": d["id"], "name": d["name"], "category": d["category"],
            "levels": [_level(l) for l in d.get("levels", [])]}


def count_for_th(data_id: int, th: int) -> int:
    rows = [r for r in _index()[int(data_id)].get("availablePerTownHall", []) if r["townHallLevel"] <= th]
    return rows[-1]["count"] if rows else 0


def _hero_hall() -> list:
    return next(x for x in _index().values() if x["id"] == "hero-hall")["levels"]


@lru_cache(maxsize=None)
def _api_hero_max() -> dict:
    """data_id -> official API hero maxLevel, from every cached /players/ body; {} with no store or no data."""
    from . import db  # ponytail: lazy import, db is only needed once the Hub has a store
    if db._db_path is None or not db._db_path.exists():
        return {}
    ids = {d["name"]: d["dataId"] for d in _index().values() if d["category"] == "hero"}
    out = {}
    with db.conn() as c:
        rows = c.execute("SELECT ok_body FROM api_cache WHERE path LIKE '/players/%' AND ok_body IS NOT NULL").fetchall()
    for (body,) in rows:
        for h in (json.loads(body).get("heroes") or []):
            did = ids.get(h.get("name"))
            if did is not None and isinstance(h.get("maxLevel"), int):
                out[did] = max(out.get(did, 0), h["maxLevel"])
    return out


def reload_api() -> None:
    """Call after a new /players/ body lands in api_cache."""
    _api_hero_max.cache_clear()
    unlock_th.cache_clear()


def max_level(data_id: int, th: int) -> int:
    d = _index()[int(data_id)]
    lv = d.get("levels", [])
    if d["category"] == "hero":  # levels carry no TH; the Hero Hall caps them
        key = _camel(d["id"])
        hall = _hero_hall()
        caps = [h["heroLevelCaps"].get(key, 0) for h in hall if (h.get("townHallRequired") or 0) <= th]
        cap = max(caps, default=0)
        # The API's maxLevel is the hero's overall max, which is the cap only at the top Town Hall.
        # The package lags game updates (0.19.1 has King 105 at TH18, the game 110), so the API wins there.
        if th >= max((h.get("townHallRequired") or 0) for h in hall):
            cap = max(cap, _api_hero_max().get(d["dataId"], 0))
        return min(cap, len(lv))
    ok = [l["level"] for l in lv if (l.get("townHallRequired") or 0) <= th]
    return max(ok, default=0)


@lru_cache(maxsize=None)
def _icons() -> dict:
    # one listing at start, not a stat per structure per poll: 190 stats on /mnt/c were 2.4 s of every village poll (2026-11-11)
    return {p.name: int(p.stat().st_mtime) for p in ICONS.glob("i-*.png")}


def icon_file(name: str) -> str | None:
    """`name?v=<mtime>`, or None when the icon is missing. The matching ?v= is what app.py serves as
    immutable, so a page open stops revalidating ~130 icons one round trip each."""
    v = _icons().get(name)
    return None if v is None else f"{name}?v={v}"


def icon(data_id: int) -> str | None:
    d = _index().get(int(data_id))
    return icon_file(f"i-{d['id']}.png") if d else None


def warm() -> None:
    """Load the package and icon list in the background at Hub start: the cold rglob over /mnt/c is ~3.5 s,
    which the first /clash/ open after a restart otherwise pays. Called from app.py's serving block only."""
    import threading
    threading.Thread(target=lambda: (_index(), _icons(), version()), daemon=True, name="clash-gamedata-warm").start()


@lru_cache(maxsize=None)
def version() -> str:
    return (GAMEDATA / "VERSION").read_text().strip()



@lru_cache(maxsize=None)
def unlock_th(data_id: int, level: int) -> int | None:
    """Lowest Town Hall whose cap reaches `level`, or None when no Town Hall does."""
    return next((t for t in range(1, 31) if max_level(data_id, t) >= level), None)
