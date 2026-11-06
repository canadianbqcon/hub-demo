#!/usr/bin/env python3
"""
Seed ingredient_location table.

Run without --seed to print the proposed mapping for review.
Run with --seed to actually insert/upsert into work.db.
"""

import sys
import pathlib
import sqlite3
from contextlib import closing

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2])
)  # dashboard/, for vault_path
from vault_path import vault_root

DB_PATH = vault_root() / "data" / "work.db"

# ---------------------------------------------------------------------------
# Location dict — inferred from storage map + common sense.
# Location strings mirror the storage map headings.
# FLAGGED entries = uncertain; review before seeding.
# Empty string = unknown; must be filled before seeding.
# ---------------------------------------------------------------------------

# fmt: off
LOCATIONS: dict[str, tuple[str, str | None]] = {
    # key: (location, note)  — note is informational only, not stored unless useful

    # ── FINISHED BATCHES ────────────────────────────────────────────────────
    "batch (chrysanthemum kiss)":                                     ("Right fridge · second row", "haku bottle"),
    "batch (golden hour / chrysanthemum tea / chrysanthemum honey)":  ("Right fridge · top row",    None),
    "batch (leaf me alone / jasmine green tea / pandan)":             ("Right fridge · top row",    None),
    "batch (macau flip)":                                             ("Right fridge · top row",    None),
    "batch (ming river baijiu / hendricks / pathfinder n/a amaro / banana liqueur)":
                                                                      ("Right fridge · second row", "dragons den batch (DD)"),
    "batch (pandan colada / ten to one caribbean dark rum)":          ("Right fridge · second row", "ten to one bottle"),
    "batch (peachy river / mizu sochu green tea / ming river)":       ("", "FLAGGED: not on storage map — which fridge?"),
    "batch (pretty in pink)":                                         ("", "FLAGGED: not on storage map — which fridge?"),
    "batch (pu'er ginseng infused redemption rye / remy / cointreau)":("", "FLAGGED: not on storage map — left fridge second row (clarified)?"),
    "batch (the sorrel)":                                             ("Right fridge · top row",    None),
    "batch (the juniper)":                                               ("Left fridge · bottom row",  "juniper roku bottle"),

    # ── BACK FRIDGE ─────────────────────────────────────────────────────────
    "coconut water":       ("Back fridge",  None),
    "fresh coconut water": ("Back fridge",  None),
    "milk":                ("Back fridge",  None),
    "whole milk":          ("Back fridge",  None),
    "egg white":           ("Back fridge",  "eggs in back fridge"),
    "whole egg":           ("Back fridge",  "eggs in back fridge"),
    "butter":              ("Back fridge",  "FLAGGED: not on storage map — back fridge assumed"),

    # ── LEFT FRIDGE — juices go upstairs ───────────────────────────────────
    "sugar cane":          ("Left fridge",  "sugar cane juice in bag"),
    "sugarcane juice":     ("Left fridge",  "sugar cane juice in bag"),
    "lemon juice":         ("Left fridge",  "all juices upstairs"),
    "lime juice":          ("Left fridge",  "all juices upstairs"),
    "orange juice":        ("Left fridge",  "all juices upstairs"),
    "pineapple juice":     ("Left fridge",  "all juices upstairs"),
    "lychee puree":        ("Left fridge",  "FLAGGED: juice/puree — upstairs assumed"),

    # Che ba mau layers live in the left fridge second row (clarified section)
    "l1: water/sugar/agar/pandan extract": ("Left fridge · second row", "che ba mau layer"),
    "l2: water/sugar/agar/mungbean":       ("Left fridge · second row", "che ba mau layer"),
    "l3: water/sugar/agar/split red bean": ("Left fridge · second row", "che ba mau layer"),

    # ── LOWBOY · TOP LEFT ───────────────────────────────────────────────────
    "yogurt":              ("Lowboy · top left",    "tub of yogurt"),
    "greek yogurt":        ("Lowboy · top left",    "tub of yogurt"),
    "pe yogurt":           ("Lowboy · top left",    "passion fruit yogurt"),
    "spicy tincture":      ("Lowboy · top left",    None),
    "egg roll cookies":    ("Lowboy · top left",    "FLAGGED: garnish area assumed"),
    "spicy squid snack toki": ("Lowboy · top left", "FLAGGED: garnish area assumed"),

    # ── LOWBOY · BOTTOM LEFT ────────────────────────────────────────────────
    "star anise vanilla syrup": ("Lowboy · bottom left", None),
    "chrysanthemum honey":      ("Lowboy · bottom left", None),
    "tamarind agave":           ("Lowboy · bottom left", None),

    # ── LOWBOY · BOTTOM RIGHT ───────────────────────────────────────────────
    "coffee":                    ("Lowboy · bottom right", None),
    "vietnamese coffee":         ("Lowboy · bottom right", "coffee"),
    "raspberry lemongrass syrup":("Lowboy · bottom right", "lemongrass — raspberry added, not prebatched"),
    "toasted coconut milk":      ("Lowboy · bottom right", "toasted coconut water slot"),
    "black sesame syrup":        ("Lowboy · bottom right", None),
    "demerara":                  ("Lowboy · bottom right", "brown sugar syrup"),
    "coconut syrup":             ("Lowboy · bottom right", None),
    "stout syrup":               ("Lowboy · bottom right", "FLAGGED: with other syrups assumed"),
    "citrus cordial":            ("Lowboy · bottom right", "FLAGGED: or left fridge?"),
    "citrus cordial (lemon/lime/orange/sugar)": ("Lowboy · bottom right", "FLAGGED: or left fridge?"),
    "ginger scallion syrup":     ("Lowboy · bottom right", "FLAGGED: which lowboy section?"),
    "pandan syrup":              ("Lowboy · bottom right", "FLAGGED: with other syrups assumed"),

    # ── LOWBOY · TOP RIGHT (canisters) ──────────────────────────────────────
    "boba":                ("Lowboy · top right", "boba water / canister"),
    "simple":              ("Lowboy · top right", "simple syrup"),
    "simple syrup":        ("Lowboy · top right", None),
    "vanilla syrup":       ("Lowboy · top right", "FLAGGED: with other syrups assumed"),

    # ── LOWBOY (section unclear) ────────────────────────────────────────────
    "red bean orgeat":     ("Lowboy", "FLAGGED: which section?"),

    # ── LEFT METAL SHELF · TOP ──────────────────────────────────────────────
    "drained longan":      ("Left metal shelf · top shelf", "longan tin"),
    "jackfruit":           ("Left metal shelf · top shelf", None),
    "condensed milk":      ("Left metal shelf · top shelf", None),
    "evaporated milk":     ("Left metal shelf · top shelf", None),
    "mung bean":           ("Left metal shelf · top shelf", "FLAGGED: or kitchen table?"),
    "split mung bean":     ("Left metal shelf · top shelf", "FLAGGED: or kitchen table?"),
    "red bean":            ("Left metal shelf · top shelf", "FLAGGED: or bottom shelf?"),
    "red bean, toasted":   ("Left metal shelf · top shelf", "FLAGGED: or kitchen table?"),
    "goji berries":        ("Left metal shelf · top shelf", "FLAGGED: top or bottom shelf?"),

    # ── LEFT METAL SHELF · BOTTOM ───────────────────────────────────────────
    "peanut butter":            ("Left metal shelf · bottom shelf", None),
    "coconut milk":             ("Left metal shelf · bottom shelf", None),
    "coco lopez":               ("Left metal shelf · bottom shelf", None),
    "unsweetened coconut":      ("Left metal shelf · bottom shelf", "FLAGGED: with coconut products"),
    "unsweetened shredded coconut": ("Left metal shelf · bottom shelf", "FLAGGED: with coconut products"),
    "coconut shreds":           ("Left metal shelf · bottom shelf", "FLAGGED: with coconut products"),
    "tapioca":                  ("Left metal shelf · bottom shelf", "FLAGGED: boba/tapioca section"),

    # ── KITCHEN TABLE (dried items) ─────────────────────────────────────────
    "dashi":                     ("Kitchen table", "mushroom powder / dashi"),
    "dried shiitake mushroom":   ("Kitchen table", "dashi = mushroom powder"),
    "salt":                      ("Kitchen table", None),
    "coconut oil":               ("Kitchen table", None),
    "maple syrup":               ("Kitchen table", None),
    "ginseng":                   ("Kitchen table", "teas section"),
    "chrysanthemum":             ("Kitchen table", "teas"),
    "chrysanthemum tea":         ("Kitchen table", "teas"),
    "jasmine tea":               ("Kitchen table", "teas"),
    "jasmine green tea":         ("Kitchen table", "teas"),
    "jasmine five spice green tea": ("Kitchen table", "teas — likely pre-infused"),
    "hong kong tea":             ("Kitchen table", "teas"),
    "irish breakfast tea":       ("Kitchen table", "teas"),
    "gunpowder green tea":       ("Kitchen table", "teas"),
    "thai tea leaves":           ("Kitchen table", "teas"),
    "longan tea":                ("Kitchen table", "teas"),
    "pu'erh tea":                ("Kitchen table", "teas"),
    "oolong tea":                ("Kitchen table", "teas"),
    "sugar":                     ("Kitchen table", "white sugar"),
    "palm sugar":                ("Kitchen table", "dried items"),
    "cinnamon sticks":           ("Kitchen table", "spices"),
    "cloves":                    ("Kitchen table", "spices"),
    "star anise":                ("Kitchen table", "spices"),
    "five spice":                ("Kitchen table", "spices"),
    "sichuan peppercorn":        ("Kitchen table", "spices"),
    "vanilla extract":           ("Kitchen table", "extracts"),
    "pandan extract":            ("Kitchen table", "extracts"),
    "ube extract":               ("Kitchen table", "extracts — FLAGGED: confirm"),
    "cocoa powder":              ("Kitchen table", "powders"),
    "ground cinnamon":           ("Kitchen table", "powders / spices"),
    "black sesame, toasted":     ("Kitchen table", "FLAGGED: or left metal shelf?"),
    "chili & garlic":            ("Kitchen table", "FLAGGED: spices/pantry?"),
    "coriander":                 ("Kitchen table", "spices — FLAGGED"),
    "fish sauce":                ("Kitchen table", "FLAGGED: or back room shelf?"),
    "white vinegar":             ("Kitchen table", "FLAGGED: or back room"),
    "oil":                       ("Kitchen table", "coconut oil — FLAGGED: confirm"),
    "pei pa koa":                ("Kitchen table", "FLAGGED: herbal/pantry"),
    "tamarind pulp":             ("Kitchen table", "FLAGGED: or left metal shelf?"),

    # ── FREEZER ─────────────────────────────────────────────────────────────
    "pandan":                    ("Freezer · front shelf", None),
    "pandan leaves":             ("Freezer · front shelf", "pandan"),
    "lemongrass, cut & cleaned": ("Freezer · front shelf", "lemongrass"),

    # ── ALCOHOL ROOM ────────────────────────────────────────────────────────
    "agave":               ("Alcohol room", None),
    "coconut aminos":      ("Alcohol room", None),
    "honey":               ("Alcohol room", None),
    "sugar in the raw":    ("Alcohol room", "sugar on the raw"),

    # ── RIGHT METAL SHELF (opened alcohol) ──────────────────────────────────
    "haku vodka":           ("Right metal shelf", "opened alcohol"),
    "ketel one":            ("Right metal shelf", "opened alcohol"),
    "ketel one (infused)":  ("Right metal shelf", "opened / infused"),
    "roku gin":             ("Right metal shelf", "opened alcohol"),
    "hendricks gin":        ("Right metal shelf", "opened alcohol"),
    "ten to one dark":      ("Right metal shelf", "opened alcohol"),
    "ten to one dark [jackfruit infused, 7day coconut aged]": ("Right metal shelf", "infused, opened"),
    "ten to one dark rum":  ("Right metal shelf", "opened alcohol"),
    "ten to one white rum": ("Right metal shelf", "opened alcohol"),
    "mijenta blanco":       ("Right metal shelf", "opened alcohol"),
    "mijenta tequila":      ("Right metal shelf", "opened alcohol"),
    "mijienta tequila":     ("Right metal shelf", "opened alcohol"),
    "ming river":           ("Right metal shelf", "opened alcohol"),
    "ming river baijiu":    ("Right metal shelf", "opened alcohol"),
    "mizu shochu green tea":("Right metal shelf", "opened alcohol"),
    "amaras verde mezcal":  ("Right metal shelf", "opened alcohol"),
    "thai chili infused montelobos mezcal": ("Right metal shelf", "infused, opened"),
    "amaro nonino":         ("Right metal shelf", "opened alcohol"),
    "see the elephant amaro": ("Right metal shelf", "opened alcohol"),
    "coffee liqueur":       ("Right metal shelf", "opened alcohol"),
    "cointreau":            ("Right metal shelf", "opened alcohol"),
    "st. germain":          ("Right metal shelf", "opened alcohol"),
    "lychee liqueur":       ("Right metal shelf", "opened alcohol"),
    "juliette peach liqueur": ("Right metal shelf", "opened alcohol"),
    "wakamomo peach brine / juliette peach liqueur split": ("Right metal shelf", "opened alcohol"),
    "jasmine verte":        ("Right metal shelf", "opened alcohol"),
    "lilit blanc":          ("Right metal shelf", "opened alcohol"),
    "lilet blanc":          ("Right metal shelf", "opened alcohol"),
    "dry vermouth":         ("Right metal shelf", "opened alcohol"),
    "dry 1757 dry vermouth":("Right metal shelf", "opened alcohol"),
    "sweet vermouth":       ("Right metal shelf", "opened alcohol"),
    "amontillado sherry":   ("Right metal shelf", "opened alcohol"),
    "redemption bourbon":   ("Right metal shelf", "opened alcohol"),
    "redemption rye":       ("Right metal shelf", "opened alcohol"),
    "roe & co irish whiskey": ("Right metal shelf", "opened alcohol"),
    "teeling":              ("Right metal shelf", "opened alcohol"),
    "tullamore dew":        ("Right metal shelf", "opened alcohol"),
    "brown butter washed tullamore dew": ("Right metal shelf", "washed / infused"),
    "remy":                 ("Right metal shelf", "opened alcohol"),
    "tanduay ube coconut rum": ("Right metal shelf", "opened alcohol"),
    "pho spiced light rum": ("Right metal shelf", "opened alcohol"),
    "pierre ferrand dry curacao": ("Right metal shelf", "opened alcohol"),
    "angostura":            ("Right metal shelf", "bitters"),
    "chocolate bitter":     ("Right metal shelf", "bitters"),
    "lyre's agave (non-alc)": ("Right metal shelf", "non-alc spirits"),
    "lyre's dry london (non-alc)": ("Right metal shelf", "non-alc spirits"),
    "lyres agave blanco n/a": ("Right metal shelf", "non-alc spirits"),
    "lyres dry london n/a": ("Right metal shelf", "non-alc spirits"),
    "oolong mijenta tequila": ("Right metal shelf", "infused, opened"),
    "chrysanthemum infused haku": ("Right metal shelf", "infused, opened"),
    "gunpowder green tea infused roku gin": ("Right metal shelf", "infused, opened"),
    "chinola passion fruit": ("Right metal shelf", "FLAGGED: liqueur — or left metal shelf?"),

    # ── RIGHT FRIDGE BOTTOM (beer / wine) ───────────────────────────────────
    "guinness":             ("Right fridge · bottom row", "beer"),
    "cabernet sauvignon":   ("Right fridge · bottom row", "wine"),

    # ── PRODUCE (top of lowboy per notes) ───────────────────────────────────
    "bitter melon":         ("Lowboy · top", "produce"),
    "arugula":              ("Lowboy · top", "produce"),
    "basil":                ("Lowboy · top", "produce"),
    "fennel":               ("Lowboy · top", "produce"),
    "pineapple":            ("Lowboy · top", "produce"),
    "thin-sliced ginger":   ("Lowboy · top", "produce — prep'd"),
    "cut thai chili":       ("Lowboy · top", "produce — prep'd"),
    "cut scallion":         ("Lowboy · top", "produce — prep'd"),
    "plums":                ("Lowboy · top", "produce"),
    "pitted plum":          ("Lowboy · top", "produce"),
    "lemon":                ("Lowboy · top", "produce / citrus"),
    "lime":                 ("Lowboy · top", "produce / citrus"),
    "orange peels (no pith)": ("Lowboy · top", "produce — prep'd"),

    # ── WATER / BAR MIXERS ──────────────────────────────────────────────────
    "hot water":            ("Kitchen", "tap"),
    "warm water":           ("Kitchen", "tap"),
    "water":                ("Kitchen", "tap"),
    "water (to a boil)":    ("Kitchen", "tap / kettle"),
    "club soda":            ("Bar well", "FLAGGED: gun or bottle?"),
    "n/a athletic (clean ice, top)": ("Bar well", "FLAGGED: top of ice bin?"),

    # ── UNKNOWN ─────────────────────────────────────────────────────────────
    "yoshi":                ("", "FLAGGED: unidentified ingredient — ask Sam"),
    "yuzu":                 ("", "FLAGGED: fresh produce or pantry?"),
    "nouc cham":            ("", "FLAGGED: made fresh or pantry?"),
    "black garlic":         ("", "FLAGGED: produce or pantry?"),
}
# fmt: on


def get_all_ingredients(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT LOWER(ingredient) FROM recipe_ingredients ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def print_review(conn: sqlite3.Connection) -> None:
    ingredients = get_all_ingredients(conn)
    flagged: list[tuple[str, str, str]] = []
    unknown: list[str] = []
    mapped: list[tuple[str, str]] = []

    for ing in ingredients:
        entry = LOCATIONS.get(ing)
        if entry is None:
            unknown.append(ing)
        elif not entry[0]:
            unknown.append(ing)
        elif "FLAGGED" in (entry[1] or ""):
            flagged.append((ing, entry[0], entry[1] or ""))
        else:
            mapped.append((ing, entry[0]))

    total = len(ingredients)
    print(f"\n{'=' * 70}")
    print(f"  PROPOSED ingredient_location mapping  ({total} ingredients)")
    print(f"{'=' * 70}")
    print(f"\n  MAPPED ({len(mapped)}) — ready to seed:")
    for ing, loc in mapped:
        print(f"    {ing:<55} {loc}")

    print(f"\n  FLAGGED ({len(flagged)}) — need Sam's call:")
    for ing, loc, note in flagged:
        print(f"    {ing:<55} {loc}")
        print(f"      ↳ {note}")

    print(f"\n  UNKNOWN ({len(unknown)}) — no location inferred:")
    for ing in unknown:
        print(f"    {ing}")

    print(
        f"\n  Summary: {len(mapped)} mapped · {len(flagged)} flagged · {len(unknown)} unknown"
    )
    print(f"{'=' * 70}\n")


def seed(conn: sqlite3.Connection) -> None:
    ingredients = get_all_ingredients(conn)
    seeded = 0
    for ing in ingredients:
        entry = LOCATIONS.get(ing)
        if not entry or not entry[0]:
            continue
        location, note = entry
        conn.execute(
            "INSERT INTO ingredient_location(name, location, note) VALUES(?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET location=excluded.location, note=excluded.note",
            (ing, location, note),
        )
        seeded += 1
    conn.commit()
    print(f"Seeded {seeded} rows into ingredient_location.")
    missing = [i for i in ingredients if i not in LOCATIONS or not LOCATIONS[i][0]]
    if missing:
        print(f"  Still unmapped ({len(missing)}): {missing}")


if __name__ == "__main__":
    # closing() rather than a trailing conn.close(): an exception in seed() or
    # print_review() would otherwise leak the connection and leave the WAL behind.
    with closing(sqlite3.connect(DB_PATH)) as conn:
        if "--seed" in sys.argv:
            seed(conn)
        else:
            print_review(conn)
