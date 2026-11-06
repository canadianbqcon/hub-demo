"""purchases.db: decisions at every pipeline stage (need to verdict), plus orders.

Brands and models are invented. Model-written text is flagged in decisions.notes
and candidates.notes with a leading "[sample output]".
"""
import json

DB = "purchases"
EXPECT = {"decisions": 6, "candidates": 12, "criteria": 12, "candidate_scores": 20, "specs": 20, "pros_cons": 20,
          "price_points": 10, "orders": 3, "projects": 2, "dimensions": 3, "evidence": 3}

S = "[sample output] "

D = [
    dict(name="Standing desk for the second room", category="Furniture", project=0, stage="need",
         use_case="Work from home two days a week and run the shift rota on weekends.", use_context="Small second room, window on the east wall, 9 by 10 feet.",
         pain_point="The dining table is the wrong height and my back tells me by 3pm.", value_prop="One surface that works sitting or standing, without a wobble.",
         budget_max=600.0, hard="Fits a 48 inch wide space\nNo permanent mounting (rental)", soft="Memory presets, cable tray, matte finish", notes="",
         state={"need": "awaiting-you"}),
    dict(name="Noise-cancelling headphones for the train", category="Audio", project=None, stage="priorities",
         use_case="45 minutes each way on the Brown Line, plus calls from the kitchen.", use_context="Loud train, glasses wearer, mostly podcasts.",
         pain_point="Earbuds leak and the train noise forces the volume up.", value_prop="Quiet enough to hear a podcast at low volume and comfortable with glasses.",
         budget_max=350.0, hard="Wireless\nBattery for two full commutes\nMic good enough for calls", soft="Folds flat, multipoint, USB-C", notes=S + "Dimensions, evidence and constraints below were drafted for review.",
         state={"need": "done", "landscape": "done", "priorities": "awaiting-you"}),
    dict(name="Carry-on backpack for Lisbon", category="Travel", project=1, stage="candidates",
         use_case="One bag for seven nights, flights with strict cabin limits.", use_context="Cobbled hills, trams, a laptop for light work.",
         pain_point="The old duffel hurts after twenty minutes of walking.", value_prop="Fits the cabin limit, opens flat, carries comfortably.",
         budget_max=180.0, hard="Under 40 liters\nLaptop sleeve", soft="Water bottle pocket, luggage strap, lockable zips", notes=S + "Candidate shortlist and research are drafts.",
         state={"need": "done", "landscape": "done", "priorities": "done", "market": "done", "candidates": "running"}),
    dict(name="Type F plug adapter", category="Travel", project=1, stage="compare",
         use_case="Charge a phone and laptop in Portugal.", use_context="Rental apartment with two sockets in the bedroom.",
         pain_point="The cheap adapters fall out of the wall under the weight of a laptop charger.", value_prop="Stays put and charges two things at once.",
         budget_max=35.0, hard="Type F plug\nOne USB-C port", soft="Folding pins, small", notes=S + "Scores are model-drafted; adjust to taste.",
         state={"need": "done", "landscape": "done", "priorities": "done", "market": "done", "candidates": "done", "compare": "awaiting-you"}),
    dict(name="Ergonomic office chair", category="Furniture", project=0, stage="decided",
         use_case="Eight hours of desk work on workdays.", use_context="Home office, hard floor.", pain_point="Lower back ache by afternoon.",
         value_prop="Lumbar support that stays adjusted.", budget_max=450.0, hard="Adjustable lumbar\nSeat depth adjustment", soft="Mesh back", notes=S + "Verdict rationale is a draft.",
         state={"need": "done", "landscape": "done", "priorities": "done", "market": "done", "candidates": "done", "compare": "done", "verdict": "done"}, verdict=1, decided=-21,
         outcome=(4, "Back pain is mostly gone by week two.", "The armrests rattle on the first adjustment.", "yes")),
    dict(name="Burr coffee grinder", category="Kitchen", project=None, stage="decided",
         use_case="One pour-over every morning.", use_context="Small kitchen counter.", pain_point="The blade grinder gives uneven grounds.", value_prop="Consistent grind with little mess.",
         budget_max=200.0, hard="Conical or flat burrs\nUnder 12 inches tall", soft="Quiet, easy to clean", notes=S + "Verdict rationale is a draft.",
         state={"need": "done", "landscape": "done", "priorities": "done", "market": "done", "candidates": "done", "compare": "done", "verdict": "done"}, verdict=0, decided=-6, outcome=None),
]

# per decision: criteria (name, priority, weight), candidates
CRIT = {
    "Ergonomic office chair": [("Lumbar adjustment range", "must-have", 5), ("Seat depth adjustment", "must-have", 4), ("Build quality", "nice-to-have", 4), ("Price", "nice-to-have", 3), ("Assembly effort", "nice-to-have", 1)],
    "Burr coffee grinder": [("Grind consistency", "must-have", 5), ("Footprint", "must-have", 3), ("Noise", "nice-to-have", 2), ("Ease of cleaning", "nice-to-have", 3), ("Price", "nice-to-have", 3)],
    "Type F plug adapter": [("Grip in the socket", "dealbreaker", 5), ("USB-C power", "must-have", 4), ("Size", "nice-to-have", 2), ("Price", "nice-to-have", 3)],
    "Carry-on backpack for Lisbon": [("Fits cabin limit", "dealbreaker", 5), ("Carry comfort", "must-have", 5), ("Opens flat", "nice-to-have", 3), ("Weight", "nice-to-have", 2), ("Price", "nice-to-have", 3)],
    "Noise-cancelling headphones for the train": [("Noise cancelling strength", "must-have", 5), ("Comfort with glasses", "must-have", 4), ("Battery life", "must-have", 3), ("Call quality", "nice-to-have", 2)],
    "Standing desk for the second room": [("Stability at standing height", "must-have", 5), ("Width", "must-have", 3), ("Price", "nice-to-have", 3)],
}

# name, vendor, price, status, rank, scores per criterion, specs, pros, cons, assessment
CAND = {
    "Ergonomic office chair": [
        ("Halden Task Chair H2", "Halden Furniture", 389.0, "chosen", 1, [9, 9, 8, 7, 5], [("Lumbar range", "4 inches, height and depth"), ("Seat depth", "Adjustable, 3 inches"), ("Weight rating", "300 lb")],
         ["Lumbar support follows the curve of the back", "Seat depth slides for shorter legs"], ["Armrests rattle until tightened"], "Meets both must-haves and sits at the knee of the price curve."),
        ("Brightside Mesh Chair", "Brightside", 279.0, "considering", 2, [6, 4, 6, 9, 8], [("Lumbar range", "Fixed pad"), ("Seat depth", "Fixed"), ("Weight rating", "250 lb")],
         ["Cheapest of the shortlist", "Assembles in ten minutes"], ["No seat depth adjustment: fails a must-have"], "Good chair for the price, but misses the seat-depth requirement."),
        ("Ardent Pro 500", "Ardent Seating", 649.0, "rejected", 3, [10, 9, 9, 2, 4], [("Lumbar range", "5 inches"), ("Seat depth", "Adjustable"), ("Weight rating", "350 lb")],
         ["Best build on the list"], ["Over budget by $199"], "Best of the three, outside the budget."),
    ],
    "Burr coffee grinder": [
        ("Wren Conical Mini", "Wren Coffee", 149.0, "chosen", 1, [8, 9, 8, 8, 8], [("Burr", "40 mm conical steel"), ("Height", "11.5 inches"), ("Settings", "40")],
         ["Even grounds at pour-over settings", "Small footprint"], ["Hopper is small"], "Consistent grind at a price under the budget."),
        ("Marlow Flat E-1", "Marlow", 189.0, "considering", 2, [9, 6, 6, 7, 6], [("Burr", "54 mm flat"), ("Height", "13 inches"), ("Settings", "Stepless")],
         ["Best consistency"], ["Too tall for the shelf"], "Excellent grinder that fails the height limit."),
    ],
    "Type F plug adapter": [
        ("Kettle Plug Duo", "Kettle & Co", 24.0, "considering", 1, [9, 9, 6, 7], [("Ports", "1 USB-C 30W, 1 USB-A"), ("Weight", "96 g")], ["Holds a laptop charger firmly"], ["A little bulky"], "Strong grip and enough power for a laptop."),
        ("Sprocket Mini", "Sprocket", 12.0, "considering", 2, [4, 0, 9, 10], [("Ports", "None"), ("Weight", "22 g")], ["Tiny"], ["No USB-C; falls out under weight"], "Cheap but fails the grip test."),
        ("Voltaic 3-Way", "Voltaic", 31.0, "considering", 3, [8, 8, 4, 5], [("Ports", "2 USB-C, 1 USB-A"), ("Weight", "148 g")], ["Charges three devices"], ["Large for a carry-on"], "Overbuilt for a week of travel."),
    ],
    "Carry-on backpack for Lisbon": [
        ("Trailmark 38", "Trailmark", 159.0, "considering", 1, [9, 8, 9, 6, 5], [("Volume", "38 L"), ("Weight", "2.4 lb"), ("Laptop sleeve", "16 inch")], ["Opens clamshell", "Hip belt holds the weight"], ["Pricey"], "Fits the cabin limit with room to spare."),
        ("Cinder Daypack Plus", "Cinder", 119.0, "considering", 2, [7, 7, 5, 8, 8], [("Volume", "32 L"), ("Weight", "1.9 lb"), ("Laptop sleeve", "15 inch")], ["Light"], ["Top-loading only"], "Light and cheaper, harder to pack."),
        ("Overland 40", "Overland Goods", 175.0, "considering", 3, [6, 9, 9, 4, 4], [("Volume", "40 L"), ("Weight", "3.3 lb"), ("Laptop sleeve", "16 inch")], ["Excellent harness"], ["At the edge of the size limit"], "Most comfortable, but risky at the gate."),
        ("Sundry Weekender", "Sundry", 89.0, "rejected", 4, [3, 4, 6, 7, 10], [("Volume", "44 L"), ("Weight", "1.6 lb"), ("Laptop sleeve", "None")], ["Cheap"], ["Oversize for cabin limits"], "Fails the size check."),
    ],
    "Noise-cancelling headphones for the train": [
        ("Quill NC700", "Quill Audio", 329.0, "considering", None, [], [("Battery", "30 hours"), ("Weight", "250 g")], [], [], ""),
        ("Brine Over-Ear 3", "Brine", 249.0, "considering", None, [], [("Battery", "38 hours"), ("Weight", "270 g")], [], [], ""),
    ],
}

PRICES = {  # candidate name -> list of (vendor, price, days ago, in stock)
    "Halden Task Chair H2": [("Halden Furniture", 429.0, 40, 1), ("Halden Furniture", 389.0, 24, 1), ("Halden Furniture", 389.0, 2, 1)],
    "Wren Conical Mini": [("Wren Coffee", 159.0, 30, 1), ("Wren Coffee", 149.0, 8, 1)],
    "Trailmark 38": [("Trailmark", 169.0, 14, 1), ("Trailmark", 159.0, 3, 1)],
    "Kettle Plug Duo": [("Kettle & Co", 26.0, 9, 1), ("Kettle & Co", 24.0, 1, 1)],
    "Overland 40": [("Overland Goods", 175.0, 5, 0)],
}

ORDERS = [  # decision idx, item, vendor, number, ordered, total, carrier, tracking, ship, eta, delivered, return_days
    (4, "Halden Task Chair H2", "Halden Furniture", "HF-204117", -19, 389.0 + 31.5, "Freight carrier", "FRT2741180", "delivered", None, -14, 30),
    (5, "Wren Conical Mini", "Wren Coffee", "WC-88231", -5, 149.0 + 12.1, "UPS", "1Z84A7710311005512", "shipped", 2, None, 30),
    (None, "Phone case, clear", "Pocketry", "PK-10442", -9, 19.0, "USPS", "9400111899223456781234", "delivered", None, -6, 30),
]


def seed(con, rnd, persona):
    ex = con.execute
    proj = [ex("INSERT INTO projects (name,status,category,notes,created,updated) VALUES (?,?,?,?,?,?)", (n, "active", c, nt, persona.d(-50), persona.d(-3))).lastrowid
            for n, c, nt in (("Home office refresh", "Furniture", "Desk, chair and lighting for the second room."),
                             ("Lisbon trip gear", "Travel", "Bag and adapters for the Lisbon trip."))]
    dec_ids, cand_ids = [], {}
    for n, d in enumerate(D):
        did = ex("INSERT INTO decisions (name,category,use_case,purchase_type,stage,time_horizon,depth,budget_max,currency,hard_constraints,soft_preferences,"
                 "verdict_candidate_id,verdict_reason,notes,created,updated,project_id,use_context,pain_point,value_prop,outcome_rating,outcome_well,outcome_regret,"
                 "would_repurchase,decided_date,section_state) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (d["name"], d["category"], d["use_case"], "one-time-product", d["stage"], "this month" if d["stage"] != "decided" else "", "standard", d["budget_max"], "USD",
                  d["hard"], d["soft"], "", d["notes"], persona.d(-45 + n * 5), persona.d(-(n % 4) - 1), proj[d["project"]] if d["project"] is not None else None,
                  d["use_context"], d["pain_point"], d["value_prop"], *(d.get("outcome") or (None, "", "", "")),
                  persona.d(d["decided"]) if d.get("decided") else "",
                  json.dumps(d["state"]))).lastrowid
        dec_ids.append(did)
        crit_ids = [ex("INSERT INTO criteria (decision_id,name,priority,weight,notes) VALUES (?,?,?,?,?)", (did, nm, pr, w, "")).lastrowid
                    for nm, pr, w in CRIT.get(d["name"], [])]
        cand_ids[d["name"]] = []
        for rank_i, c in enumerate(CAND.get(d["name"], [])):
            nm, vendor, price, status, rank, scores, specs, pros, cons, assess = c
            cid = ex("INSERT INTO candidates (decision_id,name,vendor,base_price,currency,url,image_url,status,rank,ecosystem_notes,return_policy,warranty,notes,assessment) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (did, nm, vendor, price, "USD", f"https://example.com/shop/{nm.lower().replace(' ', '-')}", "", status, rank, "", "30-day returns", "1 year limited",
                      S + "Notes below are model-drafted." if assess else "", assess)).lastrowid
            cand_ids[d["name"]].append(cid)
            for k, v in specs:
                ex("INSERT INTO specs (candidate_id,criterion_id,key,value) VALUES (?,NULL,?,?)", (cid, k, v))
            for t in pros:
                ex("INSERT INTO pros_cons (candidate_id,kind,text) VALUES (?,?,?)", (cid, "pro", t))
            for t in cons:
                ex("INSERT INTO pros_cons (candidate_id,kind,text) VALUES (?,?,?)", (cid, "con", t))
            for crit, sc in zip(crit_ids, scores):
                ex("INSERT INTO candidate_scores (candidate_id,criterion_id,score,notes) VALUES (?,?,?,?)", (cid, crit, float(sc), ""))
            for vend, p, ago, stock in PRICES.get(nm, []):
                ex("INSERT INTO price_points (candidate_id,vendor,price,currency,url,observed_on,in_stock,channel_notes,notes) VALUES (?,?,?,?,?,?,?,?,?)",
                   (cid, vend, p, "USD", f"https://example.com/shop/{nm.lower().replace(' ', '-')}", persona.d(-ago), stock, "", ""))
        if d["name"] == "Ergonomic office chair" or d["name"] == "Type F plug adapter":
            for k, (src, title, author, take, sent) in enumerate([
                ("article", "Six task chairs after a year of use", "Ellis Park", "Lumbar adjustment matters more than the headrest; the Halden's held its setting after months.", "positive"),
                ("forum", "Seat depth: why short people sit badly", "r/ergonomics thread", "Fixed-depth seats are the most common reason for returns.", "mixed")]):
                ex("INSERT INTO reviews (decision_id,candidate_id,source_type,url,title,author,takeaway,sentiment,is_current_version,notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (did, cand_ids[d["name"]][0], src, "https://example.com/review/" + str(k + 1), title, author, take, sent, 1, S))
        if d.get("verdict") is not None:
            winner = cand_ids[d["name"]][d["verdict"]]
            ex("UPDATE decisions SET verdict_candidate_id=?, verdict_reason=? WHERE id=?", (winner,
               "Meets every must-have, under budget, and the price had already fallen twice. The runner-up missed a requirement.", did))
            ex("INSERT INTO budget_entries (decision_id,label,planned_amount,actual_amount,currency,paid_on,payment_method,status) VALUES (?,?,?,?,?,?,?,?)",
               (did, "Purchase", d["budget_max"], CAND[d["name"]][d["verdict"]][2], "USD", persona.d(d["decided"]), "Card", "paid"))

    # headphones: the research layer awaiting priorities
    hp = dec_ids[1]
    dims = [("Noise cancelling strength", "How much low-frequency train noise is removed.", "Measured in decibels reduced; below 25 dB is weak.", "Light: 15 to 20 dB", "Good: 25 to 30 dB", "Best: 35 dB plus", "Typical to high", "A rattling train needs the upper half."),
            ("Comfort with glasses", "Pressure on the temples during long wear.", "Clamping force and pad softness.", "Tight clamp", "Soft pads, moderate clamp", "Memory foam, wide cups", "Soft pads or better", "Forty-five minutes with frames on is the test."),
            ("Battery life", "Hours of playback with noise cancelling on.", "20 to 60 hours.", "20 hours", "30 hours", "50 hours", "30 hours or more", "Two commutes plus calls need roughly 3 hours a day.")]
    dim_ids = [ex("INSERT INTO dimensions (decision_id,name,explainer,range_text,tier_low,tier_typical,tier_high,fit_zone,fit_reasoning,sort) VALUES (?,?,?,?,?,?,?,?,?,?)", (hp, *x, i)).lastrowid for i, x in enumerate(dims)]
    for nm, summ in (("Quill Audio", "Strong noise cancelling and a heavier build; priced at the top."), ("Brine", "Lighter and cheaper, with long battery life and weaker call mics.")):
        ex("INSERT INTO brands (decision_id,name,summary,sort) VALUES (?,?,?,?)", (hp, nm, summ, 0))
    for st, subj, claim, src, longev, grade, why in (
        ("dimension", "Noise cancelling strength", "Over-ear designs reduce low-frequency rail noise more than in-ear designs.", "review lab", "recent", "B", "Two independent measurements agree."),
        ("dimension", "Comfort with glasses", "Wide, soft pads reduce temple pressure.", "forum", "long-term", "C", "Anecdotal, but consistent across threads."),
        ("brand", "Quill Audio", "Replacement ear pads are sold for five years after launch.", "vendor", "5 years", "B", "Vendor page, matches a third-party check."),
    ):
        ex("INSERT INTO evidence (decision_id,subject_type,subject,candidate_id,claim,source_type,source_url,longevity,grade,grade_reason) VALUES (?,?,?,NULL,?,?,?,?,?,?)",
           (hp, st, subj, claim, src, "https://example.com/source", longev, grade, why))
    ex("INSERT INTO price_steps (decision_id,dimension_id,label,spec_value,price,per_unit_note,knee,note) VALUES (?,?,?,?,?,?,?,?)", (hp, dim_ids[0], "Entry", "20 dB", 129.0, "", 0, ""))
    ex("INSERT INTO price_steps (decision_id,dimension_id,label,spec_value,price,per_unit_note,knee,note) VALUES (?,?,?,?,?,?,?,?)", (hp, dim_ids[0], "Good", "28 dB", 249.0, "$6 per dB", 1, "The knee: most of the benefit."))
    ex("INSERT INTO price_steps (decision_id,dimension_id,label,spec_value,price,per_unit_note,knee,note) VALUES (?,?,?,?,?,?,?,?)", (hp, dim_ids[0], "Best", "36 dB", 399.0, "$19 per dB", 0, ""))
    for nm, req, st, origin, note in (("Wireless", "No cable", "locked", "need", ""), ("Battery", "At least 30 hours", "locked", "need", ""), ("Foldable", "Folds flat for a bag", "proposed", "research", "Nice for the commute bag.")):
        ex("INSERT INTO constraints (decision_id,name,requirement,status,origin,note) VALUES (?,?,?,?,?,?)", (hp, nm, req, st, origin, note))

    # orders
    oids = []
    for (didx, item, vendor, num, ordered, total, carrier, trk, ship, eta, delivered, rd) in ORDERS:
        oid = ex("INSERT INTO orders (decision_id,item,vendor,url,image_url,order_number,ordered_on,total,currency,carrier,tracking_number,ship_status,eta,delivered_on,return_days,return_by,return_policy,returned_on,source,notes,created,updated,delivery_address,delivery_lat,delivery_lng) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (dec_ids[didx] if didx is not None else None, item, vendor, "", "", num, persona.d(ordered), total, "USD", carrier, trk, ship,
                  persona.d(eta) if eta is not None else "", persona.d(delivered) if delivered is not None else "", rd,
                  persona.d((delivered if delivered is not None else ordered + 4) + rd), "30-day returns", "", "manual", "", persona.d(ordered), persona.d(delivered if delivered is not None else ordered + 1),
                  "1420 W Fullerton Ave, Chicago, IL 60614", None, None)).lastrowid
        oids.append(oid)
        ex("INSERT INTO order_emails (message_id,order_id,kind,sender,subject,received) VALUES (?,?,?,?,?,?)",
           (f"demo-msg-order-{oid:03d}-a", oid, "confirmation", f"orders@{vendor.lower().replace(' ', '')}.example.com", f"Your order {num} is confirmed", persona.d(ordered, "13:05:00")))
    ex("UPDATE decisions SET order_vendor=?, order_number=?, order_placed=?, order_total=?, ship_status=?, carrier=?, tracking_number=?, eta=? WHERE id=?",
       ("Wren Coffee", "WC-88231", persona.d(-5), 161.1, "shipped", "UPS", "1Z84A7710311005512", persona.d(2), dec_ids[5]))


def check(con):
    stages = {r[0] for r in con.execute("SELECT stage FROM decisions")}
    assert {"need", "priorities", "candidates", "compare", "decided"} <= stages, stages
    assert con.execute("SELECT count(*) FROM decisions WHERE stage='decided' AND verdict_candidate_id IS NULL").fetchone()[0] == 0
