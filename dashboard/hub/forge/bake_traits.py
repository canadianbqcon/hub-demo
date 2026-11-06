#!/usr/bin/env python3
"""Bake champion traits for the Draft surface into data/forge-traits.json.

Traits are computed per archetype: the keystone, core items and skill order
read off lolalytics (data/forge-archetypes.next.json), run through CommunityDragon's
champion bins (the live patch's DataValues, formula trees and cooldowns) on the
event timeline in fight_timeline.py.

The calculation contract:

  Reference state  level LEVEL; ranks counted from the archetype's skill order;
                   the archetype's core items plus its boots, from catalog.json
                   stats and data/forge-item-passives.json statics.
  The fight        FIGHT seconds against the roster's mean level-11 dummy
                   (fight_timeline.dummy). Every cast and attack hits; resource
                   costs are ignored; the target never fights back, so defensive
                   triggers and item actives are named in `excluded`.
  A spell's lines  The game's own tooltip says what each calculation is: the
                   `@Name@` inside <physicalDamage>, <magicDamage>,
                   <trueDamage>, <healing> or <shield>; a heal or shield is
                   for allies when the tooltip names allies. Per cast the largest
                   line of each kind counts (not their sum, because tooltips
                   list the same hit several ways: min, max, vs minions).
                   A percent of max Health is a share of the target's; current
                   and missing read when the hit lands; a percent of anything
                   else gives no amount. A charge spell waits on its recharge.
                   An effect with `slot` fires only on that slot's casts.
  Unsupported      A calculation with a part type `evaluate` does not know
                   (a stack count from before the fight, a non-mana resource)
                   returns None, and every trait it feeds is `unknown` for
                   that archetype, never a guess. So does a spell with no tooltip.
  CC               <status> words in the tooltip, classed hard or soft by
                   stem; the duration is the next `@Value@ second(s)` within
                   CC_LOOKAHEAD characters. A class of CC with no duration
                   anywhere in the tooltip is `unknown`.

    python3 bake_traits.py --archetypes                # every staged archetype, then publish
    python3 bake_traits.py --archetypes --champ Viego  # print rows, never publish
    python3 bake_traits.py --items                     # data/forge-item-traits.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fight_timeline as ft  # noqa: E402
import build_styles as bs  # noqa: E402
from vault_path import vault_root  # noqa: E402

OUT = vault_root() / "data" / "forge-traits.json"
STAGED = vault_root() / "data" / "forge-archetypes.next.json"
ARCH_WORK = vault_root() / "data" / "forge-archetypes.work.json"
ARCH_LIVE = vault_root() / "data" / "forge-archetypes.json"
ITEM_PASSIVES = vault_root() / "data" / "forge-item-passives.json"
WIKI = vault_root() / "data" / "forge-champions.json"   # wiki ability text, the keyword fallback
CATALOG = Path(__file__).resolve().parent / "frontend" / "static" / "catalog.json"
CACHE = Path.home() / ".cache" / "forge-cdragon"
BIN_URL = "https://raw.communitydragon.org/latest/game/data/characters/{c}/{c}.bin.json"
STRINGS_URL = "https://raw.communitydragon.org/latest/game/en_us/data/menu/en_us/lol.stringtable.json"
PERKS_BIN_URL = "https://raw.communitydragon.org/latest/game/perks.cdtb.bin.json"
PERKS_JSON_URL = ("https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/"
                  "global/default/v1/perks.json")
DDRAGON_URL = "https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")

# --- tunables ---------------------------------------------------------------
LEVEL, FIGHT, BURST, CRIT_MULT, AS_CAP = ft.LEVEL, ft.FIGHT, ft.BURST, ft.CRIT_MULT, ft.AS_CAP
REF_TARGET_HP = 2400  # a level 11 target with two defensive items, for %-health lines
CC_LOOKAHEAD = 140    # characters after a <status> word to look for its duration
MIN_COOLDOWN = 1.0    # seconds; a bin cooldown below this is ammo or a toggle
MAX_RANGE = 5000      # a cast range past this is global or self-cast, not range
MIN_RANGE = 100       # under this is no reach (Cho'Gath E castRange 40); melee self-casts sit at 125+
MELEE_BELOW = 300     # attack range; Viego 200 melee, Rakan 300 ranged
MAX_FAILED = 0.05     # failure share above which nothing is published
HARD_CC = ("stun", "root", "knock", "suppress", "charm", "fear", "flee", "taunt",
           "sleep", "polymorph", "pull", "drag", "immobiliz", "airborne", "disabl")
AIRBORNE_CC = ("knock", "pull", "drag", "airborne")   # tenacity and cleanses never shorten these
SUPPRESS_CC = ("suppress",)                          # tenacity never shortens it; QSS removes it
SOFT_CC = ("slow", "silenc", "blind", "ground", "nearsight", "cripple", "disarm")
# ---------------------------------------------------------------------------

DAMAGE_TAGS = {"physicalDamage": "physical", "magicDamage": "magic", "trueDamage": "true"}
_TAG = re.compile(r"<(physicalDamage|magicDamage|trueDamage|healing|shield)>(.*?)</\1>", re.S | re.I)
_REF = re.compile(r"@([A-Za-z_][\w]*)(?:\*[\d.]+)?@")
_LINE_REF = re.compile(r"@(?:spell\.(\w+):)?([A-Za-z_]\w*)(?:\*([\d.]+))?@(\s*%)?", re.I)
_CLIENT_VAR = re.compile(r"f\d+(?:\.\d+)?")
_PER_PERCENT = re.compile(r"per 1%")
_ADDS = re.compile(r"@\s*(?:plus|\+|\(\+)\s*@", re.I)
_HEALTH = re.compile(r"(max|maximum|current|missing)(?:\s+\w+)?[\s-]+health", re.I)
# a calc with no mDisplayAsPercent still reads as a share when a health word follows it (Zed P)
_PCT_OF_HEALTH = re.compile(r"\s*%?\s*(?:of (?:\w+ )*)?(?:max|maximum|current|missing)(?:\s+\w+)?[\s-]+health", re.I)
_OWN_MAX_HEALTH = re.compile(r"\s*(?:of (?:his|her|their) )?max(?:imum)? health(?! per)", re.I)  # after a literal %
_RANGE_LOW = re.compile(r"\s*to\s+@")                     # "@Floor@ to @Max@": the low end of a range
_CAP_OPEN = re.compile(r"\((?:max|up to)\b[^@)]*$", re.I)  # "(max: @Cap@)", "(up to a maximum of @Cap@"
_CAP_BEFORE = re.compile(r"maximum of\s*$", re.I)          # "a maximum of <healing>@Cap@</healing>" (Gwen P)
_RATE_BODY = re.compile(r"attack damage|bonus AD|mana|per @", re.I)
_HEAL_NAME = re.compile(r"heal(?!th)|shield", re.I)
_SUFFERS = re.compile(r"\b(?:suffers|loses|set to)\s*$", re.I)  # a cost paid by the caster (Locke W, K'Sante R)
# tower stays out: Azir's TowerDamage is the Sun Disc's real hit, Volibear's equals his sweet spot
_NOT_CHAMPION = re.compile(r"monster|minion|structure|nonchamp", re.I)
_ON_CHAMPION = re.compile(r"(?<!non)champion", re.I)       # HealthRestoreOnHitChampionMonster (Mundo)
_LOCKOUT = re.compile(r"more than once every @(\w+)@ seconds", re.I)  # Ekko P
_SCALE_AD = re.compile(r"<scaleAD>\s*@(\w+)@", re.I)
_STATUS = re.compile(r"<status>([^<]+)</status>", re.I)
_DURATION = re.compile(r"(?<!over )@([A-Za-z_]\w*)@\s*(?:</[^>]+>\s*)?(?:second|s\b)", re.I)  # over: a heal's time
_LITERAL_SECONDS = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:</[^>]+>\s*)?second", re.I)
_SENTENCE_END = re.compile(r"\.(?=\s|<|$)")
_WALL_IF = re.compile(r"\b(?:if|that|who)\b[^.]*\b(?:walls?|terrain)\b", re.I)
_CC_DURATION = ("ccduration", "stunduration", "grabduration")  # bin names any CC word reads
_RANGE_NAME = re.compile(r"^(?:[er]|base|e?max\w*?|e2long|spellmax|evolved)?(?:cast|dash|leap|jump|missile)?range$")
_ALLY = re.compile(r"\ball(y|ied|ies)\b", re.I)
# Thresh W "to Thresh and the first ally champion", Rakan Q, Sona W: the caster gets it too
_SELF_AND_ALLY = re.compile(r"\bto (?:himself|herself|itself|themselves|[A-Z][\w']+) and (?:an?|the|nearby|first|\s)*all(?:y|ied|ies)\b")
# Taric Q "(@MaxStackHealing@ at @MaxCharges@ stacks)": the per-stack line beside it is one cast's
_AT_STACKS = re.compile(r"\s*at @\w+@ stacks", re.I)
# "Every third consecutive Attack ..." (Vayne W): a no-cooldown spell that procs on attacks.
_EVERY_NTH = re.compile(r"every (second|third|fourth|fifth|2nd|3rd|4th|5th)\b[^.]{0,40}?\battack", re.I)
# how many times one tag lands in a cast: seconds of a per-second line, or a stated count
_CLAUSE_END = re.compile(r"\.(?=\s|<|$)|<br\s*/?>", re.I)
_PER_SECOND = re.compile(r"\b(?:per|each) second\b", re.I)
_AFTER_TAG = re.compile(r"\s*(?:\w+\s+){0,3}?(?:and\s+\w+\s+<(\w+)>[^<]*</\1>\s*)?(?:per|each) second\b", re.I)
_TICK = re.compile(r"\s*(?:\w+\s+){0,4}?every @(\w+)@ seconds", re.I)     # Kennen R
_TICK_AMP = re.compile(r"successive hits deal @(\w+)\*100@% increased damage", re.I)
_SPAN = re.compile(r"\b(?:for|over|lasts?|up to)\s+(?:the next\s+|a duration of\s+)?(?:<[^>]+>\s*)*"
                   r"(?:@([\w.]+?)(?:\*[\d.]+)?@|(\d+(?:\.\d+)?))\s*(?:</[^>]+>\s*)*seconds?\b", re.I)
_COUNT = re.compile(r"(?:@([\w.]+?)(?:\*[\d.]+)?@|\b(\d+|two|three))\s*(?:</[^>]+>\s*)?(?:\(rounded down\)\s*)?"
                    r"(?:[a-z'-]+\s+){0,2}?(waves|shots|rockets|missiles|bolts|strikes|rocks|bullets|daggers|snowballs|times)\b"
                    r"( a second)?", re.I)
_WORD_COUNT = {"two": 2.0, "three": 3.0}
_TWICE = re.compile(r"twice for\s*$", re.I)    # Samira W
# a stack cap, a stated sum, a condition (Aurora P), one empowered attack in parts (Renekton W, Warwick R)
_NOT_A_COUNT = re.compile(r"stack|a total of|past the first|\bdamaging\b"
                          r"|\battacks?\s+(?:\w+\s+){0,2}?(?:\d+|@\w+@)\s+times(?! a second)", re.I)
_SUM_NAME = re.compile(r"combined|cumulative", re.I)      # Lulu P, Warwick R
_EACH = re.compile(r"\b(?:each|per)\s+(?!enemy|enemies|champion|target|unit|\d|@)", re.I)
_TOTAL_BEFORE = re.compile(r"\(total\s*$", re.I)           # "(total <tag>@Sum@</tag>)" (Miss Fortune R)
_CRIT_LINE = re.compile(r"critically strike for[^<]*$", re.I)
_RECAST = re.compile(r"recast(?:</\w+>)?\s+up to @(\w+)@ times", re.I)  # Xerath R
# every cast repeats the line (Aatrox Q, Riven Q, Ahri R, Nunu E); Xerath's first cast deals nothing, so his stays `_RECAST`
_RECASTS = re.compile(r"<recast>Recast</recast>\s*(?:this(?: ability)?\s+)?"
                      r"(?:twice|up to twice more|up to @(\w+)@ times|up to (?:2|two) (?:more|additional) times)", re.I)
_RAMP = re.compile(r"dealing (\d+)% more damage than the previous", re.I)    # Aatrox Q
# a recast's own hit, added to the first cast's (Lee Sin Q, Akali E and R, Vex R, Gwen R, Camille Q, Renekton E)
_RECAST_HIT = re.compile(r"<recast>(?:Recast:</recast>|Recast</recast>:|(?:Second|Third) Cast:)"
                         r"|<recast>Recast</recast>(?: dash deals\s*$|[^.]*\b(?:dealing|increased to)\s*$)", re.I)
_RECAST_ELSE = re.compile(r"\bends this ability\b", re.I)    # Skarner Q throws in place of the attacks
_THROWN = re.compile(r"\s*to enemies they are thrown into", re.I)    # Renata Q, on others, not on the lone target
_PER_HIT = re.compile(r"\s*per (?:shot|hit|wave|strike)\b", re.I)
# "@Low@ to @High@": the low end carries the repeat
_CEILING = re.compile(r"(?:</\w+>\s*to|increased (?:by )?up to|between\s+<\w+>[^<]*</\w+>\s*and)\s*$", re.I)
_CHANNEL = re.compile(r"channel|rapidly|torrent|\bfiring\b", re.I)
# a one-hit channel holds the caster too; Quinn, Shen and Caitlyn R stay free (players release early)
_HOLDS = re.compile(r"(?<!interrupting )\bchannels?\b(?:(?!slow)[^.])*?\b(?:for|over)\s+(?:up to\s+)?(?:<[^>]+>\s*)*"
                    r"(?:@([\w.]+?)(?:\*[\d.]+)?@|(\d+(?:\.\d+)?))\s*(?:</[^>]+>\s*)*seconds?\b"
                    r"|\bfor up to @(\w*ChannelDuration)@ seconds"
                    r"|\brapidly\b[\s\S]*?\btotal over @(\w+)@ seconds to each enemy"     # Katarina R
                    r"|<status>Suppresses</status>[^.]*?\bover @(\w*CCDuration)@ seconds", re.I)     # Malzahar R
# the damage grows with charge, so the full-charge line read pays the full bin channel; a quick release reads a little low
_CHARGED = re.compile(r"based on (?:time )?charge|with charge time|uncharged", re.I)
# Sourced from the wiki's row, the only hand table: no bin holds these. `free` keeps a bin channel off the lock,
# `onCast` starts the cooldown at the cast (wiki cdstart), `cooldown` is added whole in place of the lock,
# `refund` is the share of the remaining cooldown given back once the spell lands or its channel ends, a number or
# the DataValue holding it, `back` the DataValue of seconds cut, `cap` the DataValue the cooldown cannot exceed.
# Only cuts a cast earns alone; cuts on attacks, crits or other casts are `_WIKI_CUTS`, on kills are left out.
_WIKI_TIMING = {
    ("Aatrox", "Q"): {"lock": 1.8, "cooldown": 2.0},   # cast time 0.6 x 3, "restarts on each successive recast", 1 s static gap x 2
    ("Pantheon", "R"): {"lock": 4.35},                 # cast time 0.1, channels of 2 and 2.25, the wiki rows all three alike, no bin channel
    ("Pantheon", "E"): {"free": True},                 # cdstart post-effect, a stance players release
    ("Rammus", "Q"): {"free": True},                   # a roll, not a stand, the bin length is its maximum
    ("Nunu", "W"): {"free": True},                     # a roll, not a stand, the bin length is its maximum
    ("Senna", "Q"): {"free": True},                    # cast time is 80% of her windup
    ("Zoe", "W"): {"free": True},                      # no channel row
    ("Galio", "W"): {"onCast": True},
    ("Vladimir", "E"): {"onCast": True},
    ("Varus", "Q"): {"onCast": True},                  # post-effect, "the cooldown is reduced equal to the charge duration"
    ("Fiddlesticks", "W"): {"onCast": True, "refund": 0.6},   # cdstart on-cast, "60% of the current cooldown is refunded"
    ("Fiora", "Q"): {"refund": "CDRefundPercent"},     # "Stabbing a target reduces Lunge's cooldown by 50%"
    ("Gragas", "E"): {"refund": "CooldownRefund"},     # "current cooldown is reduced by 40%"
    ("Pantheon", "Q"): {"refund": "TapCooldownRefund"},   # a tap, "refunding 60%"; the fight holds no charge on it
    ("TahmKench", "W"): {"onCast": True, "refund": "ChampRefund"},   # cdstart on-cast, 40 to 50% on a champion hit
    ("Thresh", "Q"): {"back": "HitBonusCooldown"},     # "reduce Death Sentence's current cooldown by 2 seconds"
    ("Olaf", "Q"): {"cap": "MinimumCooldown"},   # "pick up the axe to reduce Undertow's current cooldown to 2.5"; assumes the pick-up
    # tooltip "cannot dash over the same terrain more than once every @WallCD@ seconds"; DisplayCD 2 stays the page's
    # cooldown. `wait` is the DataValue the fight waits on in place of the cooldown.
    ("Talon", "E"): {"wait": "WallCD"},
}
# Cuts the timeline applies as events happen (ft.Cast.cuts), keyed by the spell whose wiki row states them.
# `slots` are the spells cut; a str `s` or `share` or `while` names that spell's DataValue. Wiki wording in each comment.
_WIKI_CUTS = {
    ("MonkeyKing", "Q"): [{"slots": "Q", "on": "attack", "s": "CooldownDecrease"}],   # "reduced by 0.5 s" per damage he deals
    ("Lucian", "E"): [{"slots": "E", "on": "attack", "armed": True, "s": "CDRefundChampion"}],
    # "reduced by 1 second for each Lightslinger shot hit, doubled to 2 against enemy champions"; one extra shot per cast
    ("MissFortune", "W"): [{"slots": "W", "on": "attack", "once": True, "s": "LoveTapBaseRefund"}],   # Love Tap: a NEW target only
    ("Sivir", "R"): [{"slots": "QWE", "on": "attack", "s": "AttackCooldownRefund", "while": "UltDuration"}],
    # "while active, basic attacks reduce her basic abilities' current cooldowns by 0.5"
    ("Tryndamere", "E"): [{"slots": "E", "on": "attack", "crit": True, "s": "ChampCDRefund"}],   # crits, 1.5 s vs champions
    ("Janna", "E"): [{"slots": "E", "on": "cast", "from": "QW", "cc": True, "share": "ECDRefundforCC"}],
    # "whenever her abilities slow or knock up an enemy champion, 20% of the cooldown is refunded"; R knocks back, not up
    ("Ezreal", "Q"): [{"slots": "QWER", "on": "cast", "from": "Q", "s": "CDRefund"}],   # a hit cuts all his abilities 1.5 s
}
# Stacks from before the fight, by the bin's buff hash (a BuffCounter part's mBuffName). No source
# holds a count, so these are labeled estimates at the fight's level 11, read as about minute 15
# (assumed): the fight runs on `typical`, traits it moves read source "estimate" with the
# low-to-high range. A hash not here stays unknown. Approved 2026-11-01. Kindred and Aurelion Sol
# (approved 2026-11-02) have no published numbers: low and high are game-rule bounds and typical
# is their midpoint, which no community number checks.
STACKS = {
    "{1b1d7345}": {"low": 150, "typical": 275, "high": 500, "basis": (  # Nasus Q, Siphoning Strike
        "Nasus Q stacks at minute 15: low is a guide's 'at least 150 by 15 minutes', typical is dodge.gg's "
        "400 to 700 over 30 minutes read linearly (200 to 350 at 15), high is a season 16 guide's "
        "'about 500 before 15 minutes' in a very favorable lane")},
    "{5fbfbf13}": {"low": 45, "typical": 55, "high": 70, "basis": (  # Thresh souls
        "Thresh souls at minute 15: 3 to 4 per minute (forum, 2013) gives 45 to 60, "
        "a mobafire guide states 50 to 70 by 10 to 15 minutes")},
    "{32bcea5d}": {"low": 125, "typical": 160, "high": 225, "basis": (  # Smolder Dragon Practice
        "Smolder stacks at minute 15: a guide's milestones, 125 at 12 to 13 minutes and 225 at 18 to 20, "
        "read linearly give 160; low is 125 reached late, high is 225 reached early")},
    "{8682fc00}": {"low": 3, "typical": 6, "high": 8, "basis": (  # Cho'Gath R, Feast
        "Cho'Gath Feast stacks at minute 15, spell math: R learned at level 6 (about minute 7, assumed), "
        "80 s cooldown at rank 1 gives about 6 casts, and only 6 stacks come from minions and monsters; "
        "low spends half on champions that live, high adds 2 champion kills")},
    "{64290302}": {"low": 0, "typical": 8, "high": 17, "basis": (  # Kindred marks
        "Kindred marks at minute 15, game rules only (no published count): low is no hunt finished; "
        "high is every Wolf monster mark taken the moment it appears, the first at 2:53 and one 45 s "
        "after each hunt ends, 17 by 15:00, champion marks not counted; typical is the midpoint")},
    "{c9372c6b}": {"low": 0, "typical": 93, "high": 186, "basis": (  # Aurelion Sol Stardust
        "Aurelion Sol Stardust at minute 15, game rules only (no published count): low is none; high is "
        "every lane minion dying in Singularity (1 each, 2 per siege minion, from the bin), with waves "
        "every 30 s from 0:30 and a siege minion every third wave (wiki minion rules, assumed current) "
        "giving about 28 waves, 168 minions and 9 siege by 15:00, champion Stardust (Q 2 per burst, "
        "E 1 per second, R 5 per hit) not counted; typical is the midpoint")},
}
# "<li>@StackTier3@ Stacks: ..." (Smolder Q): the line counts only once the spell's buff reaches that count
_TIER = re.compile(r"<li>\s*(?:<\w+>)?@(\w+)@ Stacks", re.I)
_BUFF = re.compile(r'"mBuffName": "([^"]+)"')
_SPELL_REF = re.compile(r"@spell\.(\w+):(\w+)")
_MOVES_FIRING = re.compile(r"can move while firing", re.I)   # Urgot W, the wiki reads Cast Time none
# one target takes the first hit whole, the rest at a stated share (Kai'Sa Q) or a share no bin holds (Heimerdinger R)
_FALLOFF = re.compile(r"additional \w+(?: hits)?(?: on [\w ]+?)? (?:deal|take) (?:@(\w+)\*100@% damage|reduced damage)", re.I)
_FALLOFF_LESS = re.compile(r"subsequent hits[^.]*deal @(\w+)(\*100)?@% less damage", re.I)    # Taliyah Q
_FALLOFF_REACH = 200   # past that the text is another section of the tooltip
_BOUNCE = re.compile(r"\b(?:each|first|subsequent) bounces?\b", re.I)  # a hit per bounce, not an ally hop (Nami W)
_THEN = re.compile(r"\bthen\b|\bfollowed by\b", re.I)    # two hits of one cast, not alternatives (Nilah R)
# Talon W, R, the wiki's Total adds both passes; Nunu E's root; Naafiri Q's second cast
_RETURN_HIT = re.compile(r"(?:\breturn to \w+, dealing|\band deals an additional|\bplus between)\s*$", re.I)
# extra damage on the same hit adds to the line before it (Morgana R, Sylas Q, Poppy Q's max Health part)
_SUM = re.compile(r"\b(?:an additional|a further|plus(?: an additional)?)\s*$", re.I)
# ...unless the fight cannot promise it: a wall, a combo, an element, an ally, a second champion
_SUM_NOT = re.compile(r"terrain|\bwall|\bduring\b|enchantment|awaken|allied|brittle|bonus:|for each champion", re.I)
_NEXT_N = re.compile(r"\bnext (\d+|two|three|@\w+@) (?:attacks|abilities)\b", re.I)   # Evelynn Q
_PER_EXTRA = re.compile(r"\s*(?:per \w+|for each \w+(?: \w+)?)\s+(?:beyond|past) the first|\s*per stack", re.I)
# out and back on one target: the wiki's Total is twice (Draven R, Sivir Q, Akshan Q, Kled E). Gnar Q stops at its target
_TWO_WAYS = re.compile(r"reverse direction and return|like a boomerang|boomerang that deals[^.]*extending"
                       r"|dash back through the same target", re.I)
_NEAREST = re.compile(r"nearest enemy takes\s*(?:<\w+>)?@(\w+)\*100@% increased damage", re.I)      # Garen E
_GATED = re.compile(r"can only use this ability", re.I)   # Samira R
_CLIENT_COUNTS = ("TotalStrikes", "NumberOfStrikes", "NumTicks")     # no bin holds an @f2.0@
_NTH = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5}


# --- the evaluator ----------------------------------------------------------

def _growth(level: int) -> float:
    """Riot's per-level stat curve: total growth multiplier at `level`."""
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def _base(rec: dict, key: str) -> float:
    v = rec.get(key)
    return float(v.get("baseValue", 0.0)) if isinstance(v, dict) else float(v or 0.0)


def ref_stats(rec: dict, items: dict, level: int = LEVEL) -> dict:
    """{(stat id, formula): value}; formula 0 total, 1 base, 2 bonus.

    Stat ids as the bins use them (checked against the data value names they
    read): 0 AP, 1 armor, 2 AD, 4 attack speed, 6 MR, 7 move speed,
    8 crit chance, 9 crit damage, 12 max health, 29 lethality. ("resource", formula)
    is the ability resource, read by its own part type.
    """
    g = _growth(level)
    base = {
        0: 0.0,
        1: _base(rec, "baseArmorModifiable") + _base(rec, "armorPerLevelModifiable") * g,
        2: _base(rec, "baseDamageModifiable") + _base(rec, "damagePerLevelModifiable") * g,
        6: _base(rec, "baseMR") + _base(rec, "mrPerLevel") * g,
        7: _base(rec, "baseMoveSpeedModifiable"),
        8: 0.0, 9: CRIT_MULT,
        12: _base(rec, "baseHPModifiable") + _base(rec, "hpPerLevelModifiable") * g,
    }
    bonus = {0: items.get("ap", 0), 1: items.get("armor", 0), 2: items.get("ad", 0),
             6: items.get("mr", 0), 7: 0.0, 8: items.get("crit", 0), 9: 0.0,
             12: items.get("hp", 0)}
    as_base = _base(rec, "attackSpeedModifiable")
    as_ratio = _base(rec, "attackSpeedRatioModifiable") or as_base
    as_bonus = _base(rec, "attackSpeedPerLevelModifiable") / 100 * g + items.get("as", 0)
    out = {}
    for s in base:
        out[(s, 0)], out[(s, 1)], out[(s, 2)] = base[s] + bonus[s], base[s], bonus[s]
    out[(4, 1)], out[(4, 2)] = as_base, as_bonus
    out[(4, 0)] = min(AS_CAP, as_base + as_ratio * as_bonus)
    del out[(7, 2)]  # no source holds bonus move speed: a damage calc on it is unknown (Janna P), Hecarim P's AD is named
    out[(29, 0)] = items.get("lethality", 0)
    res = rec.get("primaryAbilityResource") or {}
    res_base = _base(res, "{726ee5cd}") + _base(res, "{6216bf7b}") * g
    res_bonus = items.get("mana", 0) if not res.get("arType") else 0.0  # arType 0 is mana
    out[("resource", 0)], out[("resource", 1)], out[("resource", 2)] = res_base + res_bonus, res_base, res_bonus
    return out


def _hash(name: str) -> str:
    """A bin's name for a string it dropped: FNV-1a of the lowercase text, `{0508ccce}`."""
    h = 0x811c9dc5
    for b in name.lower().encode():
        h = ((h ^ b) * 0x01000193) & 0xffffffff
    return f"{{{h:08x}}}"


def _calc(ctx: dict, name) -> dict | None:
    """A sibling calculation by name; either side may be the hashed form."""
    calcs = ctx["calcs"]
    return calcs.get(name) or next((v for k, v in calcs.items() if _hash(k) == name), None)


def evaluate(calc, ctx: dict):
    """A GameCalculation (or one part of one) to a number, or None when any
    part is a type this does not support.

    ctx: {"dv": {name: value at rank}, "stats": ref_stats(...), "level": int,
    "calcs": {name: calc} (for parts that point at a sibling calculation)}.
    """
    if not isinstance(calc, dict):
        return None
    t = calc.get("__type")
    ev = lambda p: evaluate(p, ctx)  # noqa: E731
    if t in ("GameCalculation", "{e9a3c91d}", None) and "mFormulaParts" in calc:
        parts = [ev(p) for p in calc["mFormulaParts"]]
        if any(p is None for p in parts):
            return None
        total = sum(parts)
        if "mMultiplier" in calc:
            m = ev(calc["mMultiplier"])
            if m is None:
                return None
            total *= m
        if ctx.get("ranged") and "mRangedMultiplier" in calc:  # a melee/ranged split
            m = ev(calc["mRangedMultiplier"])
            if m is None:
                return None
            total *= m
        return total
    if t == "GameCalculationConditional":  # the default arm; a bonus arm needs a buff the fight lacks
        return ev(_calc(ctx, calc.get("mDefaultGameCalculation")))
    if t == "GameCalculationModified":
        inner = _calc(ctx, calc.get("mModifiedGameCalculation"))
        a, m = ev(inner), ev(calc.get("mMultiplier"))
        return None if a is None or m is None else a * m
    if t == "NumberCalculationPart":
        return float(calc.get("mNumber", 0.0))
    if t == "NamedDataValueCalculationPart":
        return ctx["dv"].get(calc.get("mDataValue"))
    if t == "EffectValueCalculationPart":  # 1-based, as tooltips say @Effect1Amount@
        return ctx["dv"].get(f"effect{calc.get('mEffectIndex', 1)}amount")
    if t == "AbilityResourceByCoefficientCalculationPart":
        if calc.get("mAbilityResource"):  # a named non-mana bar (Tryndamere's Fury): no source holds its level
            return None
        s = ctx["stats"].get(("resource", calc.get("mStatFormula", 0)))
        return None if s is None else s * float(calc.get("mCoefficient", 0.0))
    if t in ("BuffCounterByCoefficientCalculationPart", "BuffCounterByNamedDataValueCalculationPart"):
        est = STACKS.get(calc.get("mBuffName"))
        per = (float(calc.get("mCoefficient", 0.0)) if t == "BuffCounterByCoefficientCalculationPart"
               else ctx["dv"].get(calc.get("mDataValue")))
        if est is None or per is None:
            return None
        if "est" in ctx:
            ctx["est"].append(calc["mBuffName"])
        return est[ctx.get("pick", "typical")] * per
    if t == "{b22609db}":  # base data value plus per level data value (Irelia passive, 10 to 61)
        a, b = ctx["dv"].get(calc.get("{91d404a5}")), ctx["dv"].get(calc.get("{b2cd0eb0}"))
        return None if a is None or b is None else a + b * (ctx["level"] - 1)
    if t == "StatByCoefficientCalculationPart":
        s = ctx["stats"].get((calc.get("mStat", 0), calc.get("mStatFormula", 0)))
        return None if s is None else s * float(calc.get("mCoefficient", 0.0))
    if t == "StatByNamedDataValueCalculationPart":
        s = ctx["stats"].get((calc.get("mStat", 0), calc.get("mStatFormula", 0)))
        v = ctx["dv"].get(calc.get("mDataValue"))
        return None if s is None or v is None else s * v
    if t == "StatBySubPartCalculationPart":
        s = ctx["stats"].get((calc.get("mStat", 0), calc.get("mStatFormula", 0)))
        v = ev(calc.get("mSubpart"))
        return None if s is None or v is None else s * v
    if t == "SumOfSubPartsCalculationPart":
        parts = [ev(p) for p in calc.get("mSubparts", [])]
        return None if any(p is None for p in parts) else sum(parts)
    if t == "ProductOfSubPartsCalculationPart":
        a, b = ev(calc.get("mPart1")), ev(calc.get("mPart2"))
        return None if a is None or b is None else a * b
    if t == "ClampSubPartsCalculationPart":
        parts = [ev(p) for p in calc.get("mSubparts", [])]
        if any(p is None for p in parts):
            return None
        floor, ceiling = calc.get("mFloor"), calc.get("mCeiling")  # null means no bound
        return max(-math.inf if floor is None else float(floor),
                   min(math.inf if ceiling is None else float(ceiling), sum(parts)))
    if t == "ByCharLevelInterpolationCalculationPart":
        a, b = float(calc.get("mStartValue", 0.0)), float(calc.get("mEndValue", 0.0))
        return a + (b - a) * (ctx["level"] - 1) / 17
    if t == "{ee18a47b}":  # interpolation between two named data values
        a, b = ctx["dv"].get(calc.get("StartDataValue")), ctx["dv"].get(calc.get("EndDataValue"))
        return None if a is None or b is None else a + (b - a) * (ctx["level"] - 1) / 17
    if t == "ByCharLevelBreakpointsCalculationPart":
        v = float(calc.get("mLevel1Value", 0.0))
        per = float(calc.get("mInitialBonusPerLevel", 0.0))
        bps = {bp.get("mLevel"): bp for bp in calc.get("mBreakpoints", [])}
        for lvl in range(2, ctx["level"] + 1):
            bp = bps.get(lvl) or {}
            v += float(bp.get("mAdditionalBonusAtThisLevel", 0.0))
            per = float(bp.get("mBonusPerLevelAtAndAfter", per))
            v += per
        return v
    if t == "ByCharLevelFormulaCalculationPart":
        vals = calc.get("values") or []
        # ponytail: 31 entries read as levels 0..30, so index = level; unverified
        # against a tooltip, revisit if a champion using it looks off
        return float(vals[ctx["level"]]) if len(vals) > ctx["level"] else None
    if t == "{f3cbe7b2}":  # a sibling calculation by name
        return ev(_calc(ctx, calc.get("mSpellCalculationKey")))
    return None


# --- one champion -----------------------------------------------------------

def _record(binj: dict) -> dict:
    return next(v for v in binj.values() if isinstance(v, dict) and v.get("__type") == "CharacterRecord")


def _spells(binj: dict, rec: dict) -> list[dict]:
    """The four ability spells (Q, W, E, R) as their `mSpell` blocks."""
    char = rec.get("mCharacterName") or ""
    out = []
    for name in (rec.get("spellNames") or [])[:4]:
        obj = (binj.get(f"Characters/{char}/Spells/{name}")
               or next((v for k, v in binj.items() if k.lower().endswith("/" + name.lower())), None))
        out.append((obj or {}).get("mSpell") or {})
    return out


def _named_spell(binj: dict, name: str) -> dict | None:
    return next(((v.get("mSpell") or {}) for k, v in binj.items()
                 if k.lower().endswith("/" + name.lower()) and isinstance(v, dict) and v.get("mSpell")), None)


class _NoCase(dict):
    """Data value names are matched without case: calcs say `rAPCoefficient`
    where the value is named `RAPCoefficient`."""

    def get(self, k, default=None):
        return super().get(str(k).lower(), default)


def _dv(spell: dict, rank: int) -> dict:
    out = _NoCase()
    for d in spell.get("DataValues") or []:
        vals = d.get("values") or []
        out[d["name"].lower()] = out[_hash(d["name"])] = float(vals[rank]) if len(vals) > rank else 0.0
    for n, e in enumerate(spell.get("mEffectAmount") or [], 1):  # tooltips say @Effect5Amount@
        vals = e.get("value") or []
        out[f"effect{n}amount"] = float(vals[rank]) if len(vals) > rank else 0.0
    return out


def _tooltip_key(spell: dict) -> str | None:
    return (((spell.get("mClientData") or {}).get("mTooltipData") or {}).get("mLocKeys") or {}).get("keyTooltip")


def _tooltip(spell: dict, strings: dict) -> str:
    key = _tooltip_key(spell)
    return strings.get(key.lower(), "") if key else ""


def _value(name: str, calcs: dict, ctx: dict):
    if name in calcs:
        return evaluate(calcs[name], ctx)
    return ctx["dv"].get(name)


def _calc_ref(ctx: dict, name: str) -> dict | None:
    """A tooltip's calculation: any case, or stored under its hash."""
    return next((v for k, v in ctx["calcs"].items() if k.lower() == name.lower() or k == _hash(name)), None)


def _clause(tip: str, at: int) -> tuple[int, int]:
    """Bounds of the sentence holding `at`."""
    start = 0
    for m in _CLAUSE_END.finditer(tip):
        if m.end() > at:
            return start, m.start()
        start = m.end()
    return start, len(tip)


def _read_number(name: str | None, literal: str | None, ctx: dict):
    """A number in a tooltip's text; an @f2.0@ reads the bin's strike count."""
    if literal:
        return _WORD_COUNT.get(literal.lower()) or float(literal)
    names = _CLIENT_COUNTS if _CLIENT_VAR.fullmatch(name) else (name,)
    for n in names:
        calc = _calc_ref(ctx, n)
        v = evaluate(calc, ctx) if calc is not None else ctx["dv"].get(n)
        if v:
            return float(v)
    return None


def _span(text: str, ctx: dict):
    """The seconds a sentence states, or None."""
    m = _SPAN.search(text)
    return _read_number(m.group(1), m.group(2), ctx) if m else None


def _repeat(tip: str, tm: re.Match, ctx: dict) -> tuple[float, str | None, float]:
    """(times this tag lands in a cast, floor note, channel seconds). A recast refreshes a
    per-second line, so it runs until the next cast at most."""
    # ponytail: a repeat lands whole at the cast, so burst overstates a burn or channel;
    # a per-tick timeline would fix it if burst ever ranks a DoT champion wrong
    start, end = _clause(tip, tm.start())
    sentence = tip[start:end]
    head = re.sub(r"(?:<br\s*/?>|\s)+$", "", tip[:start])
    before = head[_clause(head, len(head) - 2)[0]:] if len(head) > 1 else ""
    limit = min(ctx.get("wait") or ft.FIGHT, ft.FIGHT)
    if _TOTAL_BEFORE.search(tip, 0, tm.start()):
        return 1.0, None, 0.0
    if _PER_SECOND.search(tm.group(2)) or _AFTER_TAG.match(tip, tm.end()):
        seconds = _span(sentence, ctx)
        if not seconds and "<toggle>" in tip.lower():   # before `before`: Anivia R's growth time is not its length
            return limit, None, 0.0
        seconds = seconds or _span(before, ctx)
        if seconds:
            return min(seconds, limit), None, min(seconds, limit) if _CHANNEL.search(sentence) else 0.0
        return 1.0, "damage per second, duration not read, one second counted", 0.0
    tick = _TICK.match(tip, tm.end())
    rate = _read_number(tick.group(1), None, ctx) if tick else None
    seconds = _span(sentence, ctx) if rate else None
    if seconds:
        n = min(seconds, limit) / rate
        amp = _TICK_AMP.search(tip, tm.end())
        share = _read_number(amp.group(1), None, ctx) if amp else None
        return n + (share or 0.0) * n * (n - 1) / 2, None, 0.0
    if _TWICE.search(tip, 0, tm.start()):
        return 2.0, None, 0.0
    if _BOUNCE.search(sentence):   # on one target a bounce may land on nobody (Brand R, Zac R)
        return 1.0, "bounces not read, one hit counted", 0.0
    if _NOT_A_COUNT.search(sentence) or _SUM_NAME.search(tm.group(2)):
        return 1.0, None, 0.0
    found = next(_COUNT.finditer(tip, start, end), None)
    if found and found.group(3).lower() != "times" and not _EACH.search(sentence):
        found = None   # "rockets that deal", then "Max Damage:" holds the sum (Heimerdinger W)
    if not found and _EACH.search(sentence):
        for m in reversed(list(_COUNT.finditer(tip, 0, start))):
            unit = m.group(3).lower()
            if (unit == "times" or re.search(unit[:-1], sentence, re.I)) \
                    and not _NOT_A_COUNT.search(tip[slice(*_clause(tip, m.start()))]):
                found = m
                break
    if not found:
        if _TWO_WAYS.search(tip):
            return 2.0, None, 0.0
        again = _RECAST.search(tip, 0, start)
        n = _read_number(again.group(1), None, ctx) if again else None
        if n:
            return n, None, 0.0
        return 1.0, "hit count not read, one hit counted" if _PER_HIT.match(tip, tm.end()) else None, 0.0
    n = _read_number(found.group(1), found.group(2), ctx)
    if n and "rounded down" in found.group(0).lower():   # Smolder E, 6.6 bolts at typical stacks is 6
        n = float(math.floor(n))
    seconds = None
    if found.group(4):   # "@R@ times a second" is a rate
        seconds = _span(sentence, ctx) or _span(before, ctx) or ctx["dv"].get("Duration")
        seconds = min(seconds, limit) if seconds else None
        n = n * seconds if n and seconds else None
    if not n:
        return 1.0, "hit count not read, one hit counted", 0.0
    fall = _FALLOFF.search(tip, tm.end(), tm.end() + _FALLOFF_REACH)
    less = _FALLOFF_LESS.search(tip, tm.end(), tm.end() + _FALLOFF_REACH)
    delay = ctx["dv"].get("MinimumDelayBetweenShots")      # Jhin R
    # past 48 characters, a slow's length (Jhin R)
    seconds = seconds or _span(tip[_clause(tip, found.start())[0]:found.end() + 48], ctx) or (n * delay if delay else None)
    if fall:   # with no number, the tooltip's stated Max Damage line stands for the sum
        share = _read_number(fall.group(1), None, ctx) if fall.group(1) else None
        n = 1 + (n - 1) * share if share else 1.0
    elif less:
        off = _read_number(less.group(1), None, ctx)
        n = 1 + (n - 1) * (1 - off / (1 if less.group(2) else 100)) if off else 1.0
    elif ctx["dv"].get("MultiHitReduction"):   # Nautilus E, the wiki's Maximum Total Damage agrees
        n = 1 + (n - 1) * ctx["dv"].get("MultiHitReduction")
    near = _NEAREST.search(tip, tm.end())
    bonus = _read_number(near.group(1), None, ctx) if near else None
    return n * (1 + (bonus or 0.0)), None, seconds if seconds and _CHANNEL.search(tip) else 0.0


def _cast_count(m: re.Match, tip: str, ctx: dict) -> float:
    """Damage of every cast `_RECASTS` states, in first casts."""
    n = (_read_number(m.group(1), None, ctx) or 0.0) + 1 if m.group(1) else 3
    ramp = _RAMP.search(tip)
    return n + (int(ramp.group(1)) / 100 if ramp else 0.0) * n * (n - 1) / 2


def spell_lines(spell: dict, tip: str, ctx: dict) -> dict:
    """Per cast: {physical, magic, true, pct, heal_self, heal_ally, shield_self,
    shield_ally}, a set `unknown` of the kinds a None calc touched, `floors` naming
    any repeat left at one, and `channel`, the seconds a hit count holds the caster."""
    best, unknown, floors, channel = {}, set(), [], 0.0
    ally = bool(_ALLY.search(tip))
    both = bool(_SELF_AND_ALLY.search(tip))
    prev_tag, prev_end, prev_hit, carried, last = None, 0, False, 0.0, 0.0
    many = None if "Second Cast" in tip else _RECASTS.search(tip)     # Gwen R states each cast's own line
    tier_buff, tier_read = None, False
    for tm in _TAG.finditer(tip):
        tag, body = tm.groups()
        if _SUFFERS.search(tip, 0, tm.start()):
            continue
        tag = tag[0].lower() + tag[1:]
        if tag not in DAMAGE_TAGS and (_CAP_BEFORE.search(tip, 0, tm.start()) or _AT_STACKS.match(tip, tm.end())):
            continue
        li = tip.rfind("<li>", 0, tm.start())
        tier = _TIER.match(tip, li) if li >= 0 and "</li>" not in tip[li:tm.start()] else None
        if tier and ctx["dv"].get(tier.group(1)):
            if not tier_read:   # the stacked buff, not any first one; read once per spell
                tier_read = True
                tier_buff = next((b for b in _BUFF.findall(json.dumps(ctx["calcs"])) if b in STACKS), None)
            buff = tier_buff
            est = STACKS.get(buff) if buff else None
            if est is None:   # no count to hold the tier against
                unknown.add("damage" if tag in DAMAGE_TAGS else tag.replace("healing", "heal"))
                continue
            if "est" in ctx:
                ctx["est"].append(buff)
            if est[ctx.get("pick", "typical")] < ctx["dv"].get(tier.group(1)):
                continue
        # a hit that needs a wall is not the cast's (Condemn, Poppy E, Gnar R, K'Sante R, Zeri W): the
        # fight cannot promise terrain, and a max per kind would let the bigger wall line win
        if tag in DAMAGE_TAGS and _WALL_IF.search(tip, tip.rfind(".", 0, tm.start()) + 1, tm.start()):
            continue
        times, chain, extra = 1.0, 0.0, None
        if tag in DAMAGE_TAGS:
            gap = tip[prev_end:tm.start()]
            if tag == prev_tag and not _RATE_BODY.search(body):
                if "." not in gap and _THEN.search(gap) or _RETURN_HIT.search(gap) \
                        or (not many and prev_hit and _RECAST_HIT.search(gap) and not _RECAST_ELSE.search(gap)
                            and not _THROWN.match(tip, tm.end())):
                    chain = best.get(DAMAGE_TAGS[tag], 0.0)
                elif _CEILING.search(tip, 0, tm.start()):   # "@Min@ to @Max@": the high end adds to the same first hit
                    chain = carried
                elif prev_hit and _SUM.search(gap) and not _SUM_NOT.search(gap.rpartition(".")[2]) \
                        and not _PER_EXTRA.match(tip, tm.end()):
                    chain = last
                    # the extra lands on the hits the sentence names, not on every recast
                    extra = _NEXT_N.search(gap.rpartition(".")[2]) or ""
            carried = chain
            prev_tag, prev_end, prev_hit = tag, tm.end(), "attack damage" not in body.lower()
            if _CRIT_LINE.search(tip, 0, tm.start()):
                continue
            times, floor, held = _repeat(tip, tm, ctx)
            if times > 1 and _CEILING.search(tip, 0, tm.start()):
                continue
            if extra:
                n = extra.group(1)
                times = (_read_number(n.strip("@"), None, ctx) if n[0] == "@" else _read_number(None, n, ctx)) or times
            elif extra is None and many and tm.end() <= many.start():
                times *= _cast_count(many, tip, ctx)
            channel = max(channel, held)
            if floor and floor not in floors:
                floors.append(floor)
        summed = 0.0  # "@Base@ plus @Pct@ max Health" is one hit in two parts
        adds = bool(_ADDS.search(body))
        health = None if _PER_PERCENT.search(body) else _HEALTH.search(body)
        for rm in _LINE_REF.finditer(body):
            other, name, mult, percent = rm.groups()
            if _CLIENT_VAR.fullmatch(name):  # @f1@ is filled by the client's script, no bin holds it
                continue
            if (f"{other}:{name}" if other else name).lower() in ctx.get("owned", ()):  # a spell counts it (`_owned`)
                continue
            if _NOT_CHAMPION.search(name) and not _ON_CHAMPION.search(name):
                continue
            own = ctx
            if other:  # @spell.GnarW:MiniTotalDamage@, a sibling spell's own calculation
                sib = (ctx.get("spell") or (lambda _: None))(other)
                if not sib:
                    unknown.add("damage" if tag in DAMAGE_TAGS else tag.replace("healing", "heal"))
                    continue
                rank = ctx.get("rankOf", {}).get(id(sib)) or ctx.get("rank", 1)
                own = {**ctx, "dv": _dv(sib, rank), "calcs": sib.get("mSpellCalculations") or {}}
            calc = _calc_ref(own, name)   # tooltips say TotalHoT for TotalHot
            v = evaluate(calc, own) if calc is not None else own["dv"].get(name)
            if v is None:
                unknown.add("damage" if tag in DAMAGE_TAGS or calc is None and tag not in ("healing", "shield")
                            else tag.replace("healing", "heal"))
                continue
            # evaluated first, so an unread low end or cap still marks the line unknown
            if adds and (_RANGE_LOW.match(body, rm.end()) or _CAP_OPEN.search(body, 0, rm.start())):
                continue
            is_pct = percent or (calc or {}).get("mDisplayAsPercent") or _PCT_OF_HEALTH.match(body, rm.end())
            if tag not in DAMAGE_TAGS:
                if percent and _OWN_MAX_HEALTH.match(body, rm.end()):
                    hp = ctx["stats"].get((12, 0))
                    if hp is None:
                        unknown.add(tag.replace("healing", "heal"))
                        continue
                    v, mult = v * float(mult or 1) / 100 * hp, None
                # ponytail: a rate of the damage dealt or of own missing health is not an
                # amount (115 such refs); a line for those would read the fight's own state
                elif is_pct or calc is None and not _HEAL_NAME.search(name):
                    continue
                kind = ("heal" if tag == "healing" else "shield") + ("_ally" if ally else "_self")
            else:
                kind = DAMAGE_TAGS[tag]
                if is_pct:
                    if not health:  # a share of Grit, of attack damage, of a hit: no amount
                        continue
                    ratio = v * float(mult or 1) / 100 if percent else (v / 100 if v > 1 else v)
                    which = health.group(1).lower()
                    if which in ("missing", "current"):  # read when the hit lands
                        best.setdefault("ofHealth", []).append((kind, which, ratio * times))
                        continue
                    v = ratio * ctx.get("targetHp", REF_TARGET_HP) * times
                    best["pct"] = max(best.get("pct", 0.0), v)
                elif calc is None and _RATE_BODY.search(body):
                    continue  # a rate, not an amount on a champion
                else:
                    v *= float(mult or 1) * times
            if tag not in DAMAGE_TAGS:
                v *= float(mult or 1)
            summed = summed + v if adds else v
            best[kind] = max(best.get(kind, 0.0), chain + summed)
            if both and kind.endswith("_ally"):
                mine = kind[:-5] + "_self"
                best[mine] = max(best.get(mine, 0.0), chain + summed)
        if tag in DAMAGE_TAGS:
            last = chain + summed
    hold = _HOLDS.search(tip) if not _RECAST.search(tip) and {*DAMAGE_TAGS.values(), "pct", "ofHealth"} & set(best) else None
    if hold:
        read = _read_number(hold.group(1) or hold.group(3) or hold.group(4) or hold.group(5), hold.group(2), ctx)
        channel = max(channel, min(read or 0.0, ctx.get("wait") or ft.FIGHT, ft.FIGHT))
    if "ofHealth" in best:  # "up to" lines on one health word are one hit (Varus W)
        top = {}
        for kind, which, ratio in best["ofHealth"]:
            top[kind, which] = max(top.get((kind, which), 0.0), ratio)
        best["ofHealth"] = [(*k, r) for k, r in top.items()]
    return {"lines": best, "unknown": unknown, "floors": floors, "channel": channel}


def spell_cc(spell: dict, tip: str, ctx: dict) -> dict:
    """{hard, soft, airborne, suppress} seconds per cast from the tooltip's <status> words
    (airborne and suppress are the parts of hard tenacity cannot shorten); `unknown`, the
    classes the tooltip names with no duration anywhere; `wallOnly`, when every second
    of hard CC needs the target against terrain (Condemn)."""
    calcs = spell.get("mSpellCalculations") or {}
    out, seen, free = {"hard": 0.0, "soft": 0.0, "airborne": 0.0, "suppress": 0.0}, set(), 0.0
    for m in _STATUS.finditer(tip):
        word = m.group(1).lower()
        kind = "hard" if any(s in word for s in HARD_CC) else "soft" if any(s in word for s in SOFT_CC) else None
        if not kind:
            continue
        seen.add(kind)
        ahead = _SENTENCE_END.split(tip[m.end():m.end() + CC_LOOKAHEAD], maxsplit=1)[0]
        d = _DURATION.search(ahead)
        sec = _value(d.group(1), calcs, ctx) if d else None
        if sec is None and (lit := _LITERAL_SECONDS.search(ahead)):
            sec = float(lit.group(1))
        if sec is None:  # the bin's own value, for a tooltip that never prints it
            stem = next((s for s in (*HARD_CC, *SOFT_CC) if s in word), "")
            sec = next((v for k, v in ctx["dv"].items() if stem[:4] in k and "duration" in k and v), None)
        out[kind] = max(out[kind], float(sec or 0.0))
        for sub, stems in (("airborne", AIRBORNE_CC), ("suppress", SUPPRESS_CC)):
            if kind == "hard" and any(st in word for st in stems):
                out[sub] = max(out[sub], float(sec or 0.0))
        if kind == "hard" and sec and not _WALL_IF.search(tip, tip.rfind(".", 0, m.start()) + 1, m.start()):
            free = max(free, float(sec))
    if "hard" in seen and not out["hard"]:  # "Stunned instead of Slowed" shares the bin's number
        out["hard"] = free = float(next((ctx["dv"][k] for k in _CC_DURATION if ctx["dv"].get(k)), 0.0))
    return {**out, "unknown": {k for k in seen if k in ("hard", "soft") and not out[k]}, "wallOnly": out["hard"] > 0 and not free}


def _at(v, rank: int) -> float:
    """A per-rank list or a scalar, at `rank`."""
    if isinstance(v, list):
        v = v[rank] if len(v) > rank else (v[-1] if v else 0.0)
    return float(v or 0.0)


def cooldowns(spell: dict) -> list:
    """Per-rank cooldowns from the live `Cooldown.values`; `cooldownTime` is a stale mirror
    (Darius Q 9/8/7/6/5 against the live and wiki 9/7.75/6.5/5.25/4). Both start rank 1 at index 1."""
    live = (spell.get("Cooldown") or {}).get("values") if isinstance(spell.get("Cooldown"), dict) else None
    live = live or spell.get("cooldownTime") or []
    if live and all(v < MIN_COOLDOWN for v in live[1:6]):
        # the field holds a toggle or charge gap; the cooldown sits in a DataValue (Kalista E
        # FakedCooldown, Tahm Kench R DataCooldown, Talon E DisplayCD, Singed Q ToggleCooldown).
        # An empty list stays empty: Yuumi E's `Cooldown` 18..14 is wrong against the wiki's 10.
        for d in spell.get("DataValues") or []:
            vals = d.get("values") or []
            if d.get("name", "").lower() in _CD_NAMES and any(v >= MIN_COOLDOWN for v in vals[1:6]):
                return vals
    return live


_CD_NAMES = {"cooldown", "fakedcooldown", "datacooldown", "displaycd", "togglecooldown"}


def _cooldown(spell: dict, rank: int) -> float:
    return _at(cooldowns(spell), rank)


def _recharge(spell: dict, rank: int) -> float:
    """A RechargeTime DataValue (Kled's Pocket Pistol 18..10, the wiki's), else mAmmoRechargeTime (a flat 20 there)."""
    v = next((d.get("values") for d in spell.get("DataValues") or [] if d.get("name", "").lower() == "rechargetime"), None)
    return _at(v, rank) if v else _at(spell.get("mAmmoRechargeTime"), rank)


def wait(spell: dict, rank: int) -> float:
    """Seconds until the spell can be cast again: the recharge for a charge spell, whose
    cooldown is only the gap between charges, else the cooldown."""
    return _recharge(spell, rank) if _charged(spell, rank) else _cooldown(spell, rank)


def charges(spell: dict, rank: int) -> int:
    """Stored charges: mMaxAmmo, else a MaxCharges DataValue (Taric Q), else 0."""
    if spell.get("mMaxAmmo") is not None:
        return int(_at(spell["mMaxAmmo"], rank))
    return int(next((_at(d.get("values"), rank) for d in spell.get("DataValues") or []
                     if d.get("name", "").lower() == "maxcharges"), 0))


def _charged(spell: dict, rank: int) -> bool:
    """A charge spell waits on its recharge; its cooldown is only the gap between charges."""
    cd, rech = _cooldown(spell, rank), _recharge(spell, rank)
    return rech >= MIN_COOLDOWN and (cd < MIN_COOLDOWN or (charges(spell, rank) > 1 and rech > cd))


def _sole_missile(binj: dict | None, spell: dict) -> dict | None:
    """The one `*Missile` spell in the same ability folder as `spell`, else None."""
    key = next((k for k, v in (binj or {}).items() if isinstance(v, dict) and v.get("mSpell") is spell), None)
    if not key:
        return None
    folder = key.rsplit("/", 1)[0] + "/"
    kids = [v["mSpell"] for k, v in binj.items() if k.startswith(folder) and k != key
            and k.lower().endswith("missile") and "fx" not in k.rsplit("/", 1)[1].lower()   # Graves R's FxMissile is a visual
            and isinstance(v, dict) and isinstance(v.get("mSpell"), dict)]
    return kids[0] if len(kids) == 1 else None


_VISION = re.compile(r"vision|detection|reveal")
_DASH_RANGE = ("maxdashrange", "dashdistance", "maxdashbase", "maxmissilerange")


def real_range(spell: dict, rank: int, binj: dict | None = None) -> float | None:
    """A spell's range in game units, or None when no source holds a real one.
    Order: a charge spell's mCastRangeGrowthMax, castRange, then for a line skillshot its
    sole sibling `*Missile`'s castRange (Ahri E's charm 1000; a blink or AoE parent's
    missile is another quantity: Ezreal E, Galio Q), castRangeDisplayOverride, the first
    targeter's overrideBaseRange (Seraphine R), then a DataValues name that means the
    cast's own reach (not bonusrange, attackrangeincrease, aurarange). Measured over the
    944 wiki forms (2026-11-02 audit): 261 verified / 61 differs before, 288 / 45 after;
    Maokai Q (missile 650, wiki 600) and Ivern Q go to differs. castRange before the
    override: Darius R 475 over 460, Kog'Maw R 1300 over a `Range` of 130. Under MIN_RANGE
    (Cho'Gath E's 40) or MAX_RANGE and up (the 25000 placeholder) never counts.
    Leg 51 (measured 286 / 45 -> 288 / 43, 0 verified lost, 21 forms move): castRange
    yields to a smaller override when it is a 2000+ placeholder (Azir W/E) or the spell
    is a self-centred area (Garen E's radius 325), and is skipped when it equals a vision
    DataValue (Rengar R); a Line targeter's base equal to a larger override is the reach
    (Ashe W 1200); a dash or max-missile DataValue reads before the missile and override
    (Hecarim R 1000, Briar E 600, Viego W 300); `*Fx*` missiles are visuals. Measured and
    rejected: blanket Self skip (-4: Kai'Sa Q, Nocturne R, Yorick Q, Zac W), override
    within 15% (-2), Line base before missile (-5), larger missile over castRange (-2),
    numbered siblings (-1). Left as named differs: Nami R 2550 (wiki 2750), Fiora W 750
    (900), K'Sante W growth 600 (450), Soraka E, Warwick W, Zyra E, Gragas R, Aatrox Q."""
    def ok(v):
        return v if v and MIN_RANGE <= v < MAX_RANGE else None
    grown = spell.get("mCastRangeGrowthMax")
    if grown and ok(_at(grown, rank - 1)):  # this list starts at rank 1
        return _at(grown, rank - 1)
    dv = {d.get("name", "").lower(): d.get("values") for d in spell.get("DataValues") or [] if d.get("values")}
    targeters = [t for t in (spell.get("mClientData") or {}).get("mTargeterDefinitions") or [] if isinstance(t, dict)]
    lines = [t for t in targeters if t.get("__type") == "TargeterDefinitionLine"]
    v, ov = spell.get("castRange"), spell.get("castRangeDisplayOverride")
    cr = _at(v, rank) if v is not None else None
    ov = _at(ov, rank) if ov is not None else None
    if ok(cr) and ok(ov) and ov < cr and (cr >= 2000 or (spell.get("mTargetingTypeData") or {}).get("__type") == "SelfAoe"):
        cr = None
    if ok(cr) and any(_VISION.search(n) and _at(vals, rank) == cr for n, vals in dv.items()):
        cr = None
    if ok(cr):
        base = [(t.get("overrideBaseRange") or {}).get("mPerLevelValues") for t in lines]
        if ok(ov) and ov > cr and any(b and _at(b, rank - 1) == ov for b in base):
            return float(ov)
        return float(cr)
    for n in _DASH_RANGE:
        if n in dv and ok(_at(dv[n], rank)):
            return float(_at(dv[n], rank))
    if lines:
        m = _sole_missile(binj, spell)
        if m is not None and m.get("castRange") is not None and ok(_at(m["castRange"], rank)) \
                and _at(m["castRange"], rank) not in (2500.0, 3000.0, 5000.0, 10000.0):
            return float(_at(m["castRange"], rank))
    if ok(ov):
        return float(ov)
    base = targeters[0].get("overrideBaseRange") if targeters else None
    if isinstance(base, dict) and base.get("mPerLevelValues") and ok(_at(base["mPerLevelValues"], rank - 1)):
        return float(_at(base["mPerLevelValues"], rank - 1))   # this list starts at rank 1
    for d in spell.get("DataValues") or []:
        vals = d.get("values") or []
        name = d.get("name", "").lower()
        if _RANGE_NAME.match(name) and not _VISION.search(name) and len(vals) > rank and ok(float(vals[rank])):
            return float(vals[rank])
    return None


def _line_effects(name: str, lines: dict, when: dict, target_hp: float = REF_TARGET_HP) -> list[dict]:
    """Per-cast lines as timeline effects firing on `when`. A %-health line stays a
    share of the target's max health, so the timeline reads its own target."""
    out = [{"name": f"{name} {kind}", "kind": kind, "pctTarget": which, "ratio": r, **when}
           for kind, which, r in lines.get("ofHealth", ())]
    for k, v in lines.items():
        if k in DAMAGE_TAGS.values():
            amount = {"pctTarget": "max", "ratio": v / target_hp} if lines.get("pct") == v else {"base": v}
            out.append({"name": f"{name} {k}", "kind": k, **amount, **when})
        elif k not in ("pct", "ofHealth"):
            out.append({"name": f"{name} {k}", "out": k, "base": v, **when})
    return out


def _every_nth(tip: str) -> dict | None:
    """The timing an "every third Attack" tooltip states, else None."""
    nth = _EVERY_NTH.search(tip)
    if not nth:
        return None
    return {"trigger": "every-n", "n": _NTH[nth.group(1).lower()],
            "on": "both" if re.search(r"or (?:\w+ )?abilit", tip, re.I) else "hit"}


def kit(binj: dict, strings: dict, ranks: tuple, stats: dict, haste: float,
        level: int = LEVEL, ranged: bool = False, target_hp: float = REF_TARGET_HP,
        pick: str = "typical") -> dict:
    """Q W E R for the timeline: {"casts": [Cast], "effects": [...], "unknown": kinds}.
    A no-cooldown spell that procs on attacks (Vayne W) is an effect, not a cast."""
    rec = _record(binj)
    casts, effects, unknown, unread, cuts, estimated, stacks = [], [], set(), [], [], set(), set()
    spells = _spells(binj, rec)
    rank_of = {id(s): r for s, r in zip(spells, ranks)}
    for slot, spell, rank in zip("QWER", spells, ranks):
        if not spell or not rank:
            continue
        ctx = {"dv": _dv(spell, rank), "stats": stats, "level": level, "ranged": ranged, "rank": rank,
               "calcs": spell.get("mSpellCalculations") or {}, "targetHp": target_hp,
               "spell": lambda n: _named_spell(binj, n), "rankOf": rank_of, "est": [], "pick": pick}
        if not _tooltip_key(spell):   # no text to read its lines from (Aphelios Q, E), not a spell with none
            unknown.add("damage")
            unread.append(f"{slot} has no tooltip in the game file")
        tip = _tooltip(spell, strings)
        cd = _cooldown(spell, rank)
        rech = _recharge(spell, rank)
        timing = _WIKI_TIMING.get((rec.get("mCharacterName"), slot), {})
        # a charge spell waits on its recharge; Talon E on its same-terrain lockout
        wait_s = ctx["dv"].get(timing.get("wait")) or wait(spell, rank)
        cast_time = float(spell.get("mCastTime") or spell.get("spellCastTime") or 0.0)
        cooldown = wait_s * 100 / (100 + haste) if wait_s >= MIN_COOLDOWN else None
        ctx["wait"] = cooldown
        if MIN_COOLDOWN <= wait_s <= cast_time:  # back up the moment it ends, so nothing else would ever run (Bel'Veth R)
            if "<spellPassive>" not in tip:
                unknown.add("damage")
                unread.append(f"{slot} recasts as soon as it ends")
                continue
            got = spell_lines(spell, tip.partition("<spellActive>")[0], ctx)
            unknown |= got["unknown"]
            estimated |= _est_kinds(ctx, got["lines"])
            stacks.update(ctx["est"])
            effects += _line_effects(slot, got["lines"], {"trigger": "on-hit"}, target_hp)
            effects.append({"trigger": "note", "name": f"{slot} active left out, it recasts as soon as it ends"})
            continue
        got = spell_lines(spell, tip, ctx)
        effects += _active_over_passive(spell, tip, ctx, got["lines"], slot, target_hp)
        unknown |= got["unknown"]
        estimated |= _est_kinds(ctx, got["lines"])
        stacks.update(ctx["est"])
        effects += [{"trigger": "note", "name": f"{slot}: {f}"} for f in got["floors"]]
        nth = _every_nth(tip)
        if nth and cd < MIN_COOLDOWN and rech < MIN_COOLDOWN:
            effects += _line_effects(slot, got["lines"], nth, target_hp)
            continue
        cc = spell_cc(spell, tip, ctx)
        unknown |= cc["unknown"]
        walks = bool(_MOVES_FIRING.search(tip))   # a gun in place of attacks, spells stay free
        if walks:
            effects.append({"trigger": "note", "name": f"{slot}: shots apply on-hit at a reduced rate, left out"})
        bin_channel = _at(spell.get("mChannelDuration"), rank)
        held = got["channel"]
        if bin_channel > 0 and not timing.get("free") and not _RECAST.search(tip) \
                and {*DAMAGE_TAGS.values(), "pct", "ofHealth"} & set(got["lines"]) \
                and (_CHARGED.search(tip) if spell.get("mUseChargeChanneling") else True):
            held = max(held, bin_channel)
        lock = cast_time if walks else max(cast_time, held, timing.get("lock", 0.0))
        if cooldown and "cooldown" in timing:
            cooldown += timing["cooldown"]
        # past the lock, as the wiki's cdstart post-effect says; at or over the cooldown it would also
        # requeue the moment it ends and nothing else would ever run (Aurelion Sol Q)
        elif cooldown and (lock >= cooldown or not timing.get("onCast") and (held or lock >= 1.0)):
            cooldown += lock
        if cooldown and "refund" in timing:
            share = timing["refund"]
            share = ctx["dv"].get(share, 0.0) if isinstance(share, str) else share
            cooldown = lock + (cooldown - lock) * (1 - share)
        if cooldown and "back" in timing:
            cooldown -= ctx["dv"].get(timing["back"], 0.0)
        if cooldown and ctx["dv"].get(timing.get("cap")):
            cooldown = min(cooldown, ctx["dv"].get(timing["cap"]))
        for r in _WIKI_CUTS.get((rec.get("mCharacterName"), slot), ()):
            r = {k: ctx["dv"].get(v, 0.0) if k in ("s", "share", "while") and isinstance(v, str) else v
                 for k, v in r.items()}
            if "while" in r:
                r["while"] = (slot, r["while"])
            cuts += [(s, r) for s in r.pop("slots")]
        if _GATED.search(tip):   # the gate takes a fight's worth of setup, so one cast at most
            cooldown = None
            effects.append({"trigger": "note", "name": f"{slot}: needs a Style rating no fight reads, cast once"})
        one = ft.Cast(slot, got["lines"], cooldown, lock,
                      max(1, charges(spell, rank)) if _charged(spell, rank) else 1,
                      "Trait_AoE" in (spell.get("mSpellTags") or []), cc["hard"], cc["soft"],
                      cc["airborne"], cc["suppress"], got["channel"] if walks else 0.0)
        side = ctx["dv"].get("PerSideCooldown")
        if side:  # Bel'Veth Q: cooldownTime is the gap between dashes, each of four directions waits on its own
            # assumed: ability haste reaches the per-direction cooldown as it does the rest
            speed = ctx["dv"].get("PerSideCDAttackSpeedMultiplier", 0.0) * stats.get((4, 2), 0.0) * 100
            casts += [replace(one, cooldown=side * 100 / (100 + haste + speed)) for _ in range(4)]
            effects.append({"trigger": "note", "name": f"{slot}: W's direction refresh and the dash's on-hit left out"})
            continue
        casts.append(one)
    for c in casts:
        c.cuts = [r for s, r in cuts if s == c.name]
    return {"casts": casts, "effects": effects, "unknown": unknown, "unread": unread,
            "estimated": estimated, "stacks": stacks}


_ATTACKS_DEAL = re.compile(r"\bAttacks deal\b", re.I)


def _active_over_passive(spell: dict, tip: str, ctx: dict, lines: dict, slot: str, target_hp: float) -> list[dict]:
    """A cast deals its <spellActive> line where the <spellPassive> part's line of the same kind only won
    the max (Thresh E: attacks 206 against the whip's 155; Mundo E: a bonus AD stat read as a hit). A summed
    active keeps both (Fizz W's bleed). `lines` is fixed in place; the passive part rides attacks, counted once."""
    if "<spellPassive>" not in tip or "<spellActive>" not in tip:
        return []
    head, _, rest = tip.partition("<spellActive>")
    act = spell_lines(spell, rest, ctx)["lines"]
    pas = spell_lines(spell, head, ctx)["lines"]
    won = {k for k in DAMAGE_TAGS.values() if k in act and k in pas and lines.get(k) == pas[k] != act[k]}
    if not won:
        return []
    lines.update({k: act[k] for k in won})
    if not _ATTACKS_DEAL.search(head):
        return []
    # ponytail: once, at the passive's stated top, as cadence-less passive lines count; per attack would invent damage
    return [*_line_effects(f"{slot} passive", {k: pas[k] for k in won}, {"trigger": "on-hit", "on": "hit", "cooldown": math.inf},
                           target_hp),
            {"trigger": "note", "name": f"{slot}: passive on attacks counted once"}]


def _est_kinds(ctx: dict, lines: dict) -> set:
    """The kinds a spell's lines feed, when any of them read a stack estimate.
    ponytail: per spell, not per line, so a spell's heal beside an estimated hit reads estimate too."""
    if not ctx["est"]:
        return set()
    return {"damage" if k in (*DAMAGE_TAGS.values(), "pct", "ofHealth") else k.split("_")[0]
            for k, v in lines.items() if v}


def passive_spell(binj: dict, rec: dict) -> dict:
    """The champion passive's `mSpell` block."""
    return (binj.get(rec.get("mCharacterPassiveSpell")) or {}).get("mSpell") or {}


def _owned(binj: dict, rec: dict, passive: dict, strings: dict) -> set:
    """Lines the passive leaves to a spell that counts them. A passive name a spell's tooltip states as its own
    hit (Smolder Q, W, E: `@spell.SmolderP:QBonus@`), when that tag is the spell's only line of its kind or is
    summed onto the one before; one a same-kind max drops stays the passive's (Zyra Q, E's plants). And
    `<spell>:<name>` for a `@spell.X:Name@` the passive cites that X's own tooltip already deals (Caitlyn P, W)."""
    out = set()
    spells = [s for s in _spells(binj, rec) if s]
    for s in spells:
        t = _tooltip(s, strings)
        for tm in _TAG.finditer(t):
            refs = [m for m in _SPELL_REF.finditer(tm.group(2)) if _named_spell(binj, m.group(1)) is passive]
            kind = DAMAGE_TAGS.get(tm.group(1)[0].lower() + tm.group(1)[1:])
            if not refs or kind is None:
                continue
            same = [o for o in _TAG.finditer(t) if DAMAGE_TAGS.get(o.group(1)[0].lower() + o.group(1)[1:]) == kind]
            if len(same) == 1 or _SUM.search(t[:tm.start()]) or re.search(r"\+\s*$", t[:tm.start()]):
                out |= {m.group(2).lower() for m in refs}
    for m in _SPELL_REF.finditer(_tooltip(passive, strings)):
        cited = _named_spell(binj, m.group(1))
        t = _tooltip(cited, strings) if any(cited is s for s in spells) else ""
        if "<spellPassive>" in t and "<spellActive>" in t:   # Mel R's passive part restates Overwhelm, its cast does not deal it
            t = t.partition("<spellActive>")[2]
        if re.search(rf"@{re.escape(m.group(2))}@", t, re.I):
            out.add(f"{m.group(1)}:{m.group(2)}".lower())
    return out


def passive_effects(binj: dict, strings: dict, stats: dict, level: int = LEVEL,
                    ranged: bool = False, target_hp: float = REF_TARGET_HP, ranks: tuple = (),
                    pick: str = "typical") -> list[dict]:
    """The passive's lines on the timing its tooltip or cooldown states. Most state
    none: a readable line then counts once, as a floor, and says so in `excluded`.
    Counting it per attack would invent damage, and calling it unknown would blank
    half the roster's damage rows. An unreadable line is unknown."""
    rec = _record(binj)
    spell = passive_spell(binj, rec)
    name = f"{rec.get('mCharacterName')} passive"
    ctx = {"dv": _dv(spell, 1), "stats": stats, "level": level, "ranged": ranged, "rank": 1,
           "calcs": spell.get("mSpellCalculations") or {}, "targetHp": target_hp,
           "spell": lambda n: _named_spell(binj, n),
           "rankOf": {id(s): r for s, r in zip(_spells(binj, rec), ranks)}, "est": [], "pick": pick}
    ctx["owned"] = _owned(binj, rec, spell, strings)
    tip = _tooltip(spell, strings)
    got = spell_lines(spell, tip, ctx)
    kinds = _est_kinds(ctx, got["lines"])
    unread_est = [{"trigger": "note", "name": f"{name}: stacks read as an estimate", "estimated": kinds,
                   "stacks": set(ctx["est"])}] if kinds else []
    unread = [{"handler": None, "name": f"{name} {k}", "feeds": (k,)} for k in sorted(got["unknown"])]
    unread += [{"trigger": "note", "name": f"{name}: {f}"} for f in got["floors"]]
    unread += unread_est
    unread += [{"trigger": "note", "name": f"{name}: {m} not read, left out"} for m in _SCALE_AD.findall(tip)
               if (c := _calc_ref(ctx, m)) is not None and evaluate(c, ctx) is None]  # Hecarim, a named floor
    if not got["lines"]:
        return unread
    cd = _cooldown(spell, 1)
    when = (_every_nth(tip)
            or {"trigger": "on-hit", "on": "both", "cooldown": cd if cd >= MIN_COOLDOWN else math.inf})
    lock = _LOCKOUT.search(tip)
    if lock and ctx["dv"].get(lock.group(1)):
        when["cooldown"] = ctx["dv"].get(lock.group(1))
    note = [] if "n" in when or cd >= MIN_COOLDOWN else [{"trigger": "note", "name": f"{name}: cadence not read, counted once"}]
    return unread + _line_effects(name, got["lines"], when, target_hp) + note


_ITEM_STAT = {"Attack Damage": "ad", "Ability Power": "ap", "Health": "hp", "Armor": "armor",
              "Magic Resist": "mr", "Attack Speed": "as", "Critical Strike Chance": "crit",
              "Ability Haste": "haste", "Lethality": "lethality", "Mana": "mana"}
_ITEM_PCT = {"Attack Speed": "as", "Critical Strike Chance": "crit",
             "Armor Penetration": "armor_pct", "Magic Penetration": "mr_pct"}
_STATIC = {"AP": "ap", "AD": "ad", "Attack Speed": "as", "Health": "hp"}


def item_stats(ids: list, catalog: dict, passives: dict, melee: bool = True) -> dict:
    """Summed stats of these items, from each item's `st` lines plus its static
    passives. A fraction of AP multiplies the total, so it goes last."""
    out = dict.fromkeys(("ad", "ap", "hp", "armor", "mr", "as", "crit", "haste", "lethality",
                         "mana", "armor_pct", "mr_pct", "mr_flat"), 0.0)
    amp = 0.0
    for i in ids:
        for line in (catalog.get(str(i)) or {}).get("st") or []:
            m = _STAT.match(line)
            if not m:
                continue
            value, name = float(m.group(1)), m.group(3)
            if m.group(2):
                if name in _ITEM_PCT:
                    out[_ITEM_PCT[name]] += value / 100
            elif name in _ITEM_STAT:
                out[_ITEM_STAT[name]] += value
            elif name == "Magic Penetration":
                out["mr_flat"] += value
        for e in (passives.get("effects") or {}).get(str(i)) or []:
            key = _STATIC.get(e.get("stat")) if e.get("trigger") == "static" else None
            if not key or "of" in e:
                continue
            value = e.get("base") or 0.0
            value = value.get("melee" if melee else "ranged") if isinstance(value, dict) else value
            if e.get("unit") == "fraction" and key == "ap":
                amp += value
            else:
                out[key] += value
    out["ap"] *= 1 + amp
    return out


def convert_stats(rec: dict, items: dict, ids: list, passives: dict) -> None:
    """Item passives worth a share of another stat (Riftmaker, Sterak's, Manamune), which
    need the champion's own numbers, so they land on `items` after `item_stats`."""
    stats = ref_stats(rec, items)
    # hashed names: arBaseModifiable, arPerLevelModifiable; arType 0 (absent) is mana
    res = rec.get("primaryAbilityResource") or {}
    mana = 0.0 if res.get("arType") else (_base(res, "{726ee5cd}") + _base(res, "{6216bf7b}") * _growth(LEVEL))
    of = {"base AD": stats[(2, 1)], "bonus Health": stats[(12, 2)],
          "Mana": mana + items["mana"], "bonus Mana": items["mana"]}
    for i in ids:
        for e in (passives.get("effects") or {}).get(str(i)) or []:
            if e.get("trigger") == "static" and "of" in e:
                items[_STATIC[e["stat"]]] += e["ratio"] * of[e["of"]]


def rank_caps(spells: list) -> tuple:
    """Each slot's rank count from its tooltip's LevelUp list (Udyr 6/6/6/6, Jayce Q W E 6,
    Karma R 4), else the usual 5/5/5/3."""
    return tuple(level_count(s) or d for s, d in zip(spells, (5, 5, 5, 3)))


def level_count(spell: dict | None) -> int | None:
    """A spell's rank count from its tooltip's LevelUp list, None when it states none."""
    tip = (((spell or {}).get("mClientData") or {}).get("mTooltipData") or {})
    return ((tip.get("mLists") or {}).get("LevelUp") or {}).get("levelCount")


def ranks_for(arch: dict, caps: tuple = (5, 5, 5, 3)) -> tuple | None:
    """(Q, W, E, R) points at LEVEL from the skill order, None when it stops short."""
    order = ((arch.get("skills") or {}).get("order") or "")[:LEVEL].upper()
    # a 6-point order (Kai'Sa ARAM W) reads the last real rank, not a pad past it
    return tuple(min(order.count(k), c) for k, c in zip("QWER", caps)) if len(order) == LEVEL else None


def item_ids(arch: dict) -> list:
    boots = (arch.get("boots") or {}).get("id")
    return [*arch["core"], *([boots] if boots else [])]


def _names(ids: list, catalog: dict) -> str:
    return " + ".join((catalog.get(str(i)) or {}).get("n") or str(i) for i in ids)


def item_effects(ids: list, catalog: dict, passives: dict) -> list[dict]:
    out = []
    for i in ids:
        item = (catalog.get(str(i)) or {}).get("n") or str(i)
        for e in (passives.get("effects") or {}).get(str(i)) or []:
            out.append({**e, "name": f"{item}: {e.get('name') or e.get('trigger')}"})
    return out


def fight_for(binj: dict, strings: dict, arch: dict, perks: dict, passives: dict,
              target: ft.Target, catalog: dict, desc: dict, mode: str | None = None,
              pick: str = "typical") -> dict:
    """One archetype's 10 s fight on the timeline. Stacks from before the fight read STACKS[pick];
    when any did, `low` and `high` hold the same fight at the table's other ends."""
    rec = _record(binj)
    reach = _base(rec, "attackRangeModifiable")
    # ponytail: the bin's isMelee is null on every record, so range tells them apart;
    # a melee champion at 300+ would read ranged, a source flag would replace this.
    melee = reach < MELEE_BELOW
    ids = item_ids(arch)
    items = item_stats(ids, catalog, passives, melee)
    convert_stats(rec, items, ids, passives)
    stats = ref_stats(rec, items)
    ranks = ranks_for(arch, rank_caps(_spells(binj, rec)))
    k = kit(binj, strings, ranks or (0, 0, 0, 0), stats, items["haste"], ranged=not melee,
            target_hp=target.hp, pick=pick)
    effects = [*k["effects"],
               *passive_effects(binj, strings, stats, ranged=not melee, target_hp=target.hp, ranks=ranks or (),
                                pick=pick),
               *ft.keystone_effects(arch["keystone"], perks, desc.get(str(arch["keystone"])), mode),
               *item_effects(ids, catalog, passives)]
    actor = ft.Actor(
        stats={ft.AD: stats[(2, 0)], ft.AP: stats[(0, 0)], ft.ATTACK_SPEED: stats[(4, 2)],
               "Health": stats[(12, 0)], "base AD": stats[(2, 1)], "bonus AD": stats[(2, 2)],
               "bonus Health": stats[(12, 2)], "Lethality": items["lethality"],
               "Critical Strike Chance": stats[(8, 0)], "Armor": stats[(1, 0)],
               "bonus Armor": stats[(1, 2)], "Magic Resist": stats[(6, 0)]},
        casts=k["casts"], attack_speed=stats[(4, 0)], crit=min(1.0, stats[(8, 0)]),
        lethality=items["lethality"], melee=melee,
        pen={n: items[n] for n in ("armor_pct", "mr_pct", "mr_flat")},
        as_ratio=_base(rec, "attackSpeedRatioModifiable") or _base(rec, "attackSpeedModifiable"))
    r = ft.run(actor, target, effects)
    feeds = {"damage10s": "damage"}
    kinds = {*k["unknown"], *(feeds.get(u, u) for u in r["unknown"])}
    unread = [*k["unread"], *sorted(r["unknown"] - {*ft.FEEDS, "heal", "shield", "hard", "soft", "damage"})]
    gone = [i for i in ids if str(i) not in catalog]
    if gone:   # an item the catalog lacks adds no stats, so every number built on them is unread
        kinds |= {"damage", "heal", "shield", "hard", "soft", "items"}
        unread.append(f"item {', '.join(map(str, gone))} not in the catalog")
    if "damage" in kinds:
        kinds.add("burst")   # burst is a share of the same damage; a partial total cannot give one
    if ranks is None:
        kinds |= {"damage", "burst", "heal", "shield", "hard", "soft"}
        unread.append("no skill order")
    spells = zip(_spells(binj, rec), ranks or (0, 0, 0, 0))
    # best readable range of the learned spells, like engage; none readable (or no skill
    # order) is unknown, never 0
    ranges = [x for s, n in spells if s and n and (x := real_range(s, n, binj))] if ranks else []
    if not ranges:
        kinds.add("abilityRange")
        if ranks:
            unread.append("no readable ability range")
    rank_text = "/".join(map(str, ranks)) if ranks else "unread"
    perk = ft._perk(arch["keystone"], perks) or {}
    est = {*k["estimated"], *(x for e in effects for x in e.get("estimated", ()))}
    if "damage" in est:
        est.add("burst")
    est -= kinds
    hashes = sorted({*k["stacks"], *(x for e in effects for x in e.get("stacks", ()))})
    ends = {}
    if est and pick == "typical":
        ends = {p: fight_for(binj, strings, arch, perks, passives, target, catalog, desc, mode, pick=p)
                for p in ("low", "high")}
    return {**r, **ends, "unknown": kinds, "unread": unread, "estimated": est,
            "stackBasis": "; ".join(STACKS[h]["basis"] for h in hashes) if est else "", "attackSpeed": stats[(4, 0)], "haste": items["haste"],
            "attackRange": reach, "moveSpeed": _base(rec, "baseMoveSpeedModifiable"),
            "abilityRange": max(ranges, default=None),
            "towerDps": stats[(2, 0)] * stats[(4, 0)], "itemNames": _names(ids, catalog),
            "hp": stats[(12, 0)], "bonusHp": stats[(12, 2)], "armor": stats[(1, 0)], "mr": stats[(6, 0)],
            "basis": (f"{perk.get('mPerkName') or arch['keystone']}, {_names(ids, catalog)}, "
                      f"ranks {rank_text} from lolalytics, level {LEVEL}, {FIGHT:g} s, "
                      "every cast and attack hits")}


def traits(f: dict, patch: str | None) -> dict:
    """fight_for() to the store's trait rows."""
    total = sum(f["damage"].values())
    reason = ", ".join(f["unread"]) or "a stack count from before the fight, which no source holds, or an unread formula part"

    def row(value, unit, kind=None, note="", **extra):
        if kind and kind in f["unknown"]:
            return {"value": None, "unit": unit, "source": "unknown", "reason": reason, "patch": patch}
        if kind and kind in f.get("estimated", ()):
            return {"value": round(value, 3), "unit": unit, "source": "estimate",
                    "basis": f"{f['basis']}{note}; {f['stackBasis']}", "patch": patch, **extra}
        return {"value": round(value, 3), "unit": unit, "source": "computed",
                "basis": f["basis"] + note, "patch": patch, **extra}

    share = lambda x: x / total if total else 0.0  # noqa: E731
    excluded = {"excluded": f["excluded"]} if f["excluded"] else {}
    out = {
        "physicalShare": row(share(f["damage"]["physical"]), "share", "damage"),
        "magicShare": row(share(f["damage"]["magic"]), "share", "damage"),
        "trueShare": row(share(f["damage"]["true"]), "share", "damage"),
        "damage10s": row(total, "HP pre-mitigation", "damage", **excluded),
        "damage10sPost": row(f["post"], "HP after resists", "damage", **excluded),
        "pctHealthShare": row(share(f["pct"]), "share", "damage", ", %-health lines vs the dummy"),
        "burstShare": row(share(f["burst"]), "share", "burst", f", first {BURST:g} s"),
        "aoeShare": row(share(f["aoe"]), "share", "damage", ", abilities the game tags AoE"),
        "selfHeal": row(f["heal_self"], "HP per 10 s", "heal"),
        "allyHeal": row(f["heal_ally"], "HP per 10 s", "heal"),
        "selfShield": row(f["shield_self"], "HP per 10 s", "shield"),
        "allyShield": row(f["shield_ally"], "HP per 10 s", "shield"),
        "hardCC": row(f["hard"], "potential s per 10 s", "hard", ", overlap and landing not modelled"),
        "softCC": row(f["soft"], "potential s per 10 s", "soft", ", overlap and landing not modelled"),
        # Tenacity items score only tenacityCC; a cleanse scores everything but airborneCC (Sam, 2026-11-05).
        "airborneCC": row(f["airborne"], "potential s per 10 s", "hard", ", knockups, knockbacks and pulls"),
        "suppressCC": row(f["suppress"], "potential s per 10 s", "hard", ", suppression"),
        # ponytail: per cast `hard` is the longest hard word, so a spell that stuns 1.5 s and knocks up
        # 0.75 s reads 0.75 s here, not 1.5; track a per-cast reducible max if that undercount shows.
        "tenacityCC": row(max(0.0, f["hard"] - f["airborne"] - f["suppress"]) + f["soft"], "potential s per 10 s",
                          "hard", ", hard CC tenacity shortens plus soft CC"),
        "attackRange": row(f["attackRange"], "units"),
        "abilityRange": row(f["abilityRange"], "units", "abilityRange"),
        "moveSpeed": row(f["moveSpeed"], "units"),
        "towerDps": row(f["towerDps"], "damage per second", "items", ", basic attacks only"),
        # The build engine's heal math reads these as the target at the reference state.
        "hp": row(f["hp"], "HP", "items"),
        "bonusHp": row(f["bonusHp"], "HP", "items", f", from {f['itemNames']}"),
        "armor": row(f["armor"], "armor", "items"),
        "mr": row(f["mr"], "magic resist", "items"),
    }
    if "low" in f:   # the same fight at the table's low and high stacks
        lo, hi = traits(f["low"], patch), traits(f["high"], patch)
        for t, v in out.items():
            if v["source"] == "estimate":
                v["range"] = sorted([lo[t]["value"], hi[t]["value"]])
    return out


# --- sources and the bake ---------------------------------------------------

def _get(url: str, path: Path, max_age: float) -> Path:
    if not path.exists() or time.time() - path.stat().st_mtime > max_age:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    return path


def load_sources(ver: str, max_age: float = 6 * 3600) -> tuple[dict, dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    strings = json.loads(_get(STRINGS_URL, CACHE / "lol.stringtable.json", max_age).read_text())["entries"]
    dd = json.loads(_get(DDRAGON_URL.format(ver=ver), CACHE / f"champion-{ver}.json", 30 * 86400).read_text())["data"]
    return strings, dd


def load_bin(ddid: str, max_age: float = 6 * 3600) -> dict:
    c = ddid.lower()
    return json.loads(_get(BIN_URL.format(c=c), CACHE / f"{c}.bin.json", max_age).read_text())


def write(store: dict, out: Path) -> None:
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def load_perks(max_age: float = 6 * 3600) -> tuple[dict, dict]:
    """perks.cdtb.bin.json and {str(perk id): long text} from perks.json."""
    CACHE.mkdir(parents=True, exist_ok=True)
    perks = json.loads(_get(PERKS_BIN_URL, CACHE / "perks.cdtb.bin.json", max_age).read_text(encoding="utf-8"))
    rows = json.loads(_get(PERKS_JSON_URL, CACHE / "perks.json", max_age).read_text(encoding="utf-8"))
    return perks, {str(p["id"]): p.get("longDesc") or "" for p in rows}


def bake_archetype_traits(mode: str, staged: dict, sources: dict, only: list[str] | None = None) -> dict:
    """{"rows": {champ: {role: {id: {trait: row}}}}, "failed": {"champ/role/id": why}}.
    sources: strings, perks, desc, passives, catalog {id: item}, bins {name: bin}, target."""
    out, failed = {}, {}
    for champ, roles in (staged["modes"].get(mode) or {}).items():
        if only and champ not in only:
            continue
        for role, entry in roles.items():
            for arch in entry.get("archetypes") or []:
                try:
                    f = fight_for(sources["bins"][champ], sources["strings"], arch, sources["perks"],
                                  sources["passives"], sources["target"], sources["catalog"],
                                  sources["desc"], None if mode == "ranked" else mode)
                    patch = arch.get("patch") or staged.get("patch")
                    row = traits(f, patch)
                    ids = arch["core"]
                    read = all((sources["catalog"].get(str(i)) or {}).get("st") for i in ids)
                    core = {"stats": item_stats(ids, sources["catalog"], sources["passives"]), "read": read,
                            "support": any(("Heal and Shield Power" in " ".join((sources["catalog"].get(str(i)) or {}).get("st") or []))
                                           for i in ids),
                            "onHit": any(e.get("trigger") == "on-hit" and "on" not in e and "cooldown" not in e
                                         for e in item_effects(ids, sources["catalog"], sources["passives"]))}
                    v = view(sources["bins"][champ], sources["strings"], arch, row, f,
                             (sources.get("partypes") or {}).get(champ), entry, core,
                             (sources.get("wiki") or {}).get(champ))
                    row.update(rule_rows(v, patch))
                except Exception as exc:  # one archetype's odd bin never stops the bake
                    failed[f"{champ}/{role}/{arch['id']}"] = repr(exc)
                    continue
                out.setdefault(champ, {}).setdefault(role, {})[arch["id"]] = row
    return {"rows": out, "failed": failed}


def most_played(roles: dict) -> tuple | None:
    """(role, archetype id) a champion is most played on, None with no archetypes."""
    filled = {r: e for r, e in roles.items() if e.get("archetypes")}
    if not filled:
        return None
    role = max(filled, key=lambda r: filled[r].get("roleGames") or 0)
    return role, max(filled[role]["archetypes"], key=lambda a: a.get("games") or 0)["id"]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pair_mismatch() -> str | None:
    """A sentence when the live pair carry different generation ids (a publish was cut
    off between its two replaces), else None. Both files must exist to compare."""
    a, t = _read(ARCH_LIVE).get("generation"), _read(OUT).get("generation")
    if ARCH_LIVE.exists() and OUT.exists() and a != t:
        return f"live pair mismatched: archetypes generation {a}, traits generation {t}"
    return None


def publish_generation(staged: dict, rows: dict, failed: dict | None = None, cal: dict | None = None) -> bool:
    """Both live files from one generation, or neither is touched when a gate fails.
    `rows` is {mode: {champ: {role: {id: {trait: row}}}}}, `failed` the trait failures
    by "champ/role/id". False leaves the live pair alone.

    The guarantee is weaker than a transaction: each file is written whole to a .tmp
    and replaced atomically, but the two replaces are separate, so a kill between them
    leaves the new archetypes beside the old traits (or the reverse). Both carry
    `generation`; a mismatch is reported when the next publish starts, and rerunning
    the bake repairs it. A staged mode with no archetypes keeps the live rows for that
    mode (a one-mode stage must not blank the others)."""
    if note := pair_mismatch():
        print(f"bake_traits: {note}; this publish rewrites both", file=sys.stderr)
    failed = {**(failed or {}), **(staged.get("failed") or {})}
    jobs = [(m, c, r, a["id"]) for m, champs in staged["modes"].items() for c, roles in champs.items()
            for r, e in roles.items() for a in e.get("archetypes") or []]
    missing = [j for j in jobs if f"{j[1]}/{j[2]}/{j[3]}" not in failed
               and not (rows.get(j[0]) or {}).get(j[1], {}).get(j[2], {}).get(j[3])]
    total = len(jobs) + len(staged.get("failed") or {})
    if missing or not total or len(failed) / total > MAX_FAILED:
        return False
    store = _read(OUT) or {"champions": {}}
    live_modes = _read(ARCH_LIVE).get("modes") or {}
    staged = {**staged, "modes": dict(staged["modes"])}
    rows = dict(rows)
    for m in staged["modes"]:
        if not any(j[0] == m for j in jobs):
            staged["modes"][m] = live_modes.get(m) or staged["modes"][m]
            rows[m] = (store.get("archetypes") or {}).get(m) or rows.get(m) or {}
    for champ, roles in (staged["modes"].get("ranked") or {}).items():
        top = most_played(roles)
        row = (rows.get("ranked") or {}).get(champ, {}).get(top[0], {}).get(top[1]) if top else None
        if row:
            store["champions"][champ] = {**store["champions"].get(champ, {}), **row}
    strip_judged(store)
    store.update(archetypes=rows, generation=staged.get("generation"), patch=staged.get("patch"),
                 rubricVersion=RUBRIC_VERSION, calibration=cal or store.get("calibration"),
                 fetched=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    pairs = [(ARCH_LIVE, staged), (OUT, store)]
    for path, obj in pairs:
        path.with_suffix(".json.tmp").write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, _ in pairs:
        os.replace(path.with_suffix(".json.tmp"), path)
    return True


def load_all(wiki: bool = False) -> dict:
    """Every source the bake reads. The dummy needs the whole roster, even for one champion.
    `wiki` loads the wiki ability text the trait rules fall back to (bake_champions writes it)."""
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    strings, dd = load_sources(cat["ver"])
    perks, desc = load_perks()
    bins = {c["n"]: load_bin(c["i"]) for c in cat["champs"]}
    return {"strings": strings, "perks": perks, "desc": desc, "bins": bins,
            "partypes": {c["n"]: (dd.get(c["i"]) or {}).get("partype") for c in cat["champs"]},
            "passives": json.loads(ITEM_PASSIVES.read_text(encoding="utf-8")),
            "catalog": {str(x["id"]): x for x in cat["items"]},
            "wiki": load_wiki() if wiki else {},
            "target": ft.dummy([_record(b) for b in bins.values()])}


def _ended(line: str) -> str:
    """A wiki text line closed as a sentence, so the split never runs two lines together."""
    line = line.strip()
    return line if not line or line[-1] in ".!?" else line + "."


def load_wiki() -> dict:
    """{champion: [{slot, text, range}]} from the wiki ability bake; {} when it is missing."""
    if not WIKI.exists():
        return {}
    out = {}
    for name, ch in json.loads(WIKI.read_text(encoding="utf-8"))["champions"].items():
        out[name] = [{"slot": a["slot"], "text": " ".join(_ended(t) for t in a.get("text") or []),
                      "range": " ".join(str(v) for k, v in (a.get("fields") or {}).items() if k in ("RANGE", "TARGET RANGE"))}
                     for a in (ch.get("abilities") or {}).get("value") or []]
    return out


def coverage(rows: dict) -> dict:
    """Per trait, the share of archetype rows with a computed value."""
    got = {}
    for champs in rows.values():
        for roles in champs.values():
            for ids in roles.values():
                for row in ids.values():
                    for t, v in row.items():
                        a = got.setdefault(t, [0, 0])
                        a[0] += v["source"] == "computed"
                        a[1] += 1
    return {t: round(a / b, 3) for t, (a, b) in sorted(got.items())}


def bake_archetypes(only: list[str] | None = None) -> int:
    path = STAGED if STAGED.exists() else ARCH_WORK if only else None
    if not path or not path.exists():
        print("bake_traits: nothing staged, run bake_lolalytics.py --archetypes first", file=sys.stderr)
        return 1
    staged = json.loads(path.read_text(encoding="utf-8"))
    cat_patch = ".".join(json.loads(CATALOG.read_text(encoding="utf-8"))["ver"].split(".")[:2])
    if staged.get("patch") != cat_patch:   # a stale next.json would bake one patch's rows under another's items
        print(f"bake_traits: {path.name} is patch {staged.get('patch')}, the catalog is {cat_patch}; "
              "rerun bake_lolalytics.py --archetypes", file=sys.stderr)
        return 1
    sources = load_all(wiki=True)
    if not sources["wiki"]:   # rubricVersion 3 reads it; a bake without it would score other traits
        print(f"bake_traits: {WIKI.name} is missing or empty, run bake_champions.py first", file=sys.stderr)
        return 1
    rows, failed = {}, {}
    for mode in staged["modes"]:
        r = bake_archetype_traits(mode, staged, sources, only)
        rows[mode] = r["rows"]
        failed.update(r["failed"])
    for key, why in failed.items():
        print("failed:", key, why, file=sys.stderr)
    pop = population(staged, rows)
    if pop:
        cal = calibrate(pop)
    elif cal := _read(OUT).get("calibration"):   # no ranked rows this run: score against the live boundaries
        print("bake_traits: no ranked rows, keeping the live calibration")
    else:
        print("bake_traits: no ranked rows and no live calibration to score against", file=sys.stderr)
        return 1
    apply_calibration(rows, cal)
    for t, cuts in cal["boundaries"].items():
        print(f"  boundaries {t:12} {[round(c, 2) for c in cuts]}")
    print("  judged rows: 0")
    for t, s in coverage(rows).items():
        print(f"  {t:16} {s:.0%} computed")
    if only:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0
    if not publish_generation(staged, rows, failed, cal):
        print("bake_traits: not published, a job has no row or failures are over the limit", file=sys.stderr)
        return 1
    print(f"bake_traits: published {staged.get('generation')}")
    return 0


# --- item traits --------------------------------------------------------------

ITEMS_OUT = vault_root() / "data" / "forge-item-traits.json"
# Gold per point, from the basic item that sells the stat alone (catalog 16.21):
# Long Sword, Amplifying Tome, Ruby Crystal, Cloth Armor, Null-Magic Mantle,
# Dagger, Cloak of Agility, Glowing Mote, Boots, Sapphire Crystal, Rejuvenation
# Bead, Faerie Charm; lethality from Serrated Dirk less its AD. Stats with no
# such item (penetration %, vamp, tenacity) are left out of gold efficiency.
STAT_GOLD = {
    "Attack Damage": 35.0, "Ability Power": 20.0, "Health": 400 / 150, "Armor": 20.0,
    "Magic Resist": 20.0, "Attack Speed": 25.0, "Critical Strike Chance": 40.0,
    "Ability Haste": 50.0, "Move Speed": 12.0, "Mana": 1.0, "Base Health Regen": 3.0,
    "Base Mana Regen": 4.0, "Lethality": 30.0,
}
EXPENSIVE = 3200  # gold; at or above this an item is tagged `expensive`
# Counter tags come from build_styles.COUNTERS, each item placed by reading its passive
# (Sam, 2026-11-05). The keyword guesses that stood here tagged Yun Tal anti-crit,
# Bandlepipes anti-attack-speed and Warmog's giant-slayer, and missed Randuin's.
PURPOSE = (
    ("pen", lambda t, st, tags: re.search(r"\d+% (armor|magic) penetration", st) is not None),
    ("active", lambda t, st, tags: "Active" in tags),
)
_STAT = re.compile(r"^(\d+(?:\.\d+)?)(%?) (.+)$")


def item_traits(item: dict) -> dict:
    text = " ".join(f"{p.get('h', '')} {p.get('t', '')}" for p in item.get("ps") or []).lower()
    stats = " ".join(item.get("st") or []).lower()
    worth, priced = 0.0, []
    for line in item.get("st") or []:
        m = _STAT.match(line)
        if m and m.group(3) in STAT_GOLD:
            worth += float(m.group(1)) * STAT_GOLD[m.group(3)]
            priced.append(m.group(3))
    gold = item.get("g") or 0
    tags = [n for n, f in PURPOSE if f(text, stats, item.get("t") or [])] + bs.counter_tags(item["n"])
    if gold >= EXPENSIVE:
        tags.append("expensive")
    return {"name": item["n"], "gold": gold,
            "goldEfficiency": round(worth / gold, 3) if gold and priced else None,
            "priced": priced, "tags": tags}


def bake_items() -> dict:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    gone = bs.check_counters({x["n"] for x in cat["items"]})
    if gone:   # an item renamed or removed: say so rather than bake a counter list that lost it
        raise SystemExit(f"bake_traits: build_styles.COUNTERS names items the shop no longer sells: {gone}")
    store = {"patch": cat["ver"], "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "items": {x["id"]: item_traits(x) for x in cat["items"] if x.get("g")}}
    write(store, ITEMS_OUT)
    return store


# --- rule traits --------------------------------------------------------------
# Each reads the game's own tags, tooltips and numbers. A rule returns None when the
# source does not say, so the row is `unknown`; a proven absence is 0 or false.

RUBRIC_VERSION = 3
PEEL_RANGE = 600      # units; hard CC past this does not protect a carry from a diver
AS_REFERENCE_SHARE = 0.5  # basic attacks' damage share at which attack speed is the plan
CC_TAG = "Trait_ImmobilizingCCSpell"
DASH_TAG = "Trait_PlayerSelectedDashDirection"
ENGAGE_MOVE = {DASH_TAG, "PositiveEffect_MoveBlock"}
DIVE_MOVE = ENGAGE_MOVE | {"PositiveEffect_Teleport"}
ZONE_TAGS = {"Trait_Ranged_Zone", "Trait_Trap", "Trait_CreateTerrain"}
TERRAIN_TAG = "Trait_CreateTerrain"
DRAFT_RUBRIC = ("engage", "peel", "dive", "frontline", "zoneControl")
KEYWORDS = {
    "cleanse": r"\bcleans\w*",
    "globalPresence": r"\bglobal(ly)?\b(?! cooldown)|anywhere on the map|across the map",   # Sona's shared lockout
    "vision": r"\breveal(s|ed|ing)?\b|\btrue sight\b|\b(grant|gain|give)(s|ed|ing)? (true )?(sight|vision)\b"
              r"|\b(sight|vision) of\b|\bplac\w* (a |an )?(\w+ )?wards?\b",
    "revive": r"\brevive[sd]?\b|\bresurrect\w*|\breborn\b|\brebirth\b|returns? to life|\breanimat\w*",
    "execute": r"\bexecut\w*",
    "infiniteStacking": r"\bno (maximum|limit|cap)\b|\bunlimited\b|\binfinite\w*|without (a )?limit",
}
# A sentence that matches the trait's word but is not the mechanic (audit 2026-11-03,
# forge/audit/batch-*.json): vision taken away or a self-reveal, an execute on minions only.
KEYWORD_SKIP = {
    "vision": r"nearsight|(vision|sight) radius|block\w* (their |its )?(vision|sight)"
              r"|reveal\w* (his|her|its|their) (true )?\w*\s?form",
    "execute": r"\b(minions?|monsters?)\b(?![^.]*\bchampions?\b)|\bexecut\w* (enemy )?turrets?|\bminions? executed"
               r"|will be executed once"    # Ziggs W turrets, Senna's quest minions, Zac's own bloblets
               r"|\bexecut\w* (a|an)\b|perfect execution",   # the verb "perform" and the name of Akali R
    # wiki wording (2026-11-03): resurrection named as a condition (Aurora R, Yone E)
    "revive": r"\b(dies|death),? (or )?(enters?|entering) resurrection",
}
# Trait_Parry also sits on blocks, dodges and damage reduction (Leona W, Master Yi W,
# Nilah W, Pantheon E, Braum E), so spellShield needs the words as well as the tag.
_SPELL_SHIELD = re.compile(r"spell ?shield|blocks? the next", re.I)
TAG_FLAGS = {"terrain": {TERRAIN_TAG}}
# Ability wording read beside the tags (rubricVersion 3, audit 2026-11-03): the tags miss
# targeted dashes, most CC immunity and passive stealth, and Trait_CCImmune also sits on a
# spell shield and on displacement-only immunity (Sivir E, Ambessa R, Vex R, Viego R), so
# unstoppable reads the words alone. (pattern, sentence skip, slots, tags that also count)
SAYS = {
    "dashes": (r"\b(?:dash(?:es)?|leaps?|pounces?|blinks?|lunges?|vaults?)\s+(?:to|toward|towards|in|a fixed|up to"
               r"|forward|backward|\d+|over|across|through|the|a short|with|from)\b"
               r"|\b(?:leaping|dashing) (?:to|towards?|forward|in)\b",   # not "while dashing": Yasuo Q's condition
               r"\bsoldiers?\b|\bshadow\b|\bwolf\b|\bwill not\b|'s dash|\b(enem(y|ies)|units?|targets?) (that|who)\b",
               "QWER", {DASH_TAG}),
    # Bard R hits units "despite being immune"; Morgana E grants it to an ally; Heimerdinger R's turret
    "unstoppable": (r"immun\w* to (?:all )?crowd control|crowd control immunity|cc-immunity"
                    r"|crowd control cannot be applied|immune to them",
                    r"despite being immune|\ball(?:y|ies|ied)\b|grants? crowd control immunity|\bit is immune", "QWER", set()),
    # on others: Poppy R / Tahm Kench R ("rendered"), Zilean R, Naafiri R packmates;
    # passives are death or transformation states (Karthus, Kog'Maw, Zac, Zaahen, Kayn)
    "untargetable": (r"\b(?:becom\w*|rendered)\s+(?:\w+,?\s+){0,2}untargetable|\btargetable again\b",
                     r"\bthe target\b|rendered untargetable|\bthey\b|packmates|resurrection|\ball(?:y|ies|ied)\b",
                     "QWER", {"Trait_Untargetable"}),
    "stealth": (r"\b(?:gains?|enters?|grants?|granting|becom\w*)\s+(?:\w+\s+)?(?:invisib\w*|camouflage[d]?)\b",
                None, "QWERI", {"Trait_Invisibility", "Trait_Camouflage"}),
    # the wiki's own Pets index; bare "summons" also hits walls, storms and bolts, traps are zone
    "pets": (r"See Pets for|\bsprouts? into", r"\btraps?\b", "QWERI", {"Trait_Pet"}),
}
RESOURCE = {"mana": "mana", "energy": "energy", "none": "none", "fury": "fury", "rage": "fury",
            "blood well": "health", "crimson rush": "health"}
# Crossing wording only: "terrain" alone also matched a stun into a wall (Poppy E), a dash
# that stops on terrain (Galio E) and making terrain (Jarvan IV R).
_WALL = re.compile(r"\b(through|over|across|past|ignor\w*|cross\w*)\b[^.]{0,30}?\b(walls?|terrain)\b"
                   r"|\b(walls?|terrain)\b[^.]{0,20}?\b(cross|pass)\w*", re.I)
_WALL_NOT = re.compile(r"\bnot (go |pass |dash )?(through|over|across)\b|\bcannot (pass|cross|go)\b"
                       r"|\bstops? on\b", re.I)
_GHOST = re.compile(r"ignor\w* terrain collision", re.I)
_MOVE_HINT = re.compile(r"\b(dashes|leaps|blinks|lunges)\b|during (the|his|her|its) (dash|leap|charge)"
                        r"|\blifts? up into the air\b|\bcharges? forward", re.I)
_VAR = re.compile(r"@[^@]*@")   # tooltip variable names (@ExecuteThreshold@) are not wording
_PLAIN = re.compile(r"<[^>]+>")
_RADIUS = re.compile(r"radius|width", re.I)


def view(binj: dict, strings: dict, arch: dict, row: dict | None = None, fight: dict | None = None,
         partype: str | None = None, entry: dict | None = None, core: dict | None = None,
         wiki: list | None = None) -> dict:
    """One archetype's spells as the rules read them. `row` is its traits() rows, `fight`
    its fight_for(), `core` {"stats", "onHit", "support", "read"} of its core items,
    `entry` its lolalytics role entry, `wiki` its load_wiki() abilities (keyword fallback)."""
    rec = _record(binj)
    ranks = ranks_for(arch, rank_caps(_spells(binj, rec)))
    stats = ref_stats(rec, {})
    spells = []
    for slot, spell, rank in zip("QWER", _spells(binj, rec), ranks or (0, 0, 0, 0)):
        ctx = {"dv": _dv(spell, rank), "stats": stats, "level": LEVEL,
               "calcs": spell.get("mSpellCalculations") or {}}
        tip = _tooltip(spell, strings)
        spells.append({"slot": slot, "spell": spell, "rank": rank, "tip": tip, "ctx": ctx,
                       "tags": set(spell.get("mSpellTags") or []), "range": real_range(spell, rank, binj),
                       "cc": spell_cc(spell, tip, ctx)})
    passive = passive_spell(binj, rec)
    return {"spells": spells, "ranked": ranks is not None, "row": row or {}, "fight": fight or {},
            "resolved": len(spells) == 4 and all("mSpellTags" in s["spell"] for s in spells),
            "tips": [s["tip"] for s in spells] + [_tooltip(passive, strings)], "rec": rec,
            "calcs": [s["ctx"]["calcs"] for s in spells] + [passive.get("mSpellCalculations") or {}],
            "partype": partype, "entry": entry or {}, "core": core or {}, "wiki": wiki or []}


def _learned(v: dict) -> list[dict]:
    return [s for s in v["spells"] if s["rank"]]


def _none(mechanic: str) -> dict:
    return {"raw": 0.0, "ability": None, "mechanic": mechanic, "number": 0.0}


def measure_engage(v: dict) -> dict | None:
    """Best reach times stun: a move into a CC spell, or the CC spell's own range. CC
    spells with no readable number are named in `partial`, the best readable one
    stands as a floor; only when none reads is the trait unknown."""
    if not (v["resolved"] and v["ranked"]):
        return None
    spells = _learned(v)
    cc = [s for s in spells if CC_TAG in s["tags"]]
    if not cc:
        return _none("no immobilizing spell")
    read = [s for s in cc if s["range"] and s["cc"]["hard"] > 0]
    if not read:
        return None
    # ponytail: a wall stun takes no chained move; a dash cannot promise the wall behind them
    movers = [s for s in spells if s["tags"] & ENGAGE_MOVE and s["range"]]
    best = None
    for c in read:
        for m in [None] if c["cc"]["wallOnly"] else [None, *movers]:
            reach = c["range"] + (m["range"] if m and m is not c else 0.0)
            raw = reach * c["cc"]["hard"]
            if not best or raw > best["raw"]:
                chain = f"{m['slot']} into {c['slot']}" if m and m is not c else c["slot"]
                best = {"raw": raw, "ability": chain,
                        "mechanic": "reach times hard CC" + (", needs a wall" if c["cc"]["wallOnly"] else ""),
                        "number": f"{reach:g} units, {c['cc']['hard']:g} s"}
    return {**best, **({"partial": [s["slot"] for s in cc if s not in read]} if len(read) < len(cc) else {})}


def measure_peel(v: dict) -> dict | None:
    """Two raw parts: short-range hard CC seconds, ally shield and heal per 10 s."""
    if not (v["resolved"] and v["ranked"]):
        return None
    ally = [(v["row"].get(t) or {}) for t in ("allyHeal", "allyShield")]
    if any(a.get("value") is None for a in ally):
        return None
    cc_spells = [s for s in _learned(v) if CC_TAG in s["tags"]]
    # like engage: a CC spell whose range or hard seconds do not read is named in `partial`,
    # the readable ones stand as a floor; unknown only when none reads
    unread = [s for s in cc_spells if not s["range"] or (s["range"] <= PEEL_RANGE and s["cc"]["hard"] <= 0)]
    if cc_spells and len(unread) == len(cc_spells):
        return None
    near = [s for s in cc_spells if s not in unread and s["range"] <= PEEL_RANGE]
    cc = sum(s["cc"]["hard"] for s in near)
    amount = sum(a["value"] for a in ally)
    return {"raw": {"cc": cc, "ally": amount}, "ability": "+".join(s["slot"] for s in near) or None,
            "mechanic": "hard CC within 600 units, ally shield and heal", "number": f"{cc:g} s, {amount:g} HP",
            **({"partial": [s["slot"] for s in unread]} if unread else {})}


def _casts(spell: dict, rank: int, haste: float) -> int:
    """Casts in FIGHT: charges plus hasted recharges for a charge spell (as `wait` in kit), else on cooldown, else one."""
    if _charged(spell, rank):
        return max(1, charges(spell, rank)) + math.floor(FIGHT / (_recharge(spell, rank) * 100 / (100 + haste)))
    cd = _cooldown(spell, rank)
    if cd >= MIN_COOLDOWN:
        return 1 + math.floor(FIGHT / (cd * 100 / (100 + haste)))
    return 1


def measure_dive(v: dict) -> dict | None:
    """Total move range over the fight, plus a step each for untargetable and CC immunity."""
    if not (v["resolved"] and v["ranked"]):
        return None
    moves = [s for s in _learned(v) if s["tags"] & DIVE_MOVE]
    if any(s["range"] is None for s in moves):
        return None
    tags = set().union(*(s["tags"] for s in v["spells"]))
    steps = sum(t in tags for t in ("Trait_Untargetable", "Trait_CCImmune"))
    # ponytail: ammo counted, a free recast on the same cooldown (Ahri R aside) is one cast
    # the fight's own count carries every timing rule kit and the timeline apply (Talon E WallCD, Olaf Q cap, cuts)
    # a slot the fight never cast moves nothing; _casts only when no fight was read (a bare view)
    done = v["fight"].get("casts")
    raw = sum(s["range"] * (done.get(s["slot"], 0) if done is not None
                            else _casts(s["spell"], s["rank"], v["fight"].get("haste", 0.0))) for s in moves)
    return {"raw": raw, "steps": steps, "ability": "+".join(s["slot"] for s in moves) or None,
            "mechanic": "move range over 10 s", "number": f"{raw:g} units, {steps} steps"}


def measure_frontline(v: dict) -> dict | None:
    """Effective health against half physical, half magic, plus self shield and heal."""
    r = v["row"]
    parts = [(r.get(t) or {}).get("value") for t in ("hp", "armor", "mr", "selfHeal", "selfShield")]
    if any(p is None for p in parts):
        return None
    hp, armor, mr, heal, shield = parts
    ehp = hp / (0.5 * 100 / (100 + armor) + 0.5 * 100 / (100 + mr))
    return {"raw": ehp + heal + shield, "ability": None, "mechanic": "effective health, self shield and heal",
            "number": f"{ehp:.0f} effective HP, {heal + shield:.0f} sustained"}


def _dv_first(ctx: dict, *words) -> float | None:
    for w in words:
        for k, val in ctx["dv"].items():
            if w in k and val:
                return val
    return None


def _radius(s: dict) -> float | None:
    r = _at(s["spell"].get("castRadius"), s["rank"])
    return r or next((val for k, val in s["ctx"]["dv"].items() if _RADIUS.search(k) and val), None)


def measure_zone(v: dict) -> dict | None:
    """Radius squared times duration over the zone spells; terrain is its own step."""
    if not (v["resolved"] and v["ranked"]):
        return None
    raw, used = 0.0, []
    for s in _learned(v):
        tagged = bool(s["tags"] & ZONE_TAGS)
        life = _dv_first(s["ctx"], "duration", "lifetime")
        if not tagged and not ("Trait_Target_Area" in s["tags"] and life):
            continue
        radius = _radius(s)
        if radius is None or life is None:
            return None
        raw += radius ** 2 * life
        used.append(s["slot"])
    steps = int(any(TERRAIN_TAG in s["tags"] for s in v["spells"]))
    return {"raw": raw, "steps": steps, "ability": "+".join(used) or None,
            "mechanic": "radius squared times duration", "number": f"{raw:g}, {steps} terrain steps"}


MEASURES = {"engage": measure_engage, "peel": measure_peel, "dive": measure_dive,
            "frontline": measure_frontline, "zoneControl": measure_zone}


def _flat(trait: str, raw, cal: dict | None = None) -> float:
    """One number for a measurement. Peel averages its parts, each over the roster's top."""
    if trait != "peel":
        return raw
    top = (cal or {}).get("peelTop") or {"cc": 1.0, "ally": 1.0}
    return (raw["cc"] / (top["cc"] or 1.0) + raw["ally"] / (top["ally"] or 1.0)) / 2


def _cuts(values: list[float], n: int) -> list[float]:
    """n-1 quantile cuts of `values`."""
    values = sorted(values)
    return [values[min(len(values) - 1, i * len(values) // n)] for i in range(1, n)] if values else []


def calibrate(rows: list[dict]) -> dict:
    """Boundaries from one {trait: measurement} per champion-role, its most-played
    archetype. Only positive numbers rank: a proven absence stays 0."""
    cal = {"rubricVersion": RUBRIC_VERSION, "boundaries": {}}
    peels = [r["peel"]["raw"] for r in rows if (r.get("peel") or {}).get("raw")]
    cal["peelTop"] = {k: max((p[k] for p in peels), default=0.0) for k in ("cc", "ally")}
    for t in DRAFT_RUBRIC:
        got = [_flat(t, r[t]["raw"], cal) for r in rows if r.get(t)]
        cal["boundaries"][t] = _cuts([x for x in got if x > 0], 5)
    cal["boundaries"]["earlyLate"] = _cuts([r["earlyLate"]["raw"] for r in rows if r.get("earlyLate")], 5)
    return cal


def score_rubric(raw: float, boundaries: list[float], steps: int = 0) -> int:
    """0 to 5. A raw on a boundary takes the lower score; steps add after the percentile."""
    base = 0 if raw <= 0 else 1 + sum(raw > b for b in boundaries)
    return min(5, base + steps)


def _quote(tip: str, m: re.Match, pad: int = 60) -> str:
    return tip[max(0, m.start() - pad):m.end() + pad].strip()


def _hit(rx: re.Pattern, skip: re.Pattern | None, text: str) -> str | None:
    """The first sentence of `text` that matches `rx` and not `skip`, quoted."""
    for sent in re.split(r"(?<=[.!?])\s+", _VAR.sub("", _PLAIN.sub("", text))):
        m = rx.search(sent)
        if m and not (skip and skip.search(sent)):
            return _quote(sent, m)
    return None


def _wiki_hit(rx: re.Pattern, skip: re.Pattern | None, v: dict, slots=None) -> str | None:
    """Fallback when the game text has no match: the wiki ability text (approved 2026-11-03),
    quoted with "wiki <slot>:" so the basis says where it came from."""
    for a in v.get("wiki") or []:
        if slots is None or a["slot"] in slots:
            q = _hit(rx, skip, a["text"])
            if q:
                return f"wiki {a['slot']}: {q}"
    return None


def keyword_row(trait: str, v: dict) -> tuple:
    """(True, quoted line) or None; keyword absence proves nothing, so never false.
    The game's tooltips first, then the wiki ability text."""
    rx = re.compile(KEYWORDS[trait], re.I)
    skip = re.compile(KEYWORD_SKIP[trait], re.I) if trait in KEYWORD_SKIP else None
    for tip in v["tips"]:
        q = _hit(rx, skip, tip)
        if q:
            return True, q
    q = _wiki_hit(rx, skip, v, set("QWERI"))   # not the basic attack (A) or extra rows
    if q:
        return True, q
    if trait == "globalPresence":   # the wiki's range field is just "Global" (Ashe E/R); "600 • Global" is a second part
        g = next((a for a in v.get("wiki") or [] if a["slot"] in "QWERI" and a["range"].strip().lower() == "global"), None)
        if g:
            return True, f"wiki {g['slot']}: range {g['range']}"
    return None


def rule_flag(tags: set):
    def rule(v: dict):
        if not v["resolved"]:
            return None
        hit = [s["slot"] for s in v["spells"] if s["tags"] & tags]
        return bool(hit), f"{'+'.join(hit) or 'no spell'} tagged {'/'.join(sorted(tags))}"
    return rule


_SAYS_RX = {t: (re.compile(rx, re.I), sk and re.compile(sk, re.I)) for t, (rx, sk, _, _) in SAYS.items()}


def says(trait: str, v: dict) -> dict:
    """{slot: basis} for each slot in SAYS[trait] that carries one of its tags, or whose
    game tooltip, then wiki text, has the wording. Kept on `v`: dashes and wallCrossing share it."""
    memo = v.setdefault("_says", {})
    if trait not in memo:
        memo[trait] = _says(trait, v)
    return memo[trait]


def _says(trait: str, v: dict) -> dict:
    (rx, skip), (_, _, slots, tags) = _SAYS_RX[trait], SAYS[trait]
    out = {s["slot"]: "tagged" for s in v["spells"] if s["slot"] in slots and s["tags"] & tags}
    tips = [(s["slot"], s["tip"]) for s in v["spells"]] + [("I", (v.get("tips") or [""])[-1])]
    for slot, tip in tips:
        q = slot in slots and slot not in out and _hit(rx, skip, tip)
        if q:
            out[slot] = q
    for slot in slots:
        q = slot not in out and _wiki_hit(rx, skip, v, {slot})
        if q:
            out[slot] = q
    return out


def _basis(hit: dict) -> str:
    return "; ".join(q if q.startswith("wiki") else f"{k} {q}" if q == "tagged" else f"{k}: {q}"
                     for k, q in hit.items()) or "no spell"


def rule_says(trait: str):
    def rule(v: dict):
        if not v["resolved"]:
            return None
        hit = says(trait, v)
        return bool(hit), _basis(hit)
    return rule


def rule_dashes(v: dict):
    if not v["resolved"]:
        return None
    hit = says("dashes", v)
    return len(hit), _basis(hit)


def rule_wall(v: dict):
    if not v["resolved"]:
        return None
    moved = set(says("dashes", v))
    moves = [s for s in v["spells"] if s["tags"] & DIVE_MOVE or s["slot"] in moved]
    q = _wiki_hit(_GHOST, None, v, set("QWER"))   # moving with terrain collision off (Skarner E, Smolder E)
    if q:
        return True, q
    if not moves:   # a kit that still talks about moving has a move the rules cannot see (Elise E, Nocturne R)
        if any(_hit(_MOVE_HINT, None, s["tip"]) for s in v["spells"]) or _wiki_hit(_MOVE_HINT, None, v, set("QWER")):
            return None
        return False, "no move spell"
    for s in moves:
        q = _hit(_WALL, _WALL_NOT, s["tip"])
        if q:
            return True, f"{s['slot']}: {q}"
    q = _wiki_hit(_WALL, _WALL_NOT, v, {s["slot"] for s in moves})
    return (True, q) if q else None


def rule_spell_shield(v: dict):
    if not v["resolved"]:
        return None
    hit = [s["slot"] for s in v["spells"] if "Trait_Parry" in s["tags"]
           and _SPELL_SHIELD.search(_PLAIN.sub("", s["tip"]))]
    if hit:
        return True, f"{'+'.join(hit)} tagged Trait_Parry and says spell shield"
    q = _wiki_hit(re.compile(r"\bspell ?shield", re.I), None, v, set("QWER"))   # Nocturne W, Sivir E
    return (True, q) if q else (False, "no spell tagged Trait_Parry and says spell shield")


def rule_aoe_cc(v: dict):
    f = v["fight"]
    if not f or "hard" in f["unknown"]:
        return None
    return (round(f["aoeHard"] / f["hard"], 3) if f["hard"] else 0.0), "hard CC seconds from spells the game tags AoE"


def _auto_share(v: dict) -> float | None:
    f = v["fight"]
    if not f or "damage" in f["unknown"]:
        return None
    total = sum(f["damage"].values())
    return f["autos"] / total if total else 0.0


def rule_auto(v: dict):
    share = _auto_share(v)
    return None if share is None else (round(share * 5), f"basic attacks {share:.0%} of damage over 10 s")


def rule_attack_speed(v: dict):
    share = _auto_share(v)
    if share is None:
        return None
    refs = '"mStat": 4' in json.dumps(v["calcs"])
    return bool(refs or share >= AS_REFERENCE_SHARE), f"attack share {share:.0%}, ability ratio on attack speed: {refs}"


def rule_scaling(v: dict):
    """The core's stats name the plan; a core item with no stat lines says nothing."""
    core = v["core"]
    if not core.get("read"):
        return None
    st = core["stats"]
    ad, ap, tanky = st["ad"], st["ap"], st["hp"] + st["armor"] * 10 + st["mr"] * 10
    if core.get("support"):
        kind = "utility"
    elif ap and ap >= ad:
        kind = "ap"
    elif st["crit"]:
        kind = "crit"
    elif st["lethality"]:
        kind = "lethality"
    elif st["as"] or core.get("onHit"):
        kind = "on-hit"
    elif ad and tanky:
        kind = "bruiser"
    elif tanky:
        kind = "tank"
    else:
        kind = "utility" if not ad else "bruiser"
    return kind, f"core stats: {st['ad']:g} AD, {st['ap']:g} AP, {st['crit']:.0%} crit, {st['lethality']:g} lethality, {st['as']:.0%} AS, {st['hp']:g} HP"


def rule_resource(v: dict):
    if v["partype"] is None:
        return None
    name = v["partype"].strip().lower()
    return RESOURCE.get(name, "none" if not name else "other"), f"Data Dragon partype {v['partype'] or 'blank'}"


def _keyword(trait: str):
    return lambda v: keyword_row(trait, v)


def _early_late(v: dict):
    e = v["entry"].get("earlyLate") or {}
    if e.get("early") is None or e.get("late") is None:
        return None
    return e["late"] - e["early"], f"win rate {e['early']}% early, {e['late']}% late, lolalytics"


RULES = {
    **{t: fn for t, fn in MEASURES.items()},
    **{t: _keyword(t) for t in KEYWORDS},
    **{t: rule_flag(tags) for t, tags in TAG_FLAGS.items()},
    **{t: rule_says(t) for t in SAYS if t != "dashes"},
    "dashes": rule_dashes, "wallCrossing": rule_wall, "spellShield": rule_spell_shield, "aoeCCShare": rule_aoe_cc,
    "autoReliance": rule_auto, "attackSpeedScaling": rule_attack_speed, "scaling": rule_scaling,
    "earlyLate": _early_late, "resource": rule_resource,
}
TRAITS = tuple(RULES)
_UNITS = {"aoeCCShare": "share", "autoReliance": "0..5", "dashes": "spells", "scaling": "kind",
          "resource": "kind", "earlyLate": "-2..2"}


def rule_rows(v: dict, patch: str | None) -> dict:
    """Every rule trait's row. A rubric row's `value` waits for apply_calibration."""
    out = {}
    for t, fn in RULES.items():
        unit = "0..5" if t in MEASURES else _UNITS.get(t, "yes/no")
        got = fn(v)
        if got is None:
            out[t] = {"value": None, "unit": unit, "source": "unknown", "patch": patch,
                      "reason": "the source does not say"}
        elif t in MEASURES:
            out[t] = {"value": None, "unit": unit, "source": "computed", "patch": patch, "basis": got["mechanic"],
                      **got}
        elif t == "earlyLate":
            out[t] = {"value": None, "unit": unit, "source": "computed", "patch": patch, "raw": got[0], "basis": got[1]}
        else:
            out[t] = {"value": got[0], "unit": unit, "source": "computed", "patch": patch, "basis": got[1]}
    # a rule read off an estimated fight row is an estimate too; calibration leaves those out
    est = {"autoReliance": "damage" in (v["fight"].get("estimated") or ()),
           "attackSpeedScaling": "damage" in (v["fight"].get("estimated") or ()),
           "peel": any((v["row"].get(t) or {}).get("source") == "estimate" for t in ("allyHeal", "allyShield"))}
    for t, yes in est.items():
        if yes and out[t]["source"] == "computed":
            out[t]["source"] = "estimate"
            out[t]["basis"] += "; " + v["fight"]["stackBasis"]
    return out


def apply_calibration(rows: dict, cal: dict) -> None:
    """Fill rubric values in place, across every mode: one calibration, ARAM included."""
    for champs in rows.values():
        for roles in champs.values():
            for ids in roles.values():
                for row in ids.values():
                    for t in DRAFT_RUBRIC:
                        r = row.get(t) or {}
                        if r.get("source") in ("computed", "estimate"):
                            r["value"] = score_rubric(_flat(t, r["raw"], cal), cal["boundaries"][t], r.get("steps", 0))
                    e = row.get("earlyLate") or {}
                    if e.get("source") == "computed":
                        e["value"] = sum(e["raw"] > b for b in cal["boundaries"]["earlyLate"]) - 2


def population(staged: dict, rows: dict) -> list[dict]:
    """One row per ranked champion-role, its most-played archetype."""
    out = []
    for champ, roles in (staged["modes"].get("ranked") or {}).items():
        for role, entry in roles.items():
            archs = entry.get("archetypes") or []
            if not archs:
                continue
            top = max(archs, key=lambda a: a.get("games") or 0)["id"]
            row = (rows.get("ranked") or {}).get(champ, {}).get(role, {}).get(top)
            if row:
                out.append({t: row[t] for t in (*DRAFT_RUBRIC, "earlyLate")
                            if (row.get(t) or {}).get("source") == "computed"})
    return out


def strip_judged(store: dict) -> tuple[int, list[str]]:
    """Drop judged rows in place, keep what Sam corrected. (rows dropped, rows kept)."""
    dropped, kept = 0, []
    for champ, row in store.get("champions", {}).items():
        for t in [t for t, v in row.items() if isinstance(v, dict) and v.get("source") == "judged"]:
            if row[t].get("by") == "sam":
                kept.append(f"{champ}/{t}")
            else:
                del row[t]
                dropped += 1
    return dropped, kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archetypes", action="store_true", help="bake the traits of every staged archetype")
    ap.add_argument("--champ", action="append", help="limit to these champions")
    ap.add_argument("--items", action="store_true", help="bake data/forge-item-traits.json")
    ap.add_argument("--merge", type=Path, action="append", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.merge:
        print("bake_traits: --merge is retired, rubric traits come from rules since rubricVersion 2", file=sys.stderr)
        return 2
    if not (a.archetypes or a.items):
        ap.print_help()
        return 2
    if a.items:
        st = bake_items()
        print(f"bake_traits: {len(st['items'])} items, patch {st['patch']}")
    return bake_archetypes(a.champ) if a.archetypes else 0


if __name__ == "__main__":
    sys.exit(main())
