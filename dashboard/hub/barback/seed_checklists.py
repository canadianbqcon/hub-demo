"""Seed the barback duty templates (opening + closing) + the stock_check template
header. Idempotent: upsert templates by key, replace their items each run. The
stock_check template carries NO items here — its item set is generated at run
start from work.db + stock_raw_item (see db.generate_stock_items).

Run standalone:  cd dashboard/hub/barback && PYTHONPATH=../.. python seed_checklists.py
"""
from __future__ import annotations

# `from . import db` binds THIS package's db. A bare `import db` does not: ten
# modules in dashboard/hub/ are named db.py, so under a whole-tree pytest run
# whichever one loaded first wins from sys.modules. The fallback keeps the
# standalone `python seed_*.py` entry point in the docstring working, where
# there is no package to be relative to.
try:
    from . import db as barback_db
except ImportError:  # pragma: no cover - standalone script path
    import db as barback_db  # pyright: ignore[reportMissingImports]

# key, name, kind, items[]. Each item: (text, detail, section, deadline, priority).
_TEMPLATES = [
    # Opening stays at the shift-step level. The low-boy fill is its own
    # checklist ("lowboy_fill" below) because item-level restock is a different
    # altitude from "get the bar set up".
    # Order is Sam's own walk-through of the shift (2026-07-29), not a
    # grouping by topic: the bar gets married and set up FIRST as if the
    # bartender were about to pour, and ice comes after that, not on arrival.
    # Sections are the four phases of that walk, in sequence.
    ("opening_barback", "Opening (Barback)", "duty", [
        ("Marry the bottles", "first thing on arrival", "Set up the bar", "", ""),
        ("Fill the bottles and put them in the wells",
         "batches and service bottles — get the bar completely set up, as if the bartender were "
         "about to start making drinks",
         "Set up the bar", "", ""),
        ("Track what needs restocking on the stock checker",
         "log it as you go through the bar, not from memory afterwards", "Set up the bar", "", ""),

        ("Ice in all the wells", "empty the ice sinks first", "Ice & stock", "17:00", ""),
        ("Stock beverages",
         "Tsingtao, the beers, anything bottled — get these in early, they need time to chill",
         "Ice & stock", "", ""),
        ("Stock alcohol", "", "Ice & stock", "", ""),
        ("Stock batches and syrups", "", "Ice & stock", "", ""),
        ("Stock garnishes", "", "Ice & stock", "", ""),
        ("Ghost ice",
         "check there is enough; anything that needs defrosting goes in immediately. "
         "Yogurt garnish and coconut balls in the cooler too",
         "Ice & stock", "17:45", ""),

        ("Slice the cucumbers", "thin slices for the water pitchers — the bar must be fully "
         "stocked before you go down", "Downstairs", "17:30", "red"),
        ("Stock juices", "lemon, lime, pineapple, egg whites", "Downstairs", "", ""),

        ("Bring up rags and a rack from downstairs",
         "microfibers — one dirty rag, one regular rag, and one rack for downstairs",
         "After opening", "", ""),
        ("Wash all the dirty quarts", "", "After opening", "", ""),
    ]),
    # Item-level low-boy fill. Every row is "<product> - <brand>": the brand is
    # what identifies it on the shelf, so no can-art descriptors.
    # This list is a MIRROR of the live storage map (the `storage_*` tables,
    # Bar Room > Lowboy > Fridge 1-4 > Top/Middle/Bottom), re-synced 2026-09-02
    # after the recipe-location sweep edited the tree, so section names and item
    # order match the shelves you actually walk.
    # Every row is ONE countable product — grouped rows
    # ("Cold Foams", "Lucky Ox Sparkler", "Can Sodas") cannot say which member
    # is short, so they are split into their members here. The three grouped
    # rows the tree still carries are handled the same way and so appear nowhere
    # below by their shelf name: "Service bottles" and "Canisters" are split into
    # their members through _COVERS, and "Bottled Batches" (Fridge 3 · Bottom,
    # renamed from "Clarified Drinks" in the same sweep) has no members on
    # record — see the _COVERS note.
    # Egg White appears on two shelves, and so do Peachy River and Pretty in
    # Pink since 2026-09-02: the service bottle in the well and its backup are
    # separate things to be short of. That is the map, not a duplicate, and a
    # dedupe pass would silently drop a shelf.
    # Onions left Fridge 1 · Middle in the 2026-09-02 sweep and is now stocked
    # on Fridge 4 · Top only.
    # kind='fill' (migration 017): every row is a 0-3 count of units to grab, not
    # a checkbox. The seeder upserts kind, so this MUST stay 'fill' — 'duty' here
    # would silently undo the migration on the next re-seed.
    ("lowboy_fill", "Low boy fill", "fill", [
        ('Super Hero Sidekicks', 'KCBC - hazy IPA', 'Fridge 1 · Top', "", ""),
        ('Neon City', 'Young Master - HK pale ale', 'Fridge 1 · Top', "", ""),
        ('Athletic', 'Athletic Brewing - non-alcoholic', 'Fridge 1 · Top', "", ""),
        ('Oolong Kolsh', 'OEC Brewing', 'Fridge 1 · Top', "", ""),
        ('Baby Jasmine Lager', 'Master Gao', 'Fridge 1 · Top', "", ""),

        ('Sesame Brittle', '', 'Fridge 1 · Middle', "", ""),
        ('Olives', '', 'Fridge 1 · Middle', "", ""),
        ('Lychee', '', 'Fridge 1 · Middle', "", ""),
        ('Longan', '', 'Fridge 1 · Middle', "", ""),
        ('Truffle Chocolate', '', 'Fridge 1 · Middle', "", ""),
        ('CBM Jello', '', 'Fridge 1 · Middle', "", ""),
        ('Cucumbers', '', 'Fridge 1 · Middle', "", ""),
        ('Peaches', '', 'Fridge 1 · Middle', "", ""),
        ('Salted Coconut Foam', '', 'Fridge 1 · Middle', "", ""),
        ('Condensed Milk Cold Foam', '', 'Fridge 1 · Middle', "", ""),
        ('Boba Foam', '', 'Fridge 1 · Middle', "", ""),
        ('Egg White', '', 'Fridge 1 · Middle', "", ""),

        ('Coffee', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Simple Syrup', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Demerara', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Tamarind', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Raspberry Syrup', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Black Sesame', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Coconut Syrup', '', 'Fridge 1 · Bottom · Syrups', "", ""),
        ('Toasted Coco', '', 'Fridge 1 · Bottom · Syrups', "", ""),

        ('Golden Hour', '', 'Fridge 1 · Bottom · Non-Alcoholic Batches', "", ""),
        ('Leaf Me Alone', '', 'Fridge 1 · Bottom · Non-Alcoholic Batches', "", ""),

        ('Lime', '', 'Fridge 1 · Bottom · Fresh Quarts', "", ""),
        ('Lemon', '', 'Fridge 1 · Bottom · Fresh Quarts', "", ""),
        ('Pineapple', '', 'Fridge 1 · Bottom · Fresh Quarts', "", ""),
        ('Egg White', '', 'Fridge 1 · Bottom · Fresh Quarts', "", ""),
        ('Yuzu', '', 'Fridge 1 · Bottom · Fresh Quarts', "", ""),

        ('Ginger Beer', 'Topo Chico', 'Fridge 2 · Top', "", ""),
        ('Ginger Ale', 'Fentimans', 'Fridge 2 · Top', "", ""),
        ('Tonic Water', 'Fentimans', 'Fridge 2 · Top', "", ""),
        ('Club Soda', 'Fentimans', 'Fridge 2 · Top', "", ""),
        ('Tsingtao', '', 'Fridge 2 · Top', "", ""),
        ('Matcha Lemonade', 'Lucky Ox', 'Fridge 2 · Top', "", ""),
        ('Salted Lemonade', 'Lucky Ox', 'Fridge 2 · Top', "", ""),
        ('Pandan Coconut', 'Lucky Ox', 'Fridge 2 · Top', "", ""),

        ('Bitter Remedy', '', 'Fridge 2 · Bottom', "", ""),
        ('Sorrel', '', 'Fridge 2 · Bottom', "", ""),
        ('One Inch Punch', '', 'Fridge 2 · Bottom', "", ""),
        ('Breakfast', '', 'Fridge 2 · Bottom', "", ""),
        ('House', '', 'Fridge 2 · Bottom', "", ""),
        ('Juniper', '', 'Fridge 2 · Bottom', "", ""),
        ('Che Ba Mau', '', 'Fridge 2 · Bottom', "", ""),
        ('Tea Killah', '', 'Fridge 2 · Bottom', "", ""),
        ('Ube Daiquiri', '', 'Fridge 2 · Bottom', "", ""),
        ('Lychee Martini', '', 'Fridge 2 · Bottom', "", ""),
        ('Thairish Tea', '', 'Fridge 2 · Bottom', "", ""),
        ('Passion Express', '', 'Fridge 2 · Bottom', "", ""),
        ('Pineapple Fried Rice', '', 'Fridge 2 · Bottom', "", ""),

        ('Whole Egg', '', 'Fridge 3 · Top', "", ""),
        ('Flowers', '', 'Fridge 3 · Top', "", ""),
        ('Sprite', '', 'Fridge 3 · Top', "", ""),
        ('Canada Dry', '', 'Fridge 3 · Top', "", ""),
        ('Coke', '', 'Fridge 3 · Top', "", ""),
        ('Diet Coke', '', 'Fridge 3 · Top', "", ""),

        ('Peachy River', '', 'Fridge 3 · Bottom', "", ""),
        ('Chrysanthemum Kiss', '', 'Fridge 3 · Bottom', "", ""),
        ('Pandan Colada', '', 'Fridge 3 · Bottom', "", ""),
        ('Pretty in Pink', '', 'Fridge 3 · Bottom', "", ""),

        ('Sealed Garnishes', '', 'Fridge 4 · Top', "", ""),
        ('Heavy Cream', '', 'Fridge 4 · Top', "", ""),
        ('Coconut Water', 'C2O or Vita Coco', 'Fridge 4 · Top', "", ""),
        ('Cherries', '', 'Fridge 4 · Top', "", ""),
        ('Lychee Can', '', 'Fridge 4 · Top', "", ""),
        ('Longan Can', '', 'Fridge 4 · Top', "", ""),
        ('Onions', '', 'Fridge 4 · Top', "", ""),
        ('Wakamomo Peaches', '', 'Fridge 4 · Top', "", ""),
        ('Pretty in Pink', '', 'Fridge 4 · Top', "", ""),

        ('Sauvignon Blanc', '', 'Fridge 4 · Bottom', "", ""),
        ('Rosé', '', 'Fridge 4 · Bottom', "", ""),
        ('Cabernet Sauvignon', '', 'Fridge 4 · Bottom', "", ""),
        ('Prosecco', '', 'Fridge 4 · Bottom', "", ""),
        ('Vina AB', 'Lustau Viña AB Amontillado', 'Fridge 4 · Bottom', "", ""),
        ('Lillet', 'Lillet Blanc', 'Fridge 4 · Bottom', "", ""),
        ('Dry Vermouth', 'Cinzano - Extra Dry', 'Fridge 4 · Bottom', "", ""),
        ('Sweet Vermouth', '', 'Fridge 4 · Bottom', "", ""),
        ('Dirty Martini', '', 'Fridge 4 · Bottom', "", ""),
        ('Peachy River', '', 'Fridge 4 · Bottom', "", ""),
    ]),
    # Closing follows Sam's own run order (2026-08-02), not a grouping by
    # topic: most of a close happens DURING service, which is what keeps the
    # after-hours block short. Sections are the phases in sequence. The duties
    # he did not name in that walkthrough (dishwasher interior, floor drains,
    # gas off, the overnight-soak note) are enforced by management and stay —
    # folded into the phase they belong to rather than dropped.
    ("closing_barback", "Closing (Barback)", "duty", [
        ("Floor mats washed + put away", "first thing — get them out of the way", "During service", "", ""),
        ("Mats + rack to power wash", "at last call", "During service", "", ""),
        ("Bar top mats", "start these while service is still running", "During service", "", ""),
        ("Burn extra ice", "", "During service", "", ""),
        ("Garnishes out before glass goes in", "", "During service", "", ""),
        ("Dishes + glassware", "get through as many as fast as you can", "During service", "", ""),
        ("Handwash what can be", "do not leave overnight", "During service", "", ""),
        ("Wash extra water pitchers", "", "During service", "", ""),
        ("Dry top mats + pitchers", "on the closed bar section", "During service", "", ""),
        ("Kitchen dishes to Alberto",
         "one hour before he leaves — he's out 9pm Sun, 11pm Fri/Sat; weekday time unconfirmed",
         "During service", "", "red"),

        ("Everything hand washed + drying", "", "Downstairs · by 10pm", "22:00", ""),
        ("Wipe tables + appliances", "", "Downstairs · by 10pm", "22:00", ""),
        ("Broom + mop the floor", "", "Downstairs · by 10pm", "22:00", ""),
        ("Nothing in the sink", "", "Downstairs · by 10pm", "22:00", ""),
        ("Sanitize bucket away", "", "Downstairs · by 10pm", "22:00", ""),
        ("No rags out", "", "Downstairs · by 10pm", "22:00", ""),
        ("Overnight soak / strain handled", "saran-wrapped, covered, noted in chat",
         "Downstairs · by 10pm", "22:00", ""),
        ("Boxes broken down", "full -> GC", "Downstairs · by 10pm", "", ""),

        ("Clean all bar tools", "", "Service ends", "", ""),
        ("Clean garnish box + cutting boards", "", "Service ends", "", ""),
        ("Bucket ready for the dry bar tools", "", "Service ends", "", ""),

        ("Finish the glassware", "", "Everyone's gone", "", ""),
        ("Empty + put away", "", "Everyone's gone", "", ""),
        ("Clean inside dishwasher", "rag + cleaner tablet", "Everyone's gone", "", ""),
        ("Dishwasher off", "", "Everyone's gone", "", ""),
        ("Mop", "", "Everyone's gone", "", ""),
        ("Collect garbage + new bags", "", "Everyone's gone", "", ""),
        ("Dump the mop water", "", "Everyone's gone", "", ""),
        ("Wipe bar, seats + tables", "", "Everyone's gone", "", ""),
        ("Wipe fridge tops, dishwasher top + garbage covers", "", "Everyone's gone", "", ""),
        ("Wash sink strainer + wipe the sink", "", "Everyone's gone", "", ""),
        ("Floor-drain debris", "gloves on", "Everyone's gone", "", ""),
        ("Bleach down drains", "about a capful", "Everyone's gone", "", ""),
        ("All rags downstairs", "", "Everyone's gone", "", ""),

        ("Downstairs lights off + door locked", "", "Safety", "", "red"),
        ("Kitchen garbage + gas off", "", "Safety", "", "red"),
        ("All lights + AC off", "", "Safety", "", "red"),
    ]),
    ("stock_check", "Stock check", "stock", []),  # items generated at run start
]


# Grouped storage_item -> the lowboy_fill products it stands for (migration 019).
# The storage tree names a shelf the way you read it while walking ("Canisters");
# the fill checklist names it the way you count it (three separate foams). Both
# wordings are right at their own altitude, so neither is flattened into the
# other — this map is what says they are the same shelf.
# Keys are matched against storage_item.text inside the Lowboy unit.
# 'Bottled Batches' (Fridge 3 · Bottom, called 'Clarified Drinks' until the
# 2026-09-02 sweep renamed it) is deliberately absent under either name: nothing
# on record says what that label separately holds. Every batch it could plausibly
# stand for is already counted — the clarified ones (One Inch Punch, Tea Killah,
# Lychee Martini) and the refrigerated bottled batches Sam named on 2026-09-02
# (Ube Daiquiri, Juniper, Chrysanthemum Kiss, Lychee Martini, Pretty in Pink) all
# have rows of their own. Inventing members for it would be a guess.
_COVERS: dict[str, list[str]] = {
    "Service bottles": [
        "Peachy River", "Chrysanthemum Kiss", "Pandan Colada", "Pretty in Pink",
    ],
    "Canisters": [
        "Salted Coconut Foam", "Condensed Milk Cold Foam", "Boba Foam",
    ],
}


def _seed_covers(conn) -> None:
    """Rebuild storage_item_cover from _COVERS. No-op where the storage tree isn't there.

    Both ends are validated every run rather than trusted, because both drift on
    their own schedule: the checklist is re-seeded from this file, the storage
    tree is hand-edited in the UI. A rename on either side prints a WARN and
    drops that one link — it never writes a dangling row and never guesses at a
    near-match, so an unlinked shelf stays visibly unlinked.
    """
    have = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('storage_item', 'storage_item_cover')"
        )
    }
    if len(have) < 2:
        return
    products = {
        r[0]
        for r in conn.execute(
            "SELECT i.text FROM checklist_template_item i "
            "JOIN checklist_template t ON t.id = i.template_id "
            "WHERE t.key = 'lowboy_fill'"
        )
    }
    for label, members in _COVERS.items():
        rows = conn.execute(
            "SELECT i.id FROM storage_item i "
            "JOIN storage_section s ON s.id = i.section_id "
            "JOIN storage_unit u ON u.id = s.unit_id "
            "WHERE u.name = 'Lowboy' AND i.text = ?",
            (label,),
        ).fetchall()
        if len(rows) != 1:
            print(f"  WARN: '{label}' matched {len(rows)} Lowboy items — link skipped")
            continue
        item_id = rows[0][0]
        known = [m for m in members if m in products]
        for m in members:
            if m not in products:
                print(f"  WARN: '{label}' covers '{m}', which is not a lowboy_fill product")
        conn.execute("DELETE FROM storage_item_cover WHERE item_id = ?", (item_id,))
        conn.executemany(
            "INSERT INTO storage_item_cover(item_id, product) VALUES (?,?)",
            [(item_id, m) for m in known],
        )


def run() -> None:
    with barback_db._conn() as conn:
        for order, (key, name, kind, items) in enumerate(_TEMPLATES):
            conn.execute(
                "INSERT INTO checklist_template (key, name, kind, sort_order) "
                "VALUES (?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET name=excluded.name, "
                "  kind=excluded.kind, sort_order=excluded.sort_order",
                (key, name, kind, order),
            )
            tid = conn.execute(
                "SELECT id FROM checklist_template WHERE key=?", (key,)
            ).fetchone()[0]
            # Replace items wholesale each run (idempotent projection of the notes).
            conn.execute("DELETE FROM checklist_template_item WHERE template_id=?", (tid,))
            for i, (text, detail, section, deadline, priority) in enumerate(items):
                conn.execute(
                    "INSERT INTO checklist_template_item "
                    "(template_id, text, detail, section, deadline, priority, sort_order) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (tid, text, detail, section, deadline, priority, i),
                )
        _seed_covers(conn)


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # dashboard/
    from vault_path import vault_root
    barback_db.init(vault_root() / "data" / "work.db")
    run()
    print("seed_checklists: done")
