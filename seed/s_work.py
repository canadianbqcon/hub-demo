"""Work: the bar job's batch prep, storage map and barback checklists (work.db).

All recipe, storage and checklist content is invented for the demo. No prep day is seeded
(the page builds one from a picked set of batches); templates, archived runs and one
half-ticked run for today are.
"""
DB = "work"
EXPECT = {"recipes": 25, "recipe_ingredients": 60, "recipe_dependencies": 6, "ingredient_tier": 30,
          "storage_area": 3, "storage_unit": 5, "storage_section": 10, "storage_item": 30,
          "checklist_template": 4, "checklist_template_item": 40, "checklist_run": 3,
          "checklist_run_item": 30, "stock_raw_item": 12, "ingredient_location": 20}

MENU = "fall-2026"

# name, category, yield_qty, yield_unit, lead_minutes, lead_label, method, [(ingredient, amount text, qty, unit, scalable)]
PREPS = [
    ("Lime Juice", "Juice", 2, "quart", None, None, "Juice, fine-strain, label with the date. Keep cold; good for 24 hours.",
     [("Limes", "1800 g", 1800, "g", 1)]),
    ("Lemon Juice", "Juice", 2, "quart", None, None, "Juice, fine-strain, label with the date. Keep cold; good for 24 hours.",
     [("Lemons", "1500 g", 1500, "g", 1)]),
    ("Grapefruit Juice", "Juice", 1, "quart", None, None, "Juice and fine-strain. Use within 24 hours.",
     [("Grapefruit", "1400 g", 1400, "g", 1)]),
    ("Simple Syrup", "Syrup", 2, "quart", None, None, "Stir sugar into hot water until clear. Cool, bottle, label.",
     [("Sugar", "1000 g", 1000, "g", 1), ("Water", "1000 g", 1000, "g", 1)]),
    ("Honey Syrup", "Syrup", 1, "quart", None, None, "Warm the water, stir in the honey, cool.",
     [("Honey", "600 g", 600, "g", 1), ("Water", "400 g", 400, "g", 1)]),
    ("Ginger Syrup", "Infusion", 1, "quart", 60, "1 hr steep", "Blend ginger with water, strain, heat with sugar until dissolved. Steep one hour, fine-strain.",
     [("Ginger", "500 g", 500, "g", 1), ("Sugar", "500 g", 500, "g", 1), ("Water", "500 g", 500, "g", 1)]),
    ("Pear Shrub", "Infusion", 1, "quart", 1440, "overnight", "Muddle pears with sugar, rest overnight in the fridge, add vinegar, fine-strain.",
     [("Pears", "800 g", 800, "g", 1), ("Sugar", "400 g", 400, "g", 1), ("Apple cider vinegar", "300 g", 300, "g", 1)]),
    ("Orange Oleo", "Infusion", 1, "quart", 480, "8 hr rest", "Toss peels with sugar, rest 8 hours until syrupy, strain off the oil.",
     [("Orange peel", "400 g", 400, "g", 1), ("Sugar", "300 g", 300, "g", 1)]),
    ("Cucumber Cordial", "Syrup", 1, "quart", None, None, "Blend cucumber with sugar and lime juice, fine-strain.",
     [("Cucumber", "700 g", 700, "g", 1), ("Sugar", "350 g", 350, "g", 1), ("Lime Juice", "1/4 quart", 0.25, "quart", 1)]),
    ("Cinnamon Syrup", "Syrup", 1, "quart", 120, "2 hr steep", "Steep broken cinnamon in hot simple syrup for two hours, strain.",
     [("Cinnamon sticks", "40 g", 40, "g", 1), ("Simple Syrup", "1 quart", 1, "quart", 1)]),
    ("Coffee Concentrate", "Infusion", 1, "quart", 960, "16 hr cold brew", "Steep coarse grounds in cold water 16 hours, filter twice.",
     [("Coffee beans, coarse", "250 g", 250, "g", 1), ("Water", "1000 g", 1000, "g", 1)]),
    ("Black Pepper Tincture", "Infusion", 0.5, "quart", 2880, "2 days", "Cover cracked peppercorns with neutral spirit, shake daily, strain at 48 hours.",
     [("Black peppercorns", "60 g", 60, "g", 1), ("Neutral grain spirit", "1 bottle", 1, "bottle", 1)]),
    ("Dried Orange Wheels", "Garnish", 60, "g", 600, "10 hr dehydrate", "Slice 3 mm, dry at 135F for 10 hours.",
     [("Oranges", "600 g", 600, "g", 1)]),
]
# name, category, yield_qty, yield_unit, method, notes, [(ingredient, text, qty, unit, scalable)]
BATCHES = [
    ("Lantern Hour", "Spirit-forward", 4, "quart", "Combine, stir to chill, bottle. Pour 3.25 oz per drink over a large cube.", "Dilution already included.",
     [("Rye whiskey", "3 bottle", 3, "bottle", 1), ("Cinnamon Syrup", "1 quart", 1, "quart", 1), ("Orange Oleo", "1/2 quart", 0.5, "quart", 1),
      ("Orange bitters", "2 oz", 2, "oz", 1), ("Water", "1 quart", 1, "quart", 1)]),
    ("Salt Marsh Gimlet", "Sours", 5, "quart", "Combine, bottle, keep cold. Shake with ice or serve up. 3 oz per drink.", "Make fresh every two days.",
     [("Gin", "4 bottle", 4, "bottle", 1), ("Lime Juice", "1.5 quart", 1.5, "quart", 1), ("Cucumber Cordial", "1 quart", 1, "quart", 1),
      ("Saline solution", "4 oz", 4, "oz", 1), ("Water", "1 quart", 1, "quart", 1)]),
    ("Copper Kettle", "Highballs", 4, "quart", "Combine and bottle. Build over ice and top with soda: 2.5 oz batch, 2 oz soda.", "",
     [("Bourbon", "3 bottle", 3, "bottle", 1), ("Ginger Syrup", "1 quart", 1, "quart", 1), ("Lemon Juice", "1 quart", 1, "quart", 1),
      ("Honey Syrup", "1/2 quart", 0.5, "quart", 1), ("Water", "1 quart", 1, "quart", 1)]),
    ("Blue Door Sour", "Sours", 5, "quart", "Combine, bottle. Shake with egg white (1 per 4 drinks).", "Tea is brewed and cooled first.",
     [("Pisco", "4 bottle", 4, "bottle", 1), ("Lemon Juice", "1.5 quart", 1.5, "quart", 1), ("Simple Syrup", "1 quart", 1, "quart", 1),
      ("Butterfly pea tea", "1 quart", 1, "quart", 1)]),
    ("Velvet Hour", "Spirit-forward", 4, "quart", "Combine, stir, bottle. Serve over rock, expressed orange.", "",
     [("Aged rum", "3 bottle", 3, "bottle", 1), ("Coffee Concentrate", "1 quart", 1, "quart", 1), ("Simple Syrup", "1/2 quart", 0.5, "quart", 1),
      ("Chocolate bitters", "2 oz", 2, "oz", 1)]),
    ("Orchard Ghost", "Sours", 4, "quart", "Combine and bottle. Shake, double-strain, serve up.", "Shrub separates; shake the bottle first.",
     [("Apple brandy", "3 bottle", 3, "bottle", 1), ("Pear Shrub", "1 quart", 1, "quart", 1), ("Lemon Juice", "1 quart", 1, "quart", 1),
      ("Honey Syrup", "1/2 quart", 0.5, "quart", 1)]),
    ("Night Garden Negroni", "Spirit-forward", 5, "quart", "Combine, stir, bottle. Serve over a large cube, dried orange wheel.", "Keeps for two weeks.",
     [("Gin", "2 bottle", 2, "bottle", 1), ("Sweet vermouth", "2 bottle", 2, "bottle", 1), ("Bitter aperitivo", "2 bottle", 2, "bottle", 1),
      ("Black Pepper Tincture", "2 oz", 2, "oz", 1), ("Water", "1 quart", 1, "quart", 1)]),
    ("Porch Swing Punch", "Non-Alcoholic", 4, "quart", "Combine everything but the soda; add 2 oz sparkling water to each glass.", "No alcohol.",
     [("Grapefruit Juice", "1 quart", 1, "quart", 1), ("Lime Juice", "1/2 quart", 0.5, "quart", 1), ("Ginger Syrup", "1/2 quart", 0.5, "quart", 1),
      ("Sparkling water", "3 bottle", 3, "bottle", 1)]),
]
COCKTAILS = [  # name, batch it rides on, glassware, garnish, description
    ("Lantern Hour", "Lantern Hour", "Rocks", "Dried orange wheel", "Rye, warm cinnamon and orange oil. Stirred and slow."),
    ("Salt Marsh Gimlet", "Salt Marsh Gimlet", "Coupe", "Cucumber ribbon", "Cold, green and a little savory."),
    ("Copper Kettle", "Copper Kettle", "Collins", "Candied ginger", "A bourbon highball with real ginger heat."),
    ("Blue Door Sour", "Blue Door Sour", "Coupe", "Edible flower", "Pisco sour that changes color when the lemon hits it."),
    ("Velvet Hour", "Velvet Hour", "Rocks", "Orange expression", "Rum and coffee, a not-too-sweet nightcap."),
    ("Orchard Ghost", "Orchard Ghost", "Nick and Nora", "Pear fan", "Apple brandy, pear shrub and honey. Autumn in a glass."),
]
TIER = {  # lowercased raw ingredient -> tier (0 fresh, 1 pantry, 2 alcohol, 3 refrigerated)
    "limes": 0, "lemons": 0, "grapefruit": 0, "ginger": 0, "pears": 0, "orange peel": 0, "cucumber": 0, "oranges": 0,
    "sugar": 1, "water": 1, "honey": 1, "apple cider vinegar": 1, "cinnamon sticks": 1, "coffee beans, coarse": 1,
    "black peppercorns": 1, "orange bitters": 2, "chocolate bitters": 2, "saline solution": 1, "butterfly pea tea": 1,
    "sparkling water": 1, "rye whiskey": 2, "gin": 2, "bourbon": 2, "pisco": 2, "aged rum": 2, "apple brandy": 2,
    "sweet vermouth": 2, "bitter aperitivo": 2, "neutral grain spirit": 2, "eggs": 3, "butter": 3,
}

# storage tree: area -> unit -> section -> (subsection | None) -> items
TREE = [
    ("Front room", [("Right fridge", [("Top", ["Fresh juices (quarts)", "Egg whites"]), ("Bottom", ["Syrups", "Shrubs and infusions"])]),
                    ("Left fridge", [("", ["Beer and cider", "Sodas"])])]),
    ("Back room", [("Lowboy", [("Fridge 1", [("Top", ["Hazy IPA", "Pilsner", "Zero-proof lager"]), ("Middle", ["Olives", "Cucumbers", "Peaches", "Cold foams"]),
                                            ("Bottom", ["Simple syrup", "Honey syrup", "Ginger syrup", "Cinnamon syrup"])]),
                                  ("Fridge 2", [("Top", ["Ginger beer", "Tonic"]), ("Bottom", ["Bottled batches"])])]),
                   ("Left metal shelf", [("Canned goods", ["Coconut milk", "Condensed milk"]), ("Dry garnish", ["Dried orange wheels", "Cinnamon sticks"])])]),
    ("Alcohol room", [("Spirit rack", [("Whiskey", ["Rye whiskey", "Bourbon"]), ("Gin and brandy", ["Gin", "Pisco", "Apple brandy"]),
                                       ("Rum and other", ["Aged rum", "Sweet vermouth", "Bitter aperitivo"])])]),
]
LOCATIONS = {}  # filled while building the tree

OPENING = [
    ("Marry the bottles", "Match every old bottle with the new one before pouring", "Set up the bar", "", ""),
    ("Stock the speed rail", "Check the well against the par sheet", "Set up the bar", "", ""),
    ("Set out garnish trays", "Citrus, herbs, dried wheels", "Set up the bar", "", ""),
    ("Fill the ice wells", "", "Ice and cold side", "17:00", "high"),
    ("Stock the lowboy", "Run the low boy fill list", "Ice and cold side", "", ""),
    ("Check the cooler temperature", "Under 40F", "Ice and cold side", "", ""),
    ("Cut fresh garnish", "Lime wedges, lemon twists, cucumber", "Prep", "", ""),
    ("Wipe the glassware", "Hold to the light", "Prep", "", ""),
    ("Label and date new batches", "Day-dot on every bottle", "Prep", "", ""),
    ("Set the back bar lights", "", "Floor", "", ""),
    ("Test the POS printer", "", "Floor", "", ""),
    ("Walk the floor with the manager", "Specials and 86 list", "Floor", "17:30", ""),
]
CLOSING = [
    ("Pour out and strain the open juices", "Anything made today stays only if still within 24 hours", "Bar breakdown", "", ""),
    ("Wrap and label all garnish", "", "Bar breakdown", "", ""),
    ("Pull and wash the ice wells", "", "Bar breakdown", "", "high"),
    ("Soak the bar mats", "", "Bar breakdown", "", ""),
    ("Run the glass washer last load", "", "Cleaning", "", ""),
    ("Clean the back bar bottles", "Wipe the necks", "Cleaning", "", ""),
    ("Mop behind the bar", "", "Cleaning", "", ""),
    ("Take out recycling and trash", "", "Cleaning", "", ""),
    ("Count and record low and out items", "Text the manager the list", "Wrap-up", "", ""),
    ("Lock the walk-in and back door", "", "Wrap-up", "", "high"),
]
LOWBOY = [  # text, detail, section, location
    ("Hazy IPA", "Local brewery, 16 oz can", "Fridge 1 · Top", "Lowboy · Fridge 1 · Top"),
    ("Pilsner", "", "Fridge 1 · Top", "Lowboy · Fridge 1 · Top"),
    ("Zero-proof lager", "", "Fridge 1 · Top", "Lowboy · Fridge 1 · Top"),
    ("Olives", "", "Fridge 1 · Middle", "Lowboy · Fridge 1 · Middle"),
    ("Cucumbers", "", "Fridge 1 · Middle", "Lowboy · Fridge 1 · Middle"),
    ("Peaches", "", "Fridge 1 · Middle", "Lowboy · Fridge 1 · Middle"),
    ("Salted coconut foam", "", "Fridge 1 · Middle", "Lowboy · Fridge 1 · Middle"),
    ("Egg white", "", "Fridge 1 · Middle", "Lowboy · Fridge 1 · Middle"),
    ("Simple syrup", "", "Fridge 1 · Bottom · Syrups", "Lowboy · Fridge 1 · Bottom"),
    ("Honey syrup", "", "Fridge 1 · Bottom · Syrups", "Lowboy · Fridge 1 · Bottom"),
    ("Ginger syrup", "", "Fridge 1 · Bottom · Syrups", "Lowboy · Fridge 1 · Bottom"),
    ("Cinnamon syrup", "", "Fridge 1 · Bottom · Syrups", "Lowboy · Fridge 1 · Bottom"),
    ("Lime juice", "", "Fridge 1 · Bottom · Fresh quarts", "Lowboy · Fridge 1 · Bottom"),
    ("Lemon juice", "", "Fridge 1 · Bottom · Fresh quarts", "Lowboy · Fridge 1 · Bottom"),
    ("Grapefruit juice", "", "Fridge 1 · Bottom · Fresh quarts", "Lowboy · Fridge 1 · Bottom"),
    ("Ginger beer", "Topo-style bottle", "Fridge 2 · Top", "Lowboy · Fridge 2 · Top"),
    ("Tonic", "", "Fridge 2 · Top", "Lowboy · Fridge 2 · Top"),
    ("Salt Marsh Gimlet", "Bottled batch", "Fridge 2 · Bottom · Bottled batches", "Lowboy · Fridge 2 · Bottom"),
    ("Orchard Ghost", "Bottled batch", "Fridge 2 · Bottom · Bottled batches", "Lowboy · Fridge 2 · Bottom"),
    ("Lantern Hour", "Bottled batch", "Fridge 2 · Bottom · Bottled batches", "Lowboy · Fridge 2 · Bottom"),
    ("Dried orange wheels", "", "Dry garnish", "Left metal shelf · Dry garnish"),
    ("Cinnamon sticks", "", "Dry garnish", "Left metal shelf · Dry garnish"),
    ("Coconut milk", "", "Canned goods", "Left metal shelf · Canned goods"),
    ("Condensed milk", "", "Canned goods", "Left metal shelf · Canned goods"),
]
STOCK_RAW = [("Lime juice", "Fresh juice"), ("Lemon juice", "Fresh juice"), ("Grapefruit juice", "Fresh juice"),
             ("Limes", "Produce"), ("Lemons", "Produce"), ("Cucumbers", "Produce"), ("Mint", "Produce"), ("Ginger", "Produce"),
             ("Dried orange wheels", "Dry garnish"), ("Cinnamon sticks", "Dry garnish"), ("Edible flowers", "Dry garnish"),
             ("Ginger beer", "Bottled & canned"), ("Tonic", "Bottled & canned"), ("Sparkling water", "Bottled & canned"),
             ("Coconut milk", "Bottled & canned"), ("Hazy IPA", "Bottled & canned")]


def seed(c, rnd, p):
    _seed(c, rnd, p)
    _stamp(c, p.t(-48))


def _seed(c, rnd, p):
    ids = {}

    def add_recipe(kind, name, cat, yq, yu, lead, label, method, notes=None, glass=None, garnish=None, desc=None, ings=()):
        rid = c.execute(
            "INSERT INTO recipes(kind,name,category,glassware,garnish,description,method,menu,notes,yield_qty,yield_unit,"
            "lead_minutes,lead_label) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, name, cat, glass, garnish, desc, method, MENU, notes or None, yq, yu, lead, label)).lastrowid
        ids[(kind, name)] = rid
        for i, (ing, text, qty, unit, scal) in enumerate(ings):
            prod = ids.get(("prep", ing)) or ids.get(("batch", ing))
            c.execute("INSERT INTO recipe_ingredients(recipe_id,ingredient,amount,sort_order,qty,unit,scalable,produces_recipe_id)"
                      " VALUES(?,?,?,?,?,?,?,?)", (rid, ing, text, i, qty, unit, scal, prod))
        return rid

    for name, cat, yq, yu, lead, label, method, ings in PREPS:
        add_recipe("prep", name, cat, yq, yu, lead, label, method, ings=ings)
    for name, cat, yq, yu, method, notes, ings in BATCHES:
        add_recipe("batch", name, cat, yq, yu, None, None, method, notes, ings=ings)
    for name, batch, glass, garnish, desc in COCKTAILS:
        rid = add_recipe("cocktail", name, "Fall menu", None, None, None, None, "Build per the batch card.", None, glass, garnish, desc,
                         [(batch, "3 oz", 3, "oz", 1)])
        c.execute("INSERT INTO recipe_dependencies(recipe_id,depends_on_recipe_id,note) VALUES(?,?,?)",
                  (rid, ids[("batch", batch)], "batch base"))
    for b in BATCHES:
        for ing, *_x in b[6]:
            if ("prep", ing) in ids:
                c.execute("INSERT INTO recipe_dependencies(recipe_id,depends_on_recipe_id,note) VALUES(?,?,?)",
                          (ids[("batch", b[0])], ids[("prep", ing)], "prep input"))
    for k, v in sorted(TIER.items()):
        c.execute("INSERT INTO ingredient_tier(name,tier,note) VALUES(?,?,NULL)", (k, v))
    # storage tree
    c.execute("INSERT INTO storage_note(id, body) VALUES(1, ?)",
              ("Front room: right fridge (juices, syrups), left fridge (beer, soda).\nBack room: lowboy fridges 1 and 2, left metal shelf for dry goods.\n"
               "Alcohol room: spirit rack by category.\n",))
    item_n = 0
    for ai, (area, units) in enumerate(TREE):
        aid = c.execute("INSERT INTO storage_area(name,sort_order) VALUES(?,?)", (area, ai)).lastrowid
        for ui, (unit, secs) in enumerate(units):
            uid = c.execute("INSERT INTO storage_unit(area_id,name,sort_order) VALUES(?,?,?)", (aid, unit, ui)).lastrowid
            for si, sec in enumerate(secs):
                sname, body = sec
                sid = c.execute("INSERT INTO storage_section(unit_id,name,sort_order) VALUES(?,?,?)", (uid, sname, si)).lastrowid
                subs = body if body and isinstance(body[0], tuple) else [("", body)]
                for sj, (subname, items) in enumerate(subs):
                    tid = sid if not subname else c.execute(
                        "INSERT INTO storage_section(unit_id,name,sort_order,parent_id) VALUES(?,?,?,?)", (uid, subname, sj, sid)).lastrowid
                    for ii, it in enumerate(items):
                        item_n += 1
                        c.execute("INSERT INTO storage_item(section_id,text,note,sort_order) VALUES(?,?,?,?)",
                                  (tid, it, "Check date dots weekly" if "juice" in it.lower() else "", ii))
    for text, _d, _s, loc in LOWBOY:
        c.execute("INSERT OR REPLACE INTO ingredient_location(name,location,note) VALUES(?,?,NULL)", (text, loc))
    # checklist templates
    for i, (key, name, kind, items) in enumerate([("opening_barback", "Opening (Barback)", "duty", OPENING),
                                                  ("closing_barback", "Closing (Barback)", "duty", CLOSING),
                                                  ("stock_check", "Stock check", "stock", []),
                                                  ("lowboy_fill", "Low boy fill", "fill", [(t, d, s, "", "") for t, d, s, _l in LOWBOY])]):
        tid = c.execute("INSERT INTO checklist_template(key,name,kind,sort_order) VALUES(?,?,?,?)", (key, name, kind, i)).lastrowid
        for j, (text, detail, section, deadline, prio) in enumerate(items):
            c.execute("INSERT INTO checklist_template_item(template_id,text,detail,section,deadline,priority,sort_order) VALUES(?,?,?,?,?,?,?)",
                      (tid, text, detail, section, deadline, prio, j))
    for i, (name, cat) in enumerate(STOCK_RAW):
        c.execute("INSERT INTO stock_raw_item(name,category,sort_order) VALUES(?,?,?)", (name, cat, i))
    # runs: yesterday opening + closing archived, today's opening half done
    tpl = {r[0]: r[1] for r in c.execute("SELECT key, id FROM checklist_template")}
    def run(key, items, day, status, done_frac, hm):
        rid = c.execute("INSERT INTO checklist_run(template_id,bar_date,started_at,status,completed_at) VALUES(?,?,?,?,?)",
                        (tpl[key], p.d(day), p.d(day, hm + ":00"), status,
                         p.d(day, "23:40:00") if status == "archived" and done_frac >= 1 else None)).lastrowid
        n_done = int(len(items) * done_frac)
        for j, (text, detail, section, deadline, prio) in enumerate(items):
            done = j < n_done
            c.execute("INSERT INTO checklist_run_item(run_id,text_snapshot,detail_snapshot,section,deadline,priority,state,state_at,sort_order)"
                      " VALUES(?,?,?,?,?,?,?,?,?)",
                      (rid, text, detail, section, deadline, prio, "done" if done else "open",
                       p.d(day, f"{int(hm[:2]) + j // 4:02d}:{(j * 7) % 60:02d}:00") if done else None, j))
    run("opening_barback", OPENING, -1, "archived", 1.0, "16:50")
    run("closing_barback", CLOSING, -1, "archived", 0.8, "23:10")
    run("opening_barback", OPENING, 0, "active", 0.5, "16:55")


def _stamp(con, token):
    """Pin every datetime('now') default column to a token, so the seed is deterministic."""
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'").fetchall():
        for r in con.execute(f'PRAGMA table_info("{t}")').fetchall():
            if "datetime('now')" in str(r[4]):
                con.execute(f'UPDATE "{t}" SET "{r[1]}"=? WHERE "{r[1]}" NOT LIKE \'@%\'', (token,))
