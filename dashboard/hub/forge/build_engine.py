"""Build engine: items, boots, runes and the heal math for his locked champion.

Spec: docs/specs/2026-10-29-league-draft-design.md (vault), section 4.

    Viego    Mino's decision tree (mino_tree.decide); the statistics path when
             the Mino store has no row for someone in the draft.
    others   lolalytics slot win rate among items over MIN_GAMES, coachless WPA
             beside it in its own column, then the item rules (each names the
             enemy trait that fires it), then build legality.
    heal     Mortal Reminder against Lord Dominik's in net HP per enemy over the
             time to kill that enemy at baseline, weighted by likely role.
    runes    the best page (coachless if it has the champion, else lolalytics),
             then the rune rules in fixed priority; a rule that would break the
             page is skipped with its reason.

`run(champ, role, draft, stores)` is pure; `load_stores()` reads the files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forge import draft_engine as de  # noqa: E402
from forge import mino_tree  # noqa: E402

MIN_GAMES = 1000        # same floor as the Stats page (api.MIN_GAMES)
RULE_MIN_GAMES = 100    # an item a rule swaps in needs at least this many games on him
SLOTS = 5               # full items; boots are the sixth slot
MORTAL, DOMINIK = 3033, 3036
SMITE = 11

# Heal math (section 4). Both items carry 35 AD and 25% crit, so only their
# armor pen and passives differ; everything else cancels out of the comparison.
PEN = {MORTAL: 0.30, DOMINIK: 0.35}
WOUNDS = 0.40                       # Mortal Reminder's healing cut
GIANT_MAX, GIANT_HP = 0.15, 1500    # Giant Slayer: up to 15% at 1500 bonus HP
ROLE_WEIGHT = {"mid": 0.25, "bot": 0.25, "jungle": 0.2, "top": 0.15, "support": 0.15}
ALLY_HEAL_SHARE = 0.25              # an enemy gets a quarter of each teammate's ally heal

# Item rules: tag on the item, the enemy-team value, the floor that fires it, and why.
ITEM_RULES = (
    ("anti-heal", lambda e: e["selfHeal"] + e["allyHeal"],
     200, "Enemy heals {v:.0f} HP per 10 s between them: Grievous Wounds cuts it."),
    ("anti-shield", lambda e: e["selfShield"] + e["allyShield"],
     300, "Enemy shields {v:.0f} HP per 10 s between them: an anti-shield item eats them."),
    ("anti-HP", lambda e: e["frontline"]["sum"],
     8, "Two or more real frontliners (frontline sum {v}): bonus damage against high HP."),
)

# Rune rules, fixed priority. Each places one rune; a later rule never moves a
# rune an earlier one placed. Thresholds are heuristics read off the traits
# store's spread (per champion: burstShare median 0.45, hardCC 75th percentile
# 3 s, abilityRange 75th percentile 1200), so a team trips each about a quarter
# of the time.
SHARD_ROWS = ({5008, 5005, 5007}, {5008, 5010, 5001}, {5011, 5013, 5001})
TENACITY = 5013
# A rule may put a rune on the page only when players of this champion and role
# take it in at least this share of games under the page's keystone (heuristic:
# one game in twenty). Below it the rune is a page nobody plays, whatever the
# enemy team looks like (Bone Plating on jungle Viego is 0.3%).
RUNE_FLOOR = 0.05


RUNE_RULES = (
    ("assassins", 8465, lambda e, rows: sum(1 for r in rows if r.get("burst", 0) >= 0.6 and r.get("dive", 0) >= 3) >= 2,
     "Two or more burst divers: Guardian keeps an ally alive."),
    ("burst", 8473, lambda e, rows: e["burstShare"] >= 0.5,
     "Enemy damage is mostly burst: Bone Plating blunts the first combo."),
    ("heavy CC", 8242, lambda e, rows: e["hardCC"] >= 15,
     "Enemy has {hardCC:.0f} s of hard CC per 10 s: Unflinching."),
    ("heavy CC", TENACITY, lambda e, rows: e["hardCC"] >= 15,
     "Tenacity shard for the same CC."),
    ("poke", 8444, lambda e, rows: sum(1 for r in rows if r.get("range", 0) >= 1200) >= 2,
     "Two or more long-range casters: Second Wind heals back poke."),
    ("tanky", 8017, lambda e, rows: e["frontline"]["sum"] >= 8,
     "Tanky enemy team: Cut Down."),
    ("squishy", 8014, lambda e, rows: e["frontline"]["sum"] <= 4,
     "Squishy enemy team: Coup de Grace."),
)


# --- heal math ----------------------------------------------------------------

def heal_math(me: dict, enemies: list[dict]) -> dict:
    """me: {dps, phys} (pre-mitigation damage per second, physical share).
    enemies: [{name, hp, bonusHp, armor, heal (HP per s), weight}].
    Returns both weighted net-HP totals, per-enemy rows, gold gap and T."""
    tot = {MORTAL: 0.0, DOMINIK: 0.0}
    rows = []
    wsum = sum(e["weight"] for e in enemies) or 1.0
    for e in enemies:
        p, o = me["dps"] * me["phys"], me["dps"] * (1 - me["phys"])
        base = p * 100 / (100 + e["armor"]) + o
        t = e["hp"] / base if base else 0.0
        row = {"name": e["name"], "T": round(t, 2)}
        for item in (MORTAL, DOMINIK):
            mult = 100 / (100 + e["armor"] * (1 - PEN[item]))
            gs = GIANT_MAX * min(e["bonusHp"], GIANT_HP) / GIANT_HP if item == DOMINIK else 0.0
            dmg = t * (p * mult + o) * (1 + gs)
            heal = t * e["heal"] * (1 - WOUNDS * me["phys"] if item == MORTAL else 1)
            row["mortal" if item == MORTAL else "dominik"] = round(dmg - heal, 1)
            tot[item] += (dmg - heal) * e["weight"] / wsum
        rows.append(row)
    return {"mortal": round(tot[MORTAL], 1), "dominik": round(tot[DOMINIK], 1),
            "goldGap": 300, "T": {r["name"]: r["T"] for r in rows}, "rows": rows,
            "pick": MORTAL if tot[MORTAL] >= tot[DOMINIK] else DOMINIK,
            "assumption": "No ally applies Grievous Wounds. Wounds uptime = his physical damage share."}


def heal_inputs(me: str, enemies: dict, traits: dict) -> tuple[dict, list[dict]]:
    """Heal math inputs from the traits store, at its reference state."""
    v = lambda c, t: de._v(traits, c, t) or 0  # noqa: E731
    mine = {"dps": v(me, "damage10s") / 10, "phys": v(me, "physicalShare")}
    rows = []
    for e, role in enemies.items():
        if e not in traits:
            continue
        ally_heal = sum(v(o, "allyHeal") for o in enemies if o != e) * ALLY_HEAL_SHARE
        rows.append({"name": e, "hp": v(e, "hp"), "bonusHp": v(e, "bonusHp"), "armor": v(e, "armor"),
                     "heal": (v(e, "selfHeal") + ally_heal) / 10,
                     "weight": ROLE_WEIGHT.get(role or "", 0.2)})
    return mine, rows


# --- items --------------------------------------------------------------------

def _passives(item: dict) -> set[str]:
    return {p["h"] for p in item.get("ps") or [] if p.get("h") not in (None, "", "Active", "Passive")}


def legal(ids: list[int], catalog: dict) -> str | None:
    """None when the build is legal, else why not."""
    boots = [i for i in ids if "Boots" in (catalog.get(str(i), {}).get("t") or [])]
    if len(boots) > 1:
        return "two boots"
    seen: dict = {}
    for i in ids:
        for h in _passives(catalog.get(str(i), {})):
            if h in seen:
                return f"{catalog[str(seen[h])]['n']} and {catalog[str(i)]['n']} share {h}"
            seen[h] = i
    return None if len(set(ids)) == len(ids) else "an item twice"


def _ranked(lola: dict, slot: int, floor: int) -> list[tuple[float, int, dict]]:
    out = []
    for iid, slots in (lola.get("items") or {}).items():
        s = slots.get(str(slot))
        if s and s["n"] >= floor:
            out.append((s["wr"], int(iid), s))
    return sorted(out, reverse=True)


def stats_items(champ: str, role: str, enemy_t: dict, stores: dict) -> tuple[list, dict, list]:
    lola = ((stores["lolalytics"].get("champions") or {}).get(champ) or {}).get(role) or {}
    coach = (((stores["stats"].get("champions") or {}).get(champ) or {}).get("roles") or {}).get(role) or {}
    # Off the pool, coachless' item column comes from the every-champion roster bake.
    roster = ((((stores.get("roster") or {}).get("champions") or {}).get(champ) or {}).get(role) or {})
    wpa = {i["id"]: i for i in coach.get("items") or (roster.get("items") or {}).get("role") or []}
    cat, tags = stores["catalog"], stores["itemTraits"]
    items: list[dict] = []
    for slot in range(1, SLOTS + 1):
        # Under the floor a win rate is mostly luck, so the fallback ranks by games
        # bought, not win rate, and the row says `thin` (Sam, 2026-11-04).
        floor = sorted(_ranked(lola, slot, MIN_GAMES), key=lambda t: t[0], reverse=True)
        thin = sorted(_ranked(lola, slot, 1), key=lambda t: t[2]["n"], reverse=True)
        for wr, iid, s in floor or thin:
            if "Boots" in (cat.get(str(iid), {}).get("t") or []):
                continue
            if legal([x["itemId"] for x in items] + [iid], cat) is None:
                w = wpa.get(iid)
                why = (f"Best slot {slot} win rate on him ({wr:.1f}% over {s['n']} games)." if floor else
                       f"Most bought slot {slot} item on him ({s['n']} games, {wr:.1f}% win rate); "
                       f"no item here clears {MIN_GAMES:,} games, so this is a thin read.")
                items.append({"slot": slot, "itemId": iid, "source": "lolalytics",
                              "lolalytics": {"wr": wr, "n": s["n"]},
                              "coachless": {"wpa": w["wpa"], "n": w["n"]} if w else None,
                              "thin": not floor, "why": why})
                break
    skipped = []
    for tag, value, floor, why in ITEM_RULES:
        val = value(enemy_t)
        if val < floor:
            continue
        if any(tag in (tags.get(str(x["itemId"]), {}).get("tags") or []) for x in items):
            continue
        cands = sorted({iid for sl in range(1, SLOTS + 1) for _, iid, _ in _ranked(lola, sl, RULE_MIN_GAMES)
                        if tag in (tags.get(str(iid), {}).get("tags") or [])},
                       key=lambda i: -max((wr for sl in range(1, SLOTS + 1)
                                           for wr, j, _ in _ranked(lola, sl, RULE_MIN_GAMES) if j == i), default=0))
        placed = False
        for iid in cands:
            for x in reversed(items):
                if x["slot"] < 3:
                    break
                trial = [y["itemId"] if y is not x else iid for y in items]
                if legal(trial, cat) is None:
                    # a swapped-in item carries no slot read, so it is never `thin` (the page reads its count)
                    x.update(itemId=iid, source="rule", lolalytics=None, coachless=None, thin=False,
                             why=why.format(v=val))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            skipped.append({"rule": tag, "why": why.format(v=val) + " Skipped: no item with it that he buys and that fits."})
    boots = None
    bt = sorted(((b["wr"], int(i), b) for i, b in (lola.get("boots") or {}).items()
                 if b["n"] >= MIN_GAMES and i != "1001"), reverse=True)
    if bt:
        wr, iid, b = bt[0]
        boots = {"itemId": iid, "slot": b.get("at"), "source": "lolalytics",
                 "why": f"Best boots win rate on him ({wr:.1f}% over {b['n']} games)."}
    return items, boots, skipped


def mino_items(draft_names: dict, me_role: str, draft: dict, stores: dict) -> list | None:
    """Mino's tree, or None when the Mino store lacks someone in the draft."""
    mino = stores.get("mino") or {}
    # Mino keys its table by Data Dragon id (LeeSin); the catalog maps names to it.
    by_id = mino.get("champions") or {}
    ddid = stores.get("ddid") or {}
    rows = {n: by_id.get(ddid.get(n, n)) for n in
            [draft_names["me"], *draft_names["allies"], *draft_names["enemies"]]}
    rows = {n: r for n, r in rows.items() if r}
    names = [draft_names["me"], *draft_names["allies"], *draft_names["enemies"]]
    if not mino.get("builds") or any(n not in rows for n in names):
        return None
    # teammates' summoner spells ride along so Mino counts their Barrier
    spells = {a.get("championId"): a.get("spells") or [] for a in draft.get("allies") or []}
    by_name = {v: k for k, v in (stores.get("names") or {}).items()}
    allies = [dict(rows[draft_names["me"]], me=True)] + [
        dict(rows[a], spellIds=list(spells.get(by_name.get(a)) or rows[a].get("spellIds") or []))
        for a in draft_names["allies"]]
    enemies = []
    for e in draft_names["enemies"]:
        r = rows[e]
        if draft_names["enemyRoles"].get(e) == "jungle":
            r = dict(r, spellIds=[SMITE])     # Mino reads Smite on the enemy jungler
        enemies.append(r)
    me = draft["me"]
    return mino_tree.decide(allies, enemies, spells=me.get("spells"), runes=draft.get("runes"),
                            builds=mino["builds"])


# --- his set: counter swaps ---------------------------------------------------
# Counter items come only from his own saved set for this champion and role, with no
# lolalytics slot gate (his "only in the custom build", 2026-11-05).
SET_SKIP = {"Starting Items", "Utility", "Components"}
# A counter item is for a heavily skewed draft, never an average one (Sam,
# 2026-11-05: "you dont buy randuins into 1 crit character and 50% ad"; Randuin's is for
# a crit Yi, a crit ADC and Tryndamere together). A swap needs one counter tag whose
# threat reads SKEW or more, and its score must beat the base item's by OPP_COST, the
# price of dropping an item that serves the champion's win condition (Viego: kills).
# ponytail: both are flat heuristics on item_score's scale (a full-strength tag is 1.0);
# retune when a skewed draft fails to swap or an average one swaps.
SKEW = 0.85
OPP_COST = 1.5
MAX_SWAPS = 2   # backstop: never more than two late slots go to counters
# A burst set (no armor, MR or health in its Root/Core blocks) keeps its damage: defensive items
# in the whole build, Mino's included, are capped at 0 in an average draft, 1 when a
# threat reads SKEW, 2 only when one is fully skewed (three crit carries). Sam,
# 2026-11-05: "i am not a tank, one item, maybe 2 in the most counterable situation";
# vs MF, Yi, Vayne, Irelia, Thresh, no Death's Dance, Randuin's or GA, since the
# answer to self-peel duelists is killing them first.
CORE_BLOCKS = {"Root", "Core"}


def own_set(champ: str, role: str, sets: list[dict]) -> dict | None:
    """His newest saved set for this champion and role; autobuilt sets are not his."""
    mine = [s for s in sets if s.get("champion") == champ and s.get("role") == role and s.get("auto") is not True]
    return max(mine, key=lambda s: s.get("updated") or s.get("created") or "", default=None)


def _row(traits: dict, c: str) -> dict:
    return {"name": c, **{k: (v or {}).get("value") for k, v in (traits.get(c) or {}).items()}}


def set_swaps(items: list, boots: dict | None, sset: dict, enemies: list[str], allies: list[str],
              stores: dict) -> tuple[list, dict | None]:
    """Score every build item against the draft; swap in set items that clearly beat a
    slot-3+ item (or the boots) and keep the build legal. Every item gains `counter`."""
    from forge import build_styles as bs
    cat, traits = stores["catalog"], stores["traits"]
    er = [_row(traits, e) for e in enemies if e in traits]
    th = bs.threats(er, [_row(traits, a) for a in allies if a in traits])
    n = len(er) or 1
    phys = sum(r.get("physicalShare") or 0 for r in er) / n
    magic = sum(r.get("magicShare") or 0 for r in er) / n

    def score(iid):
        it = cat.get(str(iid))
        return bs.item_score(it, th, phys, magic) if it else (0.0, [])

    def skewed(iid):
        """A counter tag on the item whose threat is heavily skewed in this draft."""
        n_ = (cat.get(str(iid)) or {}).get("n", "")
        return any(th.get(t, (0.0, ""))[0] >= SKEW for t in bs.counter_tags(n_))

    def defensive(iid):
        it = cat.get(str(iid)) or {}
        return "Boots" not in (it.get("t") or []) and any(
            st.endswith((" Armor", " Magic Resist", " Health")) for st in it.get("st") or [])

    burst = not any(defensive(x["id"]) for b in sset.get("blocks") or [] if b.get("type") in CORE_BLOCKS
                    for x in b.get("items") or [])
    # only threats a defensive item in his set answers can earn defense a slot
    answered = {t for b in sset.get("blocks") or [] for x in b.get("items") or [] if defensive(x["id"])
                for t in bs.counter_tags((cat.get(str(x["id"])) or {}).get("n", ""))}
    top = max((th[t][0] for t in answered if t in th), default=0.0)
    allowed = 0 if top < SKEW else 1 if top < 1.0 else 2
    n_def = lambda: sum(defensive(x["itemId"]) for x in items)  # noqa: E731

    cands, boot_cands = [], []
    for b in sset.get("blocks") or []:
        if b.get("type") in SET_SKIP:
            continue
        for x in b.get("items") or []:
            it = cat.get(str(x["id"])) or {}
            if "Boots" in (it.get("t") or []):
                if b.get("type") == "Boots" and x["id"] != "1001" and int(x["id"]) not in boot_cands:
                    boot_cands.append(int(x["id"]))
            elif (it.get("g") or 0) >= 2000 and int(x["id"]) not in cands:
                cands.append(int(x["id"]))
    for x in items + ([boots] if boots else []):
        s, w = score(x["itemId"])
        x["counter"] = {"score": s, "why": w}
    label = sset.get("name") or "your set"
    for _ in range(MAX_SWAPS):   # greedy: the biggest clear gain first
        ids = [x["itemId"] for x in items] + ([boots["itemId"]] if boots else [])
        best = None
        for x in [y for y in items if y["slot"] >= 3] + ([boots] if boots else []):
            pool = boot_cands if x is boots else cands
            for c in pool:
                if c in ids:
                    continue
                s, w = score(c)
                if not skewed(c):
                    continue
                if burst and x is not boots and defensive(c) and \
                        n_def() - defensive(x["itemId"]) + 1 > allowed:
                    continue
                gain = s - x["counter"]["score"]
                trial = [c if i == x["itemId"] else i for i in ids]
                if gain >= OPP_COST and (best is None or gain > best[0]) and legal(trial, cat) is None:
                    best = (gain, x, c, s, w)
        if best is None:
            break
        _, x, c, s, w = best
        old = {"itemId": x["itemId"], "score": x["counter"]["score"], "source": x["source"]}
        x.update(itemId=c, source="set", lolalytics=None, coachless=None, thin=False, replaced=old,
                 counter={"score": s, "why": w},
                 why=f"From {label}: this draft is skewed enough that it beats {cat.get(str(old['itemId']), {}).get('n', old['itemId'])}.")
    nm = lambda i: cat.get(str(i), {}).get("n", i)  # noqa: E731
    while burst and n_def() > allowed:
        ids = [x["itemId"] for x in items] + ([boots["itemId"]] if boots else [])
        drop = min((x for x in items if x["slot"] >= 3 and defensive(x["itemId"])),
                   key=lambda x: x["counter"]["score"], default=None)
        dmg = next((c for c in cands if c not in ids and not defensive(c) and drop and
                    legal([c if i == drop["itemId"] else i for i in ids], cat) is None), None)
        if drop is None or dmg is None:
            break
        old = {"itemId": drop["itemId"], "score": drop["counter"]["score"], "source": drop["source"], "damage": True}
        sc, w = score(dmg)
        cap = "no defensive item" if allowed == 0 else f"{allowed} defensive item{'s' * (allowed > 1)}"
        drop.update(itemId=dmg, source="set", lolalytics=None, coachless=None, thin=False, replaced=old,
                    counter={"score": sc, "why": w},
                    why=f"From {label}: damage over {nm(old['itemId'])}. A burst build takes {cap} into "
                        f"this draft; killing first is the counter.")
    return items, boots


# --- runes --------------------------------------------------------------------

def page_ok(page: dict, runes: dict) -> str | None:
    """None when the page is legal against runes.json, else why not."""
    def r(i):
        return runes.get(str(i)) or {}
    ks, prim, sec, shards = page["keystone"], page["primary"], page["secondary"], page["shards"]
    if r(ks).get("row") != 0:
        return "keystone is not a keystone"
    tree = r(ks)["tree"]
    if sorted(r(i).get("row") for i in prim) != [1, 2, 3] or any(r(i).get("tree") != tree for i in prim):
        return "primary rows are not one each from the keystone's tree"
    st = {r(i).get("tree") for i in sec}
    rows = [r(i).get("row") for i in sec]
    if len(sec) != 2 or len(st) != 1 or tree in st or 0 in rows or len(set(rows)) != 2:
        return "secondary is not two runes from one other tree in different rows"
    if len(shards) != 3 or any(s not in SHARD_ROWS[k] for k, s in enumerate(shards)):
        return "shards do not fit their rows"
    return None


def _coach_page(st: dict, keystone: int | None = None) -> dict | None:
    """The page under `keystone` when coachless has it, else the most-played keystone."""
    runes = st.get("runes") or {}
    by = runes.get("byKeystone") or {}
    # A keystone listed without its page block (9923 on some champion-roles) cannot be the base.
    ks = sorted((k for k in runes.get("keystones") or [] if str(k["id"]) in by), key=lambda k: -k["n"])
    if not ks:
        return None
    k = keystone if str(keystone) in by else ks[0]["id"]
    bk = runes["byKeystone"][str(k)]
    best = lambda lst: max(lst, key=lambda x: x["n"])["id"] if lst else None  # noqa: E731
    tree = bk["trees"][str(bk["tree"])]
    prim = [best(tree[row]) for row in ("rowOnes", "rowTwos", "rowThrees")]
    stree = max(bk["secondary"], key=lambda s: s["share"])["tree"]
    picks = sorted(((x["n"], x["id"], row) for row in ("rowOnes", "rowTwos", "rowThrees")
                    for x in bk["trees"].get(str(stree), {}).get(row, [])), reverse=True)
    sec, used = [], set()
    for _, i, row in picks:
        if row not in used and len(sec) < 2:
            sec.append(i)
            used.add(row)
    shards = [best(bk["shards"][s]) for s in ("offense", "flex", "defense")]
    return {"keystone": k, "primary": prim, "secondary": sec, "shards": shards, "source": "coachless"}


def _lola_page(lola: dict, runes_meta: dict, keystone: int | None = None) -> dict | None:
    by = lola.get("runesByKeystone") or {}
    if not by:
        return None
    k = str(keystone) if str(keystone) in by else max(by, key=lambda i: by[i]["n"])
    blk = by[k]
    tree = runes_meta[k]["tree"]
    rr = blk["runes"]

    def top(ids):
        return max(ids, key=lambda i: rr[i]["n"]) if ids else None
    prim = [top([i for i in rr if runes_meta.get(i, {}).get("tree") == tree and runes_meta[i]["row"] == row])
            for row in (1, 2, 3)]
    others = [(rr[i]["n"], i) for i in rr if runes_meta.get(i, {}).get("tree") not in (tree, 0, None)
              and runes_meta[i]["row"] > 0]
    sec_tree = runes_meta[max(others)[1]]["tree"] if others else None
    sec, used = [], set()
    for _, i in sorted(others, reverse=True):
        row = runes_meta[i]["row"]
        if runes_meta[i]["tree"] == sec_tree and row not in used and len(sec) < 2:
            sec.append(int(i))
            used.add(row)
    shards = []
    for row in SHARD_ROWS:
        ids = [i for i in row if str(i) in rr and i not in shards[-1:]]
        shards.append(max(ids, key=lambda i: rr[str(i)]["n"]) if ids else min(row))
    return {"keystone": int(k), "primary": [int(i) for i in prim if i], "secondary": sec,
            "shards": shards, "source": "lolalytics"}


def played(st: dict, lola: dict, keystone: int) -> dict[int, float]:
    """Share of this champion-role's games each rune is taken in: keystones over all
    games, every other rune and shard over games under `keystone`. The higher of
    the two sources wins; a rune neither lists is absent (not played)."""
    out: dict[int, float] = {}

    def put(i, v):
        out[int(i)] = max(out.get(int(i), 0.0), v)
    cr = st.get("runes") or {}
    ks = cr.get("keystones") or []
    tot = sum(k["n"] for k in ks)
    for k in ks:
        put(k["id"], k["n"] / tot if tot else 0.0)
    kn = next((k["n"] for k in ks if k["id"] == keystone), 0)
    bk = (cr.get("byKeystone") or {}).get(str(keystone)) or {}
    for rows in list((bk.get("trees") or {}).values()) + [bk.get("shards") or {}]:
        for lst in rows.values():
            for x in lst:
                if kn:
                    put(x["id"], x["n"] / kn)
    by = lola.get("runesByKeystone") or {}
    tot = sum(b["n"] for b in by.values())
    for k, b in by.items():
        put(k, b["n"] / tot if tot else 0.0)
    blk = by.get(str(keystone)) or {}
    for i, v in (blk.get("runes") or {}).items():
        if blk.get("n") and int(i) != keystone:
            put(i, v["n"] / blk["n"])
    return out


def place(page: dict, rune: int, runes: dict, locked: set,
          share: dict | None = None) -> tuple[dict | None, str]:
    """The page with `rune` placed, or None and why not. `share` (rune id to play
    share, from played()) picks what a secondary-tree change pairs it with."""
    share = share or {}
    m = runes.get(str(rune)) or {}
    p = {k: (list(v) if isinstance(v, list) else v) for k, v in page.items()}
    tree = runes[str(p["keystone"])]["tree"]
    if m.get("tree") == 0:
        if p["shards"][2] in locked:
            return None, "the defense shard was already set by an earlier rule"
        p["shards"][2] = rune
    elif m.get("row") == 0:
        if m["tree"] != tree:
            return None, f"{m['name']} is a keystone outside his primary tree"
        p["keystone"] = rune
    elif m.get("tree") == tree:
        k = next(n for n, i in enumerate(p["primary"]) if runes[str(i)]["row"] == m["row"])
        if p["primary"][k] in locked:
            return None, "that row was already set by an earlier rule"
        p["primary"][k] = rune
    else:
        same_tree = runes[str(p["secondary"][0])]["tree"] == m["tree"] if p["secondary"] else False
        if same_tree:
            k = next((n for n, i in enumerate(p["secondary"]) if runes[str(i)]["row"] == m["row"]),
                     min((0, 1), key=lambda n: share.get(p["secondary"][n], 0.0)))
            if p["secondary"][k] in locked:
                return None, "that secondary slot was already set by an earlier rule"
            p["secondary"][k] = rune
        else:
            if locked & set(p["secondary"]):
                return None, "the secondary tree was already set by an earlier rule"
            mates = [(share[int(i)], int(i)) for i, v in runes.items() if v.get("tree") == m["tree"]
                     and v.get("row") not in (0, m["row"]) and share.get(int(i), 0.0) >= RUNE_FLOOR]
            if not mates:
                return None, "no other rune from that tree is played enough to pair it with"
            p["secondary"] = [rune, max(mates)[1]]
    why = page_ok(p, runes)
    return (None, why) if why else (p, "")


def build_runes(champ: str, role: str, enemy_t: dict, enemy_rows: list[dict], stores: dict,
                keystone: int | None = None) -> dict:
    """`keystone` is the resolved archetype's, so the rune card and the seat's chip agree.
    With none, or one neither source has, the most-played keystone is the base."""
    runes = stores["runes"]
    st = (((stores["stats"].get("champions") or {}).get(champ) or {}).get("roles") or {}).get(role) or {}
    lola = ((stores["lolalytics"].get("champions") or {}).get(champ) or {}).get(role) or {}
    pages = {"coachless": _coach_page(st, keystone), "lolalytics": _lola_page(lola, runes, keystone)}
    base = next((p for p in pages.values() if p and p["keystone"] == keystone),
                pages["coachless"] or pages["lolalytics"])
    if not base or page_ok(base, runes):
        return {"pages": pages, "page": None, "applied": [], "skipped": [
            {"rule": "base", "why": "No legal rune page in either source for him in this role."}]}
    page, locked, applied, skipped = base, set(), [], []
    share = played(st, lola, base["keystone"])
    for name, rune, fires, why in RUNE_RULES:
        if not fires(enemy_t, enemy_rows):
            continue
        text = why.format(**{k: v for k, v in enemy_t.items() if not isinstance(v, (dict, list))})
        if rune in [page["keystone"], *page["primary"], *page["secondary"], *page["shards"]]:
            applied.append({"rule": name, "runeId": rune, "why": text + " Already on the page."})
            locked.add(rune)
            continue
        m = runes.get(str(rune)) or {}
        if m.get("tree") and m.get("row") == 0 and page["keystone"] == keystone:
            skipped.append({"rule": name, "runeId": rune, "why": f"{text} Skipped: the seat's archetype sets the keystone."})
            continue
        if share.get(rune, 0.0) < RUNE_FLOOR:
            skipped.append({"rule": name, "runeId": rune, "why": f"{text} Skipped: {champ} {role} players take it in "
                            f"{share.get(rune, 0.0):.1%} of games, under the {RUNE_FLOOR:.0%} floor."})
            continue
        new, reason = place(page, rune, runes, locked, share)
        if new is None:
            skipped.append({"rule": name, "runeId": rune, "why": f"{text} Skipped: {reason}."})
            continue
        page = new
        locked.add(rune)
        applied.append({"rule": name, "runeId": rune, "why": text})
    return {"pages": pages, "page": page, "applied": applied, "skipped": skipped}


# --- the whole run ------------------------------------------------------------

def run(champ: str, role: str, draft: dict, stores: dict, keystone: int | None = None) -> dict:
    names, traits = stores["names"], stores["traits"]
    allies = [names[a["championId"]] for a in draft["allies"]
              if a.get("championId") and not a.get("provisional") and a["championId"] in names]
    enemy_names = [names[e["championId"]] for e in draft["enemies"] if e.get("championId") in names]
    # Every enemy keeps a row; one left without a free role (two supports) weighs the default.
    roles = {e: None for e in enemy_names}
    roles.update(de.likely_roles(enemy_names, (stores.get("matchups") or {}).get("roleShares") or {},
                                 de.classes_of(stores), de.enemy_bans(draft, names)))
    enemy_t = de.team_traits(enemy_names, traits)
    enemy_rows = [{"burst": de._v(traits, e, "burstShare") or 0, "dive": de._v(traits, e, "dive") or 0,
                   "range": de._v(traits, e, "abilityRange") or 0} for e in enemy_names]

    skipped: list = []
    items = boots = None
    source = "statistics"
    if champ == "Viego":
        dn = {"me": champ, "allies": allies, "enemies": enemy_names, "enemyRoles": roles}
        tree = mino_items(dn, role, draft, stores)
        if tree is not None:
            source = "mino"
            cat = stores["catalog"]
            boots_row = next((x for x in tree if "Boots" in (cat.get(str(x["itemId"]), {}).get("t") or [])), None)
            items = [{"slot": x["slot"], "itemId": x["itemId"], "why": x["why"], "source": "mino"}
                     for x in tree if x is not boots_row]
            boots = boots_row and {"itemId": boots_row["itemId"], "slot": boots_row["slot"],
                                   "why": boots_row["why"], "source": "mino"}
        else:
            skipped.append({"rule": "mino", "why": "Mino's table lacks a champion in this draft; statistics path used."})
    if items is None:
        items, boots, s = stats_items(champ, role, enemy_t, stores)
        skipped += s
    sset = own_set(champ, role, stores.get("sets") or [])
    if sset:
        items, boots = set_swaps(items, boots, sset, enemy_names, allies, stores)
    else:
        skipped.append({"rule": "set", "why": f"No saved set of yours for {champ} {role}, so no counter swaps."})
    heal = None
    ids = {x["itemId"] for x in items}
    lola = ((stores["lolalytics"].get("champions") or {}).get(champ) or {}).get(role) or {}
    buys = {int(i) for i, sl in (lola.get("items") or {}).items()
            if sum(x["n"] for x in sl.values()) >= RULE_MIN_GAMES}
    # Only when the choice is real: either item is in his build or he buys them.
    if champ in traits and (ids | buys) & {MORTAL, DOMINIK}:
        mine, rows = heal_inputs(champ, roles, traits)
        if rows and mine["dps"]:
            heal = heal_math(mine, rows)
    r = build_runes(champ, role, enemy_t, enemy_rows, stores, keystone)
    return {"champ": champ, "role": role, "source": source, "items": items, "boots": boots,
            "set": sset and {"id": sset.get("id"), "name": sset.get("name")},
            "runes": r["page"], "runePages": r["pages"], "runeRules": r["applied"],
            "skipped": skipped + r["skipped"], "heal": heal}


def shop_id(i: int, cat: dict) -> int:
    """A mode's copy of a shop item (ARAM Hubris 126697) as the shop id (6697): "12" in
    front of an id the catalog holds. Checked 2026-11-05: the only id ARAM paths carry
    outside the catalog."""
    s = str(i)
    return int(s[2:]) if s not in cat and s.startswith("12") and s[2:] in cat else i


def mayhem(champ: str, stores: dict) -> dict:
    """ARAM: Mayhem build and augments: no runes (the mode has none), no counter swaps
    (tuned for Summoner's Rift). metasrc's Mayhem build when the bake read it, else
    the most-played lolalytics ARAM archetype, labelled ARAM."""
    row = ((stores.get("mayhem") or {}).get("champions") or {}).get(champ) or {}
    b = row.get("build")
    cat = stores["catalog"]
    is_boots = lambda i: "Boots" in (cat.get(str(i), {}).get("t") or [])  # noqa: E731
    if b:
        source, ids, games, wr, starting = "metasrc", b["items"], b.get("games"), None, b.get("starting") or []
    else:
        aram = (de.role_entries(stores, "aram", champ).get("aram") or {}).get("archetypes") or []
        top = max(aram, key=lambda a: a.get("share") or 0, default=None)
        path = ((top or {}).get("path") or [None])[-1]       # the most-played trail, at its longest
        # a sparse archetype carries no path, only its two-item core and the archetype's numbers
        source, ids, starting = "aram", (path or {}).get("items") or (top or {}).get("core") or [], []
        games, wr = (path or top or {}).get("games"), (path or top or {}).get("wr")
    ids = [shop_id(i, cat) for i in ids]
    boots = next((i for i in ids if is_boots(i)), None)
    kept = [x for x in ids if x != boots and "Consumable" not in (cat.get(str(x), {}).get("t") or [])]
    items = [{"slot": n + 1, "itemId": i, "source": source} for n, i in enumerate(kept)]
    # metasrc's top three per rarity. OP.GG's augment feed is not used: it returns
    # only its tier 3 to 5 augments, which leaves out every metasrc top pick checked.
    picks = (b or {}).get("augments") or {}
    return {"mode": "mayhem", "champ": champ, "source": source, "items": items,
            "boots": boots and {"itemId": boots, "source": source}, "starting": starting,
            "games": games, "wr": wr, "augments": picks,
            "runes": None, "skipped": [] if b else [{"rule": "mayhem", "why":
                f"metasrc had no Mayhem build for {champ}; showing the ARAM build."}]}


def load_stores() -> dict:
    s = de.load_stores()
    data = de.vault_root() / "data"
    static = Path(__file__).resolve().parent / "frontend" / "static"

    def read(p, default):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    cat = read(static / "catalog.json", {"items": []})
    s.update({
        "catalog": {i["id"]: i for i in cat["items"]},
        "ddid": {c["n"]: c["i"] for c in cat.get("champs") or []},
        "runes": read(static / "runes.json", {"runes": {}})["runes"],
        "itemTraits": read(data / "forge-item-traits.json", {"items": {}})["items"],
        "stats": read(data / "forge-stats.json", {"champions": {}}),
        "roster": read(data / "forge-stats-roster.json", {"champions": {}}),
        "lolalytics": read(data / "forge-lolalytics.json", {"champions": {}}),
        "mino": read(data / "forge-mino.json", {}),
        "sets": read(data / "forge-sets.json", {"sets": []}).get("sets") or [],
        "mayhem": read(data / "forge-mayhem.json", {"champions": {}}),
    })
    return s
