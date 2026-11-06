"""Seed the reasoned raw-stage tier classification into work.db `ingredient_tier`.

One row per distinct raw ingredient name (lowercased — the lookup key db.py uses),
with its prep-order tier judged per-ingredient rather than guessed from substrings:

    0 Fresh        juices, fresh produce, herbs
    1 Pantry       dry / canned / shelf-stable non-alcohol (teas, syrups, spices,
                   sugars, salt, sauces, canned + condensed + evaporated + coconut milk)
    2 Alcohol      every spirit, liqueur, wine, beer, bitters, N/A spirit
    3 Refrigerated cold-stored, grabbed last so it doesn't sit out — dairy + eggs +
                   fresh-pressed sugarcane juice (Sam 2026-06-06: dairy & sugarcane
                   only; the other fresh juices stay in tier 0 Fresh)

Re-runnable: upserts by name, so editing a tier here and re-running corrects the row.
Run from this folder:  PYTHONPATH=<repo>/dashboard python3 seed_ingredient_tiers.py
The `note` column flags genuinely ambiguous calls for Sam's review.

Keys MUST match the lowercased ingredient strings in recipe_ingredients exactly.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2])
)  # dashboard/, for vault_path
from vault_path import vault_root

_JC_DB = vault_root() / "data" / "work.db"  # renamed from jc.db 2026-06-06

# tier, optional note. Ambiguous judgments carry a note so they surface in review.
TIERS: dict[str, tuple[int, str | None]] = {
    # ── Fresh (0): juices, fresh produce, herbs ──
    "arugula": (0, None),
    "basil": (0, None),
    "bitter melon": (0, None),
    "cut scallion": (0, None),
    "cut thai chili": (0, None),
    "fennel": (0, None),
    "fresh coconut water": (
        0,
        "explicitly fresh (vs packaged 'coconut water' → pantry)",
    ),
    "lemon": (0, None),
    "lemon juice": (0, None),
    "lemongrass, cut & cleaned": (0, None),
    "lime": (0, None),
    "lime juice": (0, None),
    "orange juice": (0, None),
    "orange peels (no pith)": (0, None),
    "pandan": (0, "fresh leaf (vs 'pandan extract' → pantry)"),
    "pandan leaves": (0, None),
    "pineapple": (0, None),
    "pineapple juice": (0, None),
    "plums": (0, None),
    "thin-sliced ginger": (0, None),
    "yuzu": (0, None),
    # ── Alcohol (2): spirits, liqueurs, wine, beer, bitters, N/A spirits ──
    "amaras verde mezcal": (2, None),
    "amaro nonino": (2, None),
    "amontillado sherry": (2, None),
    "angostura": (2, "bitters"),
    "cabernet sauvignon": (2, "wine"),
    "chocolate bitter": (2, "bitters"),
    "coffee liqueur": (2, None),
    "cointreau": (2, None),
    "dry 1757 dry vermouth": (2, None),
    "dry vermouth": (2, None),
    "guinness": (2, "beer"),
    "gunpowder green tea infused roku gin": (2, "gin infusion"),
    "haku vodka": (2, None),
    "hendricks gin": (2, None),
    "jasmine verte": (
        2,
        "aromatized wine / vermouth — the original miss; NOT the green tea",
    ),
    "juliette peach liqueur": (2, None),
    "ketel one": (2, "vodka"),
    "ketel one (infused)": (2, None),
    "lilet blanc": (2, "Lillet — aromatized wine"),
    "lychee liqueur": (2, None),
    "lyre's agave (non-alc)": (
        2,
        "N/A spirit — Sam's rule puts n/a spirits in the alcohol tier",
    ),
    "lyre's dry london (non-alc)": (2, "N/A spirit"),
    "lyres agave blanco n/a": (2, "N/A spirit"),
    "lyres dry london n/a": (2, "N/A spirit"),
    "mijenta blanco": (2, "tequila"),
    "mijenta tequila": (2, None),
    "mijienta tequila": (2, "misspelling of Mijenta"),
    "ming river": (2, "baijiu"),
    "ming river baijiu": (2, None),
    "mizu shochu green tea": (2, "green-tea shochu — a spirit, not a tea"),
    "n/a athletic (clean ice, top)": (2, "Athletic = N/A beer"),
    "pierre ferrand dry curacao": (2, None),
    "redemption bourbon": (2, None),
    "redemption rye": (2, None),
    "remy": (2, "Rémy Martin cognac"),
    "roe & co irish whiskey": (2, None),
    "roku gin": (2, None),
    "see the elephant amaro": (2, None),
    "st. germain": (2, "elderflower liqueur"),
    "sweet vermouth": (2, None),
    "tanduay ube coconut rum": (2, None),
    "teeling": (2, "Irish whiskey"),
    "ten to one dark": (2, None),
    "ten to one dark [jackfruit infused, 7day coconut aged]": (2, None),
    "ten to one dark rum": (2, None),
    "ten to one white rum": (2, None),
    "thai chili infused montelobos mezcal": (2, None),
    "tullamore dew": (2, "Irish whiskey"),
    "wakamomo peach brine / juliette peach liqueur split": (2, "peach liqueur split"),
    "yoshi": (2, "matcha liqueur (Sam 2026-06-06); .5 oz in The Sorrel"),
    # ── Refrigerated (3): cold-stored, grabbed last — dairy + eggs + sugarcane juice ──
    # Sam 2026-06-06: dairy/eggs AND fresh-pressed sugarcane juice only; every
    # other fresh juice (lemon/lime/orange/pineapple) stays in tier 0 Fresh.
    "butter": (3, None),
    "egg white": (3, None),
    "greek yogurt": (3, None),
    "milk": (3, None),
    "pe yogurt": (3, "yogurt"),
    "sugar cane": (
        3,
        "1.5 gal fresh-pressed sugarcane juice — Refrigerated per Sam 2026-06-06",
    ),
    "sugarcane juice": (3, "fresh-pressed — Refrigerated per Sam 2026-06-06"),
    "whole egg": (3, None),
    "whole milk": (3, None),
    "yogurt": (3, None),
    # ── Pantry (1): shelf-stable non-alcohol, canned, dried, the catch-all ──
    "agave": (1, "agave syrup"),
    "black garlic": (1, "fermented / shelf-stable"),
    "black sesame syrup": (1, None),
    "black sesame, toasted": (1, None),
    "boba": (1, "dried tapioca pearls"),
    "chili & garlic": (
        1,
        "'half jar' in Nouc Cham → jarred chili-garlic sauce (Sam confirmed 2026-06-06)",
    ),
    "chinola passion fruit": (
        1,
        "bottled passion-fruit purée (Sam confirmed 2026-06-06)",
    ),
    "chrysanthemum": (1, "4 oz dried flower (Sam confirmed 2026-06-06)"),
    "chrysanthemum tea": (1, None),
    "cinnamon sticks": (1, None),
    "cloves": (1, None),
    "club soda": (1, None),
    "coco lopez": (1, "cream of coconut, canned"),
    "cocoa powder": (1, None),
    "coconut aminos": (1, "sauce"),
    "coconut milk": (1, "canned — pantry, not dairy"),
    "coconut oil": (1, None),
    "coconut shreds": (1, None),
    "coconut syrup": (1, None),
    "coconut water": (1, "packaged (vs 'fresh coconut water' → fresh)"),
    "toasted coconut milk": (1, "coconut-based — pantry, not dairy"),
    "coffee": (1, None),
    "condensed milk": (1, "canned — pantry, not dairy (Sam's call)"),
    "coriander": (
        1,
        "coriander seed/spice — 20g + pho blend, not fresh cilantro (Sam confirmed 2026-06-06)",
    ),
    "dashi": (1, "stock — powder/packaged"),
    "demerara": (1, "sugar"),
    "drained longan": (1, "canned, drained"),
    "dried shiitake mushroom": (1, None),
    "egg roll cookies": (1, "snack/garnish — NOT dairy despite 'egg'"),
    "evaporated milk": (1, "canned — pantry, not dairy"),
    "fish sauce": (1, None),
    "five spice": (1, None),
    "ginseng": (
        1,
        "dried root, '3 packets' for infusion (Sam confirmed 2026-06-06)",
    ),
    "goji berries": (1, "dried"),
    "ground cinnamon": (1, None),
    "gunpowder green tea": (1, None),
    "honey": (1, None),
    "hong kong tea": (1, None),
    "hot water": (1, "water → pantry"),
    "irish breakfast tea": (1, None),
    "jackfruit": (
        1,
        "'2 cans' in the infused rum → canned (Sam confirmed 2026-06-06)",
    ),
    "jasmine green tea": (1, "tea — pantry (NOT Jasmine Verte, which is alcohol)"),
    "longan tea": (1, None),
    "lychee puree": (
        1,
        "house purée from 3 drained cans (Sam confirmed 2026-06-06)",
    ),
    "maple syrup": (1, None),
    "oil": (1, None),
    "oolong tea": (1, None),
    "palm sugar": (1, None),
    "pandan extract": (1, "extract — pantry-form"),
    "peanut butter": (1, "pantry, not dairy"),
    "pei pa koa": (1, "loquat herbal syrup"),
    "pitted plum": (
        1,
        "preserved/dried sour plum (goes into Plum Powder) — Sam confirmed 2026-06-06",
    ),
    "pu'erh tea": (1, None),
    "raspberry lemongrass syrup": (1, None),
    "red bean": (1, "dried"),
    "red bean, toasted": (1, None),
    "salt": (1, None),
    "sichuan peppercorn": (1, None),
    "simple": (1, "simple syrup shorthand"),
    "simple syrup": (1, None),
    "spicy squid snack toki": (1, "snack garnish, shelf-stable"),
    "split mung bean": (1, "dried"),
    "star anise": (1, None),
    "sugar": (1, None),
    "sugar in the raw": (1, None),
    "mung bean": (1, "dried"),
    "tamarind pulp": (1, "block, shelf-stable"),
    "tapioca": (1, None),
    "thai tea leaves": (1, None),
    "ube extract": (1, "extract"),
    "unsweetened coconut": (1, None),
    "unsweetened shredded coconut": (1, None),
    "vanilla extract": (1, None),
    "vietnamese coffee": (1, None),
    "warm water": (1, "water → pantry"),
    "water": (1, None),
    "water (to a boil)": (1, None),
    "white vinegar": (1, None),
    # ── Unlinked sub-recipes / layered components (BOM-link gaps, not true raws) ──
    # These leak into raw because they carry no produces_recipe_id. Parked in pantry
    # as 'grab the pre-made component'; the real fix is linking them, out of scope here.
    "batch (chrysanthemum kiss)": (1, "unlinked sub-batch (BOM gap)"),
    "batch (golden hour / chrysanthemum tea / chrysanthemum honey)": (
        1,
        "unlinked sub-batch (BOM gap)",
    ),
    "batch (leaf me alone / jasmine green tea / pandan)": (
        1,
        "unlinked sub-batch (BOM gap)",
    ),
    "batch (macau flip)": (1, "unlinked sub-batch (BOM gap)"),
    "batch (ming river baijiu / hendricks / pathfinder n/a amaro / banana liqueur)": (
        1,
        "unlinked sub-batch (BOM gap; spirit-forward)",
    ),
    "batch (pandan colada / ten to one caribbean dark rum)": (
        1,
        "unlinked sub-batch (BOM gap)",
    ),
    "batch (peachy river / mizu sochu green tea / ming river)": (
        1,
        "unlinked sub-batch (BOM gap)",
    ),
    "batch (pretty in pink)": (1, "unlinked sub-batch (BOM gap)"),
    "batch (pu'er ginseng infused redemption rye / remy / cointreau)": (
        1,
        "unlinked sub-batch (BOM gap; spirit-forward)",
    ),
    "batch (the sorrel)": (1, "unlinked sub-batch (BOM gap)"),
    "batch (the juniper)": (1, "unlinked sub-batch (BOM gap)"),
    "citrus cordial (lemon/lime/orange/sugar)": (1, "unlinked cordial prep (BOM gap)"),
    "tamarind agave": (1, "unlinked prep (BOM gap)"),
    "l1: water/sugar/agar/pandan extract": (1, "unlinked layer component (BOM gap)"),
    "l2: water/sugar/agar/mungbean": (1, "unlinked layer component (BOM gap)"),
    "l3: water/sugar/agar/split red bean": (1, "unlinked layer component (BOM gap)"),
}


def seed() -> None:
    conn = sqlite3.connect(_JC_DB)
    try:
        for name, (tier, note) in TIERS.items():
            conn.execute(
                "INSERT INTO ingredient_tier (name, tier, note) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET tier = excluded.tier, note = excluded.note",
                (name, tier, note),
            )
        conn.commit()
        counts = dict(
            conn.execute(
                "SELECT tier, COUNT(*) FROM ingredient_tier GROUP BY tier"
            ).fetchall()
        )
        # any raw ingredient in the recipes that we did NOT classify?
        missing = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT lower(ingredient) FROM recipe_ingredients "
                "WHERE produces_recipe_id IS NULL "
                "  AND lower(ingredient) NOT IN (SELECT name FROM ingredient_tier) "
                "ORDER BY 1"
            ).fetchall()
        ]
    finally:
        conn.close()
    label = {0: "Fresh", 1: "Pantry", 2: "Alcohol", 3: "Refrigerated"}
    print(f"seeded {len(TIERS)} ingredient tiers:")
    for t in (0, 1, 2, 3):
        print(f"  {label[t]:<8} {counts.get(t, 0)}")
    if missing:
        print(f"\nUNCLASSIFIED raw ingredients still in recipes ({len(missing)}):")
        for m in missing:
            print(f"  - {m}")
    else:
        print("\nno unclassified raw ingredients — full coverage.")


if __name__ == "__main__":
    seed()
