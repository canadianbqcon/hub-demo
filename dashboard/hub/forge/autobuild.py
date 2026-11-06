"""Autobuild: turn the stores the advice engines already load into saved-set bodies.

Pure, no I/O. `generate` returns the bodies `api._save` accepts, one outcome per
source (what was built, skipped or unavailable and why) and the item ids the
catalog does not know. Spec: docs/specs/2026-11-04-forge-autobuild-design.md.
"""
from __future__ import annotations

from . import build_engine
from .bake_lolalytics import CAPS, slug

MIN_GAMES = build_engine.MIN_GAMES  # a test pins it equal to api.MIN_GAMES
BLOCK_ORDER = ("Boots", "Core", "Post-Core", "Niche")
NOT_ITEMS = {"Jungle", "Trinket", "Consumable"}  # starting pets and wards are not Core or Post-Core
SPELL_NOTE = "Read on its own across all games, not as an observed pair with the other spell."


def _pct(wr, n, lead):
    return f"{lead}: {wr:.1f}% win rate over {n:,} games"


def _caps(champ):
    return CAPS.get(slug(champ), (5, 5, 5, 3))


def _skills_ok(order, champ):
    """18 letters of QWER, each within the champion's rank cap."""
    c = dict(zip("QWER", _caps(champ)))
    return (isinstance(order, str) and len(order) == 18
            and all(ch in c and order.count(ch) <= c[ch] for ch in set(order)))


def _rune_page(page, runes):
    """(runes body without shards, None) for a legal [keystone, p1, p2, p3, s1, s2], else (None, why)."""
    if not isinstance(page, (list, tuple)) or len(page) != 6:
        return None, "rune page is not keystone, 3 primary and 2 secondary"
    ks, rows, sec = page[0], list(page[1:4]), list(page[4:6])
    m = lambda i: runes.get(str(i)) or {}  # noqa: E731
    if not all(m(i) for i in page):
        return None, "rune page holds a rune missing from the rune catalog"
    tree, stree = m(ks).get("tree"), m(sec[0]).get("tree")
    if (m(ks).get("row") != 0 or not tree or stree in (tree, None, 0)
            or any(m(i).get("tree") != tree or m(i).get("row") != r for i, r in zip(rows, (1, 2, 3)))
            or any(m(i).get("tree") != stree for i in sec) or m(sec[0]).get("row") == m(sec[1]).get("row")):
        return None, "rune page does not fit the rune trees"
    return {"primary": tree, "keystone": ks, "rows": rows, "secondary": stree, "sec": sec}, None


def _shards(lola_runes):
    """Most-picked shard per row from the role's rune picks (percent of games).
    5008 and 5001 sit in two rows each, so the shared id's pick is split by what
    the row's own ids leave of 100. A row with no reading is left out."""
    if not lola_runes:
        return {}
    p = lambda i: (lola_runes.get(str(i)) or {}).get("pick") or 0  # noqa: E731
    off8 = max(0.0, 100 - p(5005) - p(5007))
    def5001 = max(0.0, 100 - p(5011) - p(5013))
    rows = {"offense": {5005: p(5005), 5007: p(5007), 5008: off8},
            "flex": {5010: p(5010), 5008: max(0.0, p(5008) - off8), 5001: max(0.0, p(5001) - def5001)},
            "defense": {5011: p(5011), 5013: p(5013), 5001: def5001}}
    if not lola_runes:
        return {}
    return {k: max(v, key=v.get) for k, v in rows.items() if max(v.values()) > 0}


def _block_items(entries, catalog, dropped, placed):
    """[{id, count, note?}] from (id, note) pairs: catalog misses go to `dropped`, each id once."""
    out = []
    for i, note in entries:
        i = str(i)
        if i in placed:
            continue
        if i not in catalog:
            if i not in dropped:
                dropped.append(i)
            continue
        placed.add(i)
        out.append({"id": i, "count": 1, **({"note": note} if note else {})})
    return out


def _blocks(spec, catalog, dropped):
    placed: set = set()
    blocks = [{"type": t, "items": _block_items(spec.get(t, []), catalog, dropped, placed)} for t in BLOCK_ORDER]
    return [b for b in blocks if b["items"]]


def _plan(spells, skills, spell_notes=None):
    return {"spells": list(spells or []), "spellNotes": spell_notes or {}, "skills": list(skills or ""), "paths": []}


def _body(champ, role, name, key, patch, rune_body, blocks, plan, sources, champ_id):
    return {"name": name, "patch": patch, "champion": champ, "role": role,
            "champions": [champ_id] if champ_id else [], "blocks": blocks, "runes": rune_body,
            "plan": plan, "autoKey": key, "sources": sources}


def _lolalytics(champ, role, stores, patch, champ_id, bodies, outcomes, dropped):
    arch = ((((stores.get("archetypes") or {}).get("modes") or {}).get("ranked") or {}).get(champ) or {}).get(role) or {}
    ok = [a for a in arch.get("archetypes") or [] if a.get("state") == "ok"]
    if not ok:
        outcomes.append({"source": "lolalytics", "key": "lolalytics", "state": "unavailable",
                         "why": "no readable archetype for this champion and role"})
        return
    lola = ((stores["lolalytics"].get("champions") or {}).get(champ) or {}).get(role) or {}
    catalog, runes = stores["catalog"], stores["runes"]
    groups: dict = {}
    for a in sorted(ok, key=lambda a: (-a["games"], -a["wr"], a["id"])):
        groups.setdefault(a["keystone"], []).append(a)  # each group: base first, then games order
    shards = _shards(lola.get("runes"))
    spells = ((lola.get("plan") or {}).get("spells") or {}).get("ids")
    for ks, grp in sorted(groups.items(), key=lambda kv: -kv[1][0]["games"]):
        key, base = f"lola:{ks}", grp[0]
        kname = (runes.get(str(ks)) or {}).get("name") or str(ks)
        rune_body, why = _rune_page((base.get("runes") or {}).get("page"), runes)
        if not rune_body or rune_body["keystone"] != ks:
            outcomes.append({"source": "lolalytics", "key": key, "state": "unavailable",
                             "why": why or "rune page keystone differs from the archetype's"})
            continue
        rune_body = {**rune_body, "shards": shards, "scope": "role-wide"}
        boots = base.get("boots") or {}
        brow = (lola.get("boots") or {}).get(str(boots.get("id"))) or {}
        spec = {"Boots": [(boots["id"], _pct(brow["wr"], brow["n"], "boots in this role") if brow.get("n") else None)]
                if boots.get("id") else [],
                "Core": [(i, _pct(base["wr"], base["games"], "this core")) for i in base["core"]],
                "Post-Core": [(i, _pct(r["wr"], r["games"], "build path to here"))
                              for r in (base.get("full") or []) + (base.get("path") or [])
                              for i in r["items"][len(base["core"]):]],
                "Niche": [(i, _pct(o["wr"], o["games"], "this core")) for o in grp[1:] for i in o["core"]]}
        before = len(dropped)
        blocks = _blocks(spec, catalog, dropped)
        if not any(b["type"] == "Core" for b in blocks):
            outcomes.append({"source": "lolalytics", "key": key, "state": "unavailable",
                             "why": "no core item is in the catalog"})
            continue
        order = (base.get("skills") or {}).get("order")
        skills = order if _skills_ok(order, champ) else None
        missing = [n for n, ok_ in (("spells", spells), ("shards", len(shards) == 3), ("skills", skills)) if not ok_]
        bodies.append(_body(champ, role, f"Auto {kname} {champ} {role.capitalize()}", key, patch, rune_body, blocks,
                            _plan(spells, skills), {"archetypes": base.get("patch") or arch.get("patch"),
                                                    "lolalytics": lola.get("patch")}, champ_id))
        outcomes.append({"source": "lolalytics", "key": key, "state": "built",
                         "why": "built" + (f"; not read: {', '.join(missing)}" if missing else "")
                         + (f"; {len(dropped) - before} item ids not in the catalog" if len(dropped) > before else "")})


def _coachless(champ, role, stores, pool, patch, champ_id, bodies, outcomes, dropped):
    def out(state, why):
        outcomes.append({"source": "coachless", "key": "coachless", "state": state, "why": why})
    if champ not in pool:
        return out("skipped", "not in the pool")
    st = ((((stores["stats"].get("champions") or {}).get(champ) or {}).get("roles") or {}).get(role))
    page = build_engine._coach_page(st, None) if st else None
    if not page:
        return out("unavailable", "coachless has no rune reading for this role")
    catalog, runes = stores["catalog"], stores["runes"]
    ks = page["keystone"]
    rune_body, why = _rune_page([ks, *page["primary"], *page["secondary"]], runes)
    if not rune_body or len(page["shards"]) != 3 or not all(page["shards"]):
        return out("unavailable", why or "coachless page has no 3 shards")
    rune_body = {**rune_body, "shards": dict(zip(("offense", "flex", "defense"), page["shards"])), "scope": "role-wide"}
    own = (st.get("itemsByKeystone") or {}).get(str(ks)) or None
    rows = sorted((r for r in own or st.get("items") or [] if (r.get("n") or 0) >= MIN_GAMES),
                  key=lambda r: -r["share"])
    tags = lambda r: set((catalog.get(str(r["id"])) or {}).get("t") or [])  # noqa: E731
    note = lambda r: f"{r['wrPost']}% win rate over {r['n']:,} games"  # noqa: E731
    boots = [r for r in rows if "Boots" in tags(r)][:1]
    rest = [r for r in rows if "Boots" not in tags(r) and not tags(r) & NOT_ITEMS and str(r["id"]) in catalog]
    before = len(dropped)
    for r in rows:  # catalog misses are listed, not shown
        if str(r["id"]) not in catalog and str(r["id"]) not in dropped:
            dropped.append(str(r["id"]))
    spec = {"Boots": [(r["id"], note(r)) for r in boots],
            "Core": [(r["id"], note(r)) for r in rest[:3]],
            "Post-Core": [(r["id"], note(r)) for r in rest[3:6]]}
    blocks = _blocks(spec, catalog, dropped)
    if not any(b["type"] == "Core" for b in blocks):
        return out("unavailable", "no item reached the minimum games")
    spells = [r["id"] for r in sorted(st.get("spells") or [], key=lambda r: -r["share"])[:2]]
    arch = ((((stores.get("archetypes") or {}).get("modes") or {}).get("ranked") or {}).get(champ) or {}).get(role) or {}
    same = sorted((a for a in arch.get("archetypes") or [] if a.get("state") == "ok" and a["keystone"] == ks),
                  key=lambda a: (-a["games"], -a["wr"], a["id"]))
    order = ((same[0].get("skills") or {}).get("order")) if same else None
    skills = order if _skills_ok(order, champ) else None
    missing = [n for n, v in (("spells", spells), ("skills", skills)) if not v]
    kname = (runes.get(str(ks)) or {}).get("name") or str(ks)
    bodies.append(_body(champ, role, f"Auto Coachless {champ} {role.capitalize()}", "coachless", patch, rune_body,
                        blocks, _plan(spells, skills, {str(i): SPELL_NOTE for i in spells}),
                        {"coachless": stores["stats"].get("patch")}, champ_id))
    out("built", f"built under {kname}" + (f"; items are role-wide, no {kname} rows" if own is None else "")
        + (f"; not read: {', '.join(missing)}" if missing else ""))


def generate(champ: str, role: str, stores: dict, pool: dict, live: str) -> dict:
    """Bodies to save, one outcome per source, and the item ids missing from the catalog."""
    bodies, outcomes, dropped = [], [], []
    cc = stores.get("catalogChamps") or {}
    champ_id = next((c["k"] for c in (cc.values() if isinstance(cc, dict) else cc) if c.get("n") == champ), None)
    _lolalytics(champ, role, stores, live, champ_id, bodies, outcomes, dropped)
    _coachless(champ, role, stores, pool, live, champ_id, bodies, outcomes, dropped)
    return {"bodies": bodies, "outcomes": outcomes, "dropped": dropped}


def demo():
    runes = {"1": {"name": "Key", "tree": 10, "row": 0}, "2": {"tree": 10, "row": 1}, "3": {"tree": 10, "row": 2},
             "4": {"tree": 10, "row": 3}, "5": {"tree": 20, "row": 1}, "6": {"tree": 20, "row": 2}}
    cat = {"100": {"t": ["Boots"]}, "200": {"t": []}, "201": {"t": []}, "202": {"t": []}, "203": {"t": []}}

    def arch(i, core, games, path=()):
        return {"id": i, "keystone": 1, "core": core, "wr": 50.0, "games": games, "state": "ok", "patch": "1.0",
                "boots": {"id": 100}, "runes": {"page": [1, 2, 3, 4, 5, 6]},
                "path": [{"items": core + [p], "wr": 55.0, "games": 10} for p in path], "full": []}
    stores = {"archetypes": {"modes": {"ranked": {"Foo": {"top": {"archetypes": [
                  arch("a", [200, 201], 90, [202, 999]), arch("b", [200, 203], 10)]}}}}},
              "lolalytics": {"champions": {}}, "stats": {"champions": {}}, "catalog": cat, "runes": runes}
    r = generate("Foo", "top", stores, {}, "1.1")
    (b,) = r["bodies"]
    assert b["name"] == "Auto Key Foo Top" and b["patch"] == "1.1" and b["autoKey"] == "lola:1"
    got = {x["type"]: [i["id"] for i in x["items"]] for x in b["blocks"]}
    assert got == {"Boots": ["100"], "Core": ["200", "201"], "Post-Core": ["202"], "Niche": ["203"]}, got
    assert r["dropped"] == ["999"] and r["outcomes"][0]["state"] == "built", r
    assert "not read: spells, shards, skills" in r["outcomes"][0]["why"]
    assert [o["state"] for o in r["outcomes"]] == ["built", "skipped"]  # coachless: not in the pool
    assert _skills_ok("QEWQQRQEQEREEWWRWW", "Gwen") and not _skills_ok("Q" * 18, "Gwen")
    assert _skills_ok("Q" * 6 + "W" * 6 + "E" * 6, "Jayce")
    stores["runes"]["3"]["row"] = 1
    assert generate("Foo", "top", stores, {}, "1.1")["outcomes"][0]["state"] == "unavailable"
