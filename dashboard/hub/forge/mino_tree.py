"""Mino's Viego build decision tree, ported from its-mino.com's script bundle.

Reads only Mino's own fields (data/forge-mino.json, bake_mino.py), never the
Forge's computed traits: some of Mino's scores are judged from Viego's side,
so the two scales do not mix. Every threshold is the bundle's, listed in
tests/fixtures/forge_draft/mino-predicates.json, and the order of the checks
is the bundle's `runDecisionTree` (probe-notes.md "Mino tree"):

  survivability -> low-damage-dps -> shields -> tanky -> reset deniers and
  allied CC on the leaf -> boots

Champ select, not the live game Mino reads: enemy summoner spells and runes
are hidden, so enemy Barrier and Guardian never add to their shields, Kayn's
+2 durability needs perks it never has, Shaco reads AP, and "Rengar or Talon
with Smite" assumes Smite on the enemy whose likely role is jungle. His own
team's spells come from the session; perks only for himself.

`allies` is his whole team including himself, as Mino counts it.
"""

from __future__ import annotations

# The bundle's SCORING_THRESHOLDS and BOOT_THRESHOLDS, verbatim.
T = dict(shield=7, earlyShield=7, lethalityMax=7, bastionMax=11, titansMin=15,
         forgedMomentumMax=12, hubrisCcMin=8, physicalMin=3, magicDamageMax=6,
         steelcapsBonus=1)
B = dict(swiftiesDurabilityMax=12, steelcapsAdMin=3, steelcapsMagicSecond=3,
         steelcapsMagicThird=5, steelcapsMagicFourth=7, mercsScoreMin=9,
         mercsDamageThird=12, mercsDamageFourth=14)
RESET_DENIER_MIN = 2
ASSASSINS = {"Khazix", "Kha'Zix", "Talon", "Kayn", "Rengar", "Shaco", "Qiyana"}
# Shaco reads AD only on one of these keystones (and not Comet / 8992).
_AD_SHACO = {8112, 8128, 9923, 8351, 8360, 8369, 8005, 8008, 8021, 8010, 8437, 8439,
             8465, 8214, 8229, 8230, 8992}
BARRIER, SMITE, GUARDIAN = 21, 11, 8465

REASONS = {
    "v4": "Three or more AD enemies with 11+ AD damage, including Rengar or Talon with Smite, and allied shields 4 or below: Collector, Steelcaps, LDR, Shieldbow, Infinity Edge, then Guardian Angel.",
    "v1": "Three or more AD enemies with 11+ AD damage and enemy magic damage 4 or below: survivability, Collector, Steelcaps, LDR, Shieldbow, Infinity Edge, then Guardian Angel.",
    "v3": "Three or more AP enemies, enemy physical damage 4 or below and Mercs value 8+: Collector, Mercury Treads, LDR, Shieldbow, Infinity Edge, then Voltaic Cyclosword.",
    "d1": "Both teams are under the damage cap, so there is room to DPS: Forged Momentum, if B. F. Sword comes on the first reset.",
    "s1": "Shields in every fight from the first minutes: Serpent's Fang first, Collector second, then LDR into Infinity Edge.",
    "s4": "Enough shields to buy Serpent's Fang but not enough early ones to rush it: Collector and LDR first, Serpent's Fang third.",
    "t3": "Base durability reaches Titansbane: Hubris into LDR second so the %pen is online before they stack armor.",
    "t1": "Adjusted durability is low enough for full lethality: Umbral Glaive into Voltaic Cyclosword for burst on squishies.",
    "t2": "Adjusted durability sits in the old Bastionbreaker band: Umbral Glaive into Collector.",
    "t4": "Adjusted durability above the Umbral band, base below Titansbane: standard Hubris, scale into AD and crit for three items.",
    "r1": "Two or more reset deniers make Hubris stacks unreliable, so the build swaps off Hubris.",
    "c1": "Allied CC is too low to set up Hubris stacks, so the build swaps off Hubris.",
}
LEAF = {"v4": "collector-shieldbow-ga", "v1": "collector-shieldbow-ga", "v3": "collector-shieldbow",
        "d1": "yun-tal-ldr", "s1": "sit-serpents-first", "s4": "sit-serpents-late",
        "t3": "hubris-ldr", "t1": "bastionbreaker-cyclosword", "t2": "umbral-collector",
        "t4": "main-hubris"}
_SWAP = {"main-hubris": "umbral-collector", "hubris-ldr": "hubris-skip-anti-tank"}


# --- the bundle's helpers -------------------------------------------------

def _is_phys(c):
    return c.get("damageType") in ("AD", "Mixed")


def _phys(c):
    d = c.get("damageScore") or 0
    return d / 2 if c.get("damageType") == "Mixed" else d if c.get("damageType") == "AD" else 0


def _magic(c):
    d = c.get("damageScore") or 0
    return d / 2 if c.get("damageType") == "Mixed" else d if c.get("damageType") == "AP" else 0


def _kayn_bonus(c):
    if c.get("championId") != "Kayn" and c.get("name") != "Kayn":
        return 0
    perks = c.get("perkIds") or []
    return 0 if not perks or 8128 in perks or 8369 in perks else 2


def total(team, field):
    if field == "durabilityScore":
        return sum((c.get("durabilityScore") or 0) + _kayn_bonus(c) for c in team)
    return sum(c.get(field) or 0 for c in team)


def _extra_shield(c):
    return int(BARRIER in (c.get("spellIds") or [])) + int(GUARDIAN in (c.get("perkIds") or []))


def team_shield(team):
    return total(team, "shieldScore") + sum(_extra_shield(c) for c in team)


def shields(enemies):
    t = team_shield(enemies)
    late = sum(c.get("shieldScore") or 0 for c in enemies
               if c.get("shieldTiming") == "Late" or c.get("shields") == "Late")
    return {"total": t, "late": late, "early": t - late}


def durability(allies, enemies):
    """Base and Steelcaps-adjusted enemy durability (the bundle's K)."""
    base = total(enemies, "durabilityScore")
    applies = (sum(1 for c in allies if _is_phys(c)) >= T["physicalMin"]
               and sum(_magic(c) for c in allies) < T["magicDamageMax"])
    adj = sum(1 for c in enemies if c.get("canBuildSteelcaps") is True) * T["steelcapsBonus"] if applies else 0
    return base, base + adj


def _count(enemies, dtype):
    return sum(1 for c in enemies if c.get("damageType") == dtype)


def _ad_damage(enemies):
    return total([c for c in enemies if c.get("damageType") == "AD"], "damageScore")


def _assassin_block(allies, enemies):            # Z
    return team_shield(allies) > 4 and any(
        c.get("championId") in ASSASSINS or c.get("name") in ASSASSINS for c in enemies)


def _ad_heavy(allies, enemies):                  # Y
    return (not _assassin_block(allies, enemies) and _ad_damage(enemies) >= 11
            and _count(enemies, "AD") >= 3 and sum(_magic(c) for c in enemies) <= 4)


def _ad_assassin(allies, enemies):               # J
    return (_ad_damage(enemies) >= 11 and _count(enemies, "AD") >= 3
            and any(c.get("damageType") == "AD" and SMITE in (c.get("spellIds") or [])
                    and c.get("championId") in ("Rengar", "Talon") for c in enemies)
            and team_shield(allies) <= 4)


def _ap_heavy(allies, enemies):                  # X
    return (not _assassin_block(allies, enemies) and _count(enemies, "AP") >= 3
            and sum(_phys(c) for c in enemies) <= 4 and total(enemies, "mercuryTreadsScore") >= 8)


def _shaco(c):
    if c.get("championId") != "Shaco" and c.get("name") != "Shaco":
        return c
    k = next((p for p in (c.get("perkIds") or []) if p in _AD_SHACO), None)
    if k is None or k in (8229, 8992):
        return {**c, "damageType": "AP"}
    return {**c, "damageType": "AD", "ccScore": 2, "mercuryTreadsScore": 1, "damageScore": 4}


# --- the nodes, in the bundle's order -------------------------------------

def survivability(allies, enemies):
    if _ad_assassin(allies, enemies):
        return "v4"
    if _ad_heavy(allies, enemies):
        return "v1"
    if _ap_heavy(allies, enemies):
        return "v3"
    return None


def low_damage(allies, enemies):
    m = T["forgedMomentumMax"]
    return "d1" if total(enemies, "damageScore") < m and total(allies, "damageScore") < m else None


def shield_check(enemies):
    s = shields(enemies)
    if s["total"] >= T["shield"] and s["early"] >= T["earlyShield"]:
        return "s1"
    return "s4" if s["total"] >= T["shield"] else None


def tanky(allies, enemies):
    base, adj = durability(allies, enemies)
    q = sum(_phys(c) for c in enemies)
    cut = T["bastionMax"] + (1 if q < 9 else -1 if q >= 11 else 0)
    if base >= T["titansMin"]:
        return "t3"
    if adj <= T["lethalityMax"]:
        return "t1"
    return "t2" if adj <= cut else "t4"


def post(allies, enemies, build):
    """Reset deniers, then allied CC, on the leaf. Returns (build, [rule ids])."""
    fired = []
    if sum(1 for c in enemies if c.get("deniesResets")) >= RESET_DENIER_MIN and build in _SWAP:
        build, fired = _SWAP[build], fired + ["r1"]
    if total(allies, "ccScore") < T["hubrisCcMin"] and build in _SWAP:
        build, fired = _SWAP[build], fired + ["c1"]
    return build, fired


def boots(allies, enemies):
    """(itemId, slot, rule id)."""
    if _ad_assassin(allies, enemies):
        return 3047, 2, "b9"
    if _ad_heavy(allies, enemies):
        return 3047, 2, "b0"
    if _ap_heavy(allies, enemies):
        return 3111, 2, "b8"
    magic = sum(_magic(c) for c in enemies)
    if _count(enemies, "AD") >= B["steelcapsAdMin"]:
        for limit, slot, rule in ((B["steelcapsMagicSecond"], 2, "b1"),
                                  (B["steelcapsMagicThird"], 3, "b2"),
                                  (B["steelcapsMagicFourth"], 4, "b3")):
            if magic < limit:
                return 3047, slot, rule
    if total(enemies, "mercuryTreadsScore") >= B["mercsScoreMin"]:
        dmg = total(enemies, "damageScore")
        if dmg < B["mercsDamageThird"]:
            return 3111, 3, "b4"
        if dmg < B["mercsDamageFourth"]:
            return 3111, 4, "b5"
    if total(enemies, "durabilityScore") <= B["swiftiesDurabilityMax"]:
        return 3009, 4, "b6"
    return 3008, 4, "b7"


def run(allies, enemies) -> dict:
    """The whole tree: {build, rule, post, boot, trace}."""
    allies, enemies = [_shaco(c) for c in allies], [_shaco(c) for c in enemies]
    rule = (survivability(allies, enemies) or low_damage(allies, enemies)
            or shield_check(enemies) or tanky(allies, enemies))
    build, fired = post(allies, enemies, LEAF[rule])
    boot = boots(allies, enemies)
    return {"build": build, "rule": rule, "post": fired, "boot": boot,
            "trace": [rule, *fired, boot[2]]}


def decide(allies, enemies, spells=None, runes=None, builds=None) -> list[dict]:
    """The build as slots: [{slot, itemId, why, rule}].

    `spells` and `runes` are his own (session spell ids, current page perk ids):
    they attach to his row in `allies`, the one marked `me`. `builds` is the
    baked `{buildId: {items}}` table from data/forge-mino.json.
    """
    allies = [dict(c, spellIds=list(spells or c.get("spellIds") or []),
                   perkIds=list(runes or c.get("perkIds") or []))
              if c.get("me") else c for c in allies]
    r = run(allies, enemies)
    items = list((builds or {}).get(r["build"], {}).get("items") or [])
    boot_id, slot, boot_rule = r["boot"]
    why = REASONS[r["rule"]] + "".join(" " + REASONS[p] for p in r["post"])
    out = []
    for i, item in enumerate(items):
        if len(out) + 1 == slot:
            out.append({"itemId": boot_id, "why": _boot_why(boot_rule), "rule": boot_rule})
        out.append({"itemId": item, "rule": r["rule"],
                    "why": why if i == 0 else "Next in the Mino order for this build."})
    if slot > len(out):
        out.append({"itemId": boot_id, "why": _boot_why(boot_rule), "rule": boot_rule})
    return [dict(e, slot=i + 1) for i, e in enumerate(out)]


def _boot_why(rule: str) -> str:
    return {
        "b9": "Steelcaps second: AD-heavy team with Rengar or Talon jungle.",
        "b0": "Steelcaps second: three or more AD threats and little magic damage.",
        "b8": "Mercury Treads second: AP-heavy team with CC and little physical damage.",
        "b1": "Steelcaps second: three or more AD enemies and magic damage under 3.",
        "b2": "Steelcaps third: three or more AD enemies and magic damage under 5.",
        "b3": "Steelcaps fourth: three or more AD enemies and magic damage under 7.",
        "b4": "Mercury Treads third: enough CC to matter, enemy damage under 12.",
        "b5": "Mercury Treads fourth: enough CC to matter, enemy damage under 14.",
        "b6": "Swifties fourth: enemy durability 12 or under, nothing else calls for resist boots.",
        "b7": "Gluttonous Greaves fourth: enemy durability over 12, nothing else calls for resist boots.",
    }[rule]
