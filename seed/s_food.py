"""Food: a Chicago research store. Fictional restaurants, scenes and quotes.

The area rundowns, place summaries and evidence quotes are AI-written sample output; the
runs.notes column says so. Evidence URLs point at fictional .example sites.
"""
import json

DB = "food"
EXPECT = {"areas": 5, "places": 16, "evidence": 70, "runs": 3}

CITY = "Chicago"
HOODS = {  # name: (lat, lng)
    "Pilsen": (41.8563, -87.6600), "Logan Square": (41.9232, -87.7085),
    "Albany Park": (41.9686, -87.7240), "Chinatown": (41.8530, -87.6340),
}

# hood, name, broad, specific, price, discovery, depth, exec, dish, origin, extra, summary, order, pros, cons, practical, n_literate, n_general
P = [
    ("Pilsen", "Casa Tlayuda", "Mexican", "Oaxacan", "$$", "dig", 8.6, 8.2, "mole negro", "Oaxaca", "hoja santa",
     "A small room doing Oaxacan food from the ground up: masa pressed to order, moles made over two days.",
     ["Mole negro with chicken", "Tlayuda with tasajo", "Memelas"], ["Masa and moles made in house", "Owner sources chiles from Oaxaca"],
     ["Seats about 28 and fills by 7", "Mezcal list is short"], {"reservations": "walk-in only", "hours": "Tue-Sun 11:00-21:00", "cash_only": False}, 6, 3),
    ("Pilsen", "Taquería El Güero Azul", "Mexican", "Tacos al pastor", "$", "consensus", 7.4, 8.0, "al pastor", "Mexico City", "pineapple",
     "Trompo-cut pastor with a real char and a salsa bar that earns the line. A solid neighborhood anchor.",
     ["Tacos al pastor", "Gringas", "Horchata"], ["Fast, cheap, consistent", "Open late"], ["Loud, little seating"],
     {"reservations": "none", "hours": "Daily 10:00-02:00", "cash_only": True}, 3, 5),
    ("Pilsen", "Panadería La Espiga", "Mexican", "Pan dulce", "$", "consensus", 7.1, 7.8, "conchas", "Puebla", "piloncillo",
     "Morning bakery with a wall of pan dulce baked in two batches. Good conchas, better empanadas de cajeta.",
     ["Conchas", "Empanadas de cajeta", "Café de olla"], ["Fresh until midday", "Very low prices"], ["Sells out by noon on weekends"],
     {"reservations": "none", "hours": "Daily 06:00-19:00", "cash_only": True}, 2, 4),
    ("Pilsen", "Mixteca Cocina", "Mexican", "Pueblan", "$$", "dig", 8.1, 7.2, "mole poblano", "Puebla", "chile mulato",
     "Pueblan cooking from a family kitchen: cemitas on house bread, mole poblano, chiles en nogada in season.",
     ["Cemita milanesa", "Mole poblano", "Chiles en nogada (Sept-Oct)"], ["Seasonal menu", "Handmade tortillas"], ["Kitchen is slow when full"],
     {"reservations": "accepts for 6+", "hours": "Wed-Mon 12:00-21:00", "cash_only": False}, 5, 3),
    ("Logan Square", "Wicker & Rye", "American", "New American", "$$$", "consensus", 6.2, 8.8, "hearth chicken", "the Midwest", "sunchokes",
     "A polished tasting-style room. Technique is excellent; the menu reads more as a chef's showcase than a regional tradition.",
     ["Hearth chicken for two", "Burnt honey ice cream"], ["Excellent service", "Strong wine list"], ["Pricey", "Tables are tight"],
     {"reservations": "required", "hours": "Tue-Sat 17:00-23:00", "cash_only": False}, 2, 6),
    ("Logan Square", "Pierogi Dom", "Polish", "Polish home cooking", "$", "dig", 8.8, 7.9, "pierogi ruskie", "southern Poland", "twaróg",
     "Grandmother-style Polish: hand-pinched pierogi, żurek in a bread bowl, a daily gołąbki. Rooms smells like a Sunday.",
     ["Pierogi ruskie", "Żurek", "Gołąbki"], ["Real home cooking", "Generous portions"], ["Cash only", "Short hours"],
     {"reservations": "none", "hours": "Wed-Sun 11:00-20:00", "cash_only": True}, 7, 3),
    ("Logan Square", "Nonna Gia's", "Italian", "Italian-American", "$$", "consensus", 6.8, 8.1, "baked ziti", "New Jersey", "provolone",
     "Red-sauce comfort done carefully. Not trying to be Italian-Italian; very good at what it is.",
     ["Baked ziti", "Chicken parm", "Cannoli"], ["Cozy", "Great for groups"], ["Weeknights get crowded"],
     {"reservations": "yes", "hours": "Daily 16:00-22:00", "cash_only": False}, 2, 6),
    ("Logan Square", "Sabor Andino", "Peruvian", "Criollo", "$$", "dig", 7.9, 7.5, "lomo saltado", "Lima", "aji amarillo",
     "A family-run Peruvian spot with a serious ají amarillo habit. The ceviche is bright and the lomo has real wok-hei.",
     ["Ceviche clásico", "Lomo saltado", "Chicha morada"], ["Fresh fish on Fridays", "Friendly service"], ["Small kitchen, occasional waits"],
     {"reservations": "accepts", "hours": "Tue-Sun 12:00-21:30", "cash_only": False}, 4, 3),
    ("Albany Park", "Seoul Hearth", "Korean", "Home-style Korean", "$$", "dig", 8.4, 8.3, "kimchi jjigae", "Jeolla province", "gochugaru",
     "Stews and banchan like a Korean home table. The kimchi is house-fermented in jars you can see by the window.",
     ["Kimchi jjigae", "Galbi jjim", "Seafood pajeon"], ["Great banchan", "House-fermented kimchi"], ["Weekend lunch rush"],
     {"reservations": "accepts", "hours": "Tue-Sun 11:30-21:00", "cash_only": False}, 6, 4),
    ("Albany Park", "Damascus Table", "Middle Eastern", "Syrian", "$$", "dig", 8.0, 7.7, "kibbeh", "Damascus", "pomegranate molasses",
     "Syrian home cooking in a bright room: kibbeh in three forms, fattet, a proper muhammara.",
     ["Kibbeh trio", "Fattet hummus", "Muhammara"], ["Generous mezze", "Vegetarian friendly"], ["No alcohol"],
     {"reservations": "accepts", "hours": "Daily 11:00-22:00", "cash_only": False}, 5, 3),
    ("Albany Park", "Kapitolyo Kitchen", "Filipino", "Filipino", "$", "dig", 8.2, 7.0, "sinigang", "Pampanga", "tamarind",
     "Steam-table classics and a few weekend specials. Sinigang is properly sour; the lechon kawali stays crisp.",
     ["Sinigang na baboy", "Lechon kawali", "Halo-halo"], ["Very good value", "Weekend specials"], ["Order-at-counter chaos at lunch"],
     {"reservations": "none", "hours": "Daily 10:00-20:00", "cash_only": False}, 4, 3),
    ("Albany Park", "Anatolia Grill", "Turkish", "Kebab", "$$", "consensus", 6.9, 7.6, "adana kebab", "Gaziantep", "sumac",
     "Charcoal kebabs and warm bread. Reliable, a step more cautious on spice than its menu suggests.",
     ["Adana kebab", "Lahmacun", "Künefe"], ["Charcoal grill", "Fresh bread"], ["Spice is toned down"],
     {"reservations": "yes", "hours": "Daily 12:00-22:00", "cash_only": False}, 2, 5),
    ("Chinatown", "Red Pepper Pavilion", "Chinese", "Sichuan", "$$", "dig", 8.9, 8.0, "mapo tofu", "Chengdu", "Sichuan peppercorn",
     "Numbing-and-hot Sichuan without the training wheels. The menu has a page of cold dishes most places skip.",
     ["Mapo tofu", "Dan dan noodles", "Fuqi feipian"], ["Real má-là", "Deep cold-dish list"], ["Heat is not adjustable"],
     {"reservations": "accepts 6+", "hours": "Daily 11:00-22:00", "cash_only": False}, 8, 3),
    ("Chinatown", "Lotus Lane Dim Sum", "Chinese", "Cantonese dim sum", "$$", "consensus", 7.5, 7.9, "har gow", "Guangzhou", "wheat starch",
     "Cart-service dim sum on weekends, menu-order the rest of the week. Har gow skins are properly translucent.",
     ["Har gow", "Siu mai", "Turnip cake"], ["Carts on weekends", "Big round tables"], ["Long weekend waits"],
     {"reservations": "accepts", "hours": "Daily 10:00-21:00", "cash_only": False}, 3, 5),
    ("Chinatown", "Noodle Bridge", "Chinese", "Lanzhou hand-pulled noodles", "$", "dig", 8.3, 7.6, "niu rou mian", "Lanzhou", "lamian",
     "Noodles pulled to order in the front window. Clear beef broth, chili oil by the spoon.",
     ["Niu rou mian", "Fried lamb noodles"], ["Fresh pulled noodles", "Fast"], ["Few seats"],
     {"reservations": "none", "hours": "Daily 11:00-20:30", "cash_only": True}, 5, 3),
    ("Chinatown", "Tamarind Thai Kitchen", "Thai", "Northern Thai", "$$", "dig", 8.0, 7.8, "khao soi", "Chiang Mai", "fermented soybean",
     "Northern Thai that stays out of pad-thai territory: khao soi, sai ua sausage, a lab larb with offal.",
     ["Khao soi", "Sai ua", "Larb"], ["Northern specialties", "Spice levels are honest"], ["Tight parking"],
     {"reservations": "accepts", "hours": "Tue-Sun 11:30-21:30", "cash_only": False}, 5, 3),
]

SOURCES = [("Plate Talk forum", "platetalk.example"), ("The Table Ledger", "tableledger.example"),
           ("Review Tally", "reviewtally.example"), ("Kitchen Notes blog", "kitchennotes.example"),
           ("City Eats newsletter", "cityeats.example")]
LIT_REASON = ["Grew up cooking this cuisine and compares dishes to home versions.",
              "Writes long, specific posts about regional technique.",
              "Has traveled to the region and names the dishes in the local language.",
              "Former line cook; talks about method, not ambiance."]
GEN_REASON = ["Casual diner, rates on atmosphere and service.", "First-time visitor; no stated background in the cuisine."]
LIT_POS = ["The {dish} is made the way it is in {origin}; nothing here is softened for the neighborhood.",
           "Asked how the {dish} is built and the answer matched what my family does at home.",
           "You can taste the {extra}. Most places in town skip it or substitute.",
           "This is the closest I have found to the {dish} I ate in {origin}."]
LIT_MIX = ["The {dish} is good and mostly faithful, though the seasoning leans a little safer than {origin}."]
GEN_POS = ["Everything arrived hot, the {dish} was seasoned well, and the staff were quick.",
           "Went three times; the {dish} tasted the same every visit.",
           "Friendly place, generous portions, and the {dish} was a standout."]
GEN_NEG = ["Slow service on a busy night and the {dish} came out lukewarm."]
PRACT = ["Plan for a wait after 6pm on weekends; they do not take names by phone.",
         "Parking is easiest a block over; the side street has no meters after 6."]


def seed(c, rnd, p):
    _seed(c, rnd, p)
    _stamp(c, p.t(-48))


def _seed(c, rnd, p):
    ahead = {}
    for hood, (lat, lng) in HOODS.items():
        slug = f"chicago-il/{hood.lower().replace(' ', '-')}"
        ahead[hood] = slug
    city_scene = {"city": [
        {"label": "the scene", "items": [
            {"k": "shape", "v": "Food is organized by neighborhood and immigrant community more than by trend. Pilsen, Albany Park and Chinatown each hold a dense, cuisine-specific core."},
            {"k": "how to eat", "v": "Take the train or a bike; most of the best places have no parking and skip reservations."}]},
        {"label": "what to know", "items": [
            {"k": "cash", "v": "A fair number of the best small places are still cash only."},
            {"k": "timing", "v": "Lunch is cheaper and calmer than dinner almost everywhere on this list."}]}],
        "neighborhoods": [
            {"name": "Pilsen", "note": "Mexican food from several regions in a walkable grid.", "traditions": ["Oaxacan", "Pueblan", "Pan dulce"], "streets": "18th St and Blue Island Ave", "heads_up": "Cash at the taquerias."},
            {"name": "Logan Square", "note": "Mixed: a Polish core, Latin American family spots and a few chef-driven rooms.", "traditions": ["Polish", "Peruvian", "New American"], "streets": "Milwaukee Ave", "heads_up": "Weekend brunch lines."},
            {"name": "Albany Park", "note": "Korean, Syrian and Filipino kitchens along Lawrence Ave.", "traditions": ["Korean", "Syrian", "Filipino"], "streets": "Lawrence Ave", "heads_up": "Many places close by 9pm."},
            {"name": "Chinatown", "note": "Sichuan, Cantonese and hand-pulled noodles within a few blocks.", "traditions": ["Sichuan", "Cantonese", "Lanzhou"], "streets": "Wentworth Ave", "heads_up": "Dim sum waits are long on Sundays."}]}
    c.execute("INSERT INTO areas(slug,level,name,city,borough,country,lat,lng,scene,scene_researched) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("chicago-il", "city", CITY, CITY, "", "United States", 41.8781, -87.6298,
               json.dumps(city_scene), p.d(-12)))
    for hood, (lat, lng) in HOODS.items():
        scene = [{"label": "what this is", "items": [{"k": "character", "v": f"A compact stretch of {hood} where the good places are within a short walk of each other."},
                                                     {"k": "best for", "v": "Eating your way through one tradition in a single afternoon."}]}]
        c.execute("INSERT INTO areas(slug,level,name,city,borough,country,lat,lng,scene,scene_researched) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (ahead[hood], "neighborhood", hood, CITY, "", "United States", lat, lng, json.dumps(scene), p.d(-12)))
    for i, (hood, name, broad, spec, price, disc, dep, exe, dish, origin, extra, summ, order, pros, cons, prac, nl, ng) in enumerate(P):
        lat, lng = HOODS[hood]
        slug = name.lower().replace("'", "").replace("&", "and").replace("í", "i").replace("ó", "o").replace("é", "e")
        slug = "-".join(w for w in "".join(ch if ch.isalnum() else " " for ch in slug).split())
        pid = c.execute(
            "INSERT INTO places(slug,name,address,neighborhood,borough,city,country,lat,lng,cuisine_broad,cuisine_specific,"
            "cuisines_extra,discovery,summary,pros,cons,order_this,price_band,practical,practical_checked,status,researched)"
            " VALUES(?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)",
            (slug, name, f"{1100 + i * 137} N Example St", hood, CITY, "United States",
             round(lat + rnd.uniform(-0.004, 0.004), 5), round(lng + rnd.uniform(-0.004, 0.004), 5), broad, spec, "[]",
             disc, summ, json.dumps(pros), json.dumps(cons), json.dumps(order), price, json.dumps(prac),
             p.d(-rnd.randint(8, 40)), p.d(-12))).lastrowid
        rows = []
        for k in range(nl):
            tmpl = LIT_MIX if (k == nl - 1 and dep < 8) else LIT_POS
            rows.append(("literate", rnd.choice(LIT_REASON), "mixed" if tmpl is LIT_MIX else "positive", "depth", rnd.choice(tmpl)))
        for k in range(ng):
            neg = k == ng - 1 and exe < 8
            rows.append(("general", rnd.choice(GEN_REASON), "negative" if neg else "positive", "execution",
                         rnd.choice(GEN_NEG if neg else GEN_POS)))
        rows.append(("unknown", "", "positive", "practical", rnd.choice(PRACT)))
        for cohort, reason, pol, axis, q in rows:
            src, dom = rnd.choice(SOURCES)
            c.execute("INSERT INTO evidence(place_id,source,url,author,dated,quote,cohort,cohort_reason,polarity,axis,collected)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (pid, src, f"https://{dom}/posts/{rnd.randint(1000, 9999)}", "",
                       p.d(-rnd.randint(20, 400)), q.format(dish=dish, origin=origin, extra=extra), cohort, reason, pol, axis,
                       p.d(-12)))
        lit, tot = nl, len(rows)
        label = lambda n: "none" if n <= 0 else "thin" if n <= 2 else "moderate" if n <= 5 else "strong"
        c.execute("UPDATE places SET depth_score=?, depth_confidence=?, execution_score=?, execution_confidence=? WHERE id=?",
                  (dep, label(lit), exe, label(tot), pid))
    for area, cuisines, found, wrote in [("chicago-il/pilsen", ["Mexican"], 14, 4), ("chicago-il/albany-park", ["Korean", "Syrian", "Filipino"], 11, 4),
                                         ("chicago-il/chinatown", ["Chinese", "Thai"], 12, 4)]:
        c.execute("INSERT INTO runs(area_slug,cuisines,started,finished,candidates_found,places_written,sources_worked,notes)"
                  " VALUES(?,?,?,?,?,?,?,?)",
                  (area, json.dumps(cuisines), p.t(-24 * 12), p.t(-24 * 12 + 1), found, wrote,
                   json.dumps({s: rnd.randint(2, 9) for s, _ in SOURCES}), "Sample output (demo): AI-written research on fictional places."))


def _stamp(con, token):
    """Pin every datetime('now') default column to a token, so the seed is deterministic."""
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'").fetchall():
        for r in con.execute(f'PRAGMA table_info("{t}")').fetchall():
            if "datetime('now')" in str(r[4]):
                con.execute(f'UPDATE "{t}" SET "{r[1]}"=? WHERE "{r[1]}" NOT LIKE \'@%\'', (token,))
