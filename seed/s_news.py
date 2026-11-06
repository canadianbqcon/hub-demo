"""News: fictional outlets, a day and a half of grouped stories, a digest citing them.

The digest and the cached article text are AI-written sample output. news.db.digests has no
flag column, so the sample status is only in this docstring; items/clusters carry fictional
events from fictional outlets. Timestamps are ISO with T (the app compares them as strings),
so they use "@d<N>T<time>+00:00" rather than the @t hour token.
"""
import json

DB = ("news", "news-cache")
EXPECT = {"news.sources": 24, "news.topics": 4, "news.digests": 2, "news-cache.clusters": 35,
          "news-cache.items": 75, "news-cache.articles": 6, "news-cache.poll_state": 20}

# id, name, domain, kind, section, lane, lean, factual, owner, paywall, note
S = {
    "economy": [
        ("meridian-wire", "Meridian Wire", "meridianwire.example", "economy", "reporting", "center", "Very High", "Meridian Media Group", 0),
        ("ledger-post", "The Ledger Post", "ledgerpost.example", "economy", "reporting", "lean_left", "High", "Ledger Holdings", 0),
        ("capital-journal", "Capital Ledger Journal", "capitaljournal.example", "economy", "reporting", "lean_right", "High", "Harlow Capital Partners", 1),
        ("lakes-bank-press", "Lakes Reserve Bank Press Office", "lakesbank.example", "economy", "primary", "primary", "Primary source", "Lakes Reserve Bank", 0),
    ],
    "politics": [
        ("capitol-brief", "Capitol Brief", "capitolbrief.example", "politics", "reporting", "center", "Very High", "Brief Media", 0),
        ("civic-current", "Civic Current", "civiccurrent.example", "politics", "reporting", "lean_left", "Mostly Factual", "Civic Current Inc.", 0),
        ("frontier-courier", "Frontier Courier", "frontiercourier.example", "politics", "reporting", "lean_right", "Mostly Factual", "Frontier Publishing", 0),
        ("heartland-times", "Heartland Times", "heartlandtimes.example", "politics", "reporting", "right", "Mixed", "Heartland Broadcasting", 0),
    ],
    "world": [
        ("global-dispatch", "Global Dispatch", "globaldispatch.example", "world", "reporting", "center", "Very High", "Dispatch Trust", 0),
        ("open-horizon", "Open Horizon", "openhorizon.example", "world", "reporting", "lean_left", "High", "Horizon Foundation", 0),
        ("continental-review", "Continental Review", "continentalreview.example", "world", "reporting", "lean_right", "High", "Continental Press", 0),
        ("harbor-relief", "Harbor Relief Agency", "harborrelief.example", "world", "primary", "primary", "Primary source", "Harbor Relief Agency", 0),
    ],
    "nyc": [
        ("five-boroughs", "Five Boroughs Daily", "fiveboroughs.example", "nyc", "reporting", "center", "High", "Boroughs Media", 0),
        ("borough-voice", "The Borough Voice", "boroughvoice.example", "nyc", "reporting", "lean_left", "High", "Voice Cooperative", 0),
        ("skyline-post", "Skyline Post", "skylinepost.example", "nyc", "reporting", "lean_right", "Mixed", "Skyline Newsgroup", 0),
        ("metro-transit", "Metro Transit Authority", "metrotransit.example", "nyc", "primary", "primary", "Primary source", "Metro Transit Authority", 0),
    ],
    "tech": [
        ("circuit-report", "Circuit Report", "circuitreport.example", "tech", "reporting", "center", "High", "Circuit Media", 0),
        ("byte-ledger", "Byte Ledger", "byteledger.example", "tech", "reporting", "lean_left", "High", "Byte Ledger LLC", 0),
        ("open-stack", "Open Stack Weekly", "openstackweekly.example", "tech", "reporting", "lean_right", "Mostly Factual", "Open Stack Media", 0),
        ("stackwise-eng", "Stackwise Engineering Blog", "stackwise.example", "tech", "primary", "primary", "Primary source", "Stackwise Inc.", 0),
    ],
}
OTHER = [  # lane tabs
    ("sounding-board", "The Sounding Board", "soundingboard.example", "politics", "opinion", "lean_left", "Opinion", "Board Media", 0),
    ("column-right", "Column Right", "columnright.example", "economy", "opinion", "lean_right", "Opinion", "Column Media", 0),
    ("midweek-essays", "Midweek Essays", "midweekessays.example", "world", "opinion", "center", "Opinion", "Midweek Press", 0),
    ("long-walk-pod", "The Long Walk Podcast", "longwalk.example", "tech", "audience", "center", "Unrated", "Long Walk Audio", 0),
    ("dollars-sense", "Dollars & Sense Newsletter", "dollarssense.example", "economy", "audience", "lean_left", "Unrated", "Independent", 0),
    ("backroom-pod", "Backroom Politics Pod", "backroompod.example", "politics", "audience", "lean_right", "Unrated", "Backroom Audio", 0),
    ("boardwalk-forum", "Boardwalk Forum", "boardwalkforum.example", "nyc", "community", "center", "Unrated", "Community", 0),
    ("hackerplace", "HackerPlace", "hackerplace.example", "tech", "community", "center", "Unrated", "Community", 0),
    ("neighborly", "Neighborly Threads", "neighborly.example", "nyc", "community", "center", "Unrated", "Community", 0),
]
TOPICS = [("keyword", "Lisbon travel"), ("keyword", "craft cocktail trends"), ("repo", "pallets/flask"), ("pypi", "httpx")]

# key, section, day (0 today, -1 yesterday), HH:MM, source indexes, [title variants], body
ST = [
    ("rate", "economy", 0, "07:40", (0, 1, 2, 3), ["Lakes Reserve Bank holds rates steady, signals cuts could start in spring", "Reserve Bank leaves borrowing costs unchanged as inflation cools", "Rate hold disappoints those hoping for a faster pivot", "Statement on the policy rate decision"],
     "The Lakes Reserve Bank kept its benchmark rate unchanged for a third meeting. Officials said recent price data supports patience and pointed to spring as the earliest window for a cut."),
    ("jobs", "economy", 0, "06:15", (0, 1, 2), ["Employers add 142,000 jobs in October, unemployment edges up to 4.3%", "Hiring slows but holds; wage growth cools to 3.6%", "Jobs report beats forecasts, though the labor force shrank"],
     "Payrolls grew faster than economists expected while the jobless rate ticked up. Wage growth cooled, which analysts read as helpful for the rate outlook."),
    ("rent", "economy", 0, "05:05", (0, 1), ["Rents in big cities flatten for the first time in two years", "Apartment asking rents stall as new buildings open"],
     "A national index showed median asking rents flat from September. New supply in sunbelt metros is doing most of the work."),
    ("airfare", "economy", -1, "19:30", (0, 2, 1), ["Holiday airfares run 6% below last year, travel group says", "Cheaper flights ahead of Thanksgiving, but bags and seats cost more", "Airlines add fees as base fares dip"],
     "Booking data points to lower fares for the holiday week. Carriers are making up some of the difference with add-on fees."),
    ("chips", "economy", -1, "16:10", (0, 2), ["Chipmaker raises outlook on data center demand", "Semiconductor earnings beat as AI orders pile up"],
     "A large chipmaker lifted its revenue forecast for the year, citing orders from cloud customers."),
    ("budget", "politics", 0, "07:55", (0, 1, 2, 3), ["Senate clears stopgap funding bill, avoiding a weekend shutdown", "Stopgap passes after late deal on disaster aid", "Conservatives grumble as spending bill sails through", "Lawmakers punt shutdown fight to January"],
     "The Senate approved a short-term funding measure by a wide margin. The bill extends current spending levels through January and includes disaster aid."),
    ("mayor", "politics", 0, "06:50", (0, 1, 2), ["Governor signs transit funding package after months of talks", "New funding law steers $2B to bus and rail upgrades", "Governor's transit deal leaves out highway projects"],
     "The governor signed a package that sends two billion dollars to regional transit over four years."),
    ("court", "politics", 0, "04:20", (0, 3), ["Appeals court narrows the scope of the data privacy ruling", "Court trims privacy decision, sends parts back to lower judge"],
     "A three-judge panel upheld the core of a data privacy ruling but sent two provisions back for further review."),
    ("poll", "politics", -1, "21:00", (1, 2, 3, 0), ["Poll: voters split on the new school funding formula", "Education funding formula draws mixed reviews in survey", "Survey finds little support for funding overhaul", "Voters unsure about school funding changes, poll shows"],
     "A statewide poll found 41 percent in favor of the formula, 39 percent opposed, and the rest undecided."),
    ("water", "politics", -1, "14:25", (0, 1), ["County board approves water main replacement plan", "Lead pipe program gets funded after long debate"],
     "County commissioners voted to fund the replacement of aging water mains over six years."),
    ("floods", "world", 0, "07:10", (0, 1, 2, 3), ["Floods displace thousands in the Calder river basin", "Relief agencies rush supplies as Calder floodwaters rise", "Calder flooding tests regional emergency plans", "Situation report: Calder basin flooding"],
     "Heavy rain pushed the Calder river over its banks, displacing an estimated 40,000 people. Aid groups say roads are cut off in three districts."),
    ("summit", "world", 0, "05:45", (0, 1, 2), ["Leaders reach framework on shipping lane security at the Tolan summit", "Tolan summit ends with a deal on sea lane patrols", "Critics say Tolan agreement lacks enforcement"],
     "Delegates from eleven countries agreed on a framework for joint patrols of key shipping lanes."),
    ("vote", "world", 0, "03:30", (0, 2), ["Opposition wins surprise majority in Verano parliamentary vote", "Verano election upends two decades of single-party rule"],
     "Early results show the opposition alliance ahead in a vote seen as a referendum on rising food prices."),
    ("grain", "world", -1, "18:15", (0, 1), ["Grain exports resume from northern port after inspection deal", "Ships leave Port Aldana as inspections restart"],
     "Cargo ships began loading again at Port Aldana after officials agreed on a new inspection schedule."),
    ("subway", "nyc", 0, "07:25", (0, 1, 2, 3), ["Transit agency to test off-peak fare discount on two lines", "Off-peak fare pilot starts in January on the Crosstown and Harbor lines", "Fare discount pilot raises questions about cost", "Notice: off-peak fare pilot service change"],
     "The transit authority will cut fares by 20 percent outside rush hours on two lines for a six-month trial."),
    ("housing", "nyc", 0, "06:00", (0, 1, 2), ["Council advances plan for 4,000 new apartments near the waterfront", "Housing bill moves forward with affordability requirements", "Developers warn waterfront rules could stall projects"],
     "A council committee advanced a rezoning that would allow roughly 4,000 apartments, a quarter set aside as affordable."),
    ("bakery", "nyc", 0, "04:45", (0, 1), ["Neighborhood bakeries brace for butter shortage before the holidays", "Bakers hunt for butter as holiday orders pile up"],
     "Several small bakeries reported delayed butter deliveries and higher prices heading into the busiest season."),
    ("park", "nyc", -1, "17:40", (1, 0, 2), ["Greenway extension opens, linking two waterfront parks", "New riverside path opens to walkers and cyclists", "Opening day for the greenway draws a crowd and some complaints"],
     "A 1.4 mile greenway extension opened on Thursday, closing a gap between two waterfront parks."),
    ("model", "tech", 0, "07:35", (0, 1, 2, 3), ["Stackwise releases open-weight model aimed at small devices", "New small language model runs on a laptop, company says", "Open-weight release draws praise and licensing questions", "Introducing Stackwise Lite: a small model for local use"],
     "Stackwise published a compact open-weight model designed to run on laptops and phones. The license limits some commercial use."),
    ("outage", "tech", 0, "05:30", (0, 1), ["Cloud outage knocks out dozens of apps for about three hours", "Major cloud region fails, taking popular services offline"],
     "A configuration error in one cloud region disrupted payment, messaging and streaming apps for roughly three hours."),
    ("phone", "tech", 0, "02:10", (0, 2, 1), ["Repairability scores arrive for the new phone lineup", "Teardown finds easier battery swaps in this year's phones", "Right-to-repair rules begin to show up in hardware"],
     "Independent teardowns rated the latest phones higher on repairability than last year's models."),
    ("browser", "tech", -1, "20:20", (0, 1, 2), ["Browser maker ships built-in tracking blocker by default", "Default tracker blocking arrives in the next browser update", "Ad groups push back on new default blocker"],
     "The update turns on tracker blocking for all users, with a toggle in settings."),
    ("lisbon", "topics", 0, "06:40", ("topic:keyword:Lisbon travel",), ["Lisbon tram 28 to run a reduced schedule through the winter"],
     "City officials said track work will limit the famous tram line to weekday service until March."),
    ("lisbon2", "topics", -1, "13:00", ("topic:keyword:Lisbon travel",), ["Direct flights to Lisbon expand for the spring season"],
     "Two carriers announced added frequencies from several US cities starting in April."),
    ("cocktail", "topics", 0, "05:10", ("topic:keyword:craft cocktail trends",), ["Low-ABV and zero-proof menus keep growing at neighborhood bars"],
     "Bar owners say lower-alcohol cocktails now make up a fifth of orders at weeknight service."),
    ("flask", "topics", 0, "04:00", ("topic:repo:pallets/flask",), ["pallets/flask: 3.1.4 released"],
     "Patch release with fixes for session handling and the CLI."),
    ("httpx", "topics", -1, "11:30", ("topic:pypi:httpx",), ["httpx 0.29.1 published to PyPI"],
     "Maintenance release; improves connection pool cleanup."),
    # lane tabs: (source ids by name key)
    ("op1", "politics", 0, "06:30", ("sounding-board",), ["The stopgap bill is not a victory, just a delay"], "An argument that short-term funding fights waste public goodwill."),
    ("op2", "economy", 0, "05:55", ("column-right",), ["Why a rate cut in spring would be a mistake"], "A columnist argues the Reserve Bank should wait for more evidence."),
    ("op3", "world", -1, "15:00", ("midweek-essays",), ["What the Calder floods say about early-warning systems"], "An essay on why alerts reached some districts hours before others."),
    ("op4", "politics", -1, "09:30", ("sounding-board",), ["School funding needs a simpler formula"], "A case for replacing the formula with a flat per-student amount."),
    ("au1", "tech", 0, "06:00", ("long-walk-pod",), ["Episode 212: Small models, big questions"], "A conversation about running models locally and what it changes for privacy."),
    ("au2", "economy", 0, "05:00", ("dollars-sense",), ["Newsletter: what the jobs report means for your savings account"], "A plain-language breakdown of this week's rate and jobs news."),
    ("au3", "politics", -1, "12:00", ("backroom-pod",), ["Backroom Politics: the shutdown that wasn't"], "Hosts unpack the weekend's funding deal."),
    ("co1", "nyc", 0, "07:00", ("boardwalk-forum", "neighborly"), ["Anyone tried the new off-peak fare yet? (thread)", "Is the Crosstown line really getting cheaper rides?"], "A thread with 140 replies debating whether discounts will shift commuting."),
    ("co2", "tech", 0, "04:30", ("hackerplace",), ["Show: I replaced my home server with a laptop-sized model box"], "A community thread about running small models at home."),
    ("co3", "nyc", -1, "10:15", ("neighborly",), ["Best bakery for holiday pies? (butter shortage edition)"], "Neighbors trading tips on where to order ahead."),
]

DIGEST = {
    "economy": [("rate", "The Lakes Reserve Bank held its rate for a third meeting and pointed to spring as the earliest window for a cut."),
                ("jobs", "October payrolls grew by 142,000 with unemployment at 4.3%; wage growth cooled to 3.6%."),
                ("rent", "Big-city asking rents were flat from September, the first stall in two years.")],
    "politics": [("budget", "The Senate passed a stopgap funding bill through January, with disaster aid attached."),
                 ("mayor", "The governor signed a $2B transit funding package; outlets differ on what it leaves out."),
                 ("court", "An appeals court narrowed a data privacy ruling and sent two provisions back to the lower court.")],
    "world": [("floods", "Flooding in the Calder basin has displaced about 40,000 people and cut roads in three districts."),
              ("summit", "Eleven countries agreed on a shipping lane patrol framework at the Tolan summit; critics point to weak enforcement."),
              ("vote", "Verano's opposition appears to have won a parliamentary majority in a vote focused on food prices.")],
    "nyc": [("subway", "The transit authority will pilot a 20 percent off-peak fare discount on two lines starting in January."),
            ("housing", "A council committee advanced a waterfront rezoning for roughly 4,000 apartments.")],
    "tech": [("model", "Stackwise released a small open-weight model for laptops and phones; the license restricts some commercial use."),
             ("outage", "A configuration error in one cloud region took many apps offline for about three hours.")],
}
DIGEST_Y = {
    "economy": [("airfare", "Holiday airfares are running about 6 percent below last year, though fees are up."),
                ("chips", "A major chipmaker raised its outlook on data center demand.")],
    "politics": [("poll", "A statewide poll shows voters split on the school funding formula."),
                 ("water", "The county board funded a six-year water main replacement plan.")],
    "world": [("grain", "Grain exports restarted from Port Aldana after an inspection deal.")],
    "nyc": [("park", "A 1.4 mile greenway extension opened between two waterfront parks.")],
    "tech": [("browser", "A major browser will block trackers by default in its next update.")],
}


def _iso(day, hm, add=0):
    h, m = int(hm[:2]), int(hm[3:])
    tot = min(h * 60 + m + add, 23 * 60 + 59) if day == 0 else (h * 60 + m + add) % 1440
    return f"@d{day:+d}T{tot // 60:02d}:{tot % 60:02d}:00+00:00".replace("@d+0", "@d0")


def seed(cons, rnd, p):
    nw, ca = cons["news"], cons["news-cache"]
    by_sec = {}
    for sec, rows in S.items():
        for r in rows:
            by_sec.setdefault(sec, []).append(r[0])
            nw.execute("INSERT INTO sources(id,name,url,kind,section,lane,lean,factual,owner,paywall,enabled,rating_note)"
                       " VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
                       (r[0], r[1], f"https://{r[2]}/feed.xml", "rss", r[3], r[4], r[5], r[6], r[7], r[8],
                        "Fictional outlet for the demo."))
    named = {r[0]: r for rows in S.values() for r in rows}
    for r in OTHER:
        named[r[0]] = r
        nw.execute("INSERT INTO sources(id,name,url,kind,section,lane,lean,factual,owner,paywall,enabled,rating_note)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,1,?)",
                   (r[0], r[1], f"https://{r[2]}/feed.xml", "rss", r[3], r[4], r[5], r[6], r[7], r[8],
                    "Fictional outlet for the demo."))
    topic_src = {}
    for kind, q in TOPICS:
        nw.execute("INSERT INTO topics(kind, query) VALUES(?,?)", (kind, q))
        sid = f"topic:{kind}:{q}"
        lane, lean = {"keyword": ("reporting", "center"), "repo": ("primary", "primary"),
                      "pypi": ("primary", "primary")}[kind]
        nw.execute("INSERT INTO sources(id,name,url,kind,section,lane,lean,enabled) VALUES(?,?,?,?,?,?,?,0)",
                   (sid, q, "", "rss", "topics", lane, lean))
        topic_src[sid] = q

    cid, item_n, art_items, last_item = {}, 0, [], {}
    for key, sec, day, hm, cover, titles, body in ST:
        times = [_iso(day, hm, 7 * i) for i in range(len(cover))]
        cur = ca.execute("INSERT INTO clusters(section,title,first_seen,last_seen) VALUES(?,?,?,?)",
                         (sec, titles[0], times[0], times[-1]))
        cid[key] = cur.lastrowid
        for i, c in enumerate(cover):
            sid = c if isinstance(c, str) else by_sec[sec][c]
            src = named.get(sid)
            dom = src[2] if src else "news.example"
            item_n += 1
            title = titles[i % len(titles)]
            last_item[sid] = max(last_item.get(sid, ""), times[i])
            iid = ca.execute(
                "INSERT INTO items(source_id,guid,url,title,summary,published_at,fetched_at,cluster_id) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (sid, f"{sid}-{item_n}", f"https://{dom}/{key}-{item_n}", title,
                 body if i == 0 or src is None or src[4] != "primary" else "", times[i], times[i], cid[key])).lastrowid
            if key in ("rate", "jobs", "budget", "floods", "subway", "model", "housing") and i == 0:
                art_items.append((iid, title, body))
    for iid, title, body in art_items:
        paras = [body, "Analysts and officials offered differing readings of what comes next, and several groups said they would "
                 "wait for more data before changing course.",
                 "Further details are expected later this week."]
        ca.execute("INSERT INTO articles(item_id,text,fetched_at,status) VALUES(?,?,?,'ok')",
                   (iid, "\n".join(paras), _iso(0, "07:00")))
    enabled = [r[0] for r in list(named.values())]
    for sid in enabled:
        ca.execute("INSERT INTO poll_state(source_id,last_ok_at,last_item_at,consecutive_failures,last_run_at) "
                   "VALUES(?,?,?,0,?)", (sid, _iso(0, "23:59"), last_item.get(sid, _iso(0, "04:00")), _iso(0, "23:59")))
    ca.execute("INSERT INTO poll_state(source_id,last_ok_at,last_run_at) VALUES('_run',?,?)",
               (_iso(0, "23:59"), _iso(0, "23:59")))

    def digest(parts, heads):
        out = []
        for sec in ("economy", "politics", "world", "nyc", "tech"):
            if sec not in parts:
                continue
            out.append(f"## {heads[sec]}")
            out += [f"- {txt} [#{cid[k]}]" for k, txt in parts[sec]]
        return "\n".join(out) + "\n"

    heads = {"economy": "Economy", "politics": "Politics", "world": "World", "nyc": "NYC", "tech": "Tech"}
    nw.execute("INSERT INTO digests(date, markdown, created_at) VALUES(?,?,?)", (p.d(0), digest(DIGEST, heads), p.t(-2)))
    nw.execute("INSERT INTO digests(date, markdown, created_at) VALUES(?,?,?)", (p.d(-1), digest(DIGEST_Y, heads), p.t(-26)))
    _stamp(nw, p.t(-48))
    _stamp(ca, p.t(-48))


def check(cons):
    import re
    nw, ca = cons["news"], cons["news-cache"]
    ids = {r[0] for r in ca.execute("SELECT id FROM clusters")}
    for (md,) in nw.execute("SELECT markdown FROM digests"):
        cites = [int(x) for x in re.findall(r"\[#(\d+)\]", md)]
        assert cites and set(cites) <= ids


def _stamp(con, token):
    """Pin every datetime('now') default column to a token, so the seed is deterministic."""
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_migrations'").fetchall():
        for r in con.execute(f'PRAGMA table_info("{t}")').fetchall():
            if "datetime('now')" in str(r[4]):
                con.execute(f'UPDATE "{t}" SET "{r[1]}"=? WHERE "{r[1]}" NOT LIKE \'@%\'', (token,))
