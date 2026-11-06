"""The 10 s fight as an event queue: attacks and casts against one target whose
health moves, so a %-current-health hit reads the health left at that hit.

The target takes hits and never fights back, so defensive triggers cannot fire
here; they and item actives land in `excluded`. Every cast lands. An effect the
queue cannot read marks what it feeds `unknown` and names itself: never a guess.

Effect shape (bake_passives.py `effects`):
    {"trigger": "on-hit"|"every-n"|"on-cast"|"stack"|"static"|"phantom"|"rush", "n"?,
     "kind", "base"?, "ratio"?, "stat"?, "pctTarget"?, "cooldown"?, "stackMax"?,
     "duration"?, "on"?, "slot"?, "ramp"?, "whileFull"?, "condition"?, "source"}
A value is a number, {"byLevel": [18 numbers]}, or {"melee": v, "ranged": v} of
either. With `pctTarget`, `ratio` is the fraction of the target's health and
`stat` is unused. `ramp` grows the amount toward `max` as the target's health
falls. A "stack" effect adds `base` per stack to the actor's `stat` (ATTACK_SPEED
included), gaining on `on` ("hit", "cast" or "both"; "hit" by default), all
stacks dropping `duration` seconds after the last gain. A "phantom" effect applies
on-hit effects a second time every `n`th attack while the stack on `whileFull` is
full. "static" effects are stats: item_stats applies them, this queue skips them.

Keystones and passives add: kind "adaptive" (physical when bonus AD >= AP, else
magic, read once at the start); a stack `stat` "adaptive" with `adScale`, the AD
per adaptive point; `ratios` {stat: ratio}; `amp` {value, duration}, a damage
multiplier after the proc; `on` on on-hit and every-n too, where a spell only
counts if it deals damage; `delay`, no proc before that second; `below`, only
under that fraction of target health; `whileFull` on an on-hit; `out`, the amount
goes to that heal or shield total, not to damage; stack `gain` and `gainCast`;
`afterHard` on an on-cast, only on a spell with hard CC; `asScale`, the amount
grows 1% per 1% bonus attack speed; a "rush" spends `hits` attacks at `speed`
extra attack speed, past AS_CAP, dealing its amount on each. A "note" is only
named in `excluded`.
"""

from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass, field, replace

FIGHT = 10.0
BURST = 3.0
CRIT_MULT = 1.75  # crit damage; the bins still carry the legacy 2.0
AS_CAP = 2.5
KINDS = ("physical", "magic", "true")
HEALS = ("heal_self", "heal_ally", "shield_self", "shield_ally")
OUT_OF_MODEL = ("active", "defensive", "note")  # listed in `excluded`, never simulated
FEEDS = ("damage10s", "burst")  # what an unreadable effect makes unknown
NO_NUMBER = "no damage or stat number"  # bake_passives: a slow or shield, feeds no damage
AD, AP, ATTACK_SPEED = "AD", "AP", "Attack Speed"
LEVEL = 11


@dataclass
class Cast:
    """One spell. `cooldown` is after haste, None for a single cast; `charges`
    start full, as an ammo spell's do. `lines` holds per-cast amounts by name:
    KINDS, "pct", HEALS."""
    name: str
    lines: dict = field(default_factory=dict)
    cooldown: float | None = None
    cast_time: float = 0.0
    charges: int = 1
    aoe: bool = False
    hard: float = 0.0
    soft: float = 0.0
    # the part of `hard` tenacity cannot shorten: knockups, knockbacks, pulls (Airborne), suppression
    airborne: float = 0.0
    suppress: float = 0.0
    no_attacks: float = 0.0   # seconds it replaces attacks while spells stay free (Urgot W)
    # what cuts this spell's current cooldown, each {"on": "attack" | "cast", "s": seconds, "share": of the
    # cooldown, "crit": s times crit chance, "once": first attack only, "armed": the attack after a cast,
    # "while": (slot, seconds) after that slot's cast, "from": casting slots, "cc": the cast must crowd control}
    cuts: list = field(default_factory=list)


@dataclass
class Actor:
    stats: dict  # {"AD": total, "AP": total, ...}, whatever effects name in `stat`
    casts: list = field(default_factory=list)
    attack_speed: float = 0.0  # attacks per second at the start
    crit: float = 0.0
    lethality: float = 0.0
    pen: dict = field(default_factory=dict)  # {"armor_pct", "mr_pct", "mr_flat"}
    as_ratio: float = 1.0  # bonus attack speed scales by this, as the bins' ratio does
    melee: bool = True
    level: int = LEVEL


@dataclass
class Target:
    hp: float
    armor: float
    mr: float


def dummy(records: list[dict]) -> Target:
    """The roster's mean level-11 target, from bake_traits records."""
    import bake_traits  # ponytail: late, bake_traits imports this module

    n = len(records)
    stats = [bake_traits.ref_stats(r, {}) for r in records]
    return Target(sum(s[(12, 0)] for s in stats) / n, sum(s[(1, 0)] for s in stats) / n,
                  sum(s[(6, 0)] for s in stats) / n)


def post_mitigation(amount: float, kind: str, actor: Actor, target: Target) -> float:
    """Riot's order: % penetration, then flat. A resist never goes below 0 here,
    since the model has no resist shred."""
    if kind == "physical":
        left = target.armor * (1 - actor.pen.get("armor_pct", 0.0)) - actor.lethality
    elif kind == "magic":
        left = target.mr * (1 - actor.pen.get("mr_pct", 0.0)) - actor.pen.get("mr_flat", 0.0)
    else:
        return amount
    return amount * 100 / (100 + max(0.0, left))


def _num(v, actor: Actor) -> float:
    if isinstance(v, dict) and "byLevel" not in v:
        v = v.get("melee" if actor.melee else "ranged")
    if isinstance(v, dict):
        v = v["byLevel"][actor.level - 1]
    return float(v or 0.0)


def _readable(e: dict) -> bool:
    if e.get("handler", True) is None or e.get("condition"):
        return False
    if e.get("trigger") == "every-n" and not e.get("n"):
        return False
    return e.get("trigger") in ("on-hit", "every-n", "on-cast", "stack", "phantom", "rush")


def run(actor: Actor, target: Target, effects: list[dict],
        fight: float = FIGHT, burst: float = BURST) -> dict:
    dmg = dict.fromkeys(KINDS, 0.0)
    tot = dict.fromkeys(HEALS, 0.0)
    pct = post = burst_dmg = aoe = hard = soft = aoe_hard = autos = airborne = suppress = 0.0
    unknown, excluded = set(), []
    live = []
    bonus_ad, ap = actor.stats.get("bonus AD", 0.0), actor.stats.get(AP, 0.0)
    adaptive = "physical" if bonus_ad >= ap else "magic"
    for e in effects:
        if e.get("trigger") == "static":
            continue
        name = e.get("name") or e.get("source") or "unnamed effect"
        if e.get("trigger") in OUT_OF_MODEL:
            excluded.append(name)
        elif _readable(e):
            if e.get("stat") == "adaptive":
                scale = e["adScale"] if adaptive == "physical" else 1.0
                e = {**e, "stat": AD if adaptive == "physical" else AP,
                     "base": _num(e.get("base"), actor) * scale}
            live.append(e)
            # ponytail: spell lines are fixed before the run, so an in-fight AD or AP
            # stack feeds attacks and procs only. Named here; per-cast ratios lift it.
            if e.get("trigger") == "stack" and e.get("stat") in (AD, AP) and actor.casts:
                excluded.append(f"{name}: stacks not applied to spell damage")
        elif e.get("reason") == NO_NUMBER:
            excluded.append(name)
        else:
            unknown |= {name, *e.get("feeds", FEEDS)}
    hp = target.hp
    hits = 0
    busy = 0.0  # a cast locks the actor until here
    no_attacks = 0.0
    bonus, stacks, gen = {}, {}, {}
    last_proc, full_hits, counts, rush = {}, {}, {}, {}
    amp_until, amp = 0.0, 0.0

    def full(gate: dict) -> bool:
        """The gated effect's own stack, by stat and source: Lethal Tempo and Guinsoo's
        both stack Attack Speed and must not open each other."""
        return any(e["trigger"] == "stack" and e.get("stat") == gate["whileFull"]
                   and e.get("source") == gate.get("source")
                   and stacks.get(i, 0) >= (e.get("stackMax") or 1) for i, e in enumerate(live))

    def stat(name: str) -> float:
        return actor.stats.get(name, 0.0) + bonus.get(name, 0.0)

    def deal(kind: str, amount: float, t: float, area: bool = False) -> None:
        nonlocal hp, post, burst_dmg, aoe
        if t < amp_until:
            amount *= 1 + amp
        dmg[kind] += amount
        taken = post_mitigation(amount, kind, actor, target)
        post += taken
        # ponytail: a dead target stays at 0, so %-current lines stop; a respawn or
        # second target would need a per-fight target list if that undercounts.
        hp = max(0.0, hp - taken)
        if t < burst:
            burst_dmg += amount
        if area:
            aoe += amount

    def ready(i: int, e: dict, t: float) -> bool:
        cd = _num(e.get("cooldown"), actor)
        if cd and i in last_proc and t - last_proc[i] < cd:
            return False
        if t < e.get("delay", 0.0) or (e.get("whileFull") and not full(e)):
            return False
        return not e.get("below") or hp < e["below"] * target.hp

    def fire(e: dict, t: float) -> None:
        nonlocal pct, amp_until, amp
        amount = _num(e.get("base"), actor)
        ratio = _num(e.get("ratio"), actor)
        if e.get("pctTarget"):
            health = {"current": hp, "max": target.hp, "missing": target.hp - hp}[e["pctTarget"]]
            extra = ratio * health
            pct += extra
            amount += extra
        elif e.get("stat"):
            amount += ratio * stat(e["stat"])
        for name, r in (e.get("ratios") or {}).items():
            amount += _num(r, actor) * stat(name)
        ramp = e.get("ramp")
        if ramp:
            missing = 1 - hp / target.hp
            amount += (_num(ramp["max"], actor) - amount) * missing
        if e.get("asScale"):
            amount *= 1 + stat(ATTACK_SPEED)
        if e.get("out"):
            tot[e["out"]] += amount
        else:
            kind = e.get("kind") or "physical"
            deal(adaptive if kind == "adaptive" else kind, amount, t)
        if e.get("amp"):
            amp_until, amp = t + e["amp"]["duration"], e["amp"]["value"]

    def proc(i: int, e: dict, t: float) -> None:
        if ready(i, e, t):
            last_proc[i] = t
            fire(e, t)

    def count(i: int, e: dict, t: float) -> None:
        """A hit toward an every-n: hits during its cooldown do not count."""
        if ready(i, e, t):
            counts[i] = counts.get(i, 0) + 1
            if counts[i] % e["n"] == 0:
                proc(i, e, t)

    def gain_stack(i: int, e: dict, t: float, gain=1) -> None:
        if e.get("cooldown"):
            if not ready(i, e, t):
                return
            last_proc[i] = t
        n = stacks.get(i, 0)
        add = min(int(_num(gain, actor)), (e.get("stackMax") or 1) - n)
        if add > 0:
            stacks[i] = n + add
            bonus[e["stat"]] = bonus.get(e["stat"], 0.0) + add * _num(e.get("base"), actor)
        if e.get("duration"):
            gen[i] = gen.get(i, 0) + 1
            push(t + e["duration"], "expire", (i, gen[i]))

    # ties run in push order, and casts go in before the first attack
    queue, seq = [], 0

    def push(t: float, what: str, data=None) -> None:
        nonlocal seq
        if t < fight:
            seq += 1
            heapq.heappush(queue, (t, seq, what, data))

    # a cast's cooldown event carries a generation; a cut pushes a sooner one and the old one is skipped
    due, cast_at, used, counts_by = {}, {}, set(), {}
    armed = False

    def cut(on: str, t: float, src: Cast | None = None) -> None:
        for c in actor.casts:   # charge copies are not in casts, so only the recharging charge is cut
            for n, r in enumerate(c.cuts):
                if r["on"] != on or r.get("armed") and not armed:
                    continue
                if src and (r.get("from") and src.name not in r["from"] or r.get("cc") and not (src.hard or src.soft)):
                    continue
                if r.get("while") and not (r["while"][0] in cast_at and t - cast_at[r["while"][0]] < r["while"][1]):
                    continue
                if r.get("once"):
                    if (id(c), n) in used:
                        continue
                    used.add((id(c), n))
                when, g = due.get(id(c), (0.0, 0))
                if when <= t:
                    continue
                s = r.get("s", 0.0) * (actor.crit if r.get("crit") else 1.0) + r.get("share", 0.0) * c.cooldown
                due[id(c)] = (max(t, when - s), g + 1)
                push(due[id(c)][0], "cast", (c, g + 1))

    for c in actor.casts:
        push(0.0, "cast", (c, 0))
        for _ in range(c.charges - 1):
            push(0.0, "cast", (replace(c, cooldown=None), 0))  # the recharge belongs to one charge
    if actor.attack_speed > 0:
        push(0.0, "attack")

    while queue:
        t, _, what, data = heapq.heappop(queue)
        if what == "expire":
            i, g = data
            if gen.get(i) == g and stacks.get(i):
                e = live[i]
                bonus[e["stat"]] -= stacks.pop(i) * _num(e.get("base"), actor)
            continue
        if t < busy:
            push(busy, what, data)
            continue
        if what == "attack" and t < no_attacks:
            push(no_attacks, what, data)
            continue
        if what == "cast":
            c, g = data
            if due.get(id(c), (0.0, g))[1] != g:   # a cut moved it sooner
                continue
            for kind, which, r in c.lines.get("ofHealth", ()):
                extra = r * (hp if which == "current" else target.hp - hp)
                pct += extra
                deal(kind, extra, t, c.aoe)
            for kind in KINDS:
                if c.lines.get(kind):
                    deal(kind, c.lines[kind], t, c.aoe)
            pct += c.lines.get("pct", 0.0)
            for k in HEALS:
                tot[k] += c.lines.get(k, 0.0)
            hard += c.hard
            aoe_hard += c.hard if c.aoe else 0.0
            soft += c.soft
            airborne += c.airborne
            suppress += c.suppress
            busy = t + c.cast_time
            no_attacks = max(no_attacks, t + c.no_attacks)
            cast_at[c.name] = t
            counts_by[c.name] = counts_by.get(c.name, 0) + 1
            if c.cooldown:
                due[id(c)] = (t + c.cooldown, g + 1)
                push(t + c.cooldown, "cast", (c, g + 1))
            armed = True
            cut("cast", t, c)
            lands = any(c.lines.get(kind) for kind in (*KINDS, "ofHealth"))
            for i, e in enumerate(live):
                if e.get("slot") not in (None, c.name):
                    continue
                on_spell = (lands or e.get("slot")) and e.get("on") in ("cast", "both")
                if e["trigger"] == "on-cast":
                    if c.hard if e.get("afterHard") else lands:
                        proc(i, e, t)
                elif e["trigger"] == "stack" and on_spell:
                    gain_stack(i, e, t, e.get("gainCast", 1))
                elif e["trigger"] == "on-hit" and on_spell:
                    proc(i, e, t)
                elif e["trigger"] == "every-n" and on_spell:
                    count(i, e, t)
            continue
        hits += 1
        hit = stat(AD) * (1 + actor.crit * (CRIT_MULT - 1))
        autos += hit
        deal("physical", hit, t)
        cut("attack", t)
        armed = False
        for i, e in enumerate(live):
            if e["trigger"] == "on-hit":
                proc(i, e, t)
            elif e["trigger"] == "every-n":
                count(i, e, t)
            elif e["trigger"] == "stack" and e.get("on", "hit") in ("hit", "both"):
                gain_stack(i, e, t, e.get("gain", 1))
            elif e["trigger"] == "rush":
                if not rush.get(i) and ready(i, e, t):
                    last_proc[i], rush[i] = t, e["hits"]
                if rush.get(i):
                    rush[i] -= 1
                    fire(e, t)
            elif e["trigger"] == "phantom" and full(e):
                full_hits[i] = full_hits.get(i, 0) + 1
                if full_hits[i] % e["n"] == 0:
                    # ponytail: on-hit lines only; every-n counters stay on real attacks,
                    # so Vayne W gets no extra stack. Count phantoms if that undercounts.
                    for j, on_hit in enumerate(live):
                        if on_hit["trigger"] == "on-hit":
                            proc(j, on_hit, t)
        speed = min(AS_CAP, actor.attack_speed + actor.as_ratio * bonus.get(ATTACK_SPEED, 0.0))
        speed += actor.as_ratio * sum(_num(live[i]["speed"], actor) for i, left in rush.items() if left)
        push(t + 1 / speed, "attack")

    return {"damage": dmg, "post": post, "pct": pct, "burst": burst_dmg, "aoe": aoe, **tot,
            "hard": hard, "soft": soft, "airborne": airborne, "suppress": suppress, "aoeHard": aoe_hard, "autos": autos, "unknown": unknown, "excluded": excluded, "hits": hits,
            "casts": counts_by}


# --- keystones -----------------------------------------------------------------
# Numbers come from perks.cdtb.bin.json by name, ARAM's overrides included. What the
# bin leaves to the rune text (hit counts, stacks per hit) is read off perks.json's
# long text. A keystone that fails either way is `handler: None`, so unknown.

_ONCE = math.inf  # a cooldown no fight outlasts


def _lv(lo: float, hi: float) -> dict:
    """The bin's linear level curve, as ByCharLevelInterpolation runs it."""
    return {"byLevel": [lo + (hi - lo) * lvl / 17 for lvl in range(18)]}


def _perk(pid: int, perks: dict) -> dict | None:
    return next((v for v in perks.values() if isinstance(v, dict) and v.get("mPerkId") == pid), None)


def _amounts(perk: dict, mode: str | None) -> dict:
    data = perk["mScript"]["mSpellScriptData"]
    over = (data.get("mEffectAmountGameMode") or {}).get((mode or "").upper()) or {}
    return {**data["mEffectAmount"], **(over.get("mEffectAmountPerMode") or {})}


def _text(pattern: str, desc: str | None) -> int:
    return int(re.search(pattern, re.sub(r"<[^>]+>", "", desc or "")).group(1))


def _note(name: str) -> dict:
    return {"trigger": "note", "name": name}


def adaptive_ad(perks: dict) -> float:
    """AD per adaptive point: the rune shard grants StatGain1 AD or StatGain2 AP."""
    a = _perk(5008, perks)["mScript"]["mSpellScriptData"]["mEffectAmount"]
    return a["StatGain1"] / a["StatGain2"]


def _press_the_attack(a, desc, perks):
    return [{"trigger": "every-n", "n": int(a["HitsRequired"]), "kind": "adaptive",
             "base": _lv(a["MinDamage"], a["MaxDamage"]), "cooldown": a["Cooldown"],
             "amp": {"value": a["BonusPercentDamage"], "duration": a["AmpDuration"]}}]


def _conqueror(a, desc, perks):
    gain = _text(r"grant (\d+) stacks", desc)
    ranged = _text(r"only (\d+) stack per basic attack", desc)
    # ponytail: TimeUntilNextStackFromSameSpell is not modelled, so a spell that hits
    # twice in 4 s stacks twice; the fight's spells rarely repeat that fast.
    return [{"trigger": "stack", "stat": "adaptive", "adScale": adaptive_ad(perks), "on": "both",
             "base": _lv(a["MinAdaptivePerStack"], a["MaxAdaptivePerStack"]),
             "stackMax": int(a["MaxStacks"]), "duration": a["BuffDuration"],
             "gain": {"melee": gain, "ranged": ranged}, "gainCast": gain},
            {"trigger": "defensive", "name": "Conqueror healing"}]


def _lethal_tempo(a, desc, perks):
    return [{"trigger": "stack", "stat": ATTACK_SPEED, "stackMax": int(a["MaxStacks"]),
             "base": {"melee": a["TTASPerStackMelee"], "ranged": a["TTASPerStackRanged"]},
             "duration": a["Duration"]},
            {"trigger": "on-hit", "kind": "adaptive", "whileFull": ATTACK_SPEED, "asScale": True,
             "base": {"melee": _lv(a["TTMinNoteDamageMelee"], a["TTMaxNoteDamageMelee"]),
                      "ranged": _lv(a["TTMinNoteDamageRanged"], a["TTMaxNoteDamageRanged"])}}]


def _electrocute(a, desc, perks):
    return [{"trigger": "every-n", "n": _text(r"(\d+) separate", desc), "on": "both",
             "kind": "adaptive", "base": _lv(a["DamageBase"], a["DamageMax"]),
             "ratios": {"bonus AD": a["BonusADRatio"], AP: a["APRatio"]}, "cooldown": a["Cooldown"]}]


def _dark_harvest(a, desc, perks):
    # Zero souls: a soul count is match history, which one fight cannot know.
    return [{"trigger": "on-hit", "on": "both", "kind": "adaptive", "base": a["BaseDamage"],
             "ratios": {"bonus AD": a["ADRatio"], AP: a["APRatio"]}, "cooldown": a["Cooldown"],
             "below": a["HarvestThreshold"]}]


def _hail_of_blades(a, desc, perks):
    return [{"trigger": "rush", "hits": int(a["NumHits"]), "kind": "true",
             "speed": {"melee": a["ASBoost"], "ranged": a["ASBoostRanged"]},
             "base": _lv(a["BonusDamageMin"], a["BonusDamageMax"]),
             "ratios": {"bonus AD": a["BonusADRatio"], AP: a["APRatio"]}, "cooldown": a["Cooldown"]}]


def _aery(a, desc, perks):
    return [{"trigger": "on-hit", "on": "both", "kind": "adaptive", "cooldown": _ONCE,
             "base": _lv(a["DamageBase"], a["DamageMax"]),
             "ratios": {"bonus AD": a["DamageADRatio"], AP: a["DamageAPRatio"]}},
            _note("Summon Aery repeat sends, the bin has no return time")]


def _comet(a, desc, perks):
    return [{"trigger": "on-cast", "kind": "adaptive", "base": _lv(a["DamageBase"], a["DamageMax"]),
             "ratios": {"bonus AD": a["ADRatio"], AP: a["APRatio"]},
             "cooldown": _lv(a["RechargeTime"], a["RechargeTimeMin"])}]


def _grasp(a, desc, perks):
    pct = a["PercentHealthDamage"]
    return [{"trigger": "on-hit", "kind": "magic", "stat": "Health",
             "ratio": {"melee": pct, "ranged": pct * a["RangedPenaltyMod"]},
             "delay": a["TriggerTime"], "cooldown": a["TriggerTime"]},
            {"trigger": "defensive", "name": "Grasp of the Undying healing"}]


def _aftershock(a, desc, perks):
    # ponytail: lands on the cast, not DelayBeforeBurst later; only `burst` can tell.
    return [{"trigger": "on-cast", "afterHard": True, "kind": "magic", "cooldown": a["Cooldown"],
             "base": _lv(a["StartingBaseDamage"], a["MaxBaseDamage"]),
             "ratios": {"bonus Health": a["HealthRatio"]}},
            {"trigger": "defensive", "name": "Aftershock resists"}]


def _deathfire(a, desc, perks):
    calc = _perk(8992, perks)["mScript"]["mSpellScriptData"]["mCalculations"]["DamageCalc"]
    curve = next(p for p in calc["mFormulaParts"] if "mStartValue" in p)
    # Damage per second, amplified after TimeToAmp, over the whole burn.
    span = a["TimeToAmp"] + (a["Duration"] - a["TimeToAmp"]) * (1 + a["DamageMultiplier"])
    return [{"trigger": "on-cast", "kind": "magic", "cooldown": a["Duration"],
             "base": _lv(curve["mStartValue"] * span, curve["mEndValue"] * span),
             "ratios": {"bonus AD": a["ADRatio"] * span, AP: a["APRatio"] * span}}]


def _first_strike(a, desc, perks):
    return [{"trigger": "on-hit", "on": "both", "base": 0.0,
             "cooldown": _lv(a["TooltipOnlyCooldownStartAmount"], a["TooltipOnlyCooldownEndAmount"]),
             "amp": {"value": a["DamageAmp"], "duration": a["Duration"]}}]


def _guardian(a, desc, perks):
    return [{"trigger": "on-hit", "on": "both", "out": "shield_ally", "cooldown": _ONCE,
             "base": _lv(a["ShieldBase"], a["ShieldMax"]),
             "ratios": {AP: a["APRatio"], "bonus Health": a["HPRatio"]}}]


KEYSTONES = {
    8005: _press_the_attack, 8008: _lethal_tempo, 8010: _conqueror, 8112: _electrocute,
    8128: _dark_harvest, 8214: _aery, 8229: _comet, 8369: _first_strike, 8437: _grasp,
    8439: _aftershock, 8465: _guardian, 8992: _deathfire, 9923: _hail_of_blades,
    8021: lambda a, desc, perks: [{"trigger": "defensive", "name": "Fleet Footwork"}],
    8230: lambda a, desc, perks: [{"trigger": "defensive", "name": "Stormraider's Surge"}],
    8351: lambda a, desc, perks: [{"trigger": "defensive", "name": "Glacial Augment"}],
    8360: lambda a, desc, perks: [],  # Unsealed Spellbook has no combat number
}


def keystone_effects(pid: int, perks: dict, desc: str | None = None, mode: str | None = None) -> list[dict]:
    """A keystone as timeline effects. `perks` is perks.cdtb.bin.json, `desc` the
    keystone's perks.json long text, `mode` a queue with its own numbers ("aram")."""
    perk = _perk(pid, perks)
    name = (perk or {}).get("mPerkName") or f"keystone {pid}"
    try:
        out = KEYSTONES[pid](_amounts(perk, mode), desc, perks)
    except (KeyError, TypeError, AttributeError):  # no handler, or the source lost a name
        return [{"handler": None, "name": name}]
    return [{"name": name, "source": f"perks {pid}", **e} for e in out]
