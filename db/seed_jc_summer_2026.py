#!/usr/bin/env python3
"""One-shot seed for data/work.db — Juniper & Co recipe data (db renamed from jc.db 2026-06-06).

Sources (preserved as immutable receipts under raw/assets/jc-summer-2026/):
  - jc-spec-sheet-summer-2026.pdf   -> cocktails (Summer 2026 menu)
  - jc-batch-recipes-summer-2026.pdf -> prep, batches, house shots, clarified batches

Merged-in uniques from the prior (May 2026) menu wiki notes, marked menu='prior-2026-05'
so nothing is lost: Ginger Scallion Syrup, Basil Oil, Pho Spiced White Rum, Good Morning Vietnam.

Run once against a freshly migrated (empty) work.db:
    python3 data/seed_jc_summer_2026.py
"""

import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "dashboard"))
from vault_path import vault_root

DB = vault_root() / "data" / "work.db"

PRAGMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
PRAGMA temp_store   = MEMORY;
"""

S = "summer-2026"
P = "prior-2026-05"

# ---- PREP -----------------------------------------------------------------
# (name, category, method, menu, notes, [(ingredient, amount), ...])
PREP = [
    # Syrups / Cordials / Liqueur
    ("Simple Syrup", "Syrup", None, S, None, [("water", "64 oz"), ("sugar", "128 oz")]),
    (
        "Demerara Syrup",
        "Syrup",
        None,
        S,
        None,
        [("water", "64 oz"), ("sugar in the raw", "64 oz (2 boxes)")],
    ),
    (
        "Lemongrass Syrup",
        "Syrup",
        "Simmer 10 mins, stir til dissolved, strain. +Raspberry variant: 2 boxes raspberries : 1 QT lemongrass syrup, blend then strain (no filter) and QT.",
        S,
        "Has a +raspberry variant.",
        [
            ("lemongrass, cut & cleaned", "4 oz"),
            ("water", "64 oz"),
            ("sugar", "128 oz"),
        ],
    ),
    (
        "Chrysanthemum Honey",
        "Syrup",
        "Sit 3 hours then strain and QT.",
        S,
        None,
        [("honey", "10 lb"), ("hot water", "128 oz"), ("chrysanthemum tea", "4 oz")],
    ),
    (
        "Tamarind Agave",
        "Cordial",
        "Muddle thoroughly so no waste when straining. Strain then add equal parts agave, stir and QT.",
        S,
        None,
        [
            ("tamarind pulp", "3 bags (48 oz)"),
            ("hot water", "256 oz"),
            ("agave", "equal parts"),
        ],
    ),
    (
        "Black Sesame Syrup",
        "Syrup",
        "Stir til dissolved. Simmer 10 mins, strain and QT.",
        S,
        None,
        [("black sesame, toasted", "3 oz"), ("water", "64 oz"), ("sugar", "128 oz")],
    ),
    (
        "Red Bean Orgeat",
        "Syrup",
        "Simmer 40 mins then strain.",
        S,
        None,
        [
            ("red bean, toasted", "12 oz"),
            ("water (to a boil)", "128 oz"),
            ("sugar", "48 oz"),
        ],
    ),
    (
        "Pandan Syrup",
        "Syrup",
        "Add pandan extract to simple syrup.",
        S,
        None,
        [("pandan extract", "2 tsp"), ("simple syrup", "6 QT")],
    ),
    (
        "Coconut Syrup",
        "Syrup",
        "Open 12 coconuts intact, empty water into pot. Warm, add equal parts palm sugar. Simmer 10 mins. First number / 8 = coconut aminos, stir.",
        S,
        "Limited cocktail.",
        [
            ("fresh coconut water", "12 coconuts"),
            ("palm sugar", "equal parts"),
            ("coconut aminos", "coconut-water-oz / 8"),
        ],
    ),
    (
        "Nouc Cham",
        "Cordial",
        "Stir til incorporated, strain with cone filter.",
        S,
        None,
        [
            ("fish sauce", "1 bottle (750ml = 865g)"),
            ("warm water", "1730g"),
            ("sugar", "432.5g"),
            ("lemon", "432g"),
            ("white vinegar", "216.25g"),
            ("chili & garlic", "half jar"),
        ],
    ),
    (
        "Stout Syrup",
        "Syrup",
        "Simmer 20 mins on low, skim foam. Measure stout, add equal parts sugar, stir til dissolved. Do not boil. QT and label.",
        S,
        "For Sorrel.",
        [("Guinness", "32 oz (2 pints)"), ("sugar", "equal parts")],
    ),
    (
        "Star Anise and Vanilla Syrup",
        "Syrup",
        "Simmer 10 mins, strain then add vanilla extract.",
        S,
        None,
        [
            ("star anise", "4"),
            ("water", "64 oz"),
            ("sugar", "128 oz"),
            ("vanilla extract", "2 tsp"),
        ],
    ),
    (
        "Vanilla Syrup",
        "Syrup",
        "Add vanilla extract to simple syrup.",
        S,
        None,
        [("vanilla extract", "2 tsp"), ("simple syrup", "6 QT")],
    ),
    (
        "Citrus Cordial",
        "Cordial",
        None,
        S,
        "For Tea-Killah.",
        [
            ("lemon juice", "2 QT (64 oz)"),
            ("lime juice", "2 QT (64 oz)"),
            ("orange juice", "1 QT (32 oz)"),
            ("sugar", "64 oz"),
        ],
    ),
    (
        "Ginger Scallion Syrup",
        "Syrup",
        "Simmer 10 mins then strain.",
        P,
        "Prior menu (May 2026); not on Summer 2026 spec sheet. Used in Good Morning Vietnam batch.",
        [
            ("thin-sliced ginger", "225g"),
            ("cut scallion", "50g"),
            ("water", "80 oz"),
            ("sugar", "128 oz"),
        ],
    ),
    # Teas / Coffee / Foams / Float
    (
        "Chrysanthemum Tea",
        "Tea",
        "Let sit 10 mins. Strain and QT.",
        S,
        None,
        [("hot water", "128 oz"), ("chrysanthemum tea", "2 oz")],
    ),
    (
        "Jasmine Green Tea",
        "Tea",
        "Let sit 10 mins. Strain and QT.",
        S,
        None,
        [("hot water", "128 oz"), ("jasmine green tea", "2 oz")],
    ),
    (
        "Jasmine Green Tea Five Spice Stout",
        "Tea",
        "Let sit 10 mins. Strain and QT.",
        S,
        "For Sorrel.",
        [
            ("hot water", "128 oz"),
            ("jasmine green tea", "2 oz"),
            ("five spice", "1 tsp"),
        ],
    ),
    (
        "Boba H2O",
        "Tea",
        "Boil water, add half bag boba, cover, boil 15 mins, simmer 10 mins low, cool covered 10 mins, strain and QT.",
        S,
        None,
        [("water", "large pot"), ("boba", "half bag")],
    ),
    (
        "Toasted Coconut Milk",
        "Foam",
        "Brown coconut shreds on low heat stirring constantly. Add water and salt, simmer 10 mins, strain and QT.",
        S,
        None,
        [("coconut shreds", "6 cups"), ("water", "128 oz"), ("salt", "4 tsp")],
    ),
    (
        "Salted Coconut Foam",
        "Foam",
        "Mix, QT and label. Make ahead to chill.",
        S,
        "For Pandan Colada.",
        [
            ("coco lopez", "1 can (15 oz)"),
            ("unsweetened coconut", "3 cans (42 oz) or 1 box coconut milk"),
            ("salt", "1 tsp"),
        ],
    ),
    (
        "Condensed Milk Cold Foam",
        "Foam",
        "Stir, QT and label. Make ahead to chill.",
        S,
        "For ThaIrish Tea.",
        [("whole milk", "1320g"), ("condensed milk", "1 can")],
    ),
    (
        "Coffee",
        "Coffee",
        "Stir, leave overnight then strain with cone filter.",
        S,
        None,
        [("coffee", "1 tin (15 oz)"), ("hot water", "256 oz (8 QT)")],
    ),
    (
        "Wine Float",
        "Float",
        "Add to mason jar, place sealed jar in water pot, sous vide 24 hrs at 145F.",
        S,
        "24hr Umami Red Wine Float for Floating on Grand.",
        [
            ("Cabernet Sauvignon", "1 bottle"),
            ("black garlic", "1"),
            ("dashi", "1 tsp"),
            ("dried shiitake mushroom", "8"),
        ],
    ),
    # Garnish
    (
        "Dehydrated Lemon & Lime",
        "Garnish",
        "Thinly slice with mandolin, dehydrate 125F for 12 hours.",
        S,
        None,
        [],
    ),
    (
        "Dehydrated Bitter Melon",
        "Garnish",
        "Thinly slice with mandolin, dehydrate 125F for 12 hours.",
        S,
        None,
        [],
    ),
    (
        "Sorrel Stencil",
        "Garnish",
        "Layer arugula in dehydrator, dehydrate 125F for 12 hours, blend to fine powder, sift, add equal parts ground cinnamon.",
        S,
        "Arugula powder for The Sorrel.",
        [("arugula", "—"), ("ground cinnamon", "equal parts")],
    ),
    (
        "Cookie Rim",
        "Garnish",
        "Muddle egg roll cookies in QT container, add moisture absorbing packet.",
        S,
        None,
        [("egg roll cookies", "—")],
    ),
    (
        "Plum Powder",
        "Garnish",
        "Dehydrate pitted plum 125F for 12 hrs then blend into powder.",
        S,
        None,
        [("pitted plum", "—")],
    ),
    (
        "Yogurt Spoon Garnish",
        "Garnish",
        "Add tapioca to remaining PE yogurt, stir, mold & freeze. Keep 1 backup in freezer.",
        S,
        None,
        [("tapioca", "1/3 cup"), ("PE yogurt", "remaining")],
    ),
    (
        "Chocolate Truffle",
        "Garnish",
        "Low-med heat, stir to combine, fold til cakey (~10 mins), cool 10 mins, roll into balls in cocoa, press into mold.",
        S,
        None,
        [
            ("condensed milk", "2 cans"),
            ("cocoa powder", "1/2 cup"),
            ("butter", "4 tbsp"),
        ],
    ),
    (
        "Coconut Balls",
        "Garnish",
        "Prep red molds with gold dust, fill and press, saran wrap and freeze overnight, empty into dated cambro (stays in cooler).",
        S,
        None,
        [
            ("unsweetened shredded coconut", "1.5 cups"),
            ("coconut syrup", "3 tbsp (9 tsp)"),
            ("coconut oil", "3 tbsp (9 tsp)"),
        ],
    ),
    (
        "Che Ba Mau Layered Jello",
        "Garnish",
        "Combine each layer on low heat (don't over-boil). Simmer mung/red beans 20 mins, strain before adding rest. Harden each layer at room temp before next. Saran wrap tight, refrigerate.",
        S,
        "3 layered dessert garnish.",
        [
            (
                "L1: water/sugar/agar/pandan extract",
                "1 cup / 1/4 cup / 3/4 tsp / 1/2 tsp",
            ),
            ("L2: water/sugar/agar/mungbean", "2 cup / 1/4 cup / 3/4 tsp / 1/4 cup"),
            (
                "L3: water/sugar/agar/split red bean",
                "2 cup / 1/4 cup / 3/4 tsp / 1/4 cup",
            ),
        ],
    ),
    (
        "Basil Oil",
        "Garnish",
        "Blanch basil 1 min, shock in ice water, press dry between paper towels, blend with oil til smooth, strain with cone filter into QT.",
        P,
        "Prior menu (May 2026); not on Summer 2026 spec sheet.",
        [("basil", "1 bunch"), ("oil", "1 cup")],
    ),
    # Infusions / fat-washed spirits
    (
        "Thai Chili Mezcal",
        "Infusion",
        "Stir, let sit 3 hrs (no more). Bottle into Amaras Verde bottles + green tape.",
        S,
        None,
        [("Amaras Verde Mezcal", "12 bottles"), ("cut Thai chili", "2 per bottle")],
    ),
    (
        "Chrysanthemum Vodka",
        "Infusion",
        "Stir, let sit overnight. Bottle into Haku bottles + green tape.",
        S,
        None,
        [("chrysanthemum tea", "8 oz"), ("Haku vodka", "16 bottles")],
    ),
    (
        "Oolong Tequila",
        "Infusion",
        "Stir, let sit overnight. Bottle into Mijienta bottles + green tape.",
        S,
        None,
        [("oolong tea", "6 oz"), ("Mijienta tequila", "9000ml (12x750ml)")],
    ),
    (
        "Peanut Butter Whiskey",
        "Infusion",
        "Stir, let sit overnight / at least 3 hours. Strain with cone filter.",
        S,
        None,
        [("peanut butter", "1/2 large jar"), ("Redemption Rye", "12 bottles")],
    ),
    (
        "Ginseng Pu'er Remy Rye",
        "Infusion",
        "Let sit overnight, QT. Label: Antidote.",
        S,
        "Used in Antidote cocktail.",
        [
            ("Remy", "6 bottles"),
            ("Redemption Rye", "6 bottles"),
            ("ginseng", "3 packets"),
            ("Pu'erh tea", "3 oz"),
        ],
    ),
    (
        "Jackfruit Infused Ten to One Dark Rum",
        "Infusion",
        "Freeze rum + jackfruit overnight, thaw 1 hr, strain. Add to empty coconuts in cambro, saran wrap each, lid, date/label. Sit 1 week then bottle into Ten to One Dark bottles + green tape.",
        S,
        "7-day coconut aged; used In Love with the Coco.",
        [("Ten to One Dark", "1500ml (6x750ml or 4.5x1L)"), ("jackfruit", "2 cans")],
    ),
    (
        "Brown Butter Tullamore Dew",
        "Infusion",
        "Brown 2 sticks butter on med-low (melt 2-3 min, foam 1-2 min, golden-brown 3-5 min). Add 6 bottles Tully to cambro, mix in butter slowly, freeze overnight, strain with cone filter.",
        S,
        "Ratio 1 stick butter : 3 bottles Tully. This batch 6 bottles.",
        [("Tullamore Dew", "6 bottles (6x750ml or 4.5x1L)"), ("butter", "2 sticks")],
    ),
    (
        "Pho Spiced Ten to One White Rum",
        "Infusion",
        "Let sit overnight then strain.",
        P,
        "Prior menu (May 2026); not on Summer 2026 spec sheet. Used in Good Morning Vietnam batch.",
        [
            ("Ten to One White Rum", "1500ml (6x750ml or 4.5x1L)"),
            ("cinnamon sticks", "3"),
            ("star anise", "4"),
            ("fennel", "0.6 oz"),
            ("coriander", "1 oz"),
            ("cloves", "0.6 oz"),
        ],
    ),
]

# ---- BATCHES --------------------------------------------------------------
# (name, category, method, menu, notes, ingredients, [dep_prep_names])
BATCHES = [
    (
        "The Juniper",
        "House Batch",
        None,
        S,
        None,
        [
            ("Roku gin", "4500ml (6x750ml or 4.5x1L)"),
            ("pandan syrup", "1500ml (50.72 oz)"),
            ("red bean orgeat", "750ml (25.36 oz)"),
        ],
        ["Pandan Syrup", "Red Bean Orgeat"],
    ),
    (
        "The Sorrel",
        "House Batch",
        "Measure jasmine five spice green tea in oz. Divide by 0.5 oz, multiply by 0.25 oz = stout syrup. Add, QT and label.",
        S,
        None,
        [
            ("jasmine five spice green tea", "base"),
            ("stout syrup", "tea_oz / 0.5 * 0.25"),
        ],
        ["Jasmine Green Tea Five Spice Stout", "Stout Syrup"],
    ),
    (
        "Macau Flip",
        "House Batch",
        None,
        S,
        None,
        [
            ("Ketel One", "1500ml (2x750ml or 1.5x1L)"),
            ("Tanduay Ube Coconut Rum", "1500ml (2 bottles)"),
            ("See the Elephant Amaro", "2 bottles"),
            ("vanilla syrup", "1500ml (50.72 oz)"),
        ],
        ["Vanilla Syrup"],
    ),
    (
        "Pretty in Pink",
        "House Batch",
        None,
        S,
        None,
        [
            ("Mijenta Blanco", "2250ml (3x750ml)"),
            ("Ming River Baijiu", "2250ml (3x750ml)"),
        ],
        [],
    ),
    (
        "Chrysanthemum Kiss",
        "House Batch",
        None,
        S,
        None,
        [
            ("Chrysanthemum infused Haku", "4500ml (6x750ml or 4.5x1L)"),
            ("chrysanthemum honey", "1500ml (50.72 oz)"),
            ("Cointreau", "1L (1 bottle)"),
        ],
        ["Chrysanthemum Vodka", "Chrysanthemum Honey"],
    ),
    (
        "Pandan Colada",
        "House Batch",
        None,
        S,
        None,
        [
            ("Ten to One Dark Rum", "4500ml (6x750ml or 4.5x1L)"),
            ("pandan syrup", "1500ml (50.72 oz)"),
        ],
        ["Pandan Syrup"],
    ),
    (
        "Peachy River",
        "House Batch",
        None,
        S,
        None,
        [
            ("Mizu Shochu Green Tea", "3750ml (5 bottles)"),
            ("Ming River", "750ml (1 bottle)"),
        ],
        [],
    ),
    (
        "Leaf Me Alone",
        "House Batch",
        None,
        S,
        "Non-alcoholic batch.",
        [("jasmine green tea", "4 QT (3785.41ml)"), ("pandan", "946ml (32 oz)")],
        ["Jasmine Green Tea", "Pandan Syrup"],
    ),
    (
        "Golden Hour",
        "House Batch",
        None,
        S,
        "Non-alcoholic batch.",
        [
            ("chrysanthemum tea", "4 QT (3785.41ml)"),
            ("chrysanthemum honey", "946ml (32 oz)"),
        ],
        ["Chrysanthemum Tea", "Chrysanthemum Honey"],
    ),
    (
        "Dragons Den",
        "House Batch",
        "Infuse Ketel One overnight with longan tea + plums + drained longan, strain into cambro. Add batch ingredients, mix, measure oz / 3oz * 0.75oz = add water. Nitro charge.",
        S,
        "Nitro charge.",
        [
            ("Ketel One (infused)", "4500ml (6x750ml or 4.5x1L)"),
            ("longan tea", "3 oz"),
            ("plums", "full bag"),
            ("drained longan", "1 can"),
            ("St. Germain", "3 bottles (3x1L)"),
            ("dry 1757 dry vermouth", "3 bottles (3x1L)"),
            ("simple syrup", "3 QT (96 oz)"),
            ("lime juice", "3 QT (96 oz)"),
        ],
        ["Simple Syrup"],
    ),
    (
        "Good Morning Vietnam",
        "House Batch",
        None,
        P,
        "Prior menu (May 2026); not on Summer 2026 spec sheet.",
        [
            ("pho spiced light rum", "1500ml (6x750ml or 4.5x1L)"),
            ("ginger scallion syrup", "1500ml"),
            ("Nouc Cham", "750ml (not straight from bottle)"),
        ],
        ["Pho Spiced Ten to One White Rum", "Ginger Scallion Syrup", "Nouc Cham"],
    ),
    # House Shots
    (
        "Juniper Tea Shot",
        "House Shot",
        "Let sit overnight, strain.",
        S,
        None,
        [
            ("dry vermouth", "6L (6x1L)"),
            ("Teeling", "1500ml (2x750ml)"),
            ("Juliette peach liqueur", "1L (1x1L)"),
            ("water", "3 QT (96 oz)"),
            ("chrysanthemum", "1/2 bag"),
            ("goji berries", "1/2 bag"),
        ],
        [],
    ),
    (
        "Irish Breakfast",
        "House Shot",
        "Simmer tea + orange peels 5 mins, strain with cone filter into cambro. Add brown butter Tullamore, Amaro Nonino, maple. Stir and QT.",
        S,
        None,
        [
            ("Irish breakfast tea", "3 oz (26 teabags) : 128 oz hot water"),
            ("orange peels (no pith)", "4 peeled oranges"),
            ("brown butter washed Tullamore Dew", "4500ml (152.1 oz)"),
            ("Amaro Nonino", "76.1 oz"),
            ("maple syrup", "18.9 oz"),
        ],
        ["Brown Butter Tullamore Dew"],
    ),
    # Clarified Batches
    (
        "One Inch Punch",
        "Clarified Batch",
        "Tea = same amount Redemption Bourbon. /2 = simple syrup = evaporated milk. /2 again = lemon juice. Sit overnight, strain cone filter. Dilution: oz / 3oz * 0.25oz = add water.",
        S,
        "Hong Kong Tea.",
        [
            ("Hong Kong tea", "base"),
            ("Redemption Bourbon", "= tea"),
            ("simple syrup", "tea/2"),
            ("evaporated milk", "tea/2"),
            ("lemon juice", "tea/4"),
        ],
        ["Simple Syrup"],
    ),
    (
        "Passion Express",
        "Clarified Batch",
        "Stir, leave overnight, strain cone filter. Dilution: oz / 3oz * 0.25oz = add water. Save yogurt for spoon garnish.",
        S,
        "Passionfruit Yogurt.",
        [
            ("gunpowder green tea infused Roku gin", "4500ml (6x750ml or 4.5x1L)"),
            ("lime juice", "2250ml"),
            ("Chinola passion fruit", "2250ml"),
            ("Demerara", "1.5 QT (48 oz)"),
            ("yogurt", "half tub"),
        ],
        [],
    ),
    (
        "Teakillah",
        "Clarified Batch",
        "Stir, sit overnight, strain cone filter. Dilution: oz / 3oz * 0.25oz = add water.",
        S,
        "Boba Milk Tea.",
        [
            ("oolong Mijenta tequila", "4500ml (6x750ml)"),
            ("citrus cordial", "oz/2"),
            ("lemon juice", "oz/2"),
            ("sugar cane", "1 gallon"),
            ("Demerara", "to taste"),
            ("warmed milk", "60 oz"),
        ],
        ["Citrus Cordial", "Oolong Tequila"],
    ),
    (
        "Che Ba Mau",
        "Clarified Batch",
        "Simmer beans + pandan 30 mins (~152 oz). Add Teeling, mix (~304.32 oz). /2 = simple = coconut milk. orig/2 again = lemon. Sit overnight, strain. Dilution: oz/3oz*0.25oz = water.",
        S,
        None,
        [
            ("split mung bean", "24 oz"),
            ("red bean", "24 oz"),
            ("pandan leaves", "1 bag"),
            ("Teeling", "4500ml (6x750ml)"),
            ("simple syrup", "batch/2"),
            ("coconut milk", "batch/2"),
            ("lemon juice", "orig/2"),
        ],
        ["Simple Syrup"],
    ),
    (
        "ThaIrish Tea",
        "Clarified Batch",
        "Boil water, add Thai tea, sit 10 mins, strain (must equal 7110g, add water if not). Add syrup, lemon, Tullamore, milk. Stir, label, sit overnight, strain cone filter.",
        S,
        "Thai Tea.",
        [
            ("water", "7110g"),
            ("Thai tea leaves", "890g"),
            ("star anise vanilla syrup", "1000g"),
            ("lemon juice", "1000g"),
            ("Tullamore Dew", "6 bottles (1L)"),
            ("whole milk", "4335g"),
        ],
        ["Star Anise and Vanilla Syrup"],
    ),
    # HH Clarified Batches
    (
        "Bitter Sweet",
        "HH Clarified Batch",
        "Clarify, then add coconut water.",
        S,
        None,
        [
            ("Hendricks gin", "6 bottles (6L)"),
            ("bitter melon", "12 (~1495g juice)"),
            ("pineapple juice", "2600g (2 QT)"),
            ("lemon juice", "765g"),
            ("simple syrup", "1015g"),
            ("Sichuan peppercorn", "15g"),
            ("coriander", "20g"),
            ("milk", "2650g"),
            ("coconut water", "6 cans"),
        ],
        ["Simple Syrup"],
    ),
    (
        "Lychee Martini",
        "HH Clarified Batch",
        "Mix, sit overnight, strain cone filter. Dilution: oz / 2.5oz * 0.5oz = add water.",
        S,
        None,
        [
            ("Mijenta tequila", "6 bottles"),
            ("lychee liqueur", "450g"),
            ("Jasmine Verte", "1 bottle"),
            ("jasmine tea", "4500g (2 oz tea leaves)"),
            ("lychee puree", "750g (drain 3 cans, blend)"),
            ("simple syrup", "750g"),
            ("milk", "1110g"),
            ("lemon juice", "1110g"),
            ("condensed milk", "3 cans"),
        ],
        ["Jasmine Green Tea", "Simple Syrup"],
    ),
    (
        "Ube Daiquiri",
        "HH Clarified Batch",
        "Mix, sit overnight, strain cone filter. Dilution: oz / 3oz = add water.",
        S,
        None,
        [
            ("Ten to One White Rum", "6 bottles"),
            ("lime juice", "2250g"),
            ("simple syrup", "1500g"),
            ("milk", "2010g"),
            ("coco lopez", "3 cans"),
            ("coconut milk", "3 cans"),
            ("ube extract", "30g"),
        ],
        ["Simple Syrup"],
    ),
]

# ---- COCKTAILS ------------------------------------------------------------
# (name, section, glassware, garnish, description, allergy, notes, ingredients, [dep names])
COCKTAILS = [
    (
        "The Juniper",
        "Shaken",
        "up coupe",
        "purple flower",
        "Pandan gimlet.",
        None,
        None,
        [("Batch (The Juniper)", "2.25 oz"), ("coconut water", "2 oz"), ("lime", ".5 oz")],
        ["The Juniper"],
    ),
    (
        "The Sorrel",
        "Shaken",
        "up",
        "sorrel stencil (arugula powder)",
        "Dirty matcha martini.",
        None,
        None,
        [
            ("Batch (The Sorrel)", "1 oz"),
            ("yoshi", ".5 oz"),
            ("teeling", ".5 oz"),
            ("pineapple", ".5 oz"),
            ("egg white", "1 oz"),
        ],
        ["The Sorrel"],
    ),
    (
        "Saenchai Kick",
        "Shaken",
        "big rock",
        "smoked salt",
        "Spicy mezcal tamarind margarita.",
        None,
        None,
        [
            ("Thai chili infused Montelobos Mezcal", "1.5 oz"),
            ("Tamarind Agave", "1 oz"),
            ("lime", ".5 oz"),
        ],
        ["Tamarind Agave"],
    ),
    (
        "Macau Flip",
        "Shaken",
        "up sorrel glass",
        "cookie rim",
        "Egg tart.",
        None,
        None,
        [
            ("Batch (Macau Flip)", "2 oz"),
            ("Amontillado Sherry", ".5 oz"),
            ("whole egg", "1"),
        ],
        ["Macau Flip", "Cookie Rim"],
    ),
    (
        "Floating on Grand",
        "Shaken",
        "big ice, wide lip",
        "24hr Umami Red Wine Float (mushroom, dashi, black garlic)",
        "Savory smoky New York sour.",
        None,
        None,
        [
            ("Amaras Verde Mezcal", ".75 oz"),
            ("Ming River", ".75 oz"),
            ("yuzu", ".5 oz"),
            ("lemon", ".25 oz"),
            ("simple", ".5 oz"),
        ],
        ["Wine Float"],
    ),
    (
        "Ca Phe Ailen",
        "Shaken",
        "clear mug + saucer",
        "condensed milk drizzle + truffle",
        "Irish coffee meets espresso martini, with Vietnamese coffee.",
        None,
        None,
        [
            ("Roe & Co Irish Whiskey", "1.5 oz"),
            ("Vietnamese coffee", "1 oz"),
            ("coffee liqueur", ".5 oz"),
        ],
        ["Coffee", "Chocolate Truffle"],
    ),
    (
        "Pretty in Pink",
        "Shaken",
        "up martini",
        "raspberry powder",
        "French martini riff.",
        None,
        "Egg white option +$1.",
        [
            ("Batch (Pretty in Pink)", "1.5 oz"),
            ("Raspberry Lemongrass Syrup", ".5 oz"),
            ("pineapple", ".5 oz"),
            ("lemon", ".5 oz"),
        ],
        ["Pretty in Pink", "Lemongrass Syrup"],
    ),
    (
        "Chrysanthemum Kiss",
        "Shaken",
        "up martini",
        "daisy",
        "Chrysanthemum lemon drop.",
        None,
        None,
        [
            ("Batch (Chrysanthemum Kiss)", "2.25 oz"),
            ("Pierre Ferrand Dry Curacao", "in batch"),
            ("lemon", ".75 oz"),
        ],
        ["Chrysanthemum Kiss"],
    ),
    (
        "Hello Vietnam",
        "Shaken",
        "Collins wide lip",
        "squid snack / shrimp salt rim",
        "Toki highball meets michelada.",
        "FISH",
        None,
        [
            ("Spicy Squid Snack Toki", "1.5 oz"),
            ("lime", ".5 oz"),
            ("n/a Athletic (clean ice, top)", "top"),
        ],
        [],
    ),
    (
        "Temple Run",
        "Shaken",
        "animal mug",
        "daisy flower",
        "Banana tiki low-abv drink.",
        None,
        None,
        [
            (
                "Batch (Ming River Baijiu / Hendricks / Pathfinder n/a Amaro / Banana Liqueur)",
                "3.5 oz",
            ),
            ("lemon", ".75 oz"),
            ("pineapple", "1 oz"),
        ],
        [],
    ),
    (
        "Pandan Colada",
        "Shaken + Dirty Pour",
        "bamboo glass",
        "salted coco foam",
        "Pandan: earthy, vanilla/coconut.",
        None,
        None,
        [
            ("Batch (Pandan Colada / Ten to One Caribbean dark Rum)", "2 oz"),
            ("toasted coconut milk", "1 oz"),
            ("pineapple", "1 oz"),
            ("lime", ".5 oz"),
        ],
        ["Pandan Colada", "Salted Coconut Foam", "Toasted Coconut Milk"],
    ),
    (
        "Peachy River",
        "Stirred",
        "up small martini",
        "wakamomo peach skewered",
        None,
        None,
        None,
        [
            ("Batch (Peachy River / Mizu Sochu Green tea / Ming River)", "1.5 oz"),
            ("Lilet Blanc", ".5 oz"),
            ("Wakamomo Peach brine / Juliette Peach Liqueur split", ".5 oz"),
        ],
        ["Peachy River"],
    ),
    (
        "PB&S",
        "Stirred",
        "big ice small rocks glass",
        "sesame brittle",
        "Peanut butter black sesame old fashioned.",
        "NUT",
        "Egg white sour option +$1.",
        [
            ("Teeling", "2 oz"),
            ("Black Sesame Syrup", ".25 oz"),
            ("chocolate bitter", "2 dash"),
            ("angostura", "2 dash"),
        ],
        ["Black Sesame Syrup"],
    ),
    (
        "Antidote",
        "Stirred",
        "rocks dome",
        "hickory smoke",
        "Twist on Vieux Carre with pei pa koa.",
        None,
        None,
        [
            ("Batch (Pu'er ginseng infused Redemption Rye / Remy / Cointreau)", "2 oz"),
            ("sweet vermouth", "1 oz"),
            ("pei pa koa", "1 bar spoon"),
        ],
        ["Ginseng Pu'er Remy Rye"],
    ),
    (
        "In Love with the Coco",
        "Stirred",
        "coconut cup",
        "coconut candy on wooden spoon",
        "Smooth tropical old fashioned (spirit forward); 7-day coconut aged jackfruit rum.",
        None,
        None,
        [
            ("Ten to One Dark [jackfruit infused, 7day coconut aged]", "3 oz"),
            ("coconut syrup", ".5 oz"),
        ],
        ["Jackfruit Infused Ten to One Dark Rum", "Coconut Syrup"],
    ),
    (
        "One Inch Punch",
        "Clarified / Stirred",
        "goblet",
        "dehydrated lemon + daisy flower",
        "Hong Kong Tea. 3 oz stirred.",
        None,
        None,
        [
            ("Redemption Bourbon", "in batch"),
            ("Hong Kong tea", "in batch"),
            ("evaporated milk", "in batch"),
            ("simple syrup", "in batch"),
            ("lemon", "in batch"),
        ],
        ["One Inch Punch", "Dehydrated Lemon & Lime"],
    ),
    (
        "Teakillah",
        "Clarified / Stirred",
        "large ribbed rocks glass or dome glass",
        "boba foam",
        "Boba Milk Tea. 3 oz stirred.",
        None,
        None,
        [
            ("Mijienta Tequila", "in batch"),
            ("oolong tea", "in batch"),
            ("citrus cordial (lemon/lime/orange/sugar)", "in batch"),
            ("sugarcane juice", "in batch"),
            ("Demerara", "in batch"),
        ],
        ["Teakillah"],
    ),
    (
        "ThaIrish Tea",
        "Clarified / Stirred",
        "tall wide lip, clean ice",
        "condensed milk cold foam",
        "Thai Tea. 3 oz shaken.",
        None,
        None,
        [],
        ["ThaIrish Tea", "Condensed Milk Cold Foam"],
    ),
    (
        "Passion Express",
        "Clarified / Stirred",
        "short wide lip",
        "yogurt spoon garnish",
        "Passionfruit Yogurt. 3 oz stirred.",
        None,
        None,
        [
            ("Roku Gin", "in batch"),
            ("Gunpowder Green Tea", "in batch"),
            ("Chinola Passion Fruit", "in batch"),
            ("Demerara", "in batch"),
            ("lime", "in batch"),
            ("Greek Yogurt", "in batch"),
        ],
        ["Passion Express", "Yogurt Spoon Garnish"],
    ),
    (
        "Che Ba Mau",
        "Clarified / Stirred",
        "dome glass",
        "3 layered jello",
        "Classic Vietnamese 3 layered dessert. 3 oz stirred.",
        None,
        None,
        [
            ("Teeling", "in batch"),
            ("mung bean", "in batch"),
            ("red bean", "in batch"),
            ("pandan", "in batch"),
            ("coconut milk", "in batch"),
            ("lemon", "in batch"),
        ],
        ["Che Ba Mau", "Che Ba Mau Layered Jello"],
    ),
    (
        "A lil Clarity",
        "Clarified / Stirred",
        "flight",
        None,
        "Flight, left to right: Teakilla - One Inch Punch - ThaIrish Tea.",
        None,
        None,
        [],
        ["Teakillah", "One Inch Punch", "ThaIrish Tea"],
    ),
    (
        "Leaf Me Alone",
        "Non-Alcoholic",
        "up Nick & Nora",
        "dehydrated lime",
        "Refreshing and frothy.",
        None,
        None,
        [
            ("Batch (Leaf Me Alone / Jasmine green tea / Pandan)", "2.25 oz"),
            ("Lyres Agave Blanco N/A", "1.5 oz"),
            ("lime", ".5 oz"),
            ("egg white", "1"),
        ],
        ["Leaf Me Alone"],
    ),
    (
        "Golden Hour",
        "Non-Alcoholic",
        "highball boxy glass",
        "daisy",
        None,
        None,
        None,
        [
            (
                "Batch (Golden Hour / Chrysanthemum Tea / Chrysanthemum honey)",
                "2.25 oz",
            ),
            ("Lyres Dry London N/A", "1.5 oz"),
            ("lemon", ".75 oz"),
            ("club soda", "top"),
        ],
        ["Golden Hour"],
    ),
    (
        "Lucky Ox Sparklers",
        "Non-Alcoholic",
        "wide lip highball",
        "side of ice/straw/skewered lemon",
        "Poured at the table.",
        None,
        "Option to add 1oz shot of Aplos Arise // Calme (hemp infused spirit) [$6].",
        [],
        [],
    ),
    (
        "Wolffer Estate Spring in a Bottle",
        "Non-Alcoholic",
        "wine glass",
        None,
        "Blanc de Blanc Sparkling N/A wine. Opened & poured at the table.",
        None,
        None,
        [],
        [],
    ),
]


def add_recipe(cur, ids, kind, name, category=None, glassware=None, garnish=None,
               description=None, method=None, allergy=None, menu=S, notes=None):
    cur.execute(
        "INSERT INTO recipes (kind,name,category,glassware,garnish,description,method,allergy,menu,notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (kind, name, category, glassware, garnish, description, method, allergy, menu, notes),
    )
    ids[(kind, name)] = cur.lastrowid
    return cur.lastrowid


def add_ings(cur, rid, ings):
    for i, (ing, amt) in enumerate(ings):
        cur.execute(
            "INSERT INTO recipe_ingredients (recipe_id,ingredient,amount,sort_order) VALUES (?,?,?,?)",
            (rid, ing, amt, i),
        )


def cocktail_dep_entries(deps, ids):
    """Pure: for a cocktail's raw dependency names, decide (kind, name, note)
    triples by checking what is already in the ids map -- a batch takes
    priority over a prep with the same name. No DB access, so this is what
    gets characterized, not the insert calls around it."""
    out = []
    for d in deps:
        if ("batch", d) in ids:
            out.append(("batch", d, "batch base"))
        elif ("prep", d) in ids:
            out.append(("prep", d, "prep input"))
        else:
            out.append(("?", d, "unresolved"))
    return out


def resolve_dependency(dkind, dname, ids):
    """Pure: find the target recipe id for one dependency entry. Tries the
    declared kind first, then falls back to searching any kind."""
    target = None
    if dkind in ("batch", "prep"):
        target = ids.get((dkind, dname))
    if target is None:
        for k in ("batch", "prep", "cocktail"):
            if (k, dname) in ids:
                target = ids[(k, dname)]
                break
    return target


def _seed_prep(cur, ids):
    for name, category, method, menu, notes, ings in PREP:
        rid = add_recipe(cur, ids, "prep", name, category=category, method=method,
                         menu=menu, notes=notes)
        add_ings(cur, rid, ings)


def _seed_batches(cur, ids, pending_deps):
    for name, category, method, menu, notes, ings, deps in BATCHES:
        rid = add_recipe(cur, ids, "batch", name, category=category, method=method,
                         menu=menu, notes=notes)
        add_ings(cur, rid, ings)
        for d in deps:
            pending_deps.append((rid, "prep", d, "prep input"))


def _seed_cocktails(cur, ids, pending_deps):
    for name, section, glass, garnish, desc, allergy, notes, ings, deps in COCKTAILS:
        rid = add_recipe(cur, ids, "cocktail", name, category=section, glassware=glass,
                         garnish=garnish, description=desc, allergy=allergy, menu=S, notes=notes)
        add_ings(cur, rid, ings)
        pending_deps.extend((rid, k, d, note) for k, d, note in cocktail_dep_entries(deps, ids))


def _apply_dependencies(cur, pending_deps, ids):
    unresolved = []
    for rid, dkind, dname, note in pending_deps:
        target = resolve_dependency(dkind, dname, ids)
        if target is None:
            unresolved.append((rid, dname))
            continue
        cur.execute(
            "INSERT INTO recipe_dependencies (recipe_id,depends_on_recipe_id,note) VALUES (?,?,?)",
            (rid, target, note),
        )
    return unresolved


def _counts(cur):
    return {
        "recipes": cur.execute("SELECT COUNT(*) FROM recipes").fetchone()[0],
        "  cocktail": cur.execute("SELECT COUNT(*) FROM recipes WHERE kind='cocktail'").fetchone()[0],
        "  batch": cur.execute("SELECT COUNT(*) FROM recipes WHERE kind='batch'").fetchone()[0],
        "  prep": cur.execute("SELECT COUNT(*) FROM recipes WHERE kind='prep'").fetchone()[0],
        "  prior-menu rows": cur.execute(
            "SELECT COUNT(*) FROM recipes WHERE menu='prior-2026-05'"
        ).fetchone()[0],
        "ingredients": cur.execute("SELECT COUNT(*) FROM recipe_ingredients").fetchone()[0],
        "dependencies": cur.execute("SELECT COUNT(*) FROM recipe_dependencies").fetchone()[0],
    }


def main():
    conn = sqlite3.connect(DB)
    conn.executescript(PRAGMA)
    cur = conn.cursor()

    if cur.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] > 0:
        print("recipes table is not empty — aborting to avoid duplicate seed.")
        conn.close()
        return 1

    ids = {}  # (kind, name) -> id
    pending_deps = []  # (recipe_id, dep_kind, dep_name, note)
    _seed_prep(cur, ids)
    _seed_batches(cur, ids, pending_deps)
    _seed_cocktails(cur, ids, pending_deps)
    unresolved = _apply_dependencies(cur, pending_deps, ids)

    conn.commit()
    counts = _counts(cur)
    conn.close()
    for k, v in counts.items():
        print(f"{k}: {v}")
    if unresolved:
        print("UNRESOLVED deps:", unresolved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
