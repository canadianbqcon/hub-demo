"""Finances: book.db, earnings.db, owed.db, cards.db, stocks.db.

Stock analyses are AI-written sample output: flagged with "sample_output": true in
analyses.metrics_json. Fictional tickers. next_earnings stays NULL (it is a unix
timestamp, which the reset cannot move).
"""
import json

DB = ("book", "earnings", "owed", "cards", "stocks")
EXPECT = {
    "book.account": 5, "book.category": 18, "book.txn": 270, "book.payee": 30,
    "earnings.earnings": 14, "earnings.earnings_shifts": 20,
    "earnings.earnings_deductions": 20, "earnings.earnings_scheduled_shifts": 8,
    "owed.owed": 12, "owed.payment": 2, "cards.card": 4,
    "stocks.analyses": 4, "stocks.stocks": 4,
}

SPAN = 80  # days of book history


def seed(cons, rnd, p):
    _book(cons["book"], rnd, p)
    _earnings(cons["earnings"], rnd, p)
    _owed(cons["owed"], rnd, p)
    _cards(cons["cards"], p)
    _stocks(cons["stocks"], rnd, p)
    for con in cons.values():
        _stamp(con, p.t(-48))


# ---------------------------------------------------------------- book

GROUPS = {
    "Bills": ["Rent", "Utilities", "Internet", "Phone"],
    "Everyday": ["Groceries", "Dining Out", "Coffee", "Transportation", "Household", "Health"],
    "Fun": ["Entertainment", "Shopping", "Travel"],
    "Subscriptions": ["Streaming", "Music", "Gym", "Cloud Storage", "Software"],
    "Other": ["Payback", "Interest", "Reimbursements"],
    "Internal Master Category": ["Inflow: Ready to Assign"],
}

ACCTS = [  # name, type, balance_cents (YNAB sign: owing is negative)
    ("Northside Checking", "checking", 384217),
    ("Lakeshore Savings", "savings", 1426500),
    ("Sapphire Visa", "credit", -184233),
    ("Everyday Cash Card", "credit", -96410),
    ("Hearth & Home Card", "credit", -141500),
]

# payee, category, low, high, memos
VAR = {
    "Groceries": ("Fresh Basket Market|Corner Greens|Bulk Barn Wholesale|Harvest Co-op".split("|"), 22, 96,
                  ["weekly shop", "restock", "dinner stuff", "party snacks", "produce run"]),
    "Dining Out": ("Taqueria Luna|Noodle Alley|Brass Lantern|Pizza Orbit|Saffron Table".split("|"), 14, 68,
                   ["lunch", "dinner out", "takeout", "birthday dinner", "after-work bite"]),
    "Coffee": (["The Daily Grind", "Bean & Barrel"], 4, 8, ["latte", "morning coffee", "iced coffee"]),
    "Transportation": (["Rydr", "Transit Card Reload", "Pedal Share"], 8, 32,
                       ["ride home", "transit reload", "late ride"]),
    "Household": (["Hardware Hank", "Nest & Co Home"], 12, 74, ["light bulbs", "cleaning supplies", "shelf brackets"]),
    "Health": (["Northside Pharmacy", "Clearview Dental"], 9, 55, ["prescription", "copay", "vitamins"]),
    "Entertainment": (["Riverside Music Hall", "Cinema Plex", "Pinball Parlor"], 12, 58,
                      ["show tickets", "movie night", "arcade night"]),
    "Shopping": (["Pageturn Books", "Threadline Apparel", "Gadget Garage"], 15, 90,
                 ["book order", "jacket", "phone case"]),
}
VAR_COUNT = {"Groceries": 46, "Dining Out": 42, "Coffee": 66, "Transportation": 28,
             "Household": 9, "Health": 7, "Entertainment": 9, "Shopping": 11}
VAR_ACCT = {"Groceries": [2, 0, 3], "Dining Out": [2, 3, 0], "Coffee": [3, 0], "Transportation": [3, 0],
            "Household": [4, 3], "Health": [0], "Entertainment": [2, 3], "Shopping": [2, 4]}

SUBS = [  # payee, category, amount, first offset, account index
    ("Streamflix", "Streaming", 15.49, -71, 3), ("Tunebox", "Music", 11.99, -64, 2),
    ("Ironworks Fitness", "Gym", 39.00, -58, 0), ("Skyvault Storage", "Cloud Storage", 2.99, -52, 2),
    ("Paperwise Pro", "Software", 8.00, -47, 3),
]
BILLS = [  # payee, category, amount range, offsets, account idx
    ("Maple Court Apartments", "Rent", (1650, 1650), [-66, -36, -6], 0),
    ("Lakefront Electric", "Utilities", (58, 91), [-58, -28], 0),
    ("Prairie Gas & Heat", "Utilities", (34, 77), [-54, -24], 0),
    ("Fiberline Internet", "Internet", (59.99, 59.99), [-61, -31, -1], 0),
    ("Pinecone Mobile", "Phone", (45, 45), [-74, -44, -14], 0),
]


def _book(c, rnd, p):
    gid, cid = {}, {}
    for g, cats in GROUPS.items():
        cur = c.execute("INSERT INTO category_group(name, hidden) VALUES(?,?)", (g, 1 if g.startswith("Internal") else 0))
        gid[g] = cur.lastrowid
        for n in cats:
            cid[n] = c.execute("INSERT INTO category(group_id, name) VALUES(?,?)", (cur.lastrowid, n)).lastrowid
    acct = []
    for i, (n, ty, bal) in enumerate(ACCTS):
        acct.append(c.execute(
            "INSERT INTO account(name,type,simplefin_id,balance_cents,balance_at,sign_calibrated) VALUES(?,?,?,?,?,1)",
            (n, ty, f"sf-demo-{i + 1}", bal, p.t(-3))).lastrowid)
    payee = {}

    def pid(name, transfer=None):
        if name not in payee:
            payee[name] = c.execute("INSERT INTO payee(name, transfer_account_id) VALUES(?,?)",
                                    (name, transfer)).lastrowid
        return payee[name]

    n = [0]
    rows = []  # dicts, inserted sorted by date

    def add(off, ai, cents, payee_name, cat, memo, **kw):
        n[0] += 1
        rows.append(dict(off=off, ai=ai, cents=cents, payee=payee_name, cat=cat, memo=memo, seq=n[0], **kw))

    # income
    for k in range(6):
        add(-3 - 14 * k, 0, 218432, "Larkspur Labs Payroll", "Inflow: Ready to Assign", "paycheck")
    for k in range(11):
        add(-2 - 7 * k, 0, int(rnd.uniform(18000, 41000)), f"{p.RESTAURANT} Tips", "Inflow: Ready to Assign",
            "weekly tip deposit")
    # bills & subscriptions
    for name, cat, (lo, hi), offs, ai in BILLS:
        for o in offs:
            add(o, ai, -round(rnd.uniform(lo, hi) * 100), name, cat, "autopay" if cat != "Rent" else "rent")
    for name, cat, amt, o0, ai in SUBS:
        for k in range(3):
            o = o0 + 30 * k + (1 if k == 2 else 0)
            if o <= 0:
                add(o, ai, -round(amt * 100), name, cat, "monthly")
    # variable spend
    # book.fetch_subscriptions reads any payee + whole-dollar pair seen ~monthly as a
    # subscription, so a random draw that lands on one is re-rolled (Noodle Alley twice
    # on Home's subscriptions card, 2026-11-11)
    hits = {}
    for cat, (names, lo, hi, memos) in VAR.items():
        for _ in range(VAR_COUNT[cat]):
            for _try in range(50):
                off, cents, name = -rnd.randint(0, SPAN), round(rnd.uniform(lo, hi) * 100), rnd.choice(names)
                offs = sorted(hits.get((name, round(cents / 100)), []) + [off])
                gaps = [b - a for a, b in zip(offs, offs[1:]) if b > a]
                if not gaps or not 25 <= sum(gaps) / len(gaps) <= 45:
                    break
            hits.setdefault((name, round(cents / 100)), []).append(off)
            add(off, rnd.choice(VAR_ACCT[cat]), -cents, name, cat, rnd.choice(memos))
    add(-33, 3, -64000, "Skyline Air", "Travel", "Lisbon flights")
    add(-30, 3, -21800, "Casa Alfama Stays", "Travel", "Lisbon deposit")
    add(-12, 2, -38700, "Rockies Rail & Lodge", "Travel", "Denver weekend")
    for o, ai, amt in [(-52, 2, 3821), (-22, 2, 3604), (-49, 3, 1417), (-19, 3, 1522)]:
        add(o, ai, -amt, "Interest Charge", "Interest", "monthly finance charge")
    for o, who, amt in [(-41, "Priya Nair", 2850), (-27, "Marcus Bell", 4000), (-9, "Elena Ortiz", 3175)]:
        add(o, 0, amt, f"Venmo {who}", "Reimbursements", "paid me back")
    # transfers: (offset, from idx, to idx, cents)
    xfers = [(-50, 0, 2, 40000), (-20, 0, 2, 45000), (-48, 0, 3, 15000), (-18, 0, 3, 18000),
             (-46, 0, 4, 12500), (-16, 0, 4, 12500), (-45, 0, 1, 20000), (-15, 0, 1, 20000)]
    rows.sort(key=lambda r: (r["off"], r["seq"]))

    review = {}  # recent rows left unreviewed
    recent = [r for r in rows if r["off"] >= -6 and r["cents"] < 0]
    for i, r in enumerate(recent):
        review[r["seq"]] = i
    kinds = ["hi", "hi", "lo", "hi", "none", "lo", "hi", "none", "hi", "hi", "lo", "none"]

    seqn = 0
    for r in rows + [dict(off=o, xf=(a, b, amt), seq=9000 + i) for i, (o, a, b, amt) in enumerate(xfers)]:
        seqn += 1
        if "xf" in r:
            a, b, amt = r["xf"]
            ua, ub = f"demo-{seqn:04d}a", f"demo-{seqn:04d}b"
            for src, dst, cents, uid, other in [(a, b, -amt, ua, ub), (b, a, amt, ub, ua)]:
                pn = f"Transfer: {ACCTS[dst][0]}"
                c.execute(
                    "INSERT INTO txn(uid,simplefin_id,account_id,date,amount_cents,payee_id,raw_description,memo,"
                    "approved,cleared,transfer_account_id,transfer_txn_uid,source,updated_at,first_seen_at) "
                    "VALUES(?,?,?,?,?,?,?,?,1,1,?,?,'simplefin',?,?)",
                    (uid, f"sf-{uid}", acct[src], p.d(r["off"]), cents, pid(pn, acct[dst]), pn.upper(),
                     "card payment" if ACCTS[b][1] == "credit" else "savings",
                     acct[dst], other, p.t(-3), p.d(r["off"])))
            continue
        uid = f"demo-{seqn:04d}"
        recent_i = review.get(r["seq"])
        cat, approved, sug, conf, memo, pend = cid[r["cat"]], 1, None, None, r["memo"], 0
        if recent_i is not None:
            approved = 0
            kind = kinds[recent_i % len(kinds)]
            if kind == "none":
                cat, memo = None, ""
            elif kind in ("hi", "lo"):
                sug, conf = cat, "high" if kind == "hi" else "low"
                if kind == "lo":
                    cat, memo = None, ""
                elif recent_i % 2:
                    cat = None
            if r["off"] >= -1 and recent_i % 3 == 0:
                pend = 1
        c.execute(
            "INSERT INTO txn(uid,simplefin_id,account_id,date,amount_cents,payee_id,raw_description,category_id,"
            "memo,approved,cleared,pending,source,updated_at,suggested_category_id,suggested_confidence,"
            "suggested_at,first_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'simplefin',?,?,?,?,?)",
            (uid, f"sf-{uid}", acct[r["ai"]], p.d(r["off"]), r["cents"], pid(r["payee"]), r["payee"].upper(),
             cat, memo, approved, 0 if pend else 1, pend, p.t(-3), sug, conf, p.t(-3) if sug else None,
             p.d(r["off"])))
    # a split: one big grocery run split with household
    t = c.execute("SELECT id FROM txn WHERE category_id=? AND amount_cents<-5000 AND approved=1 LIMIT 1",
                  (cid["Groceries"],)).fetchone()
    if t:
        c.execute("UPDATE txn SET category_id=NULL WHERE id=?", (t[0],))
        amt = c.execute("SELECT amount_cents FROM txn WHERE id=?", (t[0],)).fetchone()[0]
        h = amt // 4
        c.execute("INSERT INTO split(txn_id,ord,amount_cents,category_id,memo) VALUES(?,?,?,?,?)",
                  (t[0], 0, amt - h, cid["Groceries"], "food"))
        c.execute("INSERT INTO split(txn_id,ord,amount_cents,category_id,memo) VALUES(?,?,?,?,?)",
                  (t[0], 1, h, cid["Household"], "cleaning gear"))
    for n_, short in [("Fresh Basket Market", "Fresh Basket"), ("Bulk Barn Wholesale", "Bulk Barn"),
                      ("Maple Court Apartments", "Rent"), ("Larkspur Labs Payroll", "Paycheck")]:
        c.execute("UPDATE payee SET short_name=? WHERE name=?", (short, n_))
    for i, a in enumerate(acct):
        c.execute("INSERT INTO account_refresh(account_id, refreshed_at, seen_at) VALUES(?,?,?)",
                  (a, p.t(-3), p.t(-3)))
    for h, st in [(-52, "ok"), (-28, "ok"), (-4, "ok"), (-3, "ok")]:
        c.execute("INSERT INTO sync_run(at,status,added,updated) VALUES(?,?,?,?)",
                  (p.t(h), st, rnd.randint(6, 30), rnd.randint(0, 5)))


# ---------------------------------------------------------------- earnings

def _earnings(c, rnd, p):
    src = "juniper-and-co"
    rate = 9.48
    ytd = {"FICA-SS": 1180.0, "FICA-Medicare": 276.0, "FIT": 1420.0, "Illinois SIT": 394.0}
    for w in range(11):
        end, start = -1 - 7 * w, -7 - 7 * w
        offs = sorted(rnd.sample(range(start, end + 1), rnd.choice([2, 3, 3, 4])))
        shifts, tot = [], dict(h=0, wage=0, cash=0, gross=0, net=0)
        for o in offs:
            hrs = round(rnd.uniform(5.5, 8.5), 2)
            cash = round(rnd.uniform(35, 120), 2)
            ccg = round(rnd.uniform(70, 210), 2)
            ccn = round(ccg * 0.97, 2)
            wage = round(hrs * rate, 2)
            ci_h = rnd.choice([16, 17, 18])
            co_h = ci_h + int(hrs)
            co_day = o + (1 if co_h >= 24 else 0)
            shifts.append((o, ci_h, co_h % 24, co_day, hrs, wage, cash, ccg, ccn, round(wage + cash + ccn, 2)))
            tot["h"] += hrs; tot["wage"] += wage; tot["cash"] += cash; tot["gross"] += ccg; tot["net"] += ccn
        wages, cash, ccg, ccn = (round(tot[k], 2) for k in ("wage", "cash", "gross", "net"))
        gross = round(wages + ccn, 2)
        tax = round(gross * 0.13, 2)
        eid = c.execute(
            "INSERT INTO earnings(source,source_type,period_start,period_end,gross,net,hours,wages,cash_tips,"
            "cc_tips_gross,cc_tips_net,tax_withheld,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (src, "tipped_hourly", p.d(start), p.d(end), gross, round(gross - tax, 2), round(tot["h"], 2), wages,
             cash, ccg, ccn, tax, "Weekly check; cash tips are self-reported.")).lastrowid
        for o, ci, co, cod, hrs, wage, cs, g, nn, total in shifts:
            c.execute(
                "INSERT INTO earnings_shifts(earnings_id,shift_date,clock_in,clock_out,hours,rate,tipped,wage_pay,"
                "cash_tips,cc_tips_gross,cc_tips_net,shift_total,note) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?)",
                (eid, p.d(o), f"{p.d(o)}T{ci:02d}:00:00-06:00", f"{p.d(cod)}T{co:02d}:00:00-06:00", hrs, rate,
                 wage, cs, g, nn, total, ""))
        parts = {"FICA-SS": 0.062, "FICA-Medicare": 0.0145, "FIT": 0.035, "Illinois SIT": 0.0185}
        for lab, f in parts.items():
            amt = round(gross * f, 2)
            ytd[lab] = round(ytd[lab] + amt, 2)
            c.execute("INSERT INTO earnings_deductions(earnings_id,label,amount,ytd_amount) VALUES(?,?,?,?)",
                      (eid, lab, amt, ytd[lab]))
    # salaried day job, biweekly
    y2 = {"FIT": 5310.0, "FICA-SS": 3180.0, "FICA-Medicare": 743.7, "Illinois SIT": 1187.0, "401(k)": 1846.0}
    for k in range(6):
        end = -3 - 14 * k
        ded = {"FIT": 412.18, "FICA-SS": 190.77, "FICA-Medicare": 44.62, "Illinois SIT": 68.90, "401(k)": 153.85}
        gross = 3076.92
        net = round(gross - sum(ded.values()) - 78.50, 2)  # 78.50 health premium
        eid = c.execute(
            "INSERT INTO earnings(source,source_type,period_start,period_end,gross,net,hours,wages,tax_withheld,notes) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("larkspur-labs", "salaried", p.d(end - 13), p.d(end), gross, net, 80.0, gross,
             round(sum(ded.values()) - 153.85, 2), "Direct deposit; salary $80,000.")).lastrowid
        for lab, a in {**ded, "Health premium": 78.50}.items():
            y2.setdefault(lab, 942.0)
            y2[lab] = round(y2[lab] + a, 2)
            c.execute("INSERT INTO earnings_deductions(earnings_id,label,amount,ytd_amount) VALUES(?,?,?,?)",
                      (eid, lab, a, y2[lab]))
    # upcoming bar shifts
    for i, o in enumerate(sorted(rnd.sample(range(1, 28), 11))):
        role = "bartender" if i % 3 else "barback"
        c.execute(
            "INSERT INTO earnings_scheduled_shifts(source,shift_date,summary,start_at,end_at,role,shift_kind,"
            "roster_source) VALUES(?,?,?,?,?,?,?,?)",
            (src, p.d(o), f"{p.RESTAURANT} {role}", rnd.choice(["16:30", "17:00", "18:00"]), "01:00", role,
             "regular", "calendar"))
    # the migration ships a real-shaped unemployment claim and tip params; replace them with invented ones
    for tb in ("earnings_ui_claim", "earnings_tip_points", "earnings_pricing_params"):
        c.execute(f"DELETE FROM {tb}")
    for role, pts in [("barback", 6), ("server", 8), ("bartender", 10), ("bar_captain", 12), ("host", 2)]:
        c.execute("INSERT INTO earnings_tip_points(source,role,points,verified,note) VALUES(?,?,?,?,?)",
                  (src, role, pts, 1 if role in ("barback", "server") else 0,
                   "confirmed with the crew" if role in ("barback", "server") else "assumed, not confirmed"))
    for k, v, ver in [("tipped_wage_rate", 9.48, 1), ("pool_weeknight", 38, 0), ("pool_thursday", 52, 0),
                      ("pool_sunday", 30, 0), ("pool_weekend_early", 70, 0), ("pool_weekend_peak", 118, 0),
                      ("buyout_multiple", 1.8, 0)]:
        c.execute("INSERT INTO earnings_pricing_params(source,key,value,verified,note) VALUES(?,?,?,?,?)",
                  (src, k, v, ver, "from paid shifts" if ver else "estimate, not yet checked"))


# ---------------------------------------------------------------- owed

def _owed(c, rnd, p):
    rows = [  # person, what, amount, incurred, paid_out, status, settled, method, grp, note, dir
        ("Priya Nair", "Her half of the Lisbon rental car", 142.50, -26, 285.0, "open", None, None, "Lisbon trip", "", 1),
        ("Marcus Bell", "Concert tickets, floor section", 96.00, -19, 192.0, "requested", None, None, "", "Asked on Venmo", 1),
        ("Elena Ortiz", "Dinner at Brass Lantern", 38.75, -14, 77.5, "open", None, None, "", "", 1),
        ("Dev Chandra", "Share of the gym guest passes", 24.00, -33, None, "open", None, None, "", "", 1),
        ("Hana Mori", "Lisbon apartment, her nights", 214.00, -30, 428.0, "requested", None, None, "Lisbon trip", "Asked on Venmo", 1),
        ("Tom Okafor", "Group gift for Priya", 22.00, -11, 110.0, "open", None, None, "Birthday gift", "", 1),
        ("Marcus Bell", "Group gift for Priya", 22.00, -11, None, "open", None, None, "Birthday gift", "", 1),
        ("Elena Ortiz", "Group gift for Priya", 22.00, -11, None, "requested", None, None, "Birthday gift", "Asked on Venmo", 1),
        ("Priya Nair", "Ride share home after the show", 17.40, -41, None, "paid", -39, "venmo", "", "", 1),
        ("Marcus Bell", "Pizza night", 31.25, -27, None, "paid", -24, "zelle", "", "", 1),
        ("Elena Ortiz", "Farmers market haul", 18.00, -45, None, "paid", -42, "cash", "", "", 1),
        ("Dev Chandra", "Pinball arcade tokens", 12.00, -37, None, "paid", -35, "venmo", "", "", 1),
        ("Hana Mori", "Parking at the lakefront", 14.50, -22, None, "unassigned", None, None, "", "Not sure who split this one", 1),
        ("Tom Okafor", "His share of the summer BBQ groceries", 41.00, -8, None, "open", None, None, "", "", -1),
    ]
    for r in rows:
        person, what, amt, inc, po, st, settled, meth, grp, note, dr = r
        c.execute(
            "INSERT INTO owed(person,what,amount,incurred,paid_out,status,settled,method,grp,note,dir) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (person, what, amt, p.d(inc), po, st, p.d(settled) if settled else None, meth, grp or None, note, dr))
    for who, v in [("Priya Nair", "priya-nair"), ("Marcus Bell", "marcus-bell"), ("Elena Ortiz", "elena-ortiz")]:
        c.execute("INSERT INTO person(person, venmo) VALUES(?,?)", (who, v))
    c.execute("INSERT INTO payment(person,amount,method,received,note,ext_id,status) VALUES(?,?,?,?,?,?,?)",
              ("Dev Chandra", 24.00, "venmo", p.d(-2), "gym passes", "vm-demo-1001", "unapplied"))
    pid = c.execute("INSERT INTO payment(person,amount,method,received,note,ext_id,status) VALUES(?,?,?,?,?,?,?)",
                    ("Priya Nair", 17.40, "venmo", p.d(-39), "ride home", "vm-demo-1000", "applied")).lastrowid
    oid = c.execute("SELECT id FROM owed WHERE what='Ride share home after the show'").fetchone()[0]
    c.execute("INSERT INTO payment_line(payment_id,owed_id,amount) VALUES(?,?,?)", (pid, oid, 17.40))


# ---------------------------------------------------------------- cards

def _cards(c, p):
    # name, due_day, last4, kind, apr, promo_apr, promo_end, limit, min, fixed, term, parent, balance, start
    rows = [
        ("Sapphire Visa", 14, "4821", "card", 24.99, None, None, 9000, 35, None, None, None, None, None),
        ("Everyday Cash Card", 22, "1096", "card", 19.99, 0.0, p.d(70), 5000, 25, None, None, None, None, None),
        ("Hearth & Home Card", 5, "7340", "card", 29.99, None, None, 3000, 30, None, None, None, None, None),
        ("Laptop Payment Plan", 5, None, "loan", 0.0, None, None, None, None, 100.0, 12, "Hearth & Home Card", 1200.0, p.d(-120)),
    ]
    for r in rows:
        c.execute("INSERT INTO card(name,due_day,last4,kind,apr,promo_apr,promo_end,credit_limit,min_payment,"
                  "fixed_payment,term_months,parent,balance,start_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r)


# ---------------------------------------------------------------- stocks

def _stocks(c, rnd, p):
    items = [  # ticker, company, sector, price, score, entry, target, stop, verdict
        ("NWGD", "Northwind Grid Systems", "Utilities", 48.20, 71, 46.0, 58.0, 42.5,
         "Steady regulated earnings and a covered dividend; not cheap, wait for a pullback."),
        ("LMNT", "Lumen Trail Software", "Technology", 131.75, 64, 124.0, 160.0, 115.0,
         "Good retention numbers, but the multiple already assumes the growth plan works."),
        ("HRBR", "Harborline Freight", "Industrials", 27.40, 52, 25.0, 33.0, 23.0,
         "Cyclical and levered. A trade at the right price, not something to hold through a downturn."),
        ("PRCH", "Porchlight Foods", "Consumer Staples", 62.10, 78, 59.5, 72.0, 55.0,
         "Boring in the useful way: pricing power, low debt, buybacks. Fair value near the current price."),
    ]
    for t, co, sec, px, sc, ent, tgt, stp, verdict in items:
        aid = c.execute(
            "INSERT INTO analyses(ticker,run_date,price_at_run,viability_score,bull_case,base_case,bear_case,"
            "lt_thesis,lt_fair_value,lt_allocation,lt_exit_triggers,trade_entry,trade_entry_num,trade_targets,"
            "trade_target_num,trade_stop,trade_stop_num,trade_timeframe,trade_risk_reward,verdict_summary,metrics_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t, p.t(-rnd.randint(30, 140)), px, sc,
             f"Margins widen and {co} beats the plan; price re-rates about 25% higher over a year.",
             f"Growth in line with guidance; the stock tracks earnings and returns roughly 8% a year.",
             f"A weaker quarter and a lower multiple take the price about 20% under today's level.",
             f"{co} earns its place on cash generation and a clear capital plan. Own it only if the thesis survives two bad quarters.",
             f"${round(px * 1.04, 2)}", "Up to 3% of the portfolio, built in thirds.",
             "Guidance cut twice in a row, or leverage above 3.5x earnings.",
             f"Buy between ${ent - 1.5:.2f} and ${ent:.2f}", ent, f"${tgt:.2f}", tgt, f"${stp:.2f}", stp,
             "6 to 9 months", f"{(tgt - ent) / (ent - stp):.1f} to 1", verdict,
             json.dumps({"sample_output": True, "note": "AI-written sample analysis of a fictional company",
                         "pe": round(rnd.uniform(11, 28), 1), "dividend_yield": round(rnd.uniform(0, 3.4), 2)}))
        ).lastrowid
        c.execute(
            "INSERT INTO stocks(ticker,company,sector,first_analyzed,last_analyzed,latest_viability_score,"
            "latest_verdict_summary,latest_price,latest_analysis_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (t, co, sec, p.t(-300), p.t(-rnd.randint(30, 140)), sc, verdict, px, aid))


def _stamp(con, token):
    """Pin every datetime('now') default column to a token, so the seed is deterministic."""
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'").fetchall():
        for r in con.execute(f'PRAGMA table_info("{t}")').fetchall():
            if "datetime('now')" in str(r[4]):
                con.execute(f'UPDATE "{t}" SET "{r[1]}"=? WHERE "{r[1]}" NOT LIKE \'@%\'', (token,))
