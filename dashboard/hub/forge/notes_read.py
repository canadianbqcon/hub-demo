#!/usr/bin/env python3
"""Turn the baked patch notes into something you can scan at a glance.

bake_patchnotes.py stores Riot's notes exactly as published: a paragraph of
prose per entry, a from/to pair of long strings per change. That is the right
thing to STORE - it is the source, and nothing derived here can recover what the
bake did not fetch - but it is not what you want to read at 11pm with the client
on the other monitor. Riot writes for a blog: every entry opens with "We are
continuing to...", and every number arrives as two near-identical strings you
have to scan character by character to find the one digit that moved.

Three readings are derived, at SERVE time rather than at bake time, so the JSON
on disk stays byte-for-byte what Riot published and a presentation change never
needs a re-bake:

    gist()     the prose with the throat-clearing deleted. Deletion only - it
               removes stock Riot filler and never rewrites a clause, so it
               cannot invent a claim Riot did not make. Worst case it under-cuts
               and you read one more clause than you needed.
    compare()  the from/to pair read number by number, so each thing that moved
               is its own small comparison and the text that did not move is
               printed once, dimmed. "60 / 80 / 100 / 120 / 140 (+35 / 40 / 45 /
               50 / 55% AP)" against its twin is five numbers of difference
               wearing forty characters of identical tail.
    verdict()  buff / nerf / mixed per change and buff / nerf / rework per entry,
               so direction is a colour and a badge instead of arithmetic you do
               yourself. Per NUMBER, not per row: an ability buffed at rank 1 and
               cut at rank 3 has to show both, or the page prints NERF over a
               change whose own paragraph calls it a trade.

Riot's markup carries NO buff/nerf classification - checked, there is no class,
attribute or icon for it anywhere on the page - so the verdict is derived. Prose
first, because Riot states intent in words ("we are buffing", "nerf her support
roaming power") and stated intent beats inferred arithmetic. Numbers only when
the prose says nothing. This ordering is the lesson from the Sundered Sky read:
Health 400 -> 450 is a real number and still the wrong summary of a patch that
cut the item's healing.

Self-check: python3 notes_read.py
"""

from __future__ import annotations

import re

# ── the prose ──────────────────────────────────────────────────────────────

# Riot's stock openers. Pure discourse glue: what is left after cutting one is
# the same claim. `With <clause>,` and `Since <clause>,` are deliberately NOT
# here - "With roaming supports all the rage, Camille has been queen" loses the
# reason if you cut the front off it.
OPENERS = re.compile(
    r"^(?:finally|similarly|additionally|also|lastly|meanwhile|however|"
    r"that said|for now however|for now|on the other hand|in addition|"
    r"speaking of [^,]{,60}|next to [^,]{,60})[,:]\s*",
    re.I)

# ordered: the longest, most specific framing first, so a general rule never
# eats the phrase a specific one was going to rewrite
PHRASES: list[tuple[re.Pattern, str]] = [(re.compile(p, re.I), r) for p, r in [
    (r"\bwe are continuing to monitor\b",                        "still watching"),
    (r"\bwe continue to feel(?: like| that)?\b",                  ""),
    (r"\bwe(?:'re| are) continuing to\b",                        "still"),
    (r"\bwe(?:'ve| have) opted to\b",                             ""),
    (r"\bwe(?:'re| are)(?: also| simultaneously)? looking to\b",  ""),
    (r"\bwe(?:'re| are) going to give (?:him|her|them|it) an?\b", ""),
    (r"\bwe(?:'re| are)(?: also)? going to\b",                    ""),
    (r"\bwe(?:'ll| will)\b",                                      ""),
    (r"\bwe(?: also)? hope(?: that)? this will\b",                "hoping to"),
    (r"\bwe (?:do |also )?(?:think|feel|believe)(?: like)?(?: that)?\b", ""),
    (r"\bwe(?:'re| are)(?: also| simultaneously)?\b",             ""),
    (r"\bwe(?:'ve| have)\b",                                      ""),
    (r"\bwe\b",                                                   ""),
    # vacuous purpose tails. "to help mage and tank junglers" survives - it names
    # who; only the ones naming the entry's own subject back at you are cut.
    (r",? ?(?:in order )?to help (?:him|her|them|it) out\b",      ""),
    (r"\bfor a while now\b",                                      ""),
    (r"\bover the course of the year\b",                          "this year"),
    (r",? on the other hand,?",                                   ""),
    (r"\bat this (?:point in )?time\b",                           ""),
    (r"\bthis is the right time to\b",                            "time to"),
    (r"\btaking the time to\b",                                   ""),
]]

# Trailing clauses that restate, in prose, what the stat rows directly below the
# line already say. "by significantly increasing her scaling with durability and
# giving her enough mana growth" sits above Mana 280 -> 300 and Armor 12% -> 16%,
# so it is the same claim twice and the numbers are the better half of it.
MECHANISM = [re.compile(p, re.I) for p in (
    r",?\s*(?:in order )?by (?:significantly |slightly |moderately |further )?\w+ing\b.*$",
    r",?\s*which (?:should|will|would|means?|helps?)\b.*$",
    r",?\s*making sure\b.*$",
    r"^this means \w+ing\b.*$",
)]

# Subordinate front clauses. Cutting "we are looking to" out of "Since we are
# looking to shift mage power back to mid lane, we are also nerfing..." leaves
# "Since shift mage power back to mid lane" - a clause with no subject, which
# reads as broken text. The clause is scene-setting, so it goes whole or not at
# all, and the sentence it introduces survives intact.
SUBORDINATE = re.compile(r"^(?:while|since|although|though|given that|"
                         r"as|because|when)\s+[^,]{10,150},\s*", re.I)

# A sentence that says what Riot is DOING, as opposed to describing the problem.
# Riot writes problem-first and action-last, so a naive head-clip drops the point.
ACTION = re.compile(
    r"\bwe\b|\bwe(?:'re|'ve|'ll)\b|\blooking to\b|\bgoing to\b|"
    r"\bopted to\b|\bbuff|\bnerf|\badjust|\bshift", re.I)

# Narrower: first-person plans only. The badge reads THIS patch's intent, and
# "Gwen has remained slightly weak since her nerfs earlier this year" is history
# - counting its "nerfs" turned a straight buff into a rework.
INTENT = re.compile(
    r"\bwe\b|\bwe(?:'re|'ve|'ll)\b|\blooking to\b|\bgoing to\b|\bopted to\b", re.I)

# The keystones and runes Riot spells out in full every patch. Sam reads
# them as initials, and a one-line gist has no room for "Press The Attack".
ALIASES = {
    "Press The Attack": "PTA",
    "Hail of Blades": "HoB",
    "Fleet Footwork": "Fleet",
    "Grasp of the Undying": "Grasp",
    "Dark Harvest": "Dark Harvest",
    "Lethal Tempo": "Lethal Tempo",
}

FILLER = re.compile(
    r"\b(?:particularly|relatively|really|quite|fairly|pretty much|"
    r"actually|simply|just|clearly|of course|in general|generally)\s+", re.I)

GIST_CHARS = 260


def _tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r"^[,;:\s]+", "", s)
    return s.strip()


def _alias(text: str) -> str:
    for full, short in ALIASES.items():
        if full != short:
            text = re.sub(re.escape(full), short, text, flags=re.I)
    return text


def _clean_sentence(raw: str, subject: str) -> tuple[bool, str] | None:
    """One sentence with the blog voice cut, or None if nothing real is left."""
    raw = raw.strip()
    acts = bool(ACTION.search(raw))
    s = raw
    for _ in range(3):                       # "Finally, next to X, ..." stacks
        cut = SUBORDINATE.sub("", OPENERS.sub("", s))
        if cut == s:
            break
        s = cut
    for pat in MECHANISM:
        s = pat.sub("", s)
    for pat, rep in PHRASES:
        s = pat.sub(rep, s)
    s = FILLER.sub("", s)
    # "Azir has been..." -> "has been...": the name is the heading
    if subject:
        s = re.sub(rf"^{re.escape(subject)}(?:'s|s')?\s+", "", s, flags=re.I)
    s = _tidy(s).rstrip(",;: ")
    if len(s.rstrip(".")) < 8:          # nothing left but punctuation
        return None
    if not s.endswith((".", "!", "?")):
        s += "."
    return acts, s[0].upper() + s[1:]


def _trim_to_budget(out: list[tuple[bool, str]]) -> str:
    """Sentences joined under GIST_CHARS.

    Over budget, the sentence to drop first is the one setting the scene, not
    the one saying what changed. Riot writes scene-first, so a head-clip drops
    the only half you opened the page for.
    """
    keep = [t for a, t in out]
    while sum(len(t) + 1 for t in keep) > GIST_CHARS and len(keep) > 1:
        drop = next((i for i, (a, t) in enumerate(out)
                     if not a and t in keep), None)
        keep.remove(keep[0] if drop is None else out[drop][1])
        out = [(a, t) for a, t in out if t in keep]
    joined = " ".join(keep)
    if len(joined) > GIST_CHARS:
        joined = joined[:GIST_CHARS].rsplit(" ", 1)[0] + "\u2026"
    return joined


def gist(context: str | None, subject: str = "") -> str:
    """Riot's paragraph with the blog voice deleted.

    Deletion and alias substitution only. No clause is reworded, so the result
    can be clipped or clumsy but never says something Riot did not. `subject` is
    the entry's own name, dropped where it is the sentence's subject - the name
    is already the heading above the line.
    """
    if not context:
        return ""

    text = _alias(context.strip())
    out = [c for c in (_clean_sentence(raw, subject)
                       for raw in re.split(r"(?<=[.!?])\s+", text)) if c]
    return _trim_to_budget(out) if out else ""


# ── the numbers ────────────────────────────────────────────────────────────

# Magnitude only, no sign. "10-130" is a RANGE in patch-note prose, not ten minus
# a hundred and thirty, and reading that hyphen as a minus flipped Fleet Footwork's
# healing buff into a nerf. Riot also writes penalties as negatives ("-25%" ->
# "-33%"), where the magnitude growing IS the change; the sign carries no
# information either way, so it is never read.
# Riot writes sub-1 values with no leading zero -- Vayne's attack speed ratio is
# ".658 + 3.3%/Level" -> ".67 + 2.8%/Level", and her health regen growth ".55/Level"
# -> ".5/Level". A number pattern that starts at a digit reads those as 658 -> 67
# and 55 -> 5: the wrong magnitude on screen, and on the regen line the wrong
# DIRECTION too, since 55 -> 5 tints as a nerf where .55 -> .5 is one, but 3.5 -> 4
# beside it made the row read as a straight buff. The leading dot is part of the
# number, so the pattern has to start there; the lookbehind keeps it from splitting
# "3.3" into "3" and ".3", and from eating a sentence-ending period after a digit.
_N = r"(?:(?<![\d.])\.\d+|\d+(?:\.\d+)?)"
NUM = re.compile(_N)

# Fields where the number going UP is the change getting worse. Everything else
# defaults to higher-is-better, which is what a stat line means: these notes are
# written from the champion's or the item's side.
LOWER_IS_BETTER = (
    "cooldown", "cost", "recipe", "consumption", "penalty", "recharge",
    "cast time", "charge time", "windup", "delay", "price",
)


# A RUN is a maximal number list: one quantity written once per level band.
# "10 / 15 / 20 / 25" is a run; so is a lone "20". Pairing at run level rather
# than at number level is what lets a flat value and a per-level curve occupy
# the same slot on both sides, which is the whole point - "20% Maximum Health"
# against "10 / 15 / 20 / 25% Maximum Health" is the same quantity gaining a
# curve, and reading it number by number sees a shape change and gives up.
RUN = re.compile(_N + r"(?:\s*/\s*" + _N + r")*")

# The band annotation Riot appends to a curve: "(levels 1 / 7 / 13 / 19)",
# "(at level 1 / 7 / 13)", "(levels 1-8)". It is legend, not a value - its
# numbers are level indices and comparing them says nothing - so it comes off
# both sides before anything is paired and goes back on as dim trailing
# context. Left in, its own numbers form a run and drag the shape comparison
# with them.
LEVELS = re.compile(r"\s*\((?:at\s+)?levels?\s+[\d\s/.-]+\)\s*$", re.I)

BAND = re.compile(r"(\s*/\s*)")


def _skeleton(s: str) -> list[str]:
    """The literal text around each RUN.

    ``"40 / 75 (+22.5% AP)"`` -> ``['', ' (+', '% AP)']``. Two values with the
    same skeleton differ ONLY inside their number lists, which is the property
    that makes pairing those lists off by position a fact rather than a guess.
    """
    return RUN.split(s)


def _strip_levels(s: str) -> tuple[str, str]:
    """The value with its band annotation taken off, and the annotation."""
    m = LEVELS.search(s)
    return (s[:m.start()], m.group(0)) if m else (s, "")


def _run_segs(field: str, ra: str, rb: str, banded: bool) -> list[dict]:
    """One run against its opposite run, band by band.

    Three ways two lists of different length are still the same quantity:

    - one side is a single value: it is a curve that does not move, so it is
      broadcast across every band. This is Camille's shield going from a flat
      ``20% Maximum Health`` to ``10 / 15 / 20 / 25%`` - weaker until level 13,
      stronger after, which is exactly what you want to know before you trade.
    - the curve lost or gained a top band and a ``(levels ...)`` annotation says
      so: the shorter side keeps its last value at the levels it no longer
      names. Camille's passive cooldown dropped its level-19 band, so at 19+ its
      level-13 value persists - 6s became 8s, a nerf inside a change whose other
      three bands are all buffs.
    - neither: no honest pairing exists, so THIS RUN renders as one uncoloured
      pair and every other run on the line still reads. The bail-out is
      localised to the run, never to the row - one unreadable list must not grey
      out the numbers beside it.
    """
    a, b = BAND.split(ra), BAND.split(rb)
    na, nb, sa, sb = a[::2], b[::2], a[1::2], b[1::2]

    if len(na) != len(nb):
        if len(na) == 1:
            na = na * len(nb)
        elif len(nb) == 1:
            nb = nb * len(na)
        elif banded and len(na) < len(nb):
            na = na + [na[-1]] * (len(nb) - len(na))
        elif banded:
            nb = nb + [nb[-1]] * (len(na) - len(nb))
        else:
            return [{"t": "chg", "old": ra, "new": rb, "v": None}]

    seps = sb if len(sb) >= len(sa) else sa
    seps = seps + [" / "] * (len(na) - 1 - len(seps))

    out: list[dict] = []
    for i, (x, y) in enumerate(zip(na, nb, strict=True)):
        if i:
            out.append({"t": "same", "s": seps[i - 1]})
        out.append({"t": "same", "s": x} if x == y else
                   {"t": "chg", "old": x, "new": y, "v": _pair_dir(field, x, y)})
    return out


def _pair_dir(field: str, a: str, b: str) -> str | None:
    """buff / nerf for one number against its opposite number, None if equal."""
    fa, fb = float(a), float(b)
    if fa == fb:
        return None
    low = any(k in field.lower() for k in LOWER_IS_BETTER)
    return "buff" if (fb > fa) != low else "nerf"


def _total_dir(field: str, old: str, new: str) -> str | None:
    """Direction from the SUM of each side. Only used when the two values cannot
    be paired number for number, and only when both sides hold the same COUNT of
    numbers - a differing count means the shape moved, and no arithmetic on that
    is honest."""
    a, b = NUM.findall(old), NUM.findall(new)
    if not a or len(a) != len(b):
        return None
    sa, sb = sum(map(float, a)), sum(map(float, b))
    if sa == sb:
        return None
    low = any(k in field.lower() for k in LOWER_IS_BETTER)
    return "buff" if (sb > sa) != low else "nerf"


def compare(field: str, old: str, new: str) -> list[dict]:
    """The two values read as a run of segments, one per thing that moved.

    Returns a list of::

        {"t": "same", "s": " / "}                            unchanged text
        {"t": "chg", "old": "5", "new": "6", "v": "buff"}    one number, its own direction
        {"t": "add", "s": " (+8% per 1000 bonus Health)"}    a clause the patch added

    Numbers are paired **by position**, and only when the text around them is
    identical on both sides. That is the whole safety property: matching
    skeletons mean run *i* on the left and run *i* on the right are the same
    quantity, so comparing them states a fact. It is also why this is not a
    generic sequence diff - `18 / 14 / 10 / 6s` against `14 / 11 / 8s` has a "14"
    on both sides, and a diff aligns them happily and reports rank 2 unchanged
    when the entire curve was restructured from four ranks to three.

    The unit of pairing is a RUN (a whole number list), not a single number, so
    a curve changing its band count is read rather than abandoned - see
    `_run_segs` for the three ways two lists of different length are still the
    same quantity. A value's `(levels ...)` annotation comes off first and goes
    back on as dim trailing context; its numbers are level indices, and pairing
    them says nothing.

    Per-element is the point of the whole function. `5 / 15 / 25%` ->
    `6 / 13 / 20%` is a buff at rank 1 and a nerf at ranks 2 and 3; one colour
    over the row printed NERF across a change whose own paragraph says her early
    game was protected and her late game cut. Reading the row by its total hid
    the half Sam opens the page for. Same for `3, increased to 12 on
    champions` -> `4, increased to 10 on champions`: the base went UP and the
    bonus came DOWN, and a single arrow spanning both mashes two opposite facts
    into one string nobody can read.

    When the skeletons do not match, the shape changed rather than the values
    ("20 for 2s" -> "[20 Melee || 10 Ranged] for 2s") and no pairing is
    meaningful, so the whole pair comes back as one segment carrying the summed
    direction - which is None whenever the counts differ too. Giving up is a real
    answer here: an uncoloured row reads as "look at this one yourself", and a
    confidently wrong colour is the failure this module has a scar from. It is
    the LAST resort now, not the first: a run that cannot be paired takes only
    itself out of the reading, and the row falls back whole only when the
    literal text between the runs is itself different.
    """
    body_a, ann_a = _strip_levels(old)
    body_b, ann_b = _strip_levels(new)
    banded = bool(ann_a or ann_b)
    # the annotation to re-emit is the one naming MORE bands: it is the legend
    # for the wider of the two curves, and the narrower one is a subset of it
    ann = max(ann_a, ann_b, key=lambda s: len(NUM.findall(s)))

    pa, pb = _skeleton(body_a), _skeleton(body_b)
    ra, rb = RUN.findall(body_a), RUN.findall(body_b)

    fallback, extra = _shape_extra(field, old, new, pa, pb, ra, rb)
    if fallback is not None:
        return fallback

    segs = _build_segments(field, pa, ra, rb, banded, extra, ann)
    return _merge_same_runs(_rejoin_ranges(segs))


def _shape_extra(field: str, old: str, new: str, pa: list[str], pb: list[str],
                 ra: list[str], rb: list[str]) -> tuple[list[dict] | None, str]:
    """(None, "") when the skeletons match plainly, so `compare()` proceeds run by
    run. Otherwise either a whole-pair fallback (the two really did restructure)
    or the literal text of a clause the patch bolted onto the end.

    The bolted-on-clause shape is the one restructure that is still safe to read
    run for run: "20 / 25 / 30 / 35 / 40%" -> the same list "(+8% per 1000 bonus
    Health)" is a comparison plus an addition, not a restructure.
    """
    if pa == pb:
        return None, ""
    k = len(pa) - 1
    if not (len(pb) > len(pa) and pa[:k] == pb[:k] and pb[k].startswith(pa[-1])):
        return [{"t": "chg", "old": old, "new": new,
                "v": _total_dir(field, old, new)}], ""
    extra = pb[k][len(pa[-1]):]
    for i in range(len(ra), len(rb)):
        extra += rb[i] + pb[i + 1]
    return None, extra


def _build_segments(field: str, pa: list[str], ra: list[str], rb: list[str],
                    banded: bool, extra: str, ann: str) -> list[dict]:
    segs: list[dict] = []
    for i, lit in enumerate(pa):
        if lit:
            segs.append({"t": "same", "s": lit})
        if i < len(ra):
            segs.extend(_run_segs(field, ra[i], rb[i], banded))
    if extra:
        segs.append({"t": "add", "s": extra})
    if ann:
        segs.append({"t": "same", "s": ann})
    return segs


def _rejoin_ranges(segs: list[dict]) -> list[dict]:
    """A range is one quantity written with two numbers. "10-25" -> "12-40" split
    into two comparisons renders as "10->12-25->40", which reads as neither a
    range nor a comparison. Rejoined only when both ends agree on direction -
    if they disagree, they really are two facts and stay apart.
    """
    joined: list[dict] = []
    for s in segs:
        if (s["t"] == "chg" and len(joined) >= 2
                and joined[-1] == {"t": "same", "s": "-"}
                and joined[-2]["t"] == "chg" and joined[-2].get("v") == s.get("v")):
            a = joined[-2]
            joined[-2:] = [{"t": "chg", "old": f'{a["old"]}-{s["old"]}',
                            "new": f'{a["new"]}-{s["new"]}', "v": s.get("v")}]
        else:
            joined.append(s)
    return joined


def _merge_same_runs(joined: list[dict]) -> list[dict]:
    """One span per literal — otherwise it is noise in the DOM and a wrap point
    the layout does not want."""
    out: list[dict] = []
    for s in joined:
        if s["t"] == "same" and out and out[-1]["t"] == "same":
            out[-1] = {"t": "same", "s": out[-1]["s"] + s["s"]}
        else:
            out.append(s)
    return out


def _row_dir(segs: list[dict]) -> str | None:
    """One direction for a whole bullet, or "mixed" when its numbers disagree."""
    seen = {s["v"] for s in segs if s["t"] == "chg" and s.get("v")}
    if not seen:
        return None
    return next(iter(seen)) if len(seen) == 1 else "mixed"


def change_verdict(field: str, old: str, new: str) -> str | None:
    """"buff" / "nerf" / "mixed" for one bullet, or None when the numbers do not say.

    "mixed" is a real verdict and a common one. Hail of Blades dropped its true
    damage floor and raised its scaling in the same line; Bel'Veth's ultimate was
    buffed at rank 1 and cut at ranks 2 and 3. Collapsing either to a single
    direction is what put a flat NERF over a change that is a trade, so the row
    now says so and the card's badge inherits it.
    """
    return _row_dir(compare(field, old, new))


# ── the badge ──────────────────────────────────────────────────────────────

# Riot states intent in words far more reliably than the arithmetic infers it,
# so the prose is read first. "adjust" and its family mean deliberately moving
# power sideways, which is what rework says.
SAYS_BUFF = re.compile(r"\bbuff(?:s|ing|ed)?\b", re.I)
SAYS_NERF = re.compile(r"\bnerf(?:s|ing|ed)?\b", re.I)
SAYS_MOVE = re.compile(r"\b(?:adjust(?:s|ing|ed|ment)?|rework(?:s|ing|ed)?|"
                       r"shift(?:s|ing|ed)?(?: power)?|rebalanc\w*|"
                       r"trading (?:the|its|her|his|their))\b", re.I)


def triage(entry: dict) -> str:
    """"buff" / "nerf" / "rework" for a whole entry.

    Prose first: Riot writes the intent down, and stated intent beats inferred
    arithmetic. Only when the paragraph says nothing does this fall back to the
    per-change verdicts, and a mix of both directions is a rework either way.
    """
    ctx = entry.get("context") or ""
    # Only the sentences stating an intent count. "Gwen has remained slightly
    # weak since her nerfs earlier this year" is history - reading its "nerfs"
    # as this patch's verdict turned a straight buff into a rework.
    said = [s for s in re.split(r"(?<=[.!?])\s+", ctx) if INTENT.search(s)] or [ctx]
    ctx = " ".join(said)

    said_b, said_n = bool(SAYS_BUFF.search(ctx)), bool(SAYS_NERF.search(ctx))
    if said_b and said_n:
        return "rework"
    # an explicit "we are buffing" outranks an incidental "shifting power":
    # Chainlaced Crushers shifts mage power AND says nerf, and it is a nerf
    if said_b:
        return "buff"
    if said_n:
        return "nerf"
    if SAYS_MOVE.search(ctx):
        return "rework"

    seen = {c.get("verdict") for g in entry.get("groups", [])
            for c in g.get("changes", []) if c.get("verdict")}
    if seen == {"buff"}:
        return "buff"
    if seen == {"nerf"}:
        return "nerf"
    return "rework"


def enrich(notes: dict) -> dict:
    """The baked notes with gist, segments and verdict added. Non-destructive: the
    original `context`, `from` and `to` are all still there, because the derived
    reading is a reading and the source is the source."""
    for section in notes.get("sections", []):
        for entry in section.get("entries", []):
            entry["gist"] = gist(entry.get("context"), entry.get("name", ""))
            for group in entry.get("groups", []):
                for c in group.get("changes", []):
                    if "from" in c and "to" in c:
                        segs = compare(c.get("field", ""), c["from"], c["to"])
                        c["segments"] = segs
                        c["verdict"] = _row_dir(segs)
            entry["triage"] = triage(entry)
    return notes


# ── self-check ─────────────────────────────────────────────────────────────

def demo() -> None:
    g = gist("We are continuing to monitor Azir, especially as players continue "
             "to pick up Press The Attack as his optimal keystone. For now "
             "however, we are going to give him a moderate buff to his laning "
             "to help him out.", "Azir")
    assert "PTA" in g, g
    assert "We are" not in g and "we are" not in g, g
    assert "help him out" not in g, g
    assert len(g) < 150, g

    # deletion never invents: every word of the gist came from the source
    src = ("Gwen has remained slightly weak since her nerfs earlier this year. "
           "We are buffing her passive sustain back up towards where it has "
           "previously been.")
    out = gist(src, "Gwen")
    for w in re.findall(r"[a-z]{4,}", out.lower()):
        assert w in src.lower(), (w, out)

    # each number is compared with its opposite number and nothing else
    s = compare("Damage", "60 / 80 / 100 / 120 / 140 (+35 / 40 / 45 / 50 / 55% AP)",
                          "75 / 95 / 115 / 135 / 155 (+35 / 40 / 45 / 50 / 55% AP)")
    moved = [(x["old"], x["new"], x["v"]) for x in s if x["t"] == "chg"]
    assert moved == [("60", "75", "buff"), ("80", "95", "buff"),
                     ("100", "115", "buff"), ("120", "135", "buff"),
                     ("140", "155", "buff")], moved
    assert "".join(x["s"] for x in s if x["t"] == "same").count("AP") == 1

    # nothing is invented and nothing is dropped: the segments rebuild both sides
    for a, b in [("40 / 75 / 110 (+22.5% AP)", "40 / 80 / 120 (+25% AP)"),
                 ("3, increased to 12 on champions", "4, increased to 10 on champions"),
                 ("20 / 25 / 30 / 35 / 40%",
                  "20 / 23 / 26 / 29 / 32% (+8% per 1000 bonus Health)")]:
        segs = compare("Damage", a, b)
        assert "".join(x.get("s", x.get("old", "")) for x in segs
                       if x["t"] != "add") == a, (a, segs)
        assert "".join(x.get("s", x.get("new", "")) for x in segs) == b, (b, segs)

    # a bracket is never cut in half - the numbers are what move, the text around
    # them is what stays, so `(+22.5%` can no longer be one side of a comparison
    for x in compare("Damage", "40 / 75 / 110 (+22.5% AP)", "40 / 80 / 120 (+25% AP)"):
        if x["t"] == "chg":
            assert "(" not in x["old"] and "[" not in x["old"], x

    # the read Sam sent this back for: rank 1 up, ranks 2 and 3 down
    belveth = compare("True Form Total Attack Speed", "5 / 15 / 25%", "6 / 13 / 20%")
    assert [(x["old"], x["new"], x["v"]) for x in belveth if x["t"] == "chg"] == [
        ("5", "6", "buff"), ("15", "13", "nerf"), ("25", "20", "nerf")], belveth
    assert change_verdict("True Form Total Attack Speed",
                          "5 / 15 / 25%", "6 / 13 / 20%") == "mixed"

    # ... and Nasus, where the two numbers are two different quantities
    nasus = compare("Stacks", "3, increased to 12 on champions / large minions / monsters",
                              "4, increased to 10 on champions / large minions / monsters")
    assert [(x["old"], x["new"], x["v"]) for x in nasus if x["t"] == "chg"] == [
        ("3", "4", "buff"), ("12", "10", "nerf")], nasus

    # a range is one quantity, not two comparisons with a hyphen between them
    rng = compare("Healing", "capped to 10-25 (based on level)",
                             "capped to 12-40 (based on level)")
    assert [(x["old"], x["new"]) for x in rng if x["t"] == "chg"] == [("10-25", "12-40")], rng

    # a value equal on both sides is not a change and gets no colour
    assert all(x["t"] == "same" or x["old"] != x["new"]
               for x in compare("Damage", "40 / 75", "40 / 80"))

    # direction, including the field where up is down
    assert change_verdict("Damage", "40", "45") == "buff"
    assert change_verdict("Cooldown", "15 / 14 / 13", "12 / 11 / 10") == "buff"
    assert change_verdict("Cooldown", "12", "15") == "nerf"
    assert change_verdict("Health", "400", "450") == "buff"
    # the read that started all this: Sundered Sky's healing went DOWN
    assert change_verdict("Healing",
                          "[100% Melee || 50% Ranged] Base Attack Damage + 6% Missing Health",
                          "[90% Melee || 45% Ranged] Base Attack Damage + 4% Missing Health") == "nerf"
    # shape changed, not the value: no colour rather than a wrong one, and no
    # pretence that a per-number reading of it would mean anything
    shape = compare("Fervor Move Speed", "20 for 2s", "[20 Melee || 10 Ranged] for 2s")
    assert len(shape) == 1 and shape[0]["v"] is None, shape
    assert change_verdict("Affected", "none here", "none here either") is None
    # four ranks became three. A diff would align the shared "14" and call rank 2
    # unchanged; the run pairing extends the shorter curve with its own last
    # value instead, so the levels the new curve stopped naming keep the value
    # it left them at. Three buffs and, at 19+, a NERF - which is the half of
    # this change its own paragraph does not mention.
    curve = compare("Cooldown", "18 / 14 / 10 / 6s (levels 1 / 7 / 13 / 19)",
                                "14 / 11 / 8s (levels 1 / 7 / 13)")
    assert [(x["old"], x["new"], x["v"]) for x in curve if x["t"] == "chg"] == [
        ("18", "14", "buff"), ("14", "11", "buff"),
        ("10", "8", "buff"), ("6", "8", "nerf")], curve
    # the wider annotation is the one kept, and it is CONTEXT, not an addition:
    # its numbers are level indices, and tinting them green says the levels
    # themselves got better
    assert curve[-1] == {"t": "same", "s": "s (levels 1 / 7 / 13 / 19)"}, curve

    # a flat value is a curve that does not move, so it is broadcast across the
    # bands of the one it is being compared with. Camille's shield: weaker until
    # 13, level with it at 13, stronger after - "weaker shield early, more often"
    shield = compare("Shield", "20% Maximum Health",
                     "10 / 15 / 20 / 25% Maximum Health (levels 1 / 7 / 13 / 19)")
    assert [(x["old"], x["new"], x["v"]) for x in shield if x["t"] == "chg"] == [
        ("20", "10", "nerf"), ("20", "15", "nerf"), ("20", "25", "buff")], shield
    assert change_verdict("Shield", "20% Maximum Health",
                          "10 / 15 / 20 / 25% Maximum Health "
                          "(levels 1 / 7 / 13 / 19)") == "mixed"
    # broadcast reads the FIELD, not the direction of the list: a mana cost
    # gaining a per-rank curve above its flat value is a nerf at every new rank
    assert [x["v"] for x in compare("Mana Cost", "55", "55 / 60 / 65 / 70 / 75")
            if x["t"] == "chg"] == ["nerf"] * 4

    # one run inside a row can be flat while another gains a curve, and each is
    # read on its own. Poppy Q: the bonus-AD ratio dropped AND the target-health
    # scaling became a curve topping out at the old flat value - a strict nerf
    # at every rank but the last, which is what Sam called it
    poppy = compare("Damage",
        "30 / 55 / 80 / 105 / 130 (+100% bonus Attack Damage) "
        "(+9% Target Maximum Health), twice",
        "30 / 55 / 80 / 105 / 130 (+75% bonus Attack Damage) "
        "(+7 / 7.5 / 8 / 8.5 / 9% Target Maximum Health), twice")
    assert [(x["old"], x["new"]) for x in poppy if x["t"] == "chg"] == [
        ("100", "75"), ("9", "7"), ("9", "7.5"), ("9", "8"), ("9", "8.5")], poppy
    assert {x["v"] for x in poppy if x["t"] == "chg"} == {"nerf"}, poppy

    # a run that cannot be paired takes only ITSELF out of the reading: the row
    # still prints its unchanged text, and the runs beside it still read
    local = compare("Passive Gold Per 5 Seconds",
                    "8 / 10.5 / 11.5 / 13 at 1 / 10 / 15 / 25 minutes",
                    "10.5 / 11.5 / 13 at 1 / 15 / 25 minutes")
    assert [x["t"] for x in local] == ["chg", "same", "chg", "same"], local
    assert all(x["v"] is None for x in local if x["t"] == "chg"), local

    # ... and the row still falls back whole when the text BETWEEN the runs is
    # what moved, because then there is no run to line up against a run
    quest = compare("Stack Consumption On Champion",
                    "22 Melee || 20 Ranged and 24 Melee || 22 Ranged", "18 and 21")
    assert len(quest) == 1 and quest[0]["v"] is None, quest

    # the badge reads Riot's own words before it reads the arithmetic
    assert triage({"context": "We are buffing her passive sustain."}) == "buff"
    assert triage({"context": "we are also taking the time to nerf down mid lane"}) == "nerf"
    assert triage({"context": "looking to nerf her support roaming power while "
                              "buffing her top lane"}) == "rework"
    assert triage({"context": "we are adjusting his Q stack generation"}) == "rework"
    # no words at all: fall back to the changes
    assert triage({"context": "Sterak's is a much healthier fit.",
                   "groups": [{"changes": [{"verdict": "buff"}]}]}) == "buff"

    print("notes_read: ok")


if __name__ == "__main__":
    demo()
