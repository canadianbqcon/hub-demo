"""tasks.db: the planner and the Home TASKS panel. Open, overdue, done, loose ends."""
DB = "tasks"
EXPECT = {"tasks": 40}

# (title, section, due, urgency, input_level, group, blocked, description)
OPEN = [
    # loose ends: work a session left half done, parked by the pending sweep
    ("Finish tailoring the resume for the Harbor & Pine analyst role", "loose ends", None, "critical", "low", "Job search", 0,
     "Parked from a session that ended mid-edit. Resume variant is saved; paragraph two of the cover letter is still unwritten."),
    ("Reconcile the October card statement against the ledger", "loose ends", None, None, "low", None, 0,
     "Parked. Eleven transactions matched, four still uncategorised."),
    ("Check that recurring shifts stop importing twice", "loose ends", None, "quickwin", "none", None, 0,
     "Fix shipped on Tuesday; needs one more Friday-night import to confirm."),
    ("Pick up the Lisbon airport transfer quote thread", "loose ends", None, None, "high", "Lisbon trip", 0,
     "Two quotes received, neither compared yet. Parked when the trip planner session closed."),
    # general
    ("Renew the street parking permit", "general", "@d+9", "critical", "none", None, 0, "Online form, needs the registration number."),
    ("Return the borrowed drill to Marcus", "general", "@d+2", "quickwin", "none", None, 0, ""),
    ("Sort the recycling bin of old cables", "general", None, None, "none", None, 0, ""),
    ("Order a replacement filter for the apartment vent", "general", None, None, "low", None, 0, "Size is printed on the old filter, 16x25x1."),
    # personal
    ("Call the landlord about the radiator in the bedroom", "personal", "@d-1", "critical", "none", None, 0,
     "Third time it has knocked all night. Ask for a visit before the cold week."),
    ("Dentist cleaning", "personal", "@d+3T09:30:00", None, "none", None, 0, "Fourth floor, bring the insurance card."),
    ("Renew the library card and clear the fine", "personal", "@d-2", "quickwin", "none", None, 0, "Fine is under four dollars."),
    ("Book a haircut before the trip", "personal", None, "quickwin", "none", "Lisbon trip", 0, ""),
    ("Write the thank-you note to Elena for hosting", "personal", "@d+1", None, "low", None, 0, ""),
    ("Plan Hana's birthday dinner", "personal", None, None, "high", None, 0, "Six people, somewhere that takes a booking for a Thursday."),
    # work
    ("Larkspur Labs: finish the Q4 vendor scorecard", "work", "@d+4", "critical", "high", "Larkspur Labs", 0,
     "Three vendors still missing delivery-time data. Ask the warehouse team for the October export."),
    ("Larkspur Labs: refresh the demand forecast workbook", "work", None, None, "high", "Larkspur Labs", 0, ""),
    ("Larkspur Labs: send the Friday ops summary", "work", "@d+0T16:00:00", None, "low", "Larkspur Labs", 0, "Five bullets, link the dashboard."),
    ("Larkspur Labs: document the receiving checklist change", "work", None, "quickwin", "low", "Larkspur Labs", 0, ""),
    ("Confirm the schedule swap for Saturday at Juniper & Co", "work", None, "quickwin", "none", "Juniper & Co", 0, "Tom has the early close if I take his Thursday."),
    ("Count and order well spirits for Juniper & Co", "work", None, None, "low", "Juniper & Co", 1,
     "Blocked until the new distributor sends the price list."),
    # travel
    ("Book the Lisbon airport transfer", "travel", "@d+3", "critical", "low", "Lisbon trip", 0, "Compare the two quotes first."),
    ("Download offline maps for Lisbon", "travel", None, "quickwin", "none", "Lisbon trip", 0, ""),
    ("Buy a Type F plug adapter", "travel", None, "quickwin", "none", "Lisbon trip", 0, "See the Purchases page for the pick."),
    ("Reserve the Alfama tram tour for day three", "travel", None, None, "low", "Lisbon trip", 1, "Waiting on the group to confirm dates."),
    ("Send Priya the Lisbon itinerary", "travel", None, None, "none", "Lisbon trip", 0, ""),
    # dashboard
    ("Add a sample-data chip to the AI summaries", "dashboard", None, None, "low", None, 0, ""),
    ("Make the planner remember its collapsed sections", "dashboard", None, "quickwin", "none", None, 0, ""),
    ("Tidy the empty states on the checklists page", "dashboard", None, None, "low", None, 0, ""),
    # setup & workflow
    ("Move the nightly backup to run after the import", "setup & workflow", None, None, "low", None, 0, ""),
    ("Write down how the weekly review works", "setup & workflow", None, None, "high", None, 0, ""),
    # explore
    ("Look into a standing desk for the second room", "explore", None, None, "none", None, 0, ""),
    ("Read about route optimisation for the warehouse pickers", "explore", None, None, "none", "Larkspur Labs", 0, ""),
]

# (title, section, completed_day, group)
DONE = [
    ("Send the October vendor invoice batch", "work", -1, "Larkspur Labs"),
    ("Submit the Harbor & Pine application", "general", -1, "Job search"),
    ("Pick up dry cleaning", "personal", -2, None),
    ("Order the Lisbon travel insurance", "travel", -2, "Lisbon trip"),
    ("Pay the electric bill", "personal", -3, None),
    ("Fix the checklist tick bug on the packing tab", "dashboard", -3, None),
    ("Reply to the recruiter at Copper Ridge", "general", -4, "Job search"),
    ("Prep Wednesday's inventory sheet", "work", -4, "Juniper & Co"),
    ("Back up the phone photos", "setup & workflow", -5, None),
    ("Renew the transit pass", "personal", -6, None),
    ("Book the Lisbon flights", "travel", -6, "Lisbon trip"),
    ("Draft the warehouse slotting proposal", "work", -7, "Larkspur Labs"),
]


def seed(con, rnd, persona):
    used = set()

    def key(title):
        base = "".join(c if c.isalnum() else "-" for c in title.lower())[:28].strip("-")
        while True:
            k = f"{base}-{rnd.getrandbits(16):04x}"
            if k not in used:
                used.add(k)
                return k

    sql = ("INSERT INTO tasks (task_key,title,status,section,due_date,completed_date,description,"
           "source,created,updated,blocked,group_label,urgency,input_level) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
    for i, (title, sec, due, urg, inp, grp, blocked, desc) in enumerate(OPEN):
        # A due date is a day token, or a day token plus T and a clock for a timed task.
        due = due.replace("@d+0", "@d0") if due else due
        age = 2 + (i * 5) % 40
        source = "park" if sec == "loose ends" else "manual"
        con.execute(sql, (key(title), title, "open", sec, due, None, desc, source,
                          persona.t(-24 * age), persona.t(-24 * (age // 3)), blocked, grp, urg, inp))
    for title, sec, day, grp in DONE:
        con.execute(sql, (key(title), title, "done", sec, persona.d(day), persona.d(day), "", "manual",
                          persona.t(-24 * (abs(day) + 6)), persona.d(day, "18:00:00"), 0, grp, None, None))


def check(con):
    assert con.execute("SELECT count(*) FROM tasks WHERE section='loose ends' AND status='open'").fetchone()[0] >= 3
    assert con.execute("SELECT count(*) FROM tasks WHERE status='done'").fetchone()[0] >= 8
    assert con.execute("SELECT count(*) FROM tasks WHERE due_date LIKE '%T%'").fetchone()[0] >= 2
