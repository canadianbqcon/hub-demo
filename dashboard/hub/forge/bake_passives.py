#!/usr/bin/env python3
"""Bake the item passives, numbers included, into data/forge-item-passives.json.

    python3 bake_passives.py          # fetch, resolve, write
    python3 bake_passives.py --check  # self-check on the shipped file

Why this exists: Data Dragon TEMPLATES THE NUMBERS OUT of item descriptions, and
`catalog.json`'s `ps` blocks come from there. Sterak's Gage reads "Gain  bonus
Attack Damage.", Sundered Sky "restores Health", Eclipse "grants you a Shield" --
the ratio simply absent, in the one place a build tool most needs it. It is the
same hole `bake_patchnotes.py` was written for: ddragon's item text is not a
readable description, so no amount of squeezing it produces one.

CommunityDragon's `v1/items.json` carries the same gutted text, and Meraki
Analytics' ready-made human text is a PATCH BEHIND (it says Sterak's is 45% base
AD; Riot's own notes for this patch say 45% -> 50% and the bin says 0.5). So the
numbers come from Riot's own two pieces, both current:

    items.cdtb.bin.json    per item, `mDataValues` (the named constants) and
                           `mItemCalculations` (the formula graph the client
                           evaluates at runtime)
    lol.stringtable.json   the tooltip TEMPLATE, `item_<id>_tooltip`, holding
                           `@Placeholder@` tokens:
                           `Gain <scaleAD>@BonusAD@ bonus Attack Damage</scaleAD>.`

So this walks the graph the client walks and writes the answer into the template.

**What lands is a ratio, not a number, and that is the honest answer.** `@BonusAD@`
resolves to 50% of BASE AD, and base AD is the champion's -- there is no absolute
value outside a running game. "Gain 50% base AD bonus Attack Damage" is what the
shop says and what the card now says.

Three things about Riot's format that the reader has to know, all of them found
the hard way and none of them documented anywhere:

- **A hashed key is FNV-1a 32 of the lowercased name.** Sundered Sky's heal calc
  is filed under `{01099b16}`, which is fnv1a("healadsplit"). Riot obfuscates
  both the KEYS and the REFERENCES to them, sometimes in the same item, so every
  table is indexed from both sides and every lookup tries both forms.
- **An absent field holds its default.** A part with no `mStat` is stat 0, which
  is Ability Power -- so Lich Bane's 45% AP scaling looks like a part with no
  stat at all. Reading that as "unknown" rather than "zero" left a tenth of the
  catalog unresolved.
- **The name is the join, not the item id.** Data Dragon 16.16.1 calls id 3097
  Stormrazor; Riot's live bin calls the same id "Stayin' Alive", a different item
  with different passives. Substituting across that prints one item's numbers
  under another's name, so a disagreeing name is dropped and printed.

The ACTIVE half (`item_<id>_active`) is deliberately NOT read: its data values
live in a spell bin this file does not carry, and Data Dragon renders actives
with their numbers intact anyway, so there is nothing to gain there and a hole to
lose. The two sources are complementary -- Riot's for passives, ddragon's for
actives -- and each is used where the other is gutted.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

CDRAGON = "https://raw.communitydragon.org/latest/game"
BIN = f"{CDRAGON}/items.cdtb.bin.json"
STRINGS = f"{CDRAGON}/en_us/data/menu/en_us/lol.stringtable.json"
# CommunityDragon 403s the stdlib's default agent string.
UA = "vault-forge/1.0"

CATALOG = Path(__file__).parent / "frontend" / "static" / "catalog.json"
OUT = "forge-item-passives.json"

# mStat -> the champion stat a coefficient multiplies; mStatFormula -> which
# slice of it. Read off Riot's own prose rather than guessed:
#   0  Lich Bane's 75% base AD + 45% AP matches its live tooltip exactly, as do
#      Nashor's 15 + 15% AP and Blackfire's 20 + 2% AP per second
#   1  Thornmail deals 20 + 10% bonus Armor
#   2  game_item_description_3053 spells Sterak's ADtoAD out as "50% of your Base
#      Attack Damage" (formula 1); Eclipse's melee shield is 150 + 40% BONUS AD
#      (formula 2); Ravenous Hydra's cleave is 40% total AD (formula 0)
#   6  pairs with Armor at 175% each in Protoplasm Harness's regen
#   7  Swiftmarch's own template says "of your Move Speed"
#   8  Essence Reaver adds 50 per 100% critical strike chance
#  12  Sterak's shield is 60% BONUS Health (2); Heartsteel is 6% MAX Health (0)
#  29  Axiom Arc refunds 10% + 25% of Lethality
STAT = {0: "AP", 1: "Armor", 2: "AD", 6: "Magic Resist", 7: "Move Speed",
        8: "Critical Strike Chance", 12: "Health",
        13: "target's current Health", 29: "Lethality", 31: "Attack Range"}
SLICE = {0: "", 1: "base ", 2: "bonus "}

# ponytail: above this a coefficient is a flat multiplier rather than a fraction
# (Essence Reaver's 50 per 100% crit). Every real ratio in the catalog sits in
# 0.03-1.75, so the gap is wide; revisit if Riot ships a ratio over 200%.
RATIO_CEILING = 2.0


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fnv1a(s: str) -> int:
    h = 2166136261
    for b in s.lower().encode():
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def index(d: dict) -> dict:
    """Every entry addressable by lowercased name AND by its {hash} form, because
    Riot obfuscates keys and references independently of each other."""
    out = {}
    for k, v in d.items():
        out[k.lower()] = v
        out["{%08x}" % fnv1a(k)] = v
    return out


def get(d: dict, name: str):
    n = name.lower()
    return d[n] if n in d else d.get("{%08x}" % fnv1a(n))


def num(v: float) -> str:
    return f"{v:g}" if abs(v - round(v)) > 1e-6 else str(int(round(v)))


def pct(v: float) -> str:
    return num(v * 100) + "%"


def scaled(r: float, stat: str, formula: int) -> str:
    """A coefficient against a champion stat, bracketed.

    The parens are how the ratio reads as one unit rather than as words that
    happen to sit in the sentence: `deal 20 + (10% bonus Armor) magic damage`,
    not `deal 20 + 10% bonus Armor magic damage`. `ungroup()` takes them back off
    whenever an enclosing bracket already does that job.
    """
    lead = pct(r) if abs(r) <= RATIO_CEILING else f"{num(r)} x"
    return f"({lead} {SLICE.get(formula, '')}{stat})"


RATIO = re.compile(r"^(-?[\d.]+)% (.*)$")
NUMS = re.compile(r"-?\d+(?:\.\d+)?")


def scale(text: str, factor: float) -> str:
    """`0.75 x (110-280 by level)` is arithmetic left on the page; Riot's own
    idiom is both sides spelled out, so the factor multiplies through. Rounded,
    because Riot's multipliers are themselves rounded (0.667 for two thirds)."""
    return NUMS.sub(lambda m: num(round(float(m.group(0)) * factor, 1)), text)


INNER = re.compile(r"\((-?[\d.]+%?[^()]*)\)")


def ungroup(s: str) -> str:
    """Drop a ratio's own parens when an outer bracket is about to supply them.

    `(150 + (40% bonus AD) melee / ...)` is one group too many; the outer one is
    what separates the two sides, so the inner ones come off.
    """
    return INNER.sub(r"\1", s)


def split(melee: str, ranged: str) -> str:
    """The two sides of a melee/ranged value, parenthesised.

    The parens are load-bearing, not decoration. These land mid-sentence, and
    without them Sundered Sky reads "restores 90% base AD melee / 45% base AD
    ranged plus 4% of missing Health" -- where the `plus` could attach to the
    ranged branch or to both. Riot's own template brackets it for the same
    reason: `item_range_type_melee` is literally `(@Melee@ | @Ranged@)`.
    """
    return f"({ungroup(melee)} melee / {ungroup(ranged)} ranged)"


def fold(mult: str, base: str) -> str:
    """`2 x (1.5% Health)` is noise; a plain number folds into a lone ratio."""
    if re.fullmatch(r"-?[\d.]+", mult):
        if abs(float(mult) - 1) < 1e-9:
            return base
        m = RATIO.match(base)
        if m:
            return f"{num(float(m.group(1)) * float(mult))}% {m.group(2)}"
    return f"{mult} x ({base})"


class Item:
    """One item's four value tables, all of them hash-addressable."""

    def __init__(self, raw: dict):
        self.raw = raw
        # A data value with NO mValue is UNRESOLVED, never zero -- the opposite
        # resolution to the absent-mStat rule above, and the distinction matters:
        # Spectre's Cowl declares `HealthRegenPassive` with no value and its real
        # figure is 100%, so defaulting to 0.0 published "gain 0% base Health
        # Regen" on the card. Riot omits a field it means as zero AND a field it
        # fills in elsewhere; only an explicit `mValue: 0.0` is a real zero.
        self.dv = index({d["mName"]: d["mValue"]
                         for d in raw.get("mDataValues", []) if "mValue" in d})
        self.calc = index(raw.get("mItemCalculations") or {})
        self.scalc = index(raw.get("StringCalculations") or {})
        self.fields = {(k[1:] if k.startswith("m") else k).lower(): v
                       for k, v in raw.items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)}

    def value(self, name: str):
        return get(self.dv, name)


def _part_number(p: dict, it: Item):
    return num(p["mNumber"])


def _part_named_value(p: dict, it: Item):
    v = it.value(p["mDataValue"])
    return None if v is None else num(v)


def _part_stat_coefficient(p: dict, it: Item):
    r = p["mCoefficient"] if "mCoefficient" in p else it.value(p.get("mDataValue", ""))
    stat = STAT.get(p.get("mStat", 0))
    if r is None or stat is None:
        return None
    return scaled(r, stat, p.get("mStatFormula", 0))


def _part_stat_subpart(p: dict, it: Item):
    inner = part(p["mSubpart"], it)
    stat = STAT.get(p.get("mStat", 0))
    if inner is None or stat is None:
        return None
    if re.fullmatch(r"-?[\d.]+", inner):
        return scaled(float(inner), stat, p.get("mStatFormula", 0))
    return f"{inner} x {SLICE.get(p.get('mStatFormula', 0), '')}{stat}"


def _part_level_interpolation(p: dict, it: Item):
    lo, hi = p["mStartValue"], p["mEndValue"]
    return num(lo) if abs(hi - lo) < 1e-9 else f"{num(lo)}-{num(hi)} by level"


def _part_level_breakpoints(p: dict, it: Item):
    # Two breakpoint shapes: a slope from that level on, and a one-off step at
    # it. Blade of the Ruined King uses the first, Terminus the second.
    lo = hi = p.get("mLevel1Value", 0.0)
    for bp in p.get("mBreakpoints", []):
        hi += bp.get("mBonusPerLevelAtAndAfter", 0.0) * (18 - bp["mLevel"] + 1)
        hi += bp.get("mAdditionalBonusAtThisLevel", 0.0)
    return num(lo) if abs(hi - lo) < 1e-9 else f"{num(lo)}-{num(hi)} by level"


def _part_buff_counter_coefficient(p: dict, it: Item):
    return f"{num(p.get('mCoefficient', 1.0))} per stack"


def _part_buff_counter_named_value(p: dict, it: Item):
    v = it.value(p.get("mDataValue", ""))
    return None if v is None else f"{num(v)} per stack"


def _part_ability_resource(p: dict, it: Item):
    return f"({pct(p.get('mCoefficient', 0.0))} max Mana)"


def _part_epicness(p: dict, it: Item):
    return "per Legendary item"


def _part_subparts(p: dict, it: Item, t: str):
    subs = [part(s, it) for s in p.get("mSubparts") or [x for x in (p.get("mPart1"), p.get("mPart2")) if x]]
    if any(s is None for s in subs):
        return None
    body = (" + " if t.startswith("Sum") else " x ").join(subs)
    if t.startswith("Clamp"):
        return f"{body}, {num(p.get('mFloor', 0))}-{num(p.get('mCeiling', 0))}"
    return body


# One handler per `__type`, dispatched by name instead of an if/elif chain --
# the two Stat*ByCoefficient/NamedValue types share a reader because the only
# difference between them is where the coefficient comes from, which the
# handler itself branches on.
_PART_HANDLERS = {
    "NumberCalculationPart": _part_number,
    "NamedDataValueCalculationPart": _part_named_value,
    "StatByNamedDataValueCalculationPart": _part_stat_coefficient,
    "StatByCoefficientCalculationPart": _part_stat_coefficient,
    "StatBySubPartCalculationPart": _part_stat_subpart,
    "ByCharLevelInterpolationCalculationPart": _part_level_interpolation,
    "ByCharLevelBreakpointsCalculationPart": _part_level_breakpoints,
    "BuffCounterByCoefficientCalculationPart": _part_buff_counter_coefficient,
    "BuffCounterByNamedDataValueCalculationPart": _part_buff_counter_named_value,
    "AbilityResourceByCoefficientCalculationPart": _part_ability_resource,
    "ByItemEpicnessCountCalculationPart": _part_epicness,
}
_SUBPART_TYPES = ("SumOfSubPartsCalculationPart", "ProductOfSubPartsCalculationPart",
                  "ClampSubPartsCalculationPart")


def part(p: dict, it: Item):
    """One calculation part -> display text, or None if it cannot be read."""
    t = p.get("__type", "")
    handler = _PART_HANDLERS.get(t)
    if handler:
        return handler(p, it)
    if t in _SUBPART_TYPES:
        return _part_subparts(p, it, t)
    if "mSpellCalculationKey" in p:
        return evaluate(p["mSpellCalculationKey"], it)
    return None


def _evaluate_melee_ranged(sc: dict, it: Item, seen, suffix: str):
    melee = expand(sc.get("MeleeResult", ""), it, seen, 1, suffix)
    ranged = expand(sc.get("RangedResult", ""), it, seen, 1, suffix)
    if melee is None or ranged is None:
        return None
    m = re.fullmatch(r"([\d.]+) x \((.*)\)", ranged)
    if m:
        ranged = scale(m.group(2), float(m.group(1)))
    return melee if melee == ranged else split(melee, ranged)


def _evaluate_modified(c: dict, it: Item, seen, suffix: str):
    base = evaluate(c["mModifiedGameCalculation"], it, seen)
    if base is None:
        return None
    mult = part(c["mMultiplier"], it) if "mMultiplier" in c else None
    return (fold(mult, base) if mult else base) + suffix


def _evaluate_formula(c: dict, it: Item, suffix: str):
    parts = [part(p, it) for p in c.get("mFormulaParts", [])]
    if not parts or any(p is None for p in parts):
        return None
    if c.get("mDisplayAsPercent") and len(parts) == 1 and re.fullmatch(r"-?[\d.]+", parts[0]):
        parts, suffix = [pct(float(parts[0]))], ""
    body = " + ".join(parts)
    if len(parts) > 1:
        # A sum is ONE figure, so it takes one bracket rather than one per term:
        # `deal (20 + 10% bonus Armor) magic damage`, which is Riot's own style,
        # not `deal 20 + (10% bonus Armor) magic damage`.
        body = f"({ungroup(body)})"
    if suffix and len(parts) == 1 and (body.startswith("(") or RATIO.match(body)):
        # A LONE ratio already carries its own %, so the template's is a duplicate:
        # `(0.5% max Mana)% Heal and Shield Power`. A SUM does not -- Axiom Arc's
        # `(10 + 25% Lethality)%` is a cooldown percentage and needs the mark.
        suffix = ""
    if "mRangedMultiplier" in c:
        rm = part(c["mRangedMultiplier"], it)
        if rm and re.fullmatch(r"-?[\d.]+", rm):
            return split(body + suffix, scale(body, float(rm)) + suffix)
        if rm:
            return f"({body}{suffix} melee, x{rm} ranged)"
    return body + suffix


def evaluate(name: str, it: Item, seen=frozenset(), suffix: str = ""):
    """A named calculation -> display text.

    `suffix` is a `%` the TEMPLATE owns, pushed inside so a melee/ranged split
    reads `50% melee / 35% ranged` rather than `50 melee / 35 ranged%`.
    """
    n = name.lower()
    if n in seen:
        return None
    seen = seen | {n}

    sc = get(it.scalc, n)
    if sc is not None:
        return _evaluate_melee_ranged(sc, it, seen, suffix)

    c = get(it.calc, n)
    if c is None:
        return None

    if c.get("__type") == "GameCalculationConditional":
        return evaluate(c["mDefaultGameCalculation"], it, seen, suffix)

    if "mModifiedGameCalculation" in c:
        return _evaluate_modified(c, it, seen, suffix)

    return _evaluate_formula(c, it, suffix)


REF = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
PH = re.compile(r"@([A-Za-z_][A-Za-z0-9_.]*)((?:[*/]-?[0-9.]+)?)@")
EFF = re.compile(r"^Effect(\d+)Amount$")

STRINGS_BY_KEY: dict = {}


def _resolve_string_refs(text: str) -> str:
    # ChampRange is the wielding champion's melee/ranged flag, which does not
    # exist outside a game. It is pinned to melee here and the ranged side comes
    # from mRangedMultiplier instead, so both numbers still get printed.
    text = text.replace("@ChampRange@", "1")
    for _ in range(4):
        new = REF.sub(lambda m: STRINGS_BY_KEY.get(m.group(1).lower(), m.group(0)), text)
        if new == text:
            break
        text = new.replace("@ChampRange@", "1")
    return text


def _placeholder_value(it: Item, name: str):
    v = it.value(name)
    eff_m = EFF.match(name)
    if v is None and eff_m:
        # `mEffectAmount` is a legacy fixed-width array, zero-filled in every
        # slot the item does not use -- Sterak's is eleven zeros. Eight items
        # do read real numbers out of it (Plated Steelcaps' 10%, Guardian
        # Angel, Runaan's), so it stays a source; a ZERO from it is the
        # filler, not a value, and counts as unresolved.
        arr = it.raw.get("mEffectAmount") or []
        i = int(eff_m.group(1)) - 1
        v = arr[i] if 0 <= i < len(arr) and arr[i] else None
    if v is None:
        v = get(it.fields, name)
    return v


def expand(text: str, it: Item, seen=frozenset(), depth: int = 0, suffix: str = ""):
    """Resolve `{{ string refs }}` then every `@Placeholder@`.

    None at depth 0 means at least one token could not be read, which is the
    signal to keep Data Dragon's sentence rather than ship a half-filled one.
    """
    if depth > 6:
        return None
    text = _resolve_string_refs(text)

    out, ok, pos = [], True, 0
    for m in PH.finditer(text):
        out.append(text[pos:m.start()])
        pos = m.end()
        name, op = m.group(1), m.group(2)
        tail = text[pos:pos + 1]

        v = _placeholder_value(it, name)
        if v is not None:
            if op:
                v = v * float(op[1:]) if op[0] == "*" else v / float(op[1:])
            out.append(num(v))
            continue

        sfx = "%" if tail == "%" else ""
        r = evaluate(name, it, seen, sfx)
        if r is None:
            ok = False
            out.append(f"@{name}{op}@")
        else:
            out.append(r)
            if sfx:
                pos += 1         # the template's % moved inside the value
    out.append(text[pos:])
    s = "".join(out) + suffix
    return s if ok else (None if depth == 0 else s)


TAG = re.compile(r"<[^>]+>")
ICON = re.compile(r"%i:[A-Za-z]+%")
HEAD = re.compile(r"<(passive|active)>(.*?)</\1>(.*?)(?=<(?:passive|active)>|$)",
                  re.S | re.I)
# `restore 3% Health Health per second` -- the calculation names the stat and so
# does the template right after it. Riot writes one of them, not both.
DUP = re.compile(r"\b(AD|AP|Armor|Magic Resist|Move Speed|Health|Lethality|"
                 r"Attack Range|Critical Strike Chance)( +\1\b)", re.I)


def plain(s: str) -> str:
    s = s.replace("<br>", "\n")
    s = TAG.sub("", ICON.sub("", s))
    s = DUP.sub(r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def blocks(resolved: str) -> list[dict]:
    """Riot's one tooltip string -> catalog `ps` shape, `{h, t}` per passive.

    A `<passive>Name</passive>` opens each one and the rest of the line is its
    heading too (`{{ Item_Cooldown }}` renders there, as it does in the shop),
    so `h` carries "Lifeline (90s)" and `t` the sentence under it.
    """
    out = []
    for _, head, body in HEAD.findall(resolved):
        rest, _, tail = body.partition("<br>")
        h = plain(head + " " + rest)
        t = plain(tail)
        if t:
            out.append({"h": h, "t": t})
    if out:
        return out
    # No heading tags at all: a single unnamed note (Redemption, the Elixirs).
    t = plain(resolved)
    return [{"h": "", "t": t}] if t else []


def resolve_item(iid: str, raw: dict) -> list[dict] | None:
    """The `ps` blocks for one item, or None to leave Data Dragon's alone."""
    tpl = STRINGS_BY_KEY.get(f"item_{iid}_tooltip")
    if not tpl:
        return None
    text = expand(tpl, Item(raw), depth=1)
    if text is None or PH.search(text):
        return None              # a half-filled sentence is worse than a gutted one
    bl = blocks(text)
    return bl or None


# ── structured effects ──────────────────────────────────────────────────────
# The display text above is evidence; these numbers are read from the bin and
# never parsed back out of any sentence (item 3041's shop text is cut off at
# "Gain 5 Ability Power per"). The tooltip TEMPLATE is read only for structure:
# which placeholder sits in a damage tag, whether the block says "every third".
# A block this cannot structure becomes `{"handler": null, "name", "reason"}`.
#
# Value shapes: a number, or {"byLevel": [18 numbers]} for a level-scaled one.
# Where melee and ranged differ the field is {"melee": v, "ranged": v}.
DMG_SPAN = re.compile(r"<(physical|magic|true)Damage>(.*?)</\1Damage>", re.S)
STAT_TAGS = {"scaleAP": "AP", "scaleAD": "AD", "attackSpeed": "Attack Speed",
             "speed": "Move Speed", "scaleHealth": "Health", "scaleArmor": "Armor",
             "scaleMR": "Magic Resist"}
STAT_SPAN = re.compile(r"<(%s)>(.*?)</\1>" % "|".join(STAT_TAGS), re.S)
NTH = {"second": 2, "third": 3, "fourth": 4, "fifth": 5}
EVERY = re.compile(r"\bevery (%s)\b" % "|".join(NTH), re.I)
# ponytail: the hit count lives in a data value with a conventional name; an item
# that names it differently is `handler: null` until its name is added here.
COUNT_NAMES = ("AttackCount", "HitCount", "AttacksRequired", "NumberOfAttacks")
CONDITION = re.compile(r"\b(if|while|when|after|below|above|against|out of combat|"
                       r"enemies|nearby|allies|for each(?! enemy))\b", re.I)  # Blackfire: one burning target in this fight
PCT_OF = re.compile(r"(?:\bof|%|@) (?:\w+'s |their |the )?(current|max|maximum|missing) Health", re.I)
PCT_WORD = {"current": "current", "max": "max", "maximum": "max", "missing": "missing"}
LEVELS = range(1, 19)
TRIGGERS = ("on-hit", "every-n", "on-cast", "stack", "static", "phantom", "note")
ONCE = 9999.0                  # a cooldown no fight outlasts, and valid JSON
# Passives that feed no number in a lone 10 s fight on a target that never hits back.
# Read block by block, so an item Riot adds later stays `handler: null` until it is read.
NOT_IN_FIGHT = {
    **dict.fromkeys(("Eminence", "Sabotage", "Glory"), "takedown stacks, none before a kill"),
    "Timeless": "time stacks, the fight has no game clock",
    **dict.fromkeys(("Dream Maker", "Going Sledding", "Fanfare", "Rapids", "Boarding Party"),
                    "goes to allies or minions"),
    **dict.fromkeys(("Thorns", "Incorporeal", "Steadfast", "Voidborn Resilience", "Retribution",
                     "Winter's Caress"), "needs damage taken or an attacking enemy"),
    **dict.fromkeys(("Haunt", "Nightstalker", "Noxian Haste", "Jungle Companions"),
                    "out of combat or out of vision"),
    **dict.fromkeys(("Wind's Fury", "Precision"), "hits other targets"),
    "Goliath": "changes size only",
    "Desolate": "needs a kill",
    "Health on Hit": "a heal per hit, left out of selfHeal",
}
# These change the fight's damage and nothing reads them yet, so the row says unknown.
UNREAD = ("Juxtaposition", "Opening Barrage", "Noxian Fervor")
SHRED = re.compile(r"reducing their <scaleMR>Magic Resist", re.I)
PER_SECOND = re.compile(r"per second(?: to nearby enemies)? for @(\w+)@ seconds|for @(\w+)@(?:s| seconds), dealing .*? per second")
SEPARATE = re.compile(r"\b(\d+) separate\b")
OWN_PCT = re.compile(r"% of your (max Health|bonus Health)")
CONVERT = re.compile(r"Gain @(\w+)\*100@% of your (bonus Health) as (Ability Power|Attack Damage)")
CONVERT_TO = {"Ability Power": "AP", "Attack Damage": "AD"}
# First match sets the trigger. Spells all open the fight, so an ultimate's trigger is a cast;
# `slot` keeps one that names the Ultimate off the other spells.
TIMING = (
    (r"^After taking or dealing damage", {"trigger": "on-hit", "on": "both"}),
    (r"^Damaging a champion with your Ultimate", {"trigger": "on-cast", "slot": "R"}),
    (r"^Damaging Abilit|Dealing Ability damage|Casting your Ultimate", {"trigger": "on-cast"}),
    (r"^Damaging a champion", {"trigger": "on-hit", "on": "both"}),
    (r"^Every @", {"trigger": "on-hit", "on": "both"}),
    (r"Energized Attack|^While moving", {"trigger": "on-hit", "cooldown": ONCE}),
    (r"next Attack", {"trigger": "on-hit"}),
)


def _lv(p: dict):
    """A level-scaled part -> 18 values (level 1..18), or a scalar if flat."""
    t = p.get("__type", "")
    if t == "ByCharLevelBreakpointsCalculationPart":
        vals = []
        for L in LEVELS:
            v = p.get("mLevel1Value", 0.0)
            for bp in p.get("mBreakpoints", []):
                if L >= bp["mLevel"]:
                    v += bp.get("mBonusPerLevelAtAndAfter", 0.0) * (L - bp["mLevel"] + 1)
                    v += bp.get("mAdditionalBonusAtThisLevel", 0.0)
            vals.append(v)
    else:
        lo, hi = p["mStartValue"], p["mEndValue"]
        # ponytail: linear across levels 1-18; Riot's interpolation curve is not
        # in the bin. Flat ranges (lo == hi) are exact, which is every case seen.
        vals = [lo + (hi - lo) * (L - 1) / 17 for L in LEVELS]
    return vals[0] if max(vals) - min(vals) < 1e-9 else {"byLevel": vals}


def _mul(v, k):
    if isinstance(v, dict):
        if "byLevel" in v:
            return {"byLevel": [x * k for x in v["byLevel"]]}
        return {f: _mul(x, k) for f, x in v.items()}
    return v * k


def _times(q: dict, k: float) -> dict:
    """A quantity times k: its amount, not its stat names."""
    return {f: (_mul(v, k) if f in ("base", "ratio", "ratios") else v) for f, v in q.items()}


def _add(a, b):
    if a is None:
        return b
    if isinstance(a, dict) or isinstance(b, dict):
        la = a["byLevel"] if isinstance(a, dict) else [a] * 18
        lb = b["byLevel"] if isinstance(b, dict) else [b] * 18
        return {"byLevel": [x + y for x, y in zip(la, lb)]}
    return a + b


def _numeric(p: dict, it: Item):
    """A part that is a plain number or a level curve -> value, else None."""
    t = p.get("__type", "")
    if t in ("ByCharLevelBreakpointsCalculationPart",
             "ByCharLevelInterpolationCalculationPart"):
        return _lv(p)
    if t in ("NumberCalculationPart", "NamedDataValueCalculationPart"):
        txt = part(p, it)          # the same readers the display text uses
        return None if txt is None else float(txt)
    if t == "ProductOfSubPartsCalculationPart" and "mPart1" in p:
        a, b = _numeric(p["mPart1"], it), _numeric(p.get("mPart2", {}), it)
        return a * b if isinstance(a, float) and isinstance(b, float) else None
    return None


def _side(c: dict, it: Item, seen, ranged: bool):
    """One calc -> {base?, ratio?, stat?, pctTarget?} for melee or ranged."""
    if c.get("__type") == "GameCalculationConditional":
        # IsRangedCastRequirement is the only condition seen: default = melee.
        key = c["mConditionalGameCalculation" if ranged else "mDefaultGameCalculation"]
        sub = get(it.calc, key)
        return None if sub is None else _side(sub, it, seen, ranged)
    if "mModifiedGameCalculation" in c:
        base = _calc(c["mModifiedGameCalculation"], it, seen)
        k = _numeric(c.get("mMultiplier", {}), it)
        if base is None or not isinstance(k, float):
            return None
        m = base["melee" if not ranged else "ranged"]
        return _times(m, k)
    out: dict = {}
    for p in c.get("mFormulaParts", []):
        t = p.get("__type", "")
        if t.startswith("StatBy") or t.startswith("AbilityResource"):
            r = p["mCoefficient"] if "mCoefficient" in p else it.value(p.get("mDataValue", ""))
            sid = p.get("mStat", 0)
            word = "Mana" if t.startswith("AbilityResource") else STAT.get(sid)
            if r is None or "pctTarget" in out:
                return None
            if sid == 13 and "ratio" not in out:
                out["pctTarget"] = "current"
                out["ratio"] = r
            elif word is None or sid == 13:
                return None
            elif "ratio" in out:   # a second stat: Lich Bane is base AD plus AP
                out.setdefault("ratios", {})[SLICE.get(p.get("mStatFormula", 0), "") + word] = r
            else:
                out["stat"] = SLICE.get(p.get("mStatFormula", 0), "") + word
                out["ratio"] = r
            continue
        v = _numeric(p, it)
        if v is None:
            return None
        out["base"] = _add(out.get("base"), v)
    if not out:
        return None
    mult = c.get("mMultiplier")
    if mult is not None:
        k = _numeric(mult, it)
        if k is None and "mSpellCalculationKey" in mult:
            sub = _calc(mult["mSpellCalculationKey"], it, seen)
            if sub is None or "base" not in sub["melee"]:
                return None
            k = sub["ranged" if ranged else "melee"]["base"]
        if not isinstance(k, float):
            return None
        out = _times(out, k)
    if ranged and "mRangedMultiplier" in c:
        k = _numeric(c["mRangedMultiplier"], it)
        if not isinstance(k, float):
            return None
        out = _times(out, k)
    return out


def _calc(name: str, it: Item, seen=frozenset()):
    """A named calculation -> {"melee": side, "ranged": side} or None."""
    n = name.lower()
    c = get(it.calc, n)
    if c is None or n in seen:
        return None
    seen = seen | {n}
    m, r = _side(c, it, seen, False), _side(c, it, seen, True)
    return None if m is None or r is None else {"melee": m, "ranged": r}


def _merge(q: dict) -> dict:
    """{"melee","ranged"} sides -> one flat dict; a field that differs is split."""
    m, r = q["melee"], q["ranged"]
    out = {f: (m[f] if m.get(f) == r.get(f) else {"melee": m.get(f), "ranged": r.get(f)})
           for f in m}
    if "ratios" in m and m["ratios"] != r.get("ratios"):
        rr = r.get("ratios") or {}
        out["ratios"] = {s: {"melee": v, "ranged": rr.get(s)} for s, v in m["ratios"].items()}
    return out


def _quantity(content: str, it: Item):
    """The first number a template fragment points at -> merged dict or None."""
    names = [m.group(1) for m in PH.finditer(content)]
    vals = []
    for nm in names:
        sc = get(it.scalc, nm)
        if sc is not None:         # Riot's melee/ranged string pair, percents when the text says %
            pair = [_placeholder_value(it, PH.search(sc.get(k) or "").group(1))
                    if PH.search(sc.get(k) or "") else None for k in ("MeleeResult", "RangedResult")]
            if None in pair:
                return None
            k = 0.01 if f"@{nm}@%" in content else 1
            return _merge({"melee": {"base": pair[0] * k}, "ranged": {"base": pair[1] * k}})
        v = _placeholder_value(it, nm)
        if v is not None:
            vals.append({"melee": {"base": v}, "ranged": {"base": v}})
            continue
        q = _calc(nm, it)
        if q is None:
            return None
        vals.append(q)
    if not vals:
        return None
    if len(names) == 1 and names[0].startswith("Melee"):
        # ChampRange is pinned to melee when the template resolves, so the ranged
        # half of Riot's `(Melee | Ranged)` pair is looked up by its sibling name.
        rq = _calc("Ranged" + names[0][5:], it)
        if rq is not None:
            return _merge({"melee": vals[0]["melee"], "ranged": rq["melee"]})
    if len(vals) == 2 and " | " in content:   # (melee | ranged) display pair
        return _merge({"melee": vals[0]["melee"], "ranged": vals[1]["melee"]})
    return _merge(vals[0])


def _blocks(tpl: str):
    """Template -> [(passive name, resolved body)], one per leading `<passive>`.

    Not `HEAD`: a passive's own name recurs inline ("per <passive>Glory</passive>"),
    which `HEAD` reads as a new block. Riot starts each real one after a blank line.
    """
    tpl = _resolve_string_refs(tpl)
    out = []
    for chunk in re.split(r"(?:<br>){2}(?=<(?:passive|active)>)", tpl):
        m = re.match(r"<passive>(.*?)</passive>", chunk)
        if m:
            out.append((plain(m.group(1)).strip(), chunk))
    return out


def _dv_named(it: Item, names):
    for n in names:
        v = it.value(n)
        if v is not None:
            return v
    return None


def _text(body: str) -> str:
    """A block's sentence, without the name line it opens on."""
    return plain(body).partition("\n")[2]


def _number(name: str, it: Item):
    """A named value or a one-number calculation."""
    v = it.value(name)
    if v is None:
        q = _calc(name, it)
        v = q["melee"].get("base") if q else None
    return v


def _timing(name: str, body: str, it: Item, every) -> dict | None:
    """When a damage line fires -> trigger fields, or None if the text does not say."""
    t = _text(body)
    head = re.search(r"\(@(\w+)@s\)", body)
    cd = _number(head.group(1), it) if head else None
    if every:
        # ponytail: the word is the count when no data value names it, as `_EVERY_NTH` does.
        return {"trigger": "every-n", "n": int(_dv_named(it, COUNT_NAMES) or NTH[every.group(1).lower()])}
    sep = SEPARATE.search(t)
    if sep:
        return {"trigger": "every-n", "n": int(sep.group(1)), "on": "both", **({"cooldown": cd} if cd else {})}
    if re.search(r"spellblade|after using an? ability", t, re.I):
        cd = _dv_named(it, ["Cooldown"])
        return {"trigger": "on-cast", **({"cooldown": cd} if cd is not None else {})}
    delayed = re.match(r"After @\w+@ seconds, deal", t)
    if delayed:
        # Stormsurge: the bin's DamageThreshold of max Health in its window. Cumulative
        # here, so it opens a little early on a slow fight.
        gate, cd = it.value("DamageThreshold"), it.value("Cooldown")
        return None if gate is None else {"trigger": "on-hit", "on": "both", "below": 1 - gate, "cooldown": cd}
    for pattern, fields in TIMING:
        if re.search(pattern, t, re.I if pattern == "next Attack" else 0):
            out = {**fields}
            if cd is not None:
                out.setdefault("cooldown", cd)
            periodic = re.match(r"Every @(\w+)@ seconds", t)
            if periodic:
                out["cooldown"] = out["delay"] = _number(periodic.group(1), it)
            near = re.search(r"nearby for @(\w+)@ seconds", t)
            if near:
                out["delay"] = _number(near.group(1), it)
            return out
    return {"trigger": "on-hit"} if "OnHit" in body or "Attacks deal" in body else None


def _block_effects(name: str, body: str, it: Item, src: str) -> list[dict]:
    if name in NOT_IN_FIGHT:
        return [{"trigger": "note", "name": name, "reason": NOT_IN_FIGHT[name], "source": src}]
    null = lambda why: [{"handler": None, "name": name, "reason": why}]  # noqa: E731
    if name in UNREAD:
        return null("changes fight damage, not read")
    every = EVERY.search(body)
    when = _timing(name, body, it, every)
    effs = []
    burn = PER_SECOND.search(_text(body))
    seconds = (it.value(burn.group(1) or burn.group(2)) if burn else None)
    over = re.search(r"over @(\w+)@ seconds", body)
    for m in DMG_SPAN.finditer(body):
        kind, content = m.groups()
        after = body[m.end():m.end() + 60]
        if "@" not in content or re.match(r"\s*(?:to monsters|against structures|against Minions|"
                                          r"to enemies behind|to nearby enemies)", after):
            continue                 # a label ("bonus physical damage"), no number
        before = body[max(0, m.start() - 12):m.start()].lower()
        if "maximum" in before and effs:   # Luden's: every Echo on one target, as the bin totals it
            q = _quantity(content, it)
            if q is None:
                return null("damage number not in the bin")
            keep = {f: v for f, v in effs[-1].items() if f not in ("base", "ratio", "ratios", "stat")}
            effs[-1] = {**keep, **q}
            continue
        for frag in re.split(r" \+ | plus ", content):
            if "@" not in frag:
                continue
            q = _quantity(frag, it)
            if q is None:
                return null("damage number not in the bin")
            if "up to" in before and effs:
                if "missing" not in body.lower():
                    return null("unrecognised max damage")
                effs[-1]["ramp"] = {"pctTarget": "missing", "max": q.get("base")}
                continue
            tail = plain(frag + after)
            pt, own = PCT_OF.search(tail), OWN_PCT.search(tail)
            if own and "base" in q:
                q = {"ratio": q.pop("base"), "stat": own.group(1).replace("max ", ""), **q}
            elif pt and "base" in q and "ratio" not in q:
                # a bare fraction followed by "of ... current Health" is a % of target
                q = {"ratio": q.pop("base"), "pctTarget": PCT_WORD[pt.group(1).lower()], **q}
            if when is None:
                return null("damage with no on-hit trigger")
            e = {"kind": kind, **q, "source": src, **when}
            if burn:
                if seconds is None:
                    return null("burn length not in the bin")
                # A second cast refreshes a burn, so it runs at most once per its length.
                e = {**e, **_times(q, seconds), "cooldown": max(seconds, e.get("cooldown") or 0)}
            elif over:
                e["cooldown"] = max(it.value(over.group(1)) or 0, e.get("cooldown") or 0)
            effs.append(e)
    if effs:
        if when.get("cooldown") == ONCE:
            effs.append({"trigger": "note", "name": f"{name}: cadence not read, counted once", "source": src})
        if "additional time" in _text(body):
            effs.append({"trigger": "note", "name": f"{name}: second on-hit application", "source": src})
        if SHRED.search(body):
            effs.append({"trigger": "note", "name": f"{name}: Magic Resist reduction left out", "source": src})
        return effs
    cv = CONVERT.search(_text(body))
    if cv and it.value(cv.group(1)) is not None:
        return [{"trigger": "static", "stat": CONVERT_TO[cv.group(3)], "of": cv.group(2),
                 "ratio": it.value(cv.group(1)), "source": src}]
    sm = STAT_SPAN.search(body)
    if sm and not DMG_SPAN.search(body):
        q = _quantity(sm.group(2), it)
        if q is not None and "base" not in q and isinstance(q.get("stat"), str):
            return [{"trigger": "static", "stat": STAT_TAGS[sm.group(1)], "of": q["stat"],
                     "ratio": q["ratio"], "source": src}]
        if q is None or "base" not in q:
            return null("stat number not in the bin")
        ult = re.match(r"After casting your Ultimate.*?for @(\w+)@ seconds", _text(body))
        if ult and it.value(ult.group(1)) is not None:
            return [{"trigger": "stack", "stat": STAT_TAGS[sm.group(1)], "on": "cast", "slot": "R", "stackMax": 1,
                     "base": q["base"], "duration": it.value(ult.group(1)),
                     "cooldown": it.value("Cooldown"), "source": src}]
        burst = re.match(r"On-Attacking an enemy champion.*?for @(\w+)@ seconds", _text(body))
        if burst and it.value(burst.group(1)) is not None and it.value("Cooldown") is not None:
            return [{"trigger": "stack", "stat": STAT_TAGS[sm.group(1)], "on": "hit", "stackMax": 1,
                     "base": q["base"], "duration": it.value(burst.group(1)),
                     "cooldown": it.value("Cooldown"), "source": src},
                    {"trigger": "note", "name": f"{name}: attacks shorten its cooldown, left out", "source": src}]
        e = {"trigger": "static", "stat": STAT_TAGS[sm.group(1)],
             "base": q["base"], "source": src}
        if re.search(r"\*100", sm.group(2)):
            e["unit"] = "fraction"
        mx = re.search(r"(?:up to|stacks) @(\w+)@", body)
        if re.search(r"\bstack|per <passive>", body, re.I) and mx:
            e["trigger"], e["stackMax"] = "stack", _dv_named(it, [mx.group(1)])
            d = re.search(r"for @(\w+)@ seconds", body)
            if d:
                e["duration"] = _dv_named(it, [d.group(1)])
            if e["stackMax"] is None:
                return null("stack cap not in the bin")
            if every:
                if re.search(r"applies .*twice", plain(body), re.I):
                    return [e, {"trigger": "phantom", "n": NTH[every.group(1).lower()],
                                "whileFull": e["stat"], "source": src}]
                return [e, *null("every-n clause on a stack effect")]
            if len(STAT_SPAN.findall(body)) > 1:
                return [e, *null("further stat clause")]
        elif CONDITION.search(plain(body)):
            return null("conditional stat")
        return [e]
    return null("no damage or stat number")


def effects_for(iid: str, raw: dict) -> list[dict]:
    tpl = STRINGS_BY_KEY.get(f"item_{iid}_tooltip")
    if not tpl:
        return []
    it = Item(raw)
    out = []
    for name, body in _blocks(tpl):
        out += _block_effects(name, body, it, f"Items/{iid}/mItemCalculations")
    return out


def riot_name(iid: str) -> str | None:
    return (STRINGS_BY_KEY.get(f"item_{iid}_name")
            or STRINGS_BY_KEY.get(f"game_item_displayname_{iid}"))


def bake() -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    print(f"catalog {catalog.get('ver')} — {len(catalog['items'])} items")
    print("fetching Riot's item bin and string table (about 49 MB)")
    items_bin = fetch(BIN)
    STRINGS_BY_KEY.clear()
    STRINGS_BY_KEY.update(fetch(STRINGS)["entries"])

    out, fx, skew, kept = {}, {}, [], 0
    for item in catalog["items"]:
        iid = str(item["id"])
        raw = items_bin.get(f"Items/{iid}")
        if raw is None:
            continue
        rn = riot_name(iid)
        if rn is None or rn.strip().lower() != item["n"].strip().lower():
            # The id is not a stable join across the two sources; print, never drop
            # silently. See the module docstring on 3097.
            skew.append(f"{item['n']} ({iid}) — Riot calls it {rn!r}")
            continue
        ef = effects_for(iid, raw)
        if ef:
            fx[iid] = ef
        bl = resolve_item(iid, raw)
        if bl:
            out[iid] = bl
            kept += 1

    for s in skew:
        print(f"  SKIPPED, name disagrees: {s}", file=sys.stderr)
    print(f"resolved {kept} items")
    nulls = sum(1 for e in fx.values() if any(x.get("handler", 1) is None for x in e))
    print(f"effects for {len(fx)} items, {nulls} with a handler: null effect")
    # `items` (display text) is unchanged; `effects` sits beside it, keyed the same.
    return {"ddragon": catalog.get("ver"), "items": out, "effects": fx}


def check() -> int:
    """The shipped file holds no unresolved token and joins to the catalog."""
    dest = vault_root() / "data" / OUT
    if not dest.exists():
        print(f"{dest} is not there — run the baker first")
        return 1
    baked = json.loads(dest.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    ids = {str(i["id"]) for i in catalog["items"]}
    ps = {str(i["id"]) for i in catalog["items"] if i.get("ps")}

    bad = []
    for iid, bl in baked["items"].items():
        if iid not in ids:
            bad.append(f"{iid}: not in the catalog")
        for b in bl:
            if PH.search(b["h"]) or PH.search(b["t"]):
                bad.append(f"{iid}: unresolved token in {b['h']!r}")
            if not b["t"].strip():
                bad.append(f"{iid}: empty passive body")
    if baked.get("ddragon") != catalog.get("ver"):
        bad.append(f"baked against {baked.get('ddragon')}, catalog is {catalog.get('ver')}")

    for iid, efs in baked.get("effects", {}).items():
        if iid not in ids:
            bad.append(f"{iid}: effects for an item not in the catalog")
        for e in efs:
            if e.get("handler", 1) is None:
                if not e.get("name"):
                    bad.append(f"{iid}: null effect with no name")
            elif not e.get("source") or e.get("trigger") not in TRIGGERS:
                bad.append(f"{iid}: effect with no source or trigger {e}")

    covered = len(set(baked["items"]) & ps)
    print("\n".join(bad) if bad else
          f"{len(baked['items'])} items clean, {covered}/{len(ps)} of the "
          f"catalog's passive-bearing items covered "
          f"({covered / len(ps) * 100:.1f}%), baked against {baked['ddragon']}")
    return 1 if bad else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()
    out = bake()
    dest = vault_root() / "data" / OUT
    dest.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(f"\n{dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
