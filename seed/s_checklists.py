"""checklists.db: grocery, packing, work and home lists with ticked items.

Also writes trips.packing_ticks for the Lisbon trip, since those rows point at
checklist ids (list_id, item_id) with no foreign key between the two databases.
"""
DB = ("checklists", "trips")
EXPECT = {"checklists.checklists": 9, "checklists.checklist_items": 90, "trips.packing_ticks": 8}

# name, category, description, protected, source, items: (text, section, checked, qty, note)
LISTS = [
    ("Grocery", "grocery", "Shared with /recipes. Cannot be deleted.", 1, "", [
        ("Spinach", "Produce", 0, "2 bags", ""), ("Lemons", "Produce", 0, "4", ""), ("Cherry tomatoes", "Produce", 1, "1 pint", ""),
        ("Yellow onions", "Produce", 1, "3", ""), ("Garlic", "Produce", 0, "1 head", ""),
        ("Greek yogurt", "Dairy", 0, "32 oz", "Plain, full fat"), ("Eggs", "Dairy", 1, "1 dozen", ""), ("Butter", "Dairy", 0, "1", "Unsalted"),
        ("Rice", "Pantry", 0, "2 lb", ""), ("Canned chickpeas", "Pantry", 0, "4", ""), ("Olive oil", "Pantry", 1, "1", "Running low"),
        ("Coffee beans", "Pantry", 0, "12 oz", "Medium roast"), ("Chicken thighs", "Meat", 0, "2 lb", "Bone-in"), ("Salmon fillets", "Meat", 0, "2", ""),
        ("Sparkling water", "Drinks", 0, "1 case", ""), ("Dish soap", "Household", 1, "1", "")]),
    ("Lisbon apartment groceries", "grocery", "First-night shop for the Alfama apartment.", 0, "trips:LIS:grocery", [
        ("Bread", "Day one", 0, "1 loaf", "Bakery on the corner of the street"), ("Butter", "Day one", 0, "1", ""), ("Coffee", "Day one", 0, "250 g", ""),
        ("Milk", "Day one", 0, "1 L", ""), ("Fruit", "Day one", 0, "1 kg", ""), ("Water", "Day one", 0, "6 bottles", ""),
        ("Olives", "To share", 0, "1 tub", ""), ("Cheese", "To share", 0, "200 g", "")]),
    ("Travel", "packing", "Documents and money.", 0, "", [
        ("Passport", "Documents", 1, "", "Valid until 2030"), ("Boarding passes saved offline", "Documents", 0, "", ""), ("Travel insurance PDF", "Documents", 1, "", ""),
        ("Apartment check-in message", "Documents", 0, "", ""), ("Cards, two of them", "Money", 1, "", "No foreign fee"), ("Euros, 100 in small bills", "Money", 0, "", ""),
        ("Phone eSIM activated", "Money", 0, "", ""), ("Neck pillow", "Flight", 0, "", ""), ("Water bottle, empty", "Flight", 1, "", "")]),
    ("Clothes", "packing", "Seven nights, light layers.", 0, "", [
        ("Underwear", "Basics", 1, "8", ""), ("Socks", "Basics", 1, "8", ""), ("T-shirts", "Tops", 0, "5", ""), ("Linen shirt", "Tops", 0, "2", ""),
        ("Light sweater", "Tops", 0, "1", ""), ("Jeans", "Bottoms", 0, "2", ""), ("Shorts", "Bottoms", 0, "1", ""), ("Rain jacket", "Outer", 1, "1", ""),
        ("Walking shoes", "Shoes", 1, "1", "Broken in"), ("Sandals", "Shoes", 0, "1", ""), ("Swimsuit", "Misc", 0, "1", "")]),
    ("Toiletries", "packing", "Carry-on sized.", 0, "", [
        ("Toothbrush", "", 1, "", ""), ("Toothpaste, travel size", "", 1, "", ""), ("Deodorant", "", 0, "", ""), ("Shampoo bar", "", 0, "", ""),
        ("Razor", "", 0, "", ""), ("Sunscreen, 100 ml", "", 0, "", ""), ("Contact lens case and solution", "", 0, "", ""), ("Medication", "", 1, "", "Two weeks' worth")]),
    ("Tech Gear", "packing", "Chargers and gadgets.", 0, "", [
        ("Phone charger", "", 1, "", ""), ("Laptop and charger", "", 0, "", ""), ("Type F plug adapter", "", 0, "", "On order"), ("Power bank", "", 1, "", ""),
        ("Headphones", "", 1, "", ""), ("Earbuds for the flight", "", 0, "", ""), ("USB-C cable, spare", "", 0, "", "")]),
    ("Beach", "activity", "For the Cascais afternoon, if we go.", 0, "", [
        ("Quick-dry towel", "", 0, "", ""), ("Sunglasses", "", 0, "", ""), ("Reef-safe sunscreen", "", 0, "", ""), ("Book", "", 0, "", "")]),
    ("Juniper & Co opening", "work", "Before doors at 4pm.", 0, "", [
        ("Count the till and log the float", "Bar", 1, "", ""), ("Cut citrus: limes, lemons, oranges", "Bar", 1, "", ""), ("Restock ice wells", "Bar", 1, "", ""),
        ("Check the beer lines and kegs", "Bar", 0, "", ""), ("Wipe down the rail and menus", "Floor", 0, "", ""), ("Music on at low volume", "Floor", 0, "", ""),
        ("Walk the floor for trip hazards", "Floor", 0, "", ""), ("Pass the pre-shift note to the team", "Team", 0, "", "")]),
    ("Juniper & Co close-out", "work", "The routine that cut close-out from 55 to 30 minutes.", 0, "", [
        ("Run the end-of-night report", "Cash", 0, "", ""), ("Count the till against the report", "Cash", 0, "", ""), ("Drop the cash in the safe", "Cash", 0, "", ""),
        ("Wash and flip the glassware", "Bar", 0, "", ""), ("Cover and label open juices", "Bar", 0, "", ""), ("Mop behind the bar", "Floor", 0, "", ""),
        ("Lock the back door and set the alarm", "Last out", 0, "", "")]),
    ("Weekly reset", "home", "Sunday evening, about 40 minutes.", 0, "", [
        ("Change the sheets", "", 1, "", ""), ("Laundry: whites", "", 1, "", ""), ("Clean the bathroom", "", 0, "", ""), ("Take out recycling", "", 0, "", ""),
        ("Plan next week's meals", "", 0, "", ""), ("Review the calendar and the planner", "", 1, "", ""), ("Water the plants", "", 1, "", "")]),
    ("Monthly admin", "personal", "First weekend of the month.", 0, "", [
        ("Check card statements against the ledger", "Money", 0, "", ""), ("Pay the credit cards", "Money", 1, "", ""), ("Move savings transfer", "Money", 1, "", ""),
        ("Back up photos and documents", "Digital", 0, "", ""), ("Renew anything expiring this month", "Digital", 0, "", ""), ("Update the job search tracker", "Career", 0, "", "")]),
]

PACKED = {"Travel": [0, 2, 4], "Clothes": [0, 1, 7, 8], "Toiletries": [0, 1, 7], "Tech Gear": [0, 3, 4]}


def seed(cons, rnd, persona):
    cl, tr = cons["checklists"], cons["trips"]
    lis = tr.execute("SELECT id FROM trips WHERE name LIKE 'Lisbon%'").fetchone()[0]
    den = tr.execute("SELECT id FROM trips WHERE name LIKE 'Denver%'").fetchone()[0]
    for name, cat, desc, prot, source, items in LISTS:
        row = cl.execute("SELECT id FROM checklists WHERE protected=1 AND category=?", (cat,)).fetchone() if prot else None
        if row:  # a booted Hub already made the protected Grocery row; fill it instead
            cid = row[0]
            cl.execute("DELETE FROM checklist_items WHERE checklist_id=?", (cid,))
        else:
            cid = cl.execute("INSERT INTO checklists (name,category,description,protected,source) VALUES (?,?,?,?,?)",
                             (name, cat, desc, prot, source.replace("LIS", str(lis)))).lastrowid
        item_ids = []
        for n, (text, section, checked, qty, note) in enumerate(items):
            item_ids.append(cl.execute("INSERT INTO checklist_items (checklist_id,text,section,checked,sort_order,qty,note) VALUES (?,?,?,?,?,?,?)",
                                       (cid, text, section, 0 if cat == "packing" else checked, n, qty, note)).lastrowid)
        # packing lists keep their ticks on the trip, not on the list
        for idx in PACKED.get(name, []):
            tr.execute("INSERT INTO packing_ticks (trip_id,list_id,item_id,ticked_at) VALUES (?,?,?,?)", (lis, cid, item_ids[idx], persona.t(-30 - idx)))
        if cat == "packing":  # the finished Denver trip: everything was packed
            for idx, iid in enumerate(item_ids):
                tr.execute("INSERT INTO packing_ticks (trip_id,list_id,item_id,ticked_at) VALUES (?,?,?,?)", (den, cid, iid, persona.d(-33, "20:00:00")))


def check(cons):
    cl, tr = cons["checklists"], cons["trips"]
    assert cl.execute("SELECT count(*) FROM checklist_items WHERE checked=1").fetchone()[0] >= 10
    for list_id, item_id in tr.execute("SELECT list_id,item_id FROM packing_ticks"):
        assert cl.execute("SELECT 1 FROM checklist_items WHERE id=? AND checklist_id=?", (item_id, list_id)).fetchone()
