"""The one grocery list every trip shares, and the amenity read that marks items covered.

Most of an arrival run is the same run every time, so there is one list. What
changes per trip is which extras section shows (picked per trip on the grocery
tab, never guessed) and what the booked
listing already stocks (which items are marked covered).

The list lives in checklists.db like every other checklist on the Hub (source
`base:trip:grocery`), because Sam's rule is that /checklists is the one store
and every other surface is a door onto it. `ITEMS` below is the SEED for that list
and the amenity vocabulary it is read with, not a second copy. Edit the list on
/checklists and the edit stands; nothing here writes over it. An item added by
hand has no `covered` phrases, so it is never marked covered, which is the safe
direction to fail.

── The one rule ──────────────────────────────────────────────────────────────────
housing.amenities stores ONLY what the listing HAS, one amenity per line, with no
"not included" block (verified against the Arvada listing, 1840 chars, 11 sections).
Against a COMPLETE positive list, "remove what the amenities already cover" and "add
back what they say they don't have" are the same operation read in two directions:
an item is on the run unless the listing names it. So there is one mechanism here,
not two. Shampoo is on the visit list precisely so it appears for the houses that
do not stock it, and is marked covered for the ones that do.

That equivalence holds only while the amenity blob is complete. An empty one (every
hotel row, and any listing nobody has scraped) covers nothing and the whole list
comes through — the honest answer, since absence of evidence is not evidence the
kitchen is bare.
"""
from __future__ import annotations

import re

# ── The list ──────────────────────────────────────────────────────────────────
#
# ONE list for every trip. Each trip used to get its own copy seeded from one of
# three shape lists, which meant a hand edit on one trip never reached the next.
# Now the list is shared and a trip keeps only its ticks (trips.packing_ticks, the
# same table the packing tab uses). The rave and snowboarding extras sit in their
# own sections on that one list and only show on a trip switched to them.
#
# What is NOT here matters as much as what is. The three activity checklists
# (Snowboarding, Rave, Beach) are PACKING lists: sunscreen, lip balm, Liquid IV,
# a first aid kit are things Sam carries, and a grocery run that re-buys them
# is a run that wastes money on landing. This list is the consumables you
# cannot fly with or would not carry: bulk water, ice, food, and the household
# stock a group burns through in four days.
#
# `covered` is the amenity phrase(s) that make an item pointless. No `covered`
# means nothing a listing can say will remove it: bottled water is never covered
# by "Hot water".

NAME = "Trip Grocery"
BLURB = ("The arrival run for every trip. The Rave and Snowboarding sections only "
         "show on trips of that kind; ticks are kept per trip.")

ITEMS: list[tuple] = [
    # Fridge
    ("Fridge", "Eggs", "1 dozen", "", ()),
    ("Fridge", "Milk or creamer", "", "", ()),
    ("Fridge", "Butter", "", "", ()),
    ("Fridge", "Bread", "", "", ()),
    ("Fridge", "Deli meat and sliced cheese", "", "lunch without a second store run", ()),
    ("Fridge", "Yogurt", "", "", ()),
    ("Fridge", "Fruit", "", "bananas and apples travel; berries do not", ()),
    ("Fridge", "Salad greens", "", "", ()),
    # Pantry
    ("Pantry", "Coffee", "", "", ("coffee",)),
    ("Pantry", "Cooking oil, salt and pepper", "", "", ("cooking basics",)),
    ("Pantry", "Pasta and sauce", "", "the one-pot night that saves a dinner out", ()),
    ("Pantry", "Snacks", "", "chips, nuts, granola bars", ()),
    # Drinks
    ("Drinks", "Bottled water", "1 flat", "", ()),
    ("Drinks", "Whatever the house drinks", "", "beer, seltzer, juice", ()),
    # Household
    ("Household", "Paper towels", "", "", ("paper towels",)),
    ("Household", "Trash bags", "", "the single most common thing a listing runs out of", ()),
    ("Household", "Dish soap and a sponge", "", "", ()),
    ("Household", "Toilet paper", "", "hosts leave a starter roll, not a week's worth", ("toilet paper",)),
    ("Household", "Foil or ziplocs", "", "for leftovers and the drive home", ()),
    # Care
    ("Care", "Shampoo", "", "", ("shampoo",)),
    ("Care", "Body wash", "", "", ("body soap", "shower gel")),
    ("Care", "Hand soap", "", "", ("soap",)),
    ("Care", "Distilled water", "2 gal", "for the CPAP", ()),
    # Rave extras: hydration, and fuel you can eat at 4am
    ("Rave", "More bottled water", "1 gal per person per day", "the festival's own water is the expensive way to buy it", ()),
    ("Rave", "Electrolyte packets", "", "a box, not a sleeve", ()),
    ("Rave", "Sports drinks", "", "Gatorade or Pedialyte for the mornings after", ()),
    ("Rave", "Ice", "", "buy twice what looks like enough", ()),
    ("Rave", "Energy drinks", "", "", ()),
    ("Rave", "Bagels and peanut butter", "", "eaten standing up on the way out the door", ()),
    ("Rave", "Granola or protein bars", "", "the thing that goes in the bag", ()),
    ("Rave", "Frozen pizza", "", "the 4am meal nobody wants to cook", ()),
    ("Rave", "Ibuprofen", "", "", ()),
    ("Rave", "Baby wipes", "", "", ()),
    ("Rave", "Cups", "", "", ()),
    # Snowboarding extras: pocket fuel, a hot dinner, altitude hydration
    ("Snowboarding", "Granola or protein bars", "", "goes in the jacket, eaten on the lift", ()),
    ("Snowboarding", "Trail mix and jerky", "", "", ()),
    ("Snowboarding", "Instant oatmeal", "", "", ()),
    ("Snowboarding", "Bacon", "", "the breakfast that gets you out by first chair", ()),
    ("Snowboarding", "Soup or chili makings", "", "the pot that is waiting when you get back", ()),
    ("Snowboarding", "Frozen pizza", "", "", ()),
    ("Snowboarding", "Electrolyte packets", "", "altitude dehydrates you faster than the cold suggests", ()),
    ("Snowboarding", "Hot cocoa or tea", "", "", ()),
    ("Snowboarding", "Ibuprofen", "", "", ()),
    ("Snowboarding", "Ziplocs", "", "wet gloves and liners", ()),
]

# Section name -> the trip shape it belongs to. Any other section shows on every
# trip, so a section Sam adds on /checklists is never hidden by accident.
EXTRA_SECTIONS = {"rave": "rave", "snowboarding": "snowboarding"}
SHAPES = ("visit", "rave", "snowboarding")

# A hotel room is not a kitchen, and that is the other thing a listing says about
# what to buy. Seeding eggs, pasta sauce and a sponge into a Hyatt stay is the same
# class of mistake as buying shampoo the bathroom already has, so the items that
# need a stove, an oven or a sink are marked covered when the stay is a hotel.
#
# Kept deliberately as an explicit list of item texts rather than a per-item flag:
# it is short, it reads as one answer to one question, and an item Sam adds by
# hand is never in it, so nothing he typed is ever marked off.
NEEDS_KITCHEN = frozenset({
    "Eggs", "Butter", "Milk or creamer", "Pasta and sauce", "Frozen pizza",
    "Cooking oil, salt and pepper", "Dish soap and a sponge", "Foil or ziplocs",
    "Soup or chili makings", "Bacon", "Salad greens",
})


BASE_SOURCE = "base:trip:grocery"
BASE_CATEGORY = "grocery base"


def for_shape(items: list[dict], shape: str) -> list[dict]:
    """The shared list minus the extras sections that belong to another shape."""
    return [i for i in items
            if EXTRA_SECTIONS.get(_norm(i.get("section", "")), shape) == shape]


def covered_phrases() -> dict[str, tuple[str, ...]]:
    """item text (normalised) -> the amenity phrases that would make it pointless."""
    return {_norm(text): phrases
            for _sec, text, _qty, _note, phrases in ITEMS if phrases}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# ── Reading a listing ─────────────────────────────────────────────────────────


def amenity_tokens(amenities: str) -> set[str]:
    """Every amenity a listing names, as comparable tokens.

    Line-oriented and delimiter-aware rather than a substring scan over the blob,
    because the blob makes two mistakes that both cost money. "Coffee maker: drip
    coffee maker, french press, Keurig" contains the substring "coffee" while
    stocking no coffee, so a substring rule drops the grounds from a house that
    has only a machine. And "Essentials / Towels, bed sheets, soap, and toilet
    paper" names toilet paper only INSIDE another amenity's detail line, so a
    whole-line rule misses a thing the house genuinely has.

    So: each line splits on ":" into a head and its detail, and the detail splits
    on commas and "and". Both sides become tokens. "coffee maker" is a token,
    "coffee" is not; "toilet paper" and "soap" both are.
    """
    tokens: set[str] = set()
    for line in (amenities or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if not line:
            continue
        # The comma split runs over the WHOLE line, not just the part after a
        # colon: Airbnb writes an amenity's detail on its own line as often as it
        # writes it after a colon ("Essentials" / "Towels, bed sheets, soap, and
        # toilet paper" is two lines and no colon), and only splitting the detail
        # missed every amenity written that way.
        parts = re.split(r",|\band\b|:", line)
        # An em-dash suffix is Airbnb's own qualifier ("Free washer – In unit"),
        # so the token is the amenity, not the qualifier.
        for part in parts:
            tok = _norm(re.split(r"–|—| - ", part)[0])
            if tok:
                tokens.add(tok)
    return tokens


def trim(items: list[dict], amenities: str,
         stay_type: str = "") -> tuple[list[dict], list[str]]:
    """Split the list into what to buy and what the stay already answers for.

    Returns (keep, covered_names). Two reasons an item comes off, and they are
    independent: the listing NAMES it (so it is already there), or the stay has no
    kitchen to use it in.

    An empty amenity blob covers nothing on the first count — a room nobody scraped
    and a house nobody scraped look identical here, and guessing at a bare kitchen
    is how you arrive without salt. `stay_type` is a different signal and is
    trusted on its own: "hotel" is recorded at booking, not scraped.
    """
    tokens = amenity_tokens(amenities)
    hotel = (stay_type or "").strip().lower() == "hotel"
    if not tokens and not hotel:
        return list(items), []
    phrases = covered_phrases()
    keep, covered = [], []
    for it in items:
        text = it.get("text", "")
        want = phrases.get(_norm(text), ())
        if want and any(p in tokens for p in want):
            covered.append(text)
        elif hotel and text in NEEDS_KITCHEN:
            covered.append(text)
        else:
            keep.append(it)
    return keep, covered


# ── Which stay a trip is in ───────────────────────────────────────────────────

# The same three the board treats as committed (trips-cost.js COMMITTED). A stay
# paid for is as booked as one marked booked.
_COMMITTED = ("booked", "confirmed", "paid")


def booked_stay(trip: dict) -> dict | None:
    """The stay the trip is actually committed to, the same one the board draws.

    A trip carries every candidate it ever considered (El Salvador holds six), so
    reading housing[0] would scan the amenities of a hotel nobody booked.
    """
    for h in trip.get("housing") or []:
        if (h.get("status") or "").lower() in _COMMITTED:
            return h
    return None
