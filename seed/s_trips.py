"""trips.db: one upcoming trip (Lisbon) and one finished (Denver), fully populated.

Packing ticks live here but need checklist ids, so s_checklists writes them.
"""
import json

DB = "trips"
EXPECT = {"trips": 2, "members": 6, "activities": 18, "flights": 6, "housing": 3, "transportation": 3,
          "expenses": 5, "airports": 3, "activity_opinions": 8, "guest_codes": 3}

# name, location, description, cost, url, notes, tags, lat, lng, days, hours, p, c, status, day offset, time, end
LISBON = [
    ("Pastéis de Belém", "Rua de Belém 84-92, 1300-085 Lisboa, Portugal",
     "The bakery that has made the custard tarts since 1837 from a recipe kept by a handful of people. The line looks long but moves quickly, and the back rooms have tiled dining halls most visitors never see. Order them warm with cinnamon and powdered sugar. Pair it with the nearby monastery to make a morning of it.",
     12, "https://pasteisdebelem.pt", "Go before 9:30 or after 3 to dodge the worst line. Sit inside rather than queue at the takeaway counter.", ["Food", "Breakfast"], 38.6975, -9.2033, "Daily", "8AM-11PM", 8, 9, "scheduled", 7, "09:00", "10:00"),
    ("Mosteiro dos Jerónimos", "Praça do Império, 1400-206 Lisboa, Portugal",
     "A 16th-century monastery in the Manueline style, with a two-storey cloister covered in carved stone ropes and sea creatures. Vasco da Gama's tomb is inside the church. Allow about 90 minutes. The church is free; the cloister takes a ticket.",
     18, "https://www.patrimoniocultural.gov.pt", "Buy the ticket online to skip the cashier line. Closed Mondays.", ["Sights", "Time Sensitive"], 38.6979, -9.2068, "Tue-Sun", "10AM-6PM", 8, 9, "scheduled", 7, "10:15", "12:00"),
    ("Castelo de São Jorge", "R. de Santa Cruz do Castelo, 1100-129 Lisboa, Portugal",
     "A Moorish hilltop castle with ramparts you can walk and the best all-round view of the city and the river. The grounds have peacocks and a small archaeology display. It is a steep walk up from Alfama, which is part of the fun.",
     17, "https://castelodesaojorge.pt", "Go late afternoon for the light. Wear shoes with grip; the stones are polished.", ["Sights"], 38.7139, -9.1334, "Daily", "9AM-9PM", 8, 8, "scheduled", 8, "16:30", "18:30"),
    ("Time Out Market", "Av. 24 de Julho 49, 1200-479 Lisboa, Portugal",
     "A big food hall in the old Ribeira market with stalls from well-known local chefs. Good for a group that cannot agree, since everyone can order from a different counter and meet at the long tables. Expect noise and crowds at peak hours.",
     25, "https://www.timeoutmarket.com/lisboa", "Eat at 2pm instead of 1pm. Grab a table first, then split up.", ["Food", "Lunch"], 38.7068, -9.1459, "Daily", "12PM-12AM", 7, 7, "scheduled", 8, "13:30", "15:00"),
    ("Tram 28 ride (early)", "Praça Martim Moniz, 1100-341 Lisboa, Portugal",
     "The yellow tram that rattles through Alfama, Graça and Estrela. It is both transport and attraction, which means it is packed all day. Board at the first stop early in the morning to get a seat and see the narrow streets empty.",
     3, "https://www.carris.pt", "Tap a Viva Viagem card instead of paying the driver. Watch your pockets.", ["Sights", "Transit"], 38.7168, -9.1360, "Daily", "6AM-9PM", 6, 7, "considering", 0, "", ""),
    ("LX Factory", "Rua Rodrigues de Faria 103, 1300-501 Lisboa, Portugal",
     "A former textile complex under the 25 de Abril bridge, now full of studios, bookshops, cafes and restaurants. It is a good place to spend an unplanned afternoon and pick up gifts. The bookshop in the old printing hall is worth the stop alone.",
     30, "https://lxfactory.com", "Sundays have a small market. Many shops close on Mondays.", ["Shopping", "Food"], 38.7036, -9.1788, "Daily", "10AM-12AM", 7, 8, "scheduled", 9, "15:00", "18:00"),
    ("Cervejaria Ramiro", "Av. Almirante Reis 1 H, 1150-007 Lisboa, Portugal",
     "A famous seafood house that does tiger prawns, goose barnacles and clams by the kilo, then finishes with a small steak sandwich. It is loud and fast, and the point is the shellfish. Order by weight and ask the price before you say yes.",
     65, "https://www.cervejariaramiro.com", "No reservations for small groups, so arrive at 6:30pm. Closed Mondays.", ["Food", "Dinner", "Time Sensitive"], 38.7226, -9.1347, "Tue-Sun", "12PM-12AM", 9, 9, "scheduled", 9, "19:00", "21:00"),
    ("Day trip to Sintra: Pena Palace", "Estrada da Pena, 2710-609 Sintra, Portugal",
     "A colourful hilltop palace in a forested range 40 minutes from Lisbon by train. The terraces look over the Atlantic on a clear day. Combine it with the walk through the Moorish Castle ruins and a late lunch in the old town.",
     20, "https://www.parquesdesintra.pt", "Take the 8:00 train and the 434 bus up. Bring a layer; it is cooler and cloudier than the city.", ["Sights", "Day Trip", "Time Sensitive"], 38.7876, -9.3906, "Daily", "9:30AM-6:30PM", 9, 9, "scheduled", 10, "09:00", "17:00"),
    ("Fado evening in Alfama", "Rua Diário de Notícias 39, 1200-141 Lisboa, Portugal",
     "A small tavern that mixes fado performances with dinner. The singing is close enough to feel in the room, and the audience goes quiet for each song. It is the most Lisbon thing on the list and worth the cover charge.",
     55, "https://example.com/fado-tavern", "Book a table in the first seating. Phones away during the songs.", ["Entertainment", "Dinner", "Time Sensitive"], 38.7108, -9.1442, "Wed-Mon", "7PM-1AM", 8, 8, "deciding", 0, "", ""),
    ("Miradouro da Senhora do Monte", "Largo Monte, 1170-107 Lisboa, Portugal",
     "The highest viewpoint in the old city, with a view over the castle, the river and the whole of Baixa. It is a quiet spot for sunset, with a kiosk selling drinks. Bring a jacket because the wind picks up.",
     5, "https://example.com/miradouro", "Walk up from Graça rather than taking the tram. Sunset is the busy hour.", ["Sights", "Free"], 38.7192, -9.1328, "Daily", "Open", 7, 8, "considering", 0, "", ""),
    ("Ginjinha at A Ginjinha", "Largo de São Domingos 8, 1150-320 Lisboa, Portugal",
     "A standing-room hole in the wall that has been serving the local sour cherry liqueur for more than a century. You order a small plastic cup, with or without fruit, and drink it on the square. It takes about five minutes.",
     3, "https://example.com/ginjinha", "Say 'com elas' for the fruit. Cash is easier.", ["Food", "Drinks"], 38.7142, -9.1394, "Daily", "9AM-10PM", 6, 7, "considering", 0, "", ""),
    ("Oceanário de Lisboa", "Esplanada D. Carlos I, 1990-005 Lisboa, Portugal",
     "One of Europe's largest aquariums, built around a central tank that holds sharks, rays and sunfish. The temporary exhibition is usually good. It is a decent plan B for a rainy afternoon, though the park around it is the best part on a dry day.",
     25, "https://www.oceanario.pt", "Weekday mornings are quietest.", ["Sights", "Rainy Day"], 38.7634, -9.0937, "Daily", "10AM-8PM", 5, 7, "skip", 0, "", ""),
]

DENVER = [
    ("Red Rocks Amphitheatre", "18300 W Alameda Pkwy, Morrison, CO 80465",
     "A natural sandstone amphitheatre where the seats are cut into the hillside, with Denver visible in the distance. We went for a daytime visit and the climb up the steps. Concerts sell out months ahead, so even the empty visit is worth it.",
     0, "https://www.redrocksonline.com", "Free to visit on non-show days. Bring water; the stairs are steeper than they look.", ["Sights", "Free"], 39.6654, -105.2057, "Daily", "5AM-11PM", 9, 9, "scheduled", -30, "10:00", "12:30"),
    ("Denver Union Station", "1701 Wynkoop St, Denver, CO 80202",
     "The restored 1914 train hall with a grand waiting room used as a lounge, plus restaurants and a bookshop. It is a good first stop after the airport train and the best place to meet people coming in on different flights.",
     20, "https://www.unionstationindenver.com", "The A line from the airport stops here directly.", ["Food", "Transit"], 39.7529, -104.9997, "Daily", "6AM-12AM", 8, 8, "scheduled", -31, "15:00", "17:00"),
    ("Denver Art Museum", "100 W 14th Ave Pkwy, Denver, CO 80204",
     "A large art museum with a strong collection of Western American and Indigenous art, split across two buildings. The Hamilton building's angular titanium shell is itself a sight. Plan about two hours without trying to see everything.",
     22, "https://www.denverartmuseum.org", "Free on the first Saturday of the month. Closed Tuesdays.", ["Sights", "Culture"], 39.7372, -104.9894, "Wed-Sun", "10AM-5PM", 7, 8, "scheduled", -29, "11:00", "13:30"),
    ("Larimer Square", "1430 Larimer St, Denver, CO 80202",
     "A restored historic block of brick buildings with string lights across the street, lined with restaurants, bars and shops. It is tourist-heavy but pleasant at dusk, and a short walk from Union Station.",
     40, "https://www.larimersquare.com", "Go after dark for the lights. Reservations help on Friday.", ["Food", "Dinner"], 39.7497, -104.9996, "Daily", "11AM-12AM", 7, 7, "scheduled", -29, "18:30", "21:00"),
    ("Meow Wolf Convergence Station", "1338 1st St, Denver, CO 80204",
     "A huge immersive art installation: four connected worlds to explore, with hidden doors, light rooms and a story you can follow if you want. Allow three hours. It was the group's favorite thing on the trip.",
     45, "https://meowwolf.com/visit/denver", "Book timed tickets for the morning. Wear comfortable shoes and skip the big bag.", ["Entertainment", "Time Sensitive"], 39.7406, -105.0013, "Daily", "10AM-10PM", 9, 9, "scheduled", -28, "10:00", "13:30"),
    ("The Source Market Hall", "3350 Brighton Blvd, Denver, CO 80216",
     "An old brick foundry converted into a market hall with bakers, a butcher, tacos, ramen and a coffee roaster. Good for a slow lunch while the group splits up and shares. The hotel upstairs has a rooftop bar.",
     28, "https://www.thesourcedenver.com", "Weekdays are calm; weekends fill up by noon.", ["Food", "Lunch"], 39.7676, -104.9757, "Daily", "7AM-10PM", 8, 8, "scheduled", -28, "14:30", "16:00"),
    ("Hike at Lookout Mountain", "Lookout Mountain Rd, Golden, CO 80401",
     "A short, steep hike with wide views over the plains. We cut it from the plan after the snow forecast turned bad and the trailhead road iced over.",
     0, "https://example.com/lookout-mountain", "Check the road conditions the morning of.", ["Outdoors"], 39.7311, -105.2381, "Daily", "Sunrise-sunset", 7, 8, "skip", 0, "", ""),
]

LOG = {
    "Red Rocks Amphitheatre": "Cold and bright. Ran the steps twice; Dev won. Roughly 90 minutes door to door from the bungalow.",
    "Denver Union Station": "Everyone landed within an hour of each other. The lounge chairs by the fireplace were taken, so we stood.",
    "Denver Art Museum": "Spent most of the time in the Western collection. Skipped the cafe; the line was long.",
    "Larimer Square": "Table for four at 6:45, no wait. The string lights were worth the cold. Dinner ran $248 with tip.",
    "Meow Wolf Convergence Station": "Best part of the trip. Booked the 10:00 slot and stayed almost four hours.",
    "The Source Market Hall": "Tacos and the ramen counter. Quiet on a Sunday afternoon.",
}

MEMBERS_LIS = ["Sam Rivera", "Priya Nair", "Hana Mori"]
MEMBERS_DEN = ["Sam Rivera", "Marcus Bell", "Elena Ortiz", "Dev Chandra"]


def _activity(con, trip_id, a, log=False):
    (name, loc, desc, cost, url, notes, tags, lat, lng, days, hours, p, c, status, day, time, end) = a
    score = round(0.25 * p + 0.75 * c, 2)
    con.execute(
        "INSERT INTO activities (trip_id,name,location,description,cost,url,notes,status,tags,scheduled_date,scheduled_time,lat,lng,"
        "score,score_p,score_c,operating_days,operating_hours,scheduled_time_end,decision_reason,true_score,cal_event_id,group_identity,log_notes,split_with) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (trip_id, name, loc, desc, float(cost), url, notes, status, json.dumps(tags),
         _day(day) if status == "scheduled" else "", time if status == "scheduled" else "", lat, lng, score, float(p), float(c),
         days, hours, end if status == "scheduled" else "",
         "Cut for time and weather." if status == "skip" else "", score, "", "", 
         (LOG.get(name, "") if log else ""), ""))
    return con.execute("SELECT last_insert_rowid()").fetchone()[0]


_P = None


def _day(n):
    return _P.d(n)


def seed(con, rnd, persona):
    global _P
    _P = persona
    ex = con.execute
    for iata, name, lat, lng, tz in [("ORD", "Chicago O'Hare International Airport", 41.9742, -87.9073, "America/Chicago"),
                                      ("LIS", "Humberto Delgado Airport", 38.7742, -9.1342, "Europe/Lisbon"),
                                      ("DEN", "Denver International Airport", 39.8561, -104.6737, "America/Denver")]:
        ex("INSERT INTO airports (iata,name,lat,lng,resolved_at,tz) VALUES (?,?,?,?,?,?)", (iata, name, lat, lng, persona.d(-40), tz))

    lis = ex("INSERT INTO trips (name,destination,start_date,end_date,cal_event_id,notes,trip_interests,cal_status,grocery_extras) VALUES (?,?,?,?,NULL,?,?,?,?)",
             ("Lisbon Long Weekend", "Lisbon, Portugal", persona.d(6), persona.d(13),
              "Seven nights. Alfama apartment, one day trip to Sintra, mostly walking. Landing early Saturday, so the apartment needs a luggage hold.",
              "food, viewpoints, history, easy walking", "", "")).lastrowid
    den = ex("INSERT INTO trips (name,destination,start_date,end_date,cal_event_id,notes,trip_interests,cal_status,grocery_extras) VALUES (?,?,?,?,NULL,?,?,?,?)",
             ("Denver Snow Weekend", "Denver, CO", persona.d(-31), persona.d(-27),
              "Long weekend with the old roommates. Snow came in Saturday, so the hike was cut.",
              "food, art, live music", "", "")).lastrowid

    mem = {}
    for tid, names in ((lis, MEMBERS_LIS), (den, MEMBERS_DEN)):
        for nm in names:
            mem[(tid, nm)] = ex("INSERT INTO members (trip_id,name,email,notes,contact_slug,card_header,card_shimmer,card_border) VALUES (?,?,?,?,?,?,?,?)",
                                (tid, nm, persona.EMAIL if nm == persona.NAME else nm.lower().replace(" ", ".") + "@example.com",
                                 "Trip owner." if nm == persona.NAME else "", "", "", "", "")).lastrowid

    # flights
    def flight(tid, direction, who, airline, num, a, b, dep, arr, conf, cost, tfrom, tto, pts=None, prog="", status="booked", notes=""):
        ex("INSERT INTO flights (trip_id,direction,airline,flight_num,from_airport,to_airport,departure_time,arrival_time,confirmation,cost,notes,status,"
           "terminal_from,terminal_to,location,passenger,points_total,points_program,points_transfer,paid_by,cents_per_point,split_with) "
           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (tid, direction, airline, num, a, b, dep, arr, conf, cost, notes, status, tfrom, tto, "", who, pts, prog,
            None, "Sam Rivera", 1.4 if pts else None, ""))
    for who, conf, cost in (("Sam Rivera", "QX7M2P", 612.0), ("Priya Nair", "QX7M2P", 612.0), ("Hana Mori", "RB4T9K", 640.0)):
        flight(lis, "outbound", who, "TAP Air Portugal", "TP 210", "ORD", "LIS", persona.d(6, "18:40"), persona.d(7, "08:25"), conf, cost, "5", "1",
               notes="Overnight; lands before the apartment is ready.")
        flight(lis, "return", who, "TAP Air Portugal", "TP 211", "LIS", "ORD", persona.d(13, "10:15"), persona.d(13, "13:50"), conf, cost, "1", "5")
    for who, cost in (("Sam Rivera", 214.0), ("Marcus Bell", 198.0), ("Elena Ortiz", 231.0), ("Dev Chandra", 205.0)):
        flight(den, "outbound", who, "United", "UA 1174", "ORD", "DEN", persona.d(-31, "07:05"), persona.d(-31, "09:10"), "DN" + who[:2].upper() + "31", cost, "1", "B")
        flight(den, "return", who, "United", "UA 1530", "DEN", "ORD", persona.d(-27, "17:30"), persona.d(-27, "21:00"), "DN" + who[:2].upper() + "27", 0.0, "B", "1")

    # housing
    def housing(tid, **kw):
        base = dict(name="", address="", check_in="", check_out="", confirmation_code="", nightly_rate=None, total_cost=None, url="", notes="",
                    status="considering", lat=None, lng=None, guests=None, bedrooms=None, beds=None, baths=None, parking="", area="", rating=None,
                    reviews=None, hot_tub=0, pool_table=0, pool=0, host="", check_in_method="", house_rules="", checkout_tasks="",
                    cancellation_deadline="", deposit=None, amenities="", wifi="", points_nightly=None, points_total=None, points_program="",
                    points_transfer=None, stay_type="rental", paid_by="", cents_per_point=None, photos="", wifi_ssid="", wifi_pass="", room_type="",
                    loyalty="", incidental_hold="", resort_fee="", breakfast="", late_checkout="", split_with="")
        base.update(kw)
        base["trip_id"] = tid
        cols = ",".join(base)
        ex(f"INSERT INTO housing ({cols}) VALUES ({','.join('?' * len(base))})", list(base.values()))
    housing(lis, name="Casa da Alfama, three-bedroom apartment", address="Rua de São Miguel 18, 1100-544 Lisboa, Portugal",
            check_in=persona.d(7), check_out=persona.d(13), confirmation_code="HMX4829KQ2", nightly_rate=186.0, total_cost=1290.0,
            url="https://example.com/stays/alfama-3br", notes="Fourth floor, no lift. Host holds luggage from 9am.", status="booked",
            lat=38.7110, lng=-9.1286, guests=3, bedrooms=3.0, beds=4, baths=2.0, parking="None", area="Alfama", rating=4.8, reviews=212,
            host="Inês", check_in_method="Key box, code sent the day before", house_rules="Quiet after 10pm. No parties.",
            checkout_tasks="Strip beds into the hamper; leave keys in the box.", cancellation_deadline=persona.d(-2), deposit=0.0,
            amenities="Washer, balcony, air conditioning, kitchen", wifi="Yes", paid_by="Sam Rivera", wifi_ssid="CasaAlfama", wifi_pass="sardinha2026",
            room_type="Entire apartment", split_with="")
    housing(lis, name="Hotel Rossio Garden", address="Rua dos Sapateiros 120, 1100-619 Lisboa, Portugal", check_in=persona.d(7), check_out=persona.d(13),
            nightly_rate=214.0, total_cost=1284.0, url="https://example.com/stays/rossio-garden", notes="Backup if the apartment falls through. Breakfast included.",
            status="rejected", lat=38.7126, lng=-9.1385, guests=3, bedrooms=2.0, beds=3, baths=1.0, area="Baixa", rating=4.5, reviews=988,
            stay_type="hotel", room_type="Triple room", breakfast="Included", amenities="Breakfast, lift, air conditioning")
    housing(den, name="Sloan's Lake Bungalow", address="1822 Raleigh St, Denver, CO 80204", check_in=persona.d(-31), check_out=persona.d(-27),
            confirmation_code="HMQ7Z3L19D", nightly_rate=211.0, total_cost=1066.0, url="https://example.com/stays/sloans-lake-bungalow",
            notes="Wood stove in the living room. Parking for two cars.", status="booked", lat=39.7487, lng=-105.0467, guests=4, bedrooms=2.0, beds=3,
            baths=1.0, parking="Driveway, two cars", area="Sloan's Lake", rating=4.9, reviews=96, hot_tub=1, host="Cal", check_in_method="Lockbox",
            amenities="Hot tub, fireplace, washer, record player", wifi="Yes", paid_by="Marcus Bell", wifi_ssid="BungalowGuest", wifi_pass="snowday2026", room_type="Entire home")

    # transportation
    def transport(tid, **kw):
        base = dict(type="other", description="", departure="", arrival="", cost=None, notes="", status="considering", location="", url="",
                    scheduled_date="", scheduled_time="", lat=None, lng=None, pickup_time="", dropoff_time="", seats=None, confirmation="",
                    points_total=None, points_program="", points_transfer=None, paid_by="", cents_per_point=None, split_with="")
        base.update(kw)
        base["trip_id"] = tid
        ex(f"INSERT INTO transportation ({','.join(base)}) VALUES ({','.join('?' * len(base))})", list(base.values()))
    transport(lis, type="shuttle", description="Airport to Alfama, private transfer (quote A)", departure="Humberto Delgado Airport", arrival="Alfama",
              cost=38.0, notes="Meets you at arrivals with a sign. Quote B is 32 euros but no name sign.", status="considering",
              location="Humberto Delgado Airport, Lisboa", scheduled_date=persona.d(7), scheduled_time="08:45", seats=4)
    transport(lis, type="rail", description="Lisbon to Sintra, Rossio line, round trip", departure="Rossio station", arrival="Sintra",
              cost=24.0, notes="Trains every 20 minutes. Buy on the Viva Viagem card.", status="booked", scheduled_date=persona.d(10), scheduled_time="08:00",
              confirmation="", paid_by="Sam Rivera")
    transport(lis, type="transit", description="Viva Viagem cards with 24-hour passes, three people", cost=30.0, notes="Reload at any metro station.", status="booked",
              scheduled_date=persona.d(7), paid_by="Sam Rivera")
    transport(den, type="rental_car", description="Compact SUV, four days", cost=312.0, notes="All-wheel drive for the snow. Picked up at the airport.",
              status="booked", scheduled_date=persona.d(-31), scheduled_time="09:45", pickup_time="09:45", dropoff_time="15:30", seats=5,
              confirmation="RC882140", paid_by="Dev Chandra")

    # expenses
    for tid, cat, desc, amt, by, st in [
        (lis, "insurance", "Travel insurance, three people", 96.0, "Sam Rivera", "paid"),
        (lis, "food", "Food budget, seven days", 560.0, "", "estimated"),
        (lis, "activities", "Sintra tickets and Jeronimos", 114.0, "", "estimated"),
        (lis, "misc", "Phone eSIM, ten days", 22.0, "Sam Rivera", "paid"),
        (den, "food", "Group dinner at Larimer Square", 248.0, "Elena Ortiz", "paid"),
        (den, "activities", "Meow Wolf tickets, four", 180.0, "Marcus Bell", "paid"),
        (den, "misc", "Groceries and firewood", 74.0, "Dev Chandra", "paid"),
    ]:
        ex("INSERT INTO expenses (trip_id,category,description,amount,currency,paid_by,status,split_with) VALUES (?,?,?,?,?,?,?,?)",
           (tid, cat, desc, amt, "USD", by, st, ""))

    # activities and opinions
    for tid, rows, log in ((lis, LISBON, False), (den, DENVER, True)):
        for a in rows:
            aid = _activity(con, tid, a, log)
            names = MEMBERS_LIS if tid == lis else MEMBERS_DEN
            for k, nm in enumerate(names[:3]):
                rating = max(2, min(5, round((a[12] / 2) + (rnd.random() - 0.5) * 1.6)))
                ex("INSERT INTO activity_opinions (activity_id,member_id,rating,created_at) VALUES (?,?,?,?)",
                   (aid, mem[(tid, nm)], rating, persona.d(-5 - k)))

    # guest codes (crew page)
    for i, (nm, first, last, status) in enumerate([("Priya Nair", "Priya", "Nair", "approved"), ("Hana Mori", "Hana", "Mori", "approved"),
                                                   ("Marcus Bell", "Marcus", "Bell", "approved"), ("Tom Okafor", "Tom", "Okafor", "pending")]):
        ex("INSERT INTO guest_codes (name,first_name,last_name,phone,email,address,code,contact_slug,status,created_at,decided_at,last_seen,home_lat,home_lng) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (nm, first, last, "", nm.lower().replace(" ", ".") + "@example.com", "", f"demo-{i + 1:03d}-{rnd.getrandbits(20):05x}", "", status,
            persona.t(-24 * (12 + i)), persona.t(-24 * (11 + i)) if status == "approved" else "", persona.t(-3 * (i + 1)) if status == "approved" else "", None, None))


def check(con):
    assert con.execute("SELECT count(*) FROM activities WHERE location='' OR description='' OR url='' OR notes='' OR lat IS NULL OR lng IS NULL "
                       "OR operating_hours='' OR score IS NULL OR cost IS NULL").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM trips WHERE start_date='' OR end_date=''").fetchone()[0] == 0
