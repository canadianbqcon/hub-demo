"""Draft engine: team traits and gaps, the two pick lists, and the game plan.

Spec: docs/specs/2026-10-29-league-draft-design.md (vault), section 3 and 5.
Every score term is in percentage points of expected win rate, so they add:

    counter  lolalytics Delta 2 of the candidate against each locked enemy at that
             enemy's likely role, shrunk by games / (games + SHRINK); mean over
             locked enemies (an enemy with no reading counts 0)
    synergy  lolalytics normalised synergy Delta 2 with each locked ally at that
             ally's role (full teammate list); else OP.GG pair win rate minus the
             candidate's own role win rate (OP.GG lists only its top 10 per lane);
             shrunk the same way; mean over locked allies
    fit      +1.0 per ally-team gap the candidate fills, at most 2 (heuristic)

lolalytics and OP.GG never blend for one pair: a pair reads from lolalytics, or
when lolalytics has none, from OP.GG, and the reason line names which.

Archetypes (spec 2026-10-30 section 6): `resolve` picks one archetype per champion
(manual, in-game items, session keystone, heuristic for his champion, most-played) and
`run` reads that archetype's trait row; the queue picks the data set (`MODE_FOR_QUEUE`).

`run(draft, stores)` is pure; `load_stores()` reads the files and wires the
OP.GG cache (fetched off the request path, see OpggCache).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

SHRINK = 300            # games; a pair with 300 games keeps half its delta
ROLE_FLOOR = 0.05       # share of a champion's games in a role (same as the matchup bake)
OVERALL = 8
JOBS = ("engage", "frontline", "peel", "damage")       # tie order for the game plan
OPGG_NAME = {"Nunu & Willump": "NUNU", "Renata Glasc": "RENATA"}
OPGG_POS = {"top": "top", "jungle": "jungle", "mid": "mid", "bot": "adc", "support": "support"}

# Team gaps, heuristics the page labels "gap", never a number. Judged 0-5 traits
# are a gap when nobody on the team reaches 3; computed shares are a gap under
# their floor. `fills` is what a candidate needs to count as filling it.
GAPS = {
    "engage": ("max", 3), "peel": ("max", 3), "frontline": ("max", 3),
    "dive": ("max", 3), "zoneControl": ("max", 3),
    "magicShare": ("share", 0.25), "physicalShare": ("share", 0.25),
}
# Which enemy trait makes a job matter (section 5). Damage always matters.
THREATS = {
    "engage": lambda e: e["peel"]["max"] <= 3,              # little to stop a dive in
    "frontline": lambda e: max(e["engage"]["max"], e["dive"]["max"]) >= 3,
    "peel": lambda e: e["dive"]["max"] >= 3,
    "damage": lambda e: True,
}
SUM_TRAITS = ("selfHeal", "allyHeal", "selfShield", "allyShield", "hardCC", "softCC", "tenacityCC", "airborneCC", "suppressCC", "towerDps")
SHARE_TRAITS = ("physicalShare", "magicShare", "trueShare", "pctHealthShare", "burstShare", "aoeShare")
RUBRIC_TRAITS = ("engage", "peel", "dive", "frontline", "zoneControl")
FLAG_TRAITS = ("wallCrossing", "unstoppable", "untargetable", "spellShield", "cleanse",
               "globalPresence", "vision", "stealth", "terrain", "revive", "execute", "pets")


# queueId -> data set; anything else (or a missing id) reads ranked and says so.
# ARAM: Mayhem (2400) reads ARAM traits and archetypes; its build comes from
# build_engine.mayhem off data/forge-mayhem.json.
MODE_FOR_QUEUE = {450: "aram", 2400: "aram", 1700: "arena"}
MAYHEM_QUEUES = (2400,)
RANKED_QUEUES = (420, 440)


def _v(traits: dict, champ: str, t: str):
    return ((traits.get(champ) or {}).get(t) or {}).get("value")


def shrink(delta: float, games: int) -> float:
    return delta * games / (games + SHRINK)


# --- team side ----------------------------------------------------------------

def team_traits(champs: list[str], traits: dict) -> dict:
    """Aggregate per the spec's table. Champions without a traits row are listed
    in `excluded` instead of counting as zeros. An unknown trait value (None) is
    skipped, never added as 0; `coverage[trait]` says how many teammates were read."""
    have = [c for c in champs if c in traits]
    out: dict = {"excluded": [c for c in champs if c not in traits]}
    cov: dict = {}
    out["coverage"] = cov

    def known(t):
        vals = {c: v for c in have if (v := _v(traits, c, t)) is not None}
        cov[t] = {"known": len(vals), "of": len(have)}
        return vals

    dmg = known("damage10s")
    total = sum(dmg.values())
    for t in SHARE_TRAITS:
        sv = known(t)
        # weighted over the champions whose share and damage are both read
        w = {c: dmg[c] for c in sv if c in dmg}
        out[t] = round(sum(sv[c] * w[c] for c in w) / sum(w.values()), 3) if sum(w.values()) else 0
    for t in SUM_TRAITS:
        out[t] = round(sum(known(t).values()), 1)
    out["damage10s"] = round(total)
    for t in RUBRIC_TRAITS:
        vals = list(known(t).values())
        out[t] = {"max": max(vals, default=0), "sum": sum(vals)}
    for t in FLAG_TRAITS:
        out[t] = sum(1 for v in known(t).values() if v is True)
    early = list(known("earlyLate").values())
    out["earlyLate"] = round(sum(early) / len(early), 2) if early else 0
    out["scaling"] = {}
    for s in known("scaling").values():
        if s:
            out["scaling"][s] = out["scaling"].get(s, 0) + 1
    return out


def trait_scales(traits: dict) -> dict:
    """Each trait's fixed bar scale, from every champion in the store, so a bar
    reads against the strongest champion there is rather than the other team.
    Shares top out at 1. A team's max (rubric) is scaled to the best single
    champion; a team total to the five best added together, so only the
    strongest possible five fills the bar. Flags count champions, so 5."""
    def vals(t):
        return sorted((abs(v) for c in traits if isinstance(v := _v(traits, c, t), (int, float))
                       and not isinstance(v, bool)), reverse=True)
    out = {t: 1.0 for t in SHARE_TRAITS}
    for t in (*SUM_TRAITS, "damage10s"):
        out[t] = round(sum(vals(t)[:5]), 1) or 1.0
    for t in (*RUBRIC_TRAITS, "earlyLate"):
        out[t] = (vals(t) or [1.0])[0] or 1.0
    out.update({t: 5 for t in FLAG_TRAITS})
    return out


def gap_states(team: dict, champs: list[str]) -> dict:
    """{trait: "gap"|"partial"}. "gap" only when every teammate was read and none
    reaches the floor; "partial" when the known ones fall short but some are unknown."""
    if not champs:
        return {}
    out = {}
    for t, (kind, floor) in GAPS.items():
        v = team[t]["max"] if kind == "max" else team[t]
        if v < floor:
            c = team["coverage"][t]
            out[t] = "gap" if c["known"] == c["of"] else "partial"
    return out


def gaps(team: dict, champs: list[str]) -> list[str]:
    """Confirmed gaps only; a gap computed with an unknown teammate is in gap_states."""
    return [t for t, st in gap_states(team, champs).items() if st == "gap"]


def fills(champ: str, gap: str, traits: dict) -> bool:
    kind = GAPS[gap][0]
    v = _v(traits, champ, gap)
    if v is None:
        return False
    return v >= 3 if kind == "max" else v >= 0.5


def likely_roles(enemies: list[str], shares: dict) -> dict:
    """Greedy one-champion-per-role assignment by role share, biggest first."""
    pairs = sorted(((s, e, r) for e in enemies for r, s in (shares.get(e) or {}).items()),
                   reverse=True)
    got: dict = {}
    for _, e, r in pairs:
        if e not in got and r not in got.values():
            got[e] = r
    return got


# --- scoring ------------------------------------------------------------------

def _baseline(row: dict) -> float | None:
    """The candidate's own role win rate: the counters page headline, which the
    bake stores as `wr`. Rows baked before that fall back to reading it back out of
    Delta 2, which is only roughly WR vs X minus own role WR (Viego jungle: wr -
    delta spans 47.5 to 60.3 around a 51.46 headline)."""
    if row.get("wr") is not None:
        return row["wr"]
    vals = [p["wr"] - p["delta"] for lane in row.get("vs", {}).values()
            for p in lane.values() if p.get("delta") is not None]
    return sum(vals) / len(vals) if vals else None


def score(cand: str, role: str, enemies: dict, allies: dict, gap_list: list[str],
          stores: dict) -> dict:
    row = ((stores["matchups"].get("champions") or {}).get(cand) or {}).get(role) or {}
    opgg = stores.get("opgg") or (lambda *a: None)
    c_terms, c_src = [], set()
    for e, er in enemies.items():
        p = (row.get("vs", {}).get(er) or {}).get(e) if er else None
        if p and p.get("delta") is not None:
            c_terms.append(shrink(p["delta"], p["games"]))
            c_src.add("lolalytics")
            continue
        o = opgg("counter", cand, role, e, er)
        if o:
            c_terms.append(shrink(o["delta"], o["games"]))
            c_src.add("op.gg")
        else:
            c_terms.append(0.0)
    base = _baseline(row)
    s_terms, s_src = [], set()
    for a, ar in allies.items():
        p = (row.get("with", {}).get(ar) or {}).get(a) if ar else None
        if p:
            s_terms.append(shrink(p["delta"], p["games"]))
            s_src.add("lolalytics")
            continue
        o = opgg("synergy", cand, role, a, ar) if base is not None and ar else None
        s_terms.append(shrink(o["wr"] - base, o["games"]) if o else 0.0)
        if o:
            s_src.add("op.gg")
    filled = [g for g in gap_list if fills(cand, g, stores["traits"])]
    terms = {
        "counter": sum(c_terms) / len(c_terms) if c_terms else 0.0,
        "synergy": sum(s_terms) / len(s_terms) if s_terms else 0.0,
        "fit": min(len(filled), 2) * 1.0,
    }
    sources = {"counter": " + ".join(sorted(c_src)) or "no reading", "synergy": " + ".join(sorted(s_src)) or "no reading",
               "fit": "traits: " + (", ".join(filled) or "no gap filled")}
    top = sorted(terms, key=lambda k: -abs(terms[k]))[:2]
    reason = "; ".join(f"{k} {terms[k]:+.1f} ({sources[k]})" for k in top)
    return {"champ": cand, "total": round(sum(terms.values()), 2),
            "terms": {k: round(v, 2) for k, v in terms.items()},
            "reason": reason, "sources": sources}


# --- game plan ----------------------------------------------------------------

def _job_value(champ: str, job: str, traits: dict) -> float | None:
    return _v(traits, champ, "damage10s" if job == "damage" else job)


def _jv(champ: str, job: str, traits: dict) -> float:
    """Sort value: unknown ranks below any real value, including a proven 0."""
    v = _job_value(champ, job, traits)
    return -1 if v is None else v


def game_plan(me: str | None, allies: list[str], enemy_team: dict, provisional: bool,
              traits: dict) -> dict | None:
    if not me or me not in traits:
        return None
    team = [me] + [a for a in allies if a in traits]
    unknown = [f"{c} {j}" for j in JOBS for c in team if _job_value(c, j, traits) is None]
    best = {j: max(team, key=lambda c: _jv(c, j, traits)) for j in JOBS}
    firsts = [j for j in JOBS
              if _job_value(me, j, traits) is not None
              and _jv(me, j, traits) >= _jv(best[j], j, traits) and THREATS[j](enemy_team)]
    shared = None
    if firsts:
        job = firsts[0]
    else:
        # His best rank: the job where he sits closest to the top, ties in JOBS order.
        def rank(j):
            return sorted(team, key=lambda c: -_jv(c, j, traits)).index(me)
        job = min(JOBS, key=lambda j: (rank(j), JOBS.index(j)))
        others = [c for c in team if c != me and _job_value(c, job, traits) is not None]
        shared = max(others, key=lambda c: _jv(c, job, traits)) if others else None
    covers = {}
    for j in JOBS:
        if j == job:
            continue
        others = [a for a in allies if a in traits and _job_value(a, j, traits) is not None]
        if others:
            covers[j] = max(others, key=lambda c: _jv(c, j, traits))
    tail = ", ".join(f"{a} {j}" for j, a in covers.items())
    text = (f"Your job: {job}" + (f", shared with {shared}" if shared else "")
            + (f". Covered: {tail}." if tail else "."))
    if unknown:
        text += " Unknown, skipped: " + ", ".join(unknown) + "."
    return {"job": job, "sharedWith": shared, "covers": covers, "unknown": unknown,
            "provisional": provisional, "text": ("Provisional. " if provisional else "") + text}


# --- archetypes ---------------------------------------------------------------

def archetype_score(arch: dict, role_wr: float | None, enemy_team: dict | None) -> dict:
    """shrink(wr - roleWr, games) + counterTerm, in points. `arch["traits"]` is the
    archetype's trait row. counterTerm is pctHealthShare + trueShare when the enemy
    frontline max is at or over 3, else 0; an unknown share makes it 0 and says so."""
    notes = []
    if role_wr is None:
        notes.append("role win rate unknown, delta read as 0")
    base = shrink(arch["wr"] - role_wr, arch["games"]) if role_wr is not None else 0.0
    counter = 0.0
    if enemy_team and enemy_team["frontline"]["max"] >= 3:
        row = arch.get("traits") or {}
        vals = [(row.get(t) or {}).get("value") for t in ("pctHealthShare", "trueShare")]
        if None in vals:
            notes.append("counter term 0: pctHealthShare or trueShare unknown")
        else:
            counter = sum(vals)
    out = {"score": round(base + counter, 4), "counterTerm": counter, "label": "heuristic"}
    if notes:
        out["note"] = "; ".join(notes)
    return out


def _mode_store(stores: dict, mode: str) -> dict:
    return ((stores.get("archetypes") or {}).get("modes") or {}).get(mode) or {}


def role_entries(stores: dict, mode: str, champ: str) -> dict:
    return _mode_store(stores, mode).get(champ) or {}


def _entry(ctx: dict, mode: str, champ: str, role: str | None):
    """(role, role entry) from the archetypes store. A missing role takes the
    champion's biggest role."""
    by_role = role_entries(ctx, mode, champ)
    if role is None and by_role:
        role = max(by_role, key=lambda r: by_role[r].get("roleGames") or 0)
    return role, by_role.get(role)


def resolve(champ: str, role: str | None, mode: str, ctx: dict) -> dict:
    """One precedence list: his manual pick, observed in-game items, his session
    keystone, the heuristic ranking (his own champion only), most-played.
    ctx: archetypes (store), archetypeTraits, champions (default rows), picks,
    ingame, keystone, enemyTeam, me. Returns archetype (the store row or None),
    why, state, traits (its trait row), role, and a note when something is missing."""
    role, entry = _entry(ctx, mode, champ, role)
    arches = (entry or {}).get("archetypes") or []
    if not arches:
        row = (ctx.get("champions") or {}).get(champ) if mode == "ranked" else None
        return {"archetype": None, "why": "most-played", "state": "stale" if row else "unavailable",
                "traits": row, "role": role, "note": "no archetype for this role, default row"
                if row else "no archetype and no default row"}
    by_id = {a["id"]: a for a in arches}

    def most(cands):                                    # most games; list order breaks a dead tie
        return max(cands, key=lambda a: a.get("games") or 0)

    pick, note = None, None
    if (ctx.get("picks") or {}).get(champ) in by_id:
        pick, why = by_id[ctx["picks"][champ]], "yours"
    elif (ctx.get("ingame") or {}).get(champ) in by_id:
        pick, why = by_id[ctx["ingame"][champ]], "items"
    else:
        mine = champ == ctx.get("me")
        ks = [a for a in arches if a.get("keystone") == ctx.get("keystone")] if mine and ctx.get("keystone") else []
        if ks:
            pick, why = most(ks), "keystone"
        elif mine:
            ranked = [(archetype_score(dict(a, traits=_row(ctx, mode, champ, role, a)), entry.get("roleWr"),
                                       ctx.get("enemyTeam")), a) for a in arches]
            sc, pick = max(ranked, key=lambda x: (x[0]["score"], x[1].get("games") or 0))
            why, note = "heuristic", sc.get("note")
        else:
            pick, why = most(arches), "most-played"
    row = _row(ctx, mode, champ, role, pick)
    state = pick.get("state") or entry.get("state") or "ok"
    if row is None:
        row = (ctx.get("champions") or {}).get(champ) if mode == "ranked" else None
        state, note = "stale" if row else "unavailable", "archetype has no trait row"
    return {"archetype": pick, "why": why, "state": state, "traits": row, "role": role,
            **({"note": note} if note else {})}


def _row(ctx, mode, champ, role, arch):
    return ((((ctx.get("archetypeTraits") or {}).get(mode) or {}).get(champ) or {}).get(role) or {}).get(arch["id"])


def _mode_rows(stores: dict, mode: str) -> dict:
    """Default trait row per champion for a non-ranked mode: the most-played
    archetype's row in that mode. Ranked rows never stand in (Check 10)."""
    out = {}
    for champ, roles in _mode_store(stores, mode).items():
        for role, entry in roles.items():
            arches = entry.get("archetypes") or []
            if arches:
                a = max(arches, key=lambda x: x.get("games") or 0)
                row = _row({"archetypeTraits": stores.get("archetypeTraits")}, mode, champ, role, a)
                if row is not None:
                    out[champ] = row
                    break
    return out


def mode_for(draft: dict) -> tuple[str, str | None]:
    """(mode, note). Note is set when the page must say it is reading ranked data."""
    q = draft.get("queueId")
    if q in MODE_FOR_QUEUE:
        return MODE_FOR_QUEUE[q], None
    if q in RANKED_QUEUES:
        return "ranked", None
    return "ranked", ("queue unknown, reading ranked data" if q is None
                      else f"queue {q} has no data of its own, reading ranked data")


# --- the whole run ------------------------------------------------------------

def run(draft: dict, stores: dict, picks: dict | None = None, ingame: dict | None = None) -> dict:
    names = stores["names"]
    mode, mode_note = mode_for(draft)
    has_arch = stores.get("archetypes") is not None
    default_rows = stores["traits"] if mode == "ranked" else _mode_rows(stores, mode)
    traits = default_rows
    shares = stores["matchups"].get("roleShares") or {}
    me = draft["me"]
    role = me.get("role")
    my_champ = names.get(me.get("championId") or me.get("hover"))
    allies = {names[a["championId"]]: a.get("role") for a in draft["allies"]
              if a.get("championId") and not a.get("provisional") and a["championId"] in names}
    hovers = {names[a["championId"]]: a.get("role") for a in draft["allies"]
              if a.get("championId") and a.get("provisional") and a["championId"] in names}
    enemy_names = [names[e["championId"]] for e in draft["enemies"] if e.get("championId") in names]
    enemies = likely_roles(enemy_names, shares)
    enemies.update({e: None for e in enemy_names if e not in enemies})

    ally_list = list(allies) + list(hovers)
    resolved: dict = {}
    if has_arch:
        runes = draft.get("runes")
        ctx = {"archetypes": stores["archetypes"], "archetypeTraits": stores.get("archetypeTraits"),
               "champions": stores["traits"], "picks": picks, "ingame": ingame, "me": my_champ,
               "keystone": runes[0] if isinstance(runes, list) and runes else None}

        def res(champs, roles):
            for c in champs:
                resolved[c] = resolve(c, "aram" if mode == "aram" else roles.get(c), mode, ctx)
        res(enemy_names, enemies)                      # enemies first: the heuristic reads their team
        traits = {**default_rows, **{c: r["traits"] for c, r in resolved.items() if r["traits"]}}
        ctx["enemyTeam"] = team_traits(enemy_names, traits)
        res(([my_champ] if my_champ else []) + ally_list, {**allies, **hovers, my_champ: role})
        traits = {**default_rows, **{c: r["traits"] for c, r in resolved.items() if r["traits"]}}
    ally_t = team_traits(([my_champ] if my_champ else []) + ally_list, traits)
    enemy_t = team_traits(enemy_names, traits)
    gap_state = gap_states(ally_t, ally_list)
    gap_list = [t for t, st in gap_state.items() if st == "gap"]
    # A candidate replaces his unlocked hover, so it is scored on the team without it:
    # otherwise hovering Leona fills engage and zeroes her own fit.
    fit_gaps = gap_list if me.get("championId") or not my_champ else \
        gaps(team_traits(ally_list, traits), ally_list)
    excluded = {"ally": ally_t["excluded"], "enemy": enemy_t["excluded"]}
    scales = (stores.get("traitScales") if mode == "ranked" else None) or trait_scales(default_rows)
    sstores = {**stores, "traits": traits}             # fit reads the resolved rows
    trait_rows = [{"name": t, "ally": ally_t[t], "enemy": enemy_t[t], "gap": t in gap_list, "gapState": gap_state.get(t),
                   "coverage": {"ally": ally_t["coverage"].get(t), "enemy": enemy_t["coverage"].get(t)},
                   "excluded": excluded, "scale": scales.get(t)}
                  for t in (*SHARE_TRAITS, "damage10s", *SUM_TRAITS, *RUBRIC_TRAITS,
                            *FLAG_TRAITS, "earlyLate", "scaling")]

    taken = set(enemy_names) | set(allies) | {names.get(b) for b in draft.get("bans") or []}
    if me.get("championId"):
        taken.add(my_champ)
    pool = [c for c in stores.get("pool") or [] if c not in taken]
    no_data, scored = [], []
    for cand in sorted(set(names.values()) - taken):
        in_pool = cand in pool
        if not in_pool and (shares.get(cand) or {}).get(role, 0) < ROLE_FLOOR:
            continue
        has = cand in traits and role in ((stores["matchups"].get("champions") or {}).get(cand) or {})
        if not has:
            no_data.append(cand)
            continue
        scored.append(score(cand, role, enemies, allies, fit_gaps, sstores))
    scored.sort(key=lambda s: -s["total"])
    pool_rows = [s for s in scored if s["champ"] in pool]
    pool_rows += [{"champ": c, "total": None, "terms": {}, "reason": "no data", "sources": {}}
                  for c in pool if c in no_data]

    provisional = len(enemy_names) < 5 or not me.get("championId")
    return {
        "role": role, "me": my_champ,
        "teams": {"ally": ally_t, "enemy": enemy_t, "enemyRoles": enemies},
        "traits": trait_rows, "gaps": gap_list, "gapStates": gap_state,
        "overall": scored[:OVERALL], "pool": pool_rows, "noData": no_data,
        "plan": game_plan(my_champ, ally_list, enemy_t, provisional, traits),
        "mode": mode, "modeNote": mode_note, "queueId": draft.get("queueId"),
        "archetypes": {c: {"id": (r["archetype"] or {}).get("id"), "why": r["why"], "state": r["state"],
                           "note": r.get("note")} for c, r in resolved.items()},
    }


# --- stores and the OP.GG cache -------------------------------------------------

class OpggCache:
    """OP.GG off the request path. `__call__` answers from the cache or returns
    None and starts one background fetch for that key; the page's next poll has
    it. Entries live 6 h, keyed by (champion, role, patch)."""

    TTL = 6 * 3600
    FAIL_TTL = 300          # a failed fetch waits this long, not one 0.5 s poll
    WORKERS = 4             # a pool with no `with` rows asks for about 236 fetches at once

    def __init__(self, patch: str | None):
        self.patch = patch
        self._data: dict = {}
        self._busy: set = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(self.WORKERS, thread_name_prefix="opgg")
        self.fetched_at: float | None = None

    def __call__(self, kind, cand, role, other, other_role):
        # ponytail: synergy only; OP.GG publishes 3+3 counters per champion with
        # no stated side, so the counter fallback has no source yet.
        if kind != "synergy":
            return None
        key = (cand, role, other_role, self.patch)
        with self._lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < (self.TTL if hit[1] else self.FAIL_TTL):
                return hit[1].get(other)
            if key in self._busy:
                return None
            self._busy.add(key)
        self._pool.submit(self._load, key)
        return None

    def _load(self, key):
        try:
            got = _opgg_synergies(key[0], key[1], key[2])
        except Exception:                             # noqa: BLE001 - retried after FAIL_TTL
            got = None
        with self._lock:
            self._busy.discard(key)
            self._data[key] = (time.time(), got or {})
            if got is not None:
                self.fetched_at = time.time()      # epoch seconds, as the page's ago() reads it


def _opgg_synergies(cand: str, role: str, other_role: str) -> dict:
    """{ally name: {wr, games}} for one candidate-role against one ally role."""
    hub = str(Path(__file__).resolve().parents[1])
    if hub not in sys.path:
        sys.path.insert(0, hub)
    from forge import opgg_me
    up = OPGG_NAME.get(cand) or "".join(ch for ch in cand.upper().replace(" ", "_") if ch.isalnum() or ch == "_")
    r = opgg_me.call("lol_get_champion_synergies", timeout=3, champion=up, my_position=OPGG_POS[role],
                     synergy_position=OPGG_POS[other_role],
                     desired_output_fields=["data.synergies[].{synergy_champion_name,play,win_rate}"])
    return {s["synergy_champion_name"]: {"wr": s["win_rate"] * 100, "games": s["play"]}
            for s in r["data"]["synergies"]}


_cache: OpggCache | None = None


def load_stores() -> dict:
    global _cache
    data = vault_root() / "data"

    def read(name, default):
        p = data / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    cat = json.loads((Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json")
                     .read_text(encoding="utf-8"))
    matchups = read("forge-matchups.json", {"champions": {}, "roleShares": {}})
    traits = read("forge-traits.json", {"champions": {}})
    if _cache is None or _cache.patch != matchups.get("patch"):
        _cache = OpggCache(matchups.get("patch"))
    return {
        "names": {c["k"]: c["n"] for c in cat["champs"]},
        "catalogChamps": cat["champs"],
        "traits": traits["champions"],
        "traitsPatch": traits.get("patch"),
        "traitsGeneration": traits.get("generation"),
        "traitScales": trait_scales(traits["champions"]),
        "archetypes": read("forge-archetypes.json", None),       # absent until baked
        "archetypeTraits": traits.get("archetypes"),
        "matchups": matchups,
        "pool": read("forge-draft.json", {"pool": []})["pool"],
        "opgg": _cache,
    }
