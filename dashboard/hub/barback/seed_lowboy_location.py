#!/usr/bin/env python3
"""Seed storage locations for the lowboy_fill products into `ingredient_location`.

The low boy fill list says WHERE A PRODUCT GOES (which low boy door and zone).
The sweep needs the opposite: where the product is COLLECTED FROM, so a restock
can be walked one area at a time instead of running back and forth.

Every location below is read off the storage map in work.db `storage_note` — the
same map the /batch storage tab renders. Where the map names a category rather
than the product ("Beer", "Wine", "Bottled alcohol"), the products in that
category inherit it. Nothing here is guessed from the product name alone: an
item the map does not place is left OUT of this table entirely, so it surfaces
in the sweep's Unsorted bucket where Sam can assign it by tapping, rather
than being silently walked to the wrong room.

Re-runnable: DELETEs the rows it owns, then re-INSERTs.
Run from this folder:  PYTHONPATH=<repo>/dashboard python3 seed_lowboy_location.py
Add --dry to print without writing.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # dashboard/, for vault_path
from vault_path import vault_root

_WORK_DB = vault_root() / "data" / "work.db"

# product (must match checklist_template_item.text) -> storage-map location.
# Location strings mirror the storage_note headings verbatim.
LOCATIONS: dict[str, str] = {
    # ── Fridge 1 · Top (beers) → map: Right fridge, bottom row, "Beer" ──
    "Super Hero Sidekicks": "Right fridge · bottom row",
    "Baby Jasmine Lager": "Right fridge · bottom row",
    "Oolong Kolsh": "Right fridge · bottom row",
    "Neon City": "Right fridge · bottom row",
    "Athletic": "Right fridge · bottom row",
    "Tsingtao": "Right fridge · bottom row",
    # ── Fridge 1 · Middle (garnishes + foams) ──
    "Sesame Brittle": "Lowboy · top left",
    "Truffle Chocolate": "Lowboy · top left",          # map: "Chocolate truffle"
    "Lychee": "Left metal shelf · top shelf",
    "Longan": "Left metal shelf · top shelf",
    "CBM Jello": "Left fridge · second row",           # map: "Che ba mau jello"
    "Cucumbers": "Right fridge · second row",
    "Olives": "Left fridge · bottom row",
    "Salted Coconut Foam": "Lowboy · top right",
    "Condensed Milk Cold Foam": "Lowboy · top right",
    "Boba Foam": "Lowboy · top right",
    # ── Fridge 1 · Bottom (syrups, N/A batches, fresh quarts) ──
    "Black Sesame": "Lowboy · bottom right",
    "Coconut Syrup": "Lowboy · bottom right",
    "Demerara": "Lowboy · bottom right",
    "Toasted Coco": "Lowboy · bottom right",           # map: "Toasted coconut water"
    "Coffee": "Lowboy · bottom right",
    "Simple Syrup": "Lowboy · top right",
    "Tamarind": "Lowboy · bottom left",                # map: "Tamarind agave"
    "Leaf Me Alone": "Right fridge · top row",
    "Golden Hour": "Right fridge · top row",
    "Egg White": "Keg fridge",                         # map: "Eggs"
    "Raspberry Syrup": "Front freezer shelf",          # fresh made off the frozen raspberries
    "Lime": "Keg fridge",                              # whole fruit, juiced fresh
    "Lemon": "Keg fridge",
    "Pineapple": "Keg fridge",
    # ── Fridge 2 · Top (sodas, sparklers) ──
    "Club Soda": "Bar well",
    "Ginger Beer": "Back rack",                        # Topo Chico
    "Ginger Ale": "Back rack",                         # Fentimans
    "Tonic Water": "Back rack",                        # Fentimans
    "Matcha Lemonade": "Keg fridge · on top",          # Lucky Ox
    "Salted Lemonade": "Keg fridge · on top",          # Lucky Ox
    "Pandan Coconut": "Keg fridge · on top",           # Lucky Ox
    # ── Fridge 2 · Bottom (batches) — every one is named on the map ──
    "Bitter Remedy": "Right fridge · top row",         # map: "Bitter melon"; prebatched
    "Macau Flip": "Right fridge · top row",
    "Sorrel": "Right fridge · top row",
    "Breakfast": "Right fridge · second row",          # map: "Breakfast tea shot"
    "One Inch Punch": "Left fridge · second row",
    "Che Ba Mau": "Left fridge · second row",
    "Thairish Tea": "Left fridge · second row",
    "House": "Left fridge · top row",                  # map: "House shot (JT SHOT)"
    "Tea Killah": "Left fridge · top row",             # map: "Teakillah"
    "Lychee Martini": "Left fridge · top row",
    "Juniper": "Left fridge · bottom row",                # map: "Juniper roku bottle"
    "Ube Daiquiri": "Left fridge · bottom row",        # map: "Ube daquiri"
    # ── Fridge 3 · Top / Fridge 4 · Top (miscellaneous) ──
    "Whole Egg": "Keg fridge",
    "Coconut Water": "Keg fridge · on top",
    "Sprite": "Back rack",
    "Canada Dry": "Back rack",
    "Coke": "Back rack",
    "Diet Coke": "Back rack",
    "Lychee Can": "Left metal shelf · top shelf",
    "Longan Can": "Left metal shelf · top shelf",
    "Wakamomo Peaches": "Back rack · middle shelf",    # by the Fentimans
    # ── Fridge 3 · Bottom (prepped service bottles) ──
    "Peachy River": "Alcohol drawer",                  # behind the bar, Mizu bottles, green tape
    "Chrysanthemum Kiss": "Right fridge · second row",
    "Pandan Colada": "Right fridge · second row",
    # ── Fridge 4 · Bottom (wines) → map: Right fridge, bottom row, "Wine" ──
    "Sauvignon Blanc": "Right fridge · bottom row",
    "Rosé": "Right fridge · bottom row",
    "Cabernet Sauvignon": "Right fridge · bottom row",
    "Prosecco": "Right fridge · bottom row",
    # ── Fridge 4 · Bottom (fortified + vermouth) → the flattened alcohol room ──
    "Vina AB": "Alcohol room",                         # Lustau Viña AB Amontillado
    "Lillet": "Alcohol room",                          # Lillet Blanc
    "Dry Vermouth": "Alcohol room",                    # Bottega Cinzano — Extra Dry
    "Sweet Vermouth": "Alcohol room",                  # Cinzano Rosso / Carpano Antica
}

# Deliberately absent, so they land in the sweep's Unsorted bucket rather than a
# wrong room: Onions, Peaches, Cherries, Heavy Cream, Sealed Garnishes, Flowers
# (Sam has not placed these — asked 2026-08-17), plus Yuzu, Dirty Martini and
# Pretty in Pink, added or orphaned by the 2026-09-02 sweep. Pretty in Pink used
# to read "Alcohol room · back shelf, bottom level"; that shelf no longer exists
# (the room was flattened to one list on 2026-09-02) and the bottle is not among
# its 88 entries, so the string was dropped rather than pointed at a near-match.
# Peachy River moved the other way in the same sweep: out of the alcohol room
# record and into the **alcohol drawer** behind the bar.
#
# Naming, settled 2026-08-17 against `storage_note`: the map's "Front room" is
# what the storage tree calls Garbage Room, and its "Back room" is what the tree
# calls Kitchen. "Back fridge" and "Keg fridge" are one fridge — the strings here
# use **Keg fridge**, Sam's own word, so the sweep walks it as one stop.
# "Keg fridge · on top" is a separate stop: the three Lucky Ox sparklers and the
# canned coconut water sit on the lid, not inside.


def seed(dry: bool = False) -> None:
    conn = sqlite3.connect(_WORK_DB)
    conn.row_factory = sqlite3.Row
    try:
        wanted = {
            r["text"]
            for r in conn.execute(
                "SELECT i.text FROM checklist_template_item i "
                "JOIN checklist_template t ON t.id = i.template_id "
                "WHERE t.key = 'lowboy_fill'"
            )
        }
        unknown = sorted(set(LOCATIONS) - wanted)
        for name in unknown:
            print(f"  WARN: '{name}' is not a lowboy_fill product")
        if dry:
            for name, loc in sorted(LOCATIONS.items(), key=lambda kv: (kv[1], kv[0])):
                print(f"  {name:24s} -> {loc}")
        else:
            # Delete by the note this seeder owns, not by the keys about to be
            # written: deleting only what we re-insert leaves a row behind every
            # time a product is renamed or dropped from LOCATIONS. Six such
            # orphans had accumulated by 2026-09-02 ("Cold Foams", "Rose",
            # "Upside Dawn (NA)", ...), one of them pointing at a shelf the
            # alcohol-room flatten had deleted.
            conn.execute("DELETE FROM ingredient_location WHERE note = 'lowboy fill'")
            conn.executemany(
                "INSERT INTO ingredient_location(name, location, note) VALUES (?,?,?)",
                [(n, loc, "lowboy fill") for n, loc in LOCATIONS.items()],
            )
            conn.commit()
        unplaced = sorted(wanted - set(LOCATIONS))
    finally:
        conn.close()
    verb = "would seed" if dry else "seeded"
    print(f"{verb} {len(LOCATIONS)} of {len(LOCATIONS) + len(unplaced)} lowboy products.")
    if unplaced:
        print(f"\nUNPLACED — {len(unplaced)} (these show under Unsorted in the sweep):")
        for u in unplaced:
            print(f"  - {u}")


if __name__ == "__main__":
    seed(dry="--dry" in sys.argv)
