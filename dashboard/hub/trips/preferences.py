"""Crew travel-preference aggregation for the trips module.

Reads `contact` wiki nodes (their `travel_prefs` frontmatter) and rolls member
opinions up to a trip-level breakdown — shared interests, dealbreakers, diet,
pace. Ported from the 5001 dashboard's api.py. The VaultReader is lazily built
on first use (parsing the whole wiki is heavy; we don't want it at import).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_reader = None
# Separate flag rather than stuffing a False sentinel into _reader: a bool in a
# slot otherwise holding a VaultReader makes every reader.get_node() call a type
# error, and it reads as a value rather than as "we already tried and failed".
_reader_failed = False


def _get_reader(vault_root: Path):
    global _reader, _reader_failed
    if _reader is None and not _reader_failed:
        try:
            from vault_reader import VaultReader

            # contacts only: this module reads nothing else, and parsing the
            # whole wiki for it cost 1.6s on the first crew-tab load
            _reader = VaultReader(vault_root / "wiki", subdirs=["contacts"])
        except Exception:  # frontmatter missing, wiki unreadable, etc.
            logger.exception("VaultReader unavailable; preference lookups disabled")
            _reader_failed = True  # tried and failed; don't retry every call
    return _reader


def _contact_dict(node) -> dict:
    return {
        "path": node.path,
        "slug": node.path.split("/")[-1].replace(".md", ""),
        "name": node.name or node.title,
        "email": node.email,
        "aliases": node.aliases,
        "summary": node.summary,
        "travel_prefs": node.travel_prefs,
        "body": node.body,
    }


def contact_for_member(vault_root: Path, member: dict) -> dict | None:
    """Find a member's contact node by explicit slug, then by name/alias match."""
    reader = _get_reader(vault_root)
    if not reader:
        return None
    slug = (member.get("contact_slug") or "").strip()
    if slug:
        node = reader.get_node(f"wiki/contacts/{slug}.md")
        if node:
            return _contact_dict(node)
    name = (member.get("name") or "").strip().lower()
    if not name:
        return None
    for node in reader.get_nodes(types=["contact"]):
        if node.name and node.name.lower() == name:
            return _contact_dict(node)
        if any(a.lower() == name for a in (node.aliases or [])):
            return _contact_dict(node)
    return None


_NOISE_RESPONSES = {
    "", "none", "na", "nothing", "no", "joke", "nope", "nada", "nil", "lol",
}
_SOFT_NO_PREFIXES = ("none", "nothing", "no", "na", "nope")
_JOKE_MARKERS = ("joke", "lol", "lmao", "(jk)", "/s")
_SOFT_NO_PHRASES = (
    "effectively none", "actually none", "essentially none", "basically none",
)


def is_noise(text) -> bool:
    """Is this free-text answer an answered-nothing rather than a real flag?

    Module level, and public, because the crew CARDS need the same verdict the
    group rollup reaches. They used to disagree: the rail dropped Megan's "none"
    and the card printed it, so one surface said she had no restrictions while
    the other said her restriction was the word "none".
    """
    lower = str(text or "").lower()
    normalized = "".join(ch for ch in lower if ch.isalnum())
    if normalized in _NOISE_RESPONSES:
        return True
    if any(marker in lower for marker in _JOKE_MARKERS):
        return True
    if any(phrase in lower for phrase in _SOFT_NO_PHRASES):
        return True
    first_token = lower.split(None, 1)[0] if lower.split() else ""
    first_token_alnum = "".join(ch for ch in first_token if ch.isalnum())
    if first_token_alnum in _SOFT_NO_PREFIXES:
        rest = lower[len(first_token):].lstrip()
        if rest.startswith(("\u2014", "-", ",", ".", ":", ";", "(")):
            return True
    return False


# ── the ordinal scales ────────────────────────────────────────────────────────
#
# Every ordinal question on both forms, as an ORDER rather than as a set of
# labels. This is the one place that knows which way a question runs, and it is
# the reason the frontend can now draw a scale at all: the answers themselves
# carry no order, and the form's own option order is not it either (`adventure`
# and `sharing` are authored high-first, `spice` and `venue` low-first, and
# `raw` is not monotonic in either direction).
#
# Each entry is `(ordered values low → high, low end in words, high end in
# words)`. `low` and `high` name the AXIS, not the answers — they are what a
# reader needs to know what the track measures before reading where anybody
# sits on it. They obey the same rules as LABELS below: a direction, not a
# sentence, and never a like or a dislike ON A QUESTION THAT IS NOT ABOUT LIKING.
# "the hotter the better" and "loves it" were both, and they sat over option
# lists that had already stopped talking that way. `cuisines` is the exception,
# because there the axis genuinely runs hate → love.
#
# Retired 2026-08-29: the escape hatches ("depends" on spend / funk /
# chill_days, "mixed" on venue) are no longer offered. An escape is not an
# answer — it is a way to not answer, and it produced rows the rail could not
# place, which is exactly what the scale exists to do. Every question is now
# exactly five stops and every stop is a position. Old rows still carrying an
# escape keep their LABELS entry so they print a word, and _spread ignores them
# the way it always did.
#
# Every question here is a single pick on an order. The one question that was
# neither — coffee / tea / neither / both — is retired: it was a category wearing
# a radio, and worse, two questions wearing one, since "coffee, and I care about
# it" and "both" were not mutually exclusive. It is a `drinks` multi-select now
# (forms_intake._DRINK_OPTIONS), which needs no scale and no label table: the
# options ARE the words.
_SCALES = {
    # travel form
    "interests": (["hate", "rather-not", "neutral", "want", "must"], "hard pass", "must do"),
    "active_hours": (["2-hrs", "4-hrs", "6-hrs", "9-hrs", "12-hrs"], "short days", "long days"),
    "start_time": (["by-6", "by-8", "by-10", "by-noon", "after-noon"], "early", "late"),
    "chill_days": (["0", "half", "1", "2", "3+"], "no days off", "three or more"),
    "downtime": (["after-each", "midday-rest", "short-breaks", "one-break", "none-till-night"],
                 "breaks often", "keeps moving"),
    "walking": (["under-1-mi", "1-2-mi", "2-4-mi", "4-7-mi", "any"], "short walks", "any distance"),
    "distance_willing": (["15-min", "30-min", "60-min", "90-min", "any"], "stays close", "any distance"),
    "long_travel_days": (["hard-no", "prefer-none", "prefer-short", "once-or-twice", "welcome"],
                         "hard no", "no issue"),
    "meals_coordinated": (["flexible", "some-dinners", "dinner", "lunch-dinner", "every"],
                          "eats separately", "every meal together"),
    # food form
    "cuisines": (["hate", "rather-not", "neutral", "want", "must"], "hate", "love"),
    "spice": (["none", "mild", "medium", "hot", "very-hot"], "no heat", "no limit"),
    "adventure": (["familiar-only", "mostly-familiar", "balanced", "adventurous", "very-adventurous"],
                  "familiar only", "very adventurous"),
    # Form order, minus "depends on the dish", which is the escape hatch and not
    # the middle of anything.
    # Four stops mean no middle, and no middle means the question forces a side:
    # somebody who genuinely sits in the centre on sharing or drinking has to
    # round their answer up or down, and the rail then reads the rounded answer as
    # if it were the real one. "half-shared", "nicer", "either-way" and
    # "sometimes" are the centres those four were missing; like "a-bite" below
    # they exist on the vault's form only, which the option list can express
    # because it is built from this table rather than from the response parser.
    #
    # The QUANTITY scales are deliberately left even. A range of hours or dollars
    # has no neutral to add — only a finer bucket, which makes the answer harder
    # to pick rather than easier, and "~7 hrs" is not a middle opinion about
    # anything. The rule is that a question about how you FEEL has a centre.
    #
    # "a-bite" is not on the Google Form: funk was the one willingness question
    # with no middle, so it asked people to jump from "rather not" to "willing"
    # while offal and raw both let them say they would try some. The option list
    # is built from this order, not from the form's vocabulary, so the stop exists
    # on the vault's form without a fabricated entry in the response parser.
    "funk": (["hard-no", "rather-not", "a-bite", "willing", "seek"], "hard no", "seeks it out"),
    "offal": (["hard-no", "rather-not", "a-bite", "willing", "love"], "hard no", "seeks it out"),
    # NOT the form's order: it lists "cooked fish yes, raw no" above "only if I
    # know the place", and the second of those eats more raw than the first.
    "raw": (["hard-no", "cooked-only", "if-trusted", "willing", "love"], "hard no", "seeks it out"),
    "sharing": (["own-only", "own-with-bites", "half-shared", "mostly-share", "family-style"],
                "own dish", "shares everything"),
    "spend": (["under-15", "15-25", "25-40", "40-70", "70-plus"], "under $15", "$70+"),
    "venue": (["street-food", "casual", "mid-range", "nicer", "upscale"], "street food", "upscale"),
    "reservations": (["walk-in", "short-wait", "either-way", "will-book", "will-chase"],
                     "walks in", "chases a booking"),
    "alcohol": (["none", "rarely", "sometimes", "social", "enthusiastic"],
                "doesn't drink", "enthusiastic"),
}

# The two grids are the only questions whose ends are a verdict rather than a
# position: "skip" and "hate" ARE the bad end, which is what earns them the
# red→green ramp. Every other scale gets the neutral cool→warm one, because "own
# dish" is not worse than "family style" and a colour that says it is would be
# the app scoring the crew's answers instead of placing them.
_VALENCE = {"interests", "cuisines"}

# What ships to the browser. Same table, one dict per question, plus the rank map
# the frontend never has to rebuild.
SCALES = {
    key: {
        "order": order,
        "low": low,
        "high": high,
        "valence": key in _VALENCE,
        "rank": {v: i for i, v in enumerate(order)},
    }
    for key, (order, low, high) in _SCALES.items()
}


# ── the words ─────────────────────────────────────────────────────────────────
#
# One short label per (question, value). This is the ONLY display vocabulary:
# the account page's form draws its options from it, the crew cards and the group
# rail print it, and forms_intake.schema() hands it to the browser. It replaced
# three copies — the Google Form's own prose on the form, PREF_LABEL on the board,
# FOOD_LABEL beside it — which is why the form used to say "About 9 hours, most of
# the day with breaks" for the same answer the card called "~9 hrs".
#
# The rules these follow, because a scale is unreadable without them:
#
#   * a label is a POSITION, not a sentence. "A little kick is fine" is a person
#     talking; "mild" is a point you can put a dot on. Nothing here is longer than
#     three words and nothing carries a comma or a clause.
#   * no like / dislike, UNLESS the question is about liking. "Hate" and "Love
#     them" score the answer instead of placing it, and the neutral ramp exists
#     precisely so the board does not do that. The willingness questions (funk /
#     offal / raw) all run the same ladder — hard no → rather not → a bite →
#     willing → seeks it out — so three questions read as one scale instead of
#     three vocabularies. `cuisines` is the one place the words ARE feelings,
#     because the question it asks is how you feel about a food, not whether to
#     go eat it.
#   * per QUESTION, not per value. `none` is no heat on spice and a non-drinker on
#     alcohol, and `any` is a distance on one question and a walk on another. A
#     single value→word map is how the drinks row used to print "mild only".
#
# Keyed by question, so a value's meaning is never borrowed from another question.
# The keys and values here are the FORM's enums (forms_intake's _*_CHOICES map the
# Google prose onto them); nothing in this table is stored, so rewording a label
# is a display change with no migration behind it.
LABELS = {
    # travel ──────────────────────────────────────────────────────────────────
    # Interests is a decision — whether to spend a day on the thing — so its
    # answers are stated as decisions. Cuisines asks the opposite kind of
    # question and gets the opposite vocabulary; see the note there.
    "interests": {"must": "must", "want": "want", "neutral": "neutral",
                  "rather-not": "skip", "hate": "hard pass"},
    "active_hours": {"2-hrs": "~2 hrs", "4-hrs": "~4 hrs", "6-hrs": "~6 hrs",
                     "9-hrs": "~9 hrs", "12-hrs": "12+ hrs"},
    "downtime": {"after-each": "after each", "midday-rest": "midday rest",
                 "short-breaks": "short breaks", "one-break": "one break",
                 "none-till-night": "none till night"},
    "start_time": {"by-6": "by 6am", "by-8": "by 8am", "by-10": "by 10am",
                   "by-noon": "by noon", "after-noon": "after noon"},
    # "2+" and "depends" are retired options that five member_prefs rows still
    # carry. Kept here so an old row prints a word rather than a raw enum; they
    # are not on any scale, so nobody is offered them again.
    "chill_days": {"0": "0", "half": "half a day", "1": "1", "2": "2", "3+": "3+",
                   "2+": "2+", "depends": "depends"},
    "meals_coordinated": {"flexible": "none planned", "some-dinners": "some dinners",
                          "dinner": "dinner", "lunch-dinner": "lunch + dinner",
                          "every": "every meal"},
    "walking": {"under-1-mi": "under 1 mi", "1-2-mi": "1–2 mi", "2-4-mi": "2–4 mi",
                "4-7-mi": "4–7 mi", "any": "any distance"},
    "distance_willing": {"15-min": "15 min", "30-min": "30 min", "60-min": "1 hr",
                         "90-min": "90 min", "any": "any distance"},
    "long_travel_days": {"hard-no": "hard no", "prefer-none": "prefer none",
                         "prefer-short": "keep short", "once-or-twice": "once or twice",
                         "welcome": "no issue"},
    # food ────────────────────────────────────────────────────────────────────
    # NOT the interests wording. Interests asks whether to DO a thing, so its
    # answers are decisions ("must do", "skip"). Cuisines asks whether you LIKE
    # a food, which is a feeling and not a plan — "must have Korean" was asking
    # people to commit to a meal when the honest answer is that they love it.
    # The stored enums are still the interests ones; only the words changed.
    "cuisines": {"must": "love", "want": "like", "neutral": "neutral",
                 "rather-not": "dislike", "hate": "hate"},
    # Sam's own wording for this one, verbatim: none, mild, medium, hot, no
    # limit. It is the shape every other scale here is cut to.
    "spice": {"none": "none", "mild": "mild", "medium": "medium", "hot": "hot",
              "very-hot": "no limit"},
    "adventure": {"familiar-only": "familiar only", "mostly-familiar": "mostly familiar",
                  "balanced": "balanced", "adventurous": "adventurous",
                  "very-adventurous": "very adventurous"},
    "funk": {"hard-no": "hard no", "rather-not": "rather not", "a-bite": "a bite",
             "willing": "willing", "seek": "seeks it out", "depends": "depends"},
    "offal": {"hard-no": "hard no", "rather-not": "rather not", "a-bite": "a bite",
              "willing": "willing", "love": "seeks it out"},
    "raw": {"hard-no": "hard no", "cooked-only": "cooked only", "if-trusted": "if trusted",
            "willing": "willing", "love": "seeks it out"},
    "sharing": {"own-only": "own only", "own-with-bites": "trades bites",
                "half-shared": "half and half", "mostly-share": "mostly shares",
                "family-style": "family style"},
    "spend": {"under-15": "under $15", "15-25": "$15–25", "25-40": "$25–40",
              "40-70": "$40–70", "70-plus": "$70+", "depends": "depends"},
    "venue": {"street-food": "street food", "casual": "casual", "mid-range": "mid-range",
              "nicer": "nicer", "upscale": "upscale", "mixed": "all of it"},
    "reservations": {"walk-in": "walks in", "short-wait": "short wait",
                     "either-way": "either way", "will-book": "will book",
                     "will-chase": "will chase"},
    "alcohol": {"none": "none", "rarely": "rarely", "sometimes": "sometimes",
                "social": "social", "enthusiastic": "enthusiastic"},
}


def label(key: str, value) -> str:
    """The display word for one answer, or the raw value if it has no label.

    The fallback is the value rather than an empty string on purpose: a missing
    label should look like a rough edge, not like an unanswered question.
    """
    if value is None or value == "":
        return ""
    return LABELS.get(key, {}).get(str(value), str(value))


def rank_map(key: str) -> dict:
    """The ordinal rank map for one question, derived from its scale.

    Every rollup below reads this rather than carrying its own copy. The maps
    used to be eleven literals inside aggregate_preferences, which is how the
    frontend ended up with no way to know the order at all — it lived in a
    function body, on the server, and nothing else could see it.
    """
    return SCALES[key]["rank"]


RATING_RANK = rank_map("interests")

# The verdict is a floor — the lowest rating anybody gave — which is the right
# read for six activity tags and the wrong one for thirteen cuisines: with five
# people answering, one "rather not" anywhere buries a cuisine two of them want,
# and every row collapses to pushback. The score is the appetite alongside it, so
# the rail can lead with what the crew actually wants to eat and still print what
# somebody would refuse.
_RATING_SCORE = {"must": 2, "want": 1, "neutral": 0, "rather-not": -2, "hate": -4}


def _verdict(min_rank) -> str:
    """A group's read on one tag is the LOWEST rating anybody gave it."""
    if min_rank is None:
        return "unrated"
    if min_rank >= 4:
        return "everyone-must"
    if min_rank >= 3:
        return "shared-want"
    if min_rank >= 2:
        return "ok-for-all"
    if min_rank >= 1:
        return "someone-rather-not"
    return "vetoed"


def _grid_rollup(contacts, prefs_key, grid_key, tags, default=None) -> list[dict]:
    """Roll a must→hate ratings grid up to one verdict per tag.

    `default` is what a member who never answered counts as. Travel interests
    pass "neutral" — the six tags always render and a silent member is not an
    objection. Cuisines pass None so silence is not a vote: with the food form
    unsubmitted the row reads `unrated` rather than claiming the crew is fine
    with everything.
    """
    out = []
    for tag in tags:
        ratings, min_rank = {}, None
        for c in contacts:
            r = ((c.get(prefs_key) or {}).get(grid_key) or {}).get(tag, default)
            if r is None:
                continue
            ratings[c["name"]] = r
            rank = RATING_RANK.get(r, 2)
            min_rank = rank if min_rank is None else min(min_rank, rank)
        out.append({
            "tag": tag, "verdict": _verdict(min_rank), "per_member": ratings,
            "score": sum(_RATING_SCORE.get(r, 0) for r in ratings.values()),
        })
    return out


def _spread(vals, rank_map) -> dict:
    ranked = [(name, v, rank_map.get(v)) for name, v in vals]
    ranked = [(name, v, r) for name, v, r in ranked if r is not None]
    if not ranked:
        return {
            "alignment": "unknown", "min_value": None, "max_value": None,
            "min_members": [], "max_members": [],
        }
    ranks = [r for _, _, r in ranked]
    lo, hi = min(ranks), max(ranks)
    return {
        "alignment": {0: "aligned", 1: "close", 2: "diverging"}.get(hi - lo, "diverging"),
        "min_value": next(v for _, v, r in ranked if r == lo),
        "max_value": next(v for _, v, r in ranked if r == hi),
        "min_members": [name for name, _, r in ranked if r == lo],
        "max_members": [name for name, _, r in ranked if r == hi],
    }


def _rollup(contacts, prefs_key, field, rank_map) -> dict:
    """One ordinal question, collapsed to a `min → max` range plus per-member.

    Values are stringified because `chill_days` arrives as an int — and via
    `str()` rather than `or ""`, since 0 is a real answer and a falsy one.
    """
    vals = []
    for c in contacts:
        raw = (c.get(prefs_key) or {}).get(field, "")
        vals.append((c["name"], "" if raw is None else str(raw)))
    return {"per_member": [{"member": n, "value": v} for n, v in vals], **_spread(vals, rank_map)}


def aggregate_preferences(contacts: list[dict]) -> dict:
    """Build a trip-level breakdown across all member contacts."""
    primary_tags = ["Nature", "City", "Food", "Nightlife", "Arts", "Music"]

    dealbreakers = []
    physical_limits = []
    diets = []
    for c in contacts:
        prefs = c.get("travel_prefs") or {}
        absolute = (prefs.get("absolute_nos") or "").strip()
        if absolute and not is_noise(absolute):
            dealbreakers.append({"member": c["name"], "text": absolute})
        limits = (prefs.get("physical_limits") or "").strip()
        if limits and not is_noise(limits):
            physical_limits.append({"member": c["name"], "text": limits})
        # The travel form used to carry a single free-text "any dietary
        # restrictions?" line. The food form asks it properly — an allergy, a
        # diet and a won't-eat are three different facts — so the rollup reads
        # those, the same three the crew card already prints.
        food = c.get("food_prefs") or {}
        diet = " · ".join(
            t for t in (
                (food.get("allergies") or "").strip(),
                (food.get("wont_eat") or "").strip(),
                ", ".join(d for d in (food.get("diets") or []) if d != "No restrictions"),
            ) if t and not is_noise(t)
        )
        if diet:
            diets.append({"member": c["name"], "text": diet})

    # The 13 cuisine tags are not hard-coded: a submission always carries the
    # whole grid, so first-seen order across the crew IS the form's order and it
    # cannot drift out of sync with forms_intake._FOOD_GRID.
    cuisine_tags = []
    for c in contacts:
        for tag in ((c.get("food_prefs") or {}).get("cuisines") or {}):
            if tag not in cuisine_tags:
                cuisine_tags.append(tag)

    # The rank maps used to be eleven literals right here. They are one table now
    # (SCALES at the top of this file), because the frontend needs the same order
    # to draw a scale and could not reach a dict living in this function body.
    # What has not changed is which values are ON a scale: "depends", "mixed" and
    # "other" are real answers and not scale positions, they stay out of the
    # order, ride along in per_member, and _spread ignores them.

    return {
        "members_count": len(contacts),
        # How many people the food card is actually speaking for. Without it an
        # empty card cannot tell "nobody filled the form" from "they all said
        # something unrankable".
        "food_responses": sum(1 for c in contacts if c.get("food_prefs")),
        "interests": _grid_rollup(contacts, "travel_prefs", "interests", primary_tags, default="neutral"),
        "cuisines": _grid_rollup(contacts, "food_prefs", "cuisines", cuisine_tags),
        "dealbreakers": dealbreakers,
        "physical_limits": physical_limits,
        "diet_restrictions": diets,
        "food": {
            # Off the FOOD form. The travel form asked the identical question on
            # the identical scale, and the two answers drifted apart — Leo read
            # as very-adventurous on one and balanced on the other. One question,
            # one home. `meals` is the exception: it is still a travel-form
            # question, it just belongs in the food read.
            "adventure": _rollup(contacts, "food_prefs", "adventure", rank_map("adventure")),
            "spice": _rollup(contacts, "food_prefs", "spice", rank_map("spice")),
            "sharing": _rollup(contacts, "food_prefs", "sharing", rank_map("sharing")),
            "spend": _rollup(contacts, "food_prefs", "spend", rank_map("spend")),
            "venue": _rollup(contacts, "food_prefs", "venue", rank_map("venue")),
            "reservations": _rollup(contacts, "food_prefs", "reservations", rank_map("reservations")),
            "alcohol": _rollup(contacts, "food_prefs", "alcohol", rank_map("alcohol")),
            "meals": _rollup(contacts, "travel_prefs", "meals_coordinated", rank_map("meals_coordinated")),
        },
        "pace": {
            "active_hours": _rollup(contacts, "travel_prefs", "active_hours", rank_map("active_hours")),
            "start_time": _rollup(contacts, "travel_prefs", "start_time", rank_map("start_time")),
            "chill_days": _rollup(contacts, "travel_prefs", "chill_days", rank_map("chill_days")),
        },
    }
