"""Home page (/): the frozen daily briefing snapshots for the last week plus today.

The schedule strip shows trips from trips.db (s_trips), the task panel reads
tasks.db (s_tasks). Calendar events, card balances and subscriptions come from
outside services in the real Hub and are not seeded here.
"""
import json

DB = "tasks"
EXPECT = {"briefing_day": 8}

# (temp F, WMO code, hi, lo, precip %, bring, prep) for today and the seven days before.
DAYS = [
    (47, 3, 52, 41, 20, ["Light jacket"], ["Print the vendor scorecard draft"]),
    (44, 61, 49, 40, 70, ["Umbrella", "Rain jacket"], ["Charge the laptop before the commute"]),
    (51, 2, 56, 43, 10, [], ["Lay out clothes for the early shift"]),
    (39, 71, 41, 33, 60, ["Gloves", "Warm hat", "Boots"], ["Check the train alerts"]),
    (42, 3, 45, 36, 25, ["Scarf"], []),
    (55, 0, 58, 44, 0, [], ["Prep Wednesday's inventory sheet"]),
    (50, 1, 54, 42, 5, ["Light jacket"], ["Pack the gym bag"]),
    (46, 61, 50, 41, 65, ["Umbrella"], ["Return the library books"]),
]


def seed(con, rnd, persona):
    for i, (temp, code, hi, lo, precip, bring, prep) in enumerate(DAYS):
        con.execute(
            "INSERT INTO briefing_day (date,temp,code,hi,lo,precip,bring,prep,updated_at,wx) VALUES (?,?,?,?,?,?,?,?,?,NULL)",
            (persona.d(-i), temp, code, hi, lo, precip, json.dumps(bring), json.dumps(prep),
             persona.d(-i, "21:30:00")))
