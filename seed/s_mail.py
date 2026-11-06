"""mail.db for the demo: one mailbox, labels, threads, summaries, list titles and previews.

internal_date is an epoch-millisecond INTEGER, which the reset does not rewrite, so
dates are counted from the fixed ANCHOR day (see report). AI-written rows (summary,
short_title, list_preview) carry model "demo-sample" so a later task can chip them.
"""
import calendar
import hashlib
import html
import json

DB = "mail"
EXPECT = {"account": 1, "label": 8, "message": 20, "summary": 3, "short_title": 10, "list_preview": 10}

ANCHOR = (2026, 11, 6)  # fixed day the seeder was written; hours below count from its midnight UTC
SAMPLE = "demo-sample"
AIRLINE_NOTE = "Atlantic Air"


def _ms(day_off, hour, minute=0):
    base = calendar.timegm((*ANCHOR, 0, 0, 0))
    return (base + day_off * 86400 + hour * 3600 + minute * 60) * 1000


LABELS = [  # (id, name, type)
    ("INBOX", "INBOX", "system"), ("UNREAD", "UNREAD", "system"), ("SENT", "SENT", "system"),
    ("DRAFT", "DRAFT", "system"), ("SPAM", "SPAM", "system"), ("TRASH", "TRASH", "system"),
    ("STARRED", "STARRED", "system"), ("IMPORTANT", "IMPORTANT", "system"),
    ("Label_1", "Receipts", "user"), ("Label_2", "Travel", "user"), ("Label_3", "Jobs", "user"),
    ("Label_4", "Banking", "user"), ("Label_5", "Newsletters", "user"), ("Label_6", "Work", "user"),
]

ME = ("Sam Rivera", "sam.rivera@example.com")

# Each thread: key, labels, subject, short title, preview, [message...]
# Message: (day_offset, hour, minute, from_name, from_addr, body, unread, attachments)
T = []


def _t(key, labels, subject, title, preview, msgs, summary=None):
    T.append(dict(key=key, labels=labels, subject=subject, title=title, preview=preview, msgs=msgs, summary=summary))


_t("order", ["INBOX", "UNREAD", "Label_1"], "Your Brightcart order has shipped", "Brightcart Order Shipped",
   "Plug adapter ships today, arrives Tuesday.",
   [(-1, 15, 4, "Brightcart", "orders@brightcart.example",
     "Hi Sam,\n\nGood news: your order #BC-48213 has shipped.\n\nItem: Type F travel adapter (2 pack)\nCarrier: Parcel Express\nTracking: PX904412267\nExpected delivery: Tuesday\n\nThanks for shopping with Brightcart.", True, [])])

_t("harbor", ["INBOX", "IMPORTANT", "Label_3"], "Re: Operations Analyst - next steps", "Harbor & Pine Next Steps",
   "Recruiter proposes a 45 minute call Thursday at 2pm.",
   [(-4, 16, 20, "Noor Hadley", "noor.hadley@harborpine.example",
     "Hi Sam,\n\nThanks for applying to the Operations Analyst role at Harbor & Pine. The team liked your write-up of the inventory forecasting project.\n\nWould you have 45 minutes this week for a call with the hiring manager? I have Wednesday afternoon or Thursday at 2pm Central open.\n\nBest,\nNoor", False, []),
    (-4, 18, 2, ME[0], ME[1],
     "Hi Noor,\n\nThursday at 2pm works well. Happy to share a one page summary of the forecasting project beforehand if that helps the team prepare.\n\nThanks,\nSam", False, []),
    (-3, 9, 41, "Noor Hadley", "noor.hadley@harborpine.example",
     "Perfect, Thursday at 2pm Central it is. The invite will come from the scheduling tool in a few minutes. A one pager would be great, send it whenever it is ready.\n\nNoor", False, [])],
   summary=dict(bullets=["Noor at Harbor & Pine wants a 45 minute call with the hiring manager.",
                         "Sam accepted Thursday at 2pm Central and offered a one page project summary.",
                         "Noor confirmed the slot and asked for the one pager before the call."],
                needs="Send the one page summary of the forecasting project before Thursday."))

_t("copper", ["INBOX", "Label_3"], "Copper Ridge: quick intro call?", "Copper Ridge Intro Call",
   "Recruiter asks for a 20 minute intro call next week.",
   [(-6, 11, 15, "Elliot Marsh", "elliot@copperridge.example",
     "Hello Sam,\n\nI came across your profile and think you could be a fit for a senior analyst opening on our supply planning team at Copper Ridge. Do you have 20 minutes next week for an intro call?\n\nElliot", False, [])])

_t("transfer", ["INBOX", "UNREAD", "Label_2"], "Lisbon airport transfer: your quote", "Lisbon Transfer Quote",
   "Two quotes in: 38 euros private, 22 euros shared shuttle.",
   [(-3, 13, 10, "Tagus Transfers", "bookings@tagustransfers.example",
     "Dear Sam,\n\nThank you for your enquiry. For arrival at LIS, we can offer:\n\n- Private car, up to 4 passengers: 38 EUR\n- Shared shuttle to central Lisbon: 22 EUR per person\n\nThe quote is valid for 7 days. Reply with your flight number to confirm.\n\nKind regards,\nTagus Transfers", True, []),
    (-2, 8, 5, "Lisboa Easy Ride", "hello@lisboaeasyride.example",
     "Hello Sam,\n\nHere is our price for the airport pickup: 41 EUR for a private minivan, meet and greet included, 60 minutes of waiting time free.\n\nBest wishes,\nLisboa Easy Ride", True, [])],
   summary=dict(bullets=["Tagus Transfers quoted 38 EUR private or 22 EUR per person shared.",
                         "Lisboa Easy Ride quoted 41 EUR for a private minivan with meet and greet.",
                         "Tagus quote is valid for 7 days."],
                needs="Compare the two quotes and reply with the flight number to the one chosen."))

_t("priya", ["INBOX", "STARRED"], "Lisbon itinerary?", "Lisbon Itinerary Question",
   "Priya asks for the day by day plan before she books time off.",
   [(-2, 19, 30, "Priya Nair", "priya.nair@example.com",
     "Hey Sam, are you sharing the Lisbon plan soon? I want to put in my time off request and need to know which days have the tram tour.", False, []),
    (-2, 20, 14, ME[0], ME[1],
     "Working on it tonight. Day three is the Alfama tram tour, the rest is loose. I will send the full list tomorrow.", False, []),
    (-1, 12, 3, "Priya Nair", "priya.nair@example.com", "Great, thank you! No rush, just need it by Friday.", False, [])],
   summary=dict(bullets=["Priya wants the Lisbon plan before she requests time off.",
                         "Sam said day three is the Alfama tram tour and the rest is loose.",
                         "Priya needs the list by Friday."],
                needs="Send Priya the full Lisbon list by Friday."))

_t("schedule", ["INBOX", "UNREAD", "Label_6"], "Juniper & Co: schedule for next week", "Next Week Shift Schedule",
   "Posted: Fri, Sat close; Thu bar back. Swap requests by Wednesday.",
   [(0, 7, 45, "Dana Whitcomb", "dana@juniperandco.example",
     "Team,\n\nNext week's schedule is posted.\n\nSam: Thu 5pm-close (bar back), Fri 6pm-close (bar), Sat 6pm-close (bar)\n\nSwap requests need to be in by Wednesday noon. Please keep the group thread clean.\n\nDana", True,
     [{"filename": "schedule-week46.pdf", "mimeType": "application/pdf", "size": 48213, "attachmentId": ""}])])

_t("hr", ["INBOX", "Label_6"], "Open enrollment closes November 15", "Benefits Enrollment Deadline",
   "Larkspur Labs benefits enrollment closes Nov 15.",
   [(-8, 10, 0, "Larkspur Labs People Team", "people@larkspurlabs.example",
     "Hi Sam,\n\nA reminder that open enrollment for 2027 benefits closes on November 15. If you make no changes, your current elections roll over.\n\nSelections are made in the benefits portal.\n\nPeople Team", False, [])])

_t("statement", ["INBOX", "Label_4"], "Your October statement is ready", "October Statement Ready",
   "Lakeshore Credit Union statement is ready to view.",
   [(-5, 6, 0, "Lakeshore Credit Union", "noreply@lakeshorecu.example",
     "Your October statement for the account ending 4471 is now available in online banking. For your security, we never include account details in email.", False, [])])

_t("code", ["INBOX", "UNREAD"], "Your sign-in code", "Sign-in Code",
   "Your verification code is 482913.",
   [(0, 6, 12, "Parcel Express", "security@parcelexpress.example",
     "Your Parcel Express verification code is 482913. It expires in 10 minutes. If you did not request it, ignore this message.", True, [])])

_t("nl-data", ["INBOX", "UNREAD", "Label_5"], "Data Notes #212: forecasting with small samples", "Data Notes Small Samples",
   "This week: bootstrapping, and when a plain average beats a model.",
   [(-1, 5, 30, "Data Notes", "editor@datanotes.example",
     "Data Notes #212\n\n1. Forecasting with small samples: when a plain average beats a model\n2. A checklist for reading a dashboard before you trust it\n3. Three charts that hide more than they show\n\nRead online or reply to this email with questions.", True, [])])

_t("nl-cook", ["INBOX", "Label_5"], "The Cook's Almanac: braise season", "Almanac Braise Season",
   "Five braises worth the weekend, with a shopping list.",
   [(-3, 5, 30, "The Cook's Almanac", "hello@cooksalmanac.example",
     "Braise season is here. This week: short rib with orange, a white bean and fennel pot, chicken thighs with olives, a lamb shoulder for company, and a vegetarian one with squash.", False, [])])

_t("promo", ["INBOX", "UNREAD"], "48 hours only: 40% off everything", "Flash Sale Promo",
   "Promotional offer, expires in 48 hours.",
   [(-1, 8, 0, "StyleDash Deals", "offers@styledash.example",
     "FLASH SALE! 40% off everything for the next 48 hours. Use code FLASH40 at checkout.\n\nTo stop these emails, unsubscribe here.", True, [])])

_t("electric", ["INBOX", "Label_1"], "Your electric bill is ready", "Electric Bill Ready",
   "October electric bill, due Nov 21.",
   [(-4, 7, 0, "Prairie Power", "billing@prairiepower.example",
     "Your October bill is ready. Amount due: $61.18. Due date: November 21. Pay online or set up automatic payments.", False, [])])

_t("sent-draft", ["DRAFT"], "Re: Copper Ridge: quick intro call?", "Copper Ridge Reply Draft",
   "Draft reply to Elliot, not sent.",
   [(-5, 21, 3, ME[0], ME[1], "Hi Elliot,\n\nThanks for reaching out. I am currently in an active process elsewhere but would be glad to talk next week. Tuesday or Wednesday morning works.\n\nSam", False, [])])

_t("spam", ["SPAM", "UNREAD"], "You have been selected: claim your reward", "Reward Claim Spam",
   "Unsolicited reward notice.",
   [(-2, 3, 11, "Rewards Team", "claims@rewardz-now.example", "Congratulations, you have been selected! Click the link to claim your reward before it expires.", True, [])])

_t("trash", ["TRASH"], "Parking permit renewal receipt", "Parking Permit Receipt",
   "Old receipt, moved to trash.",
   [(-12, 9, 0, "City Parking", "permits@cityparking.example", "Your residential permit has been renewed through next November. Receipt attached.", False, [])])


def _id(n):
    return hashlib.sha256(f"demo-mail-{n}".encode()).hexdigest()[:16]


def build():
    """Deterministic ids and the rows, shared with s_system (gmail_item rows point at these)."""
    out, n = [], 0
    for t in T:
        mids = []
        for m in t["msgs"]:
            n += 1
            mids.append(_id(n))
        out.append((t, mids))
    return out


def thread_ids():
    """{thread key: (thread_id, [message ids newest last])} for other modules."""
    return {t["key"]: (mids[0], mids) for t, mids in build()}


def _html(body):
    paras = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in body.split("\n\n"))
    return f"<html><body style=\"font-family:sans-serif;font-size:14px\">{paras}</body></html>"


def seed(con, rnd, persona):
    con.execute("INSERT INTO account (id, provider, address, history_id, synced_at, scan_gen) VALUES (1,'gmail',?,?,?,1)",
                (persona.EMAIL, "5120934", persona.t(-1)))
    con.executemany("INSERT INTO label (account_id, id, name, type) VALUES (1,?,?,?)", LABELS)
    now = persona.t(-1)
    for t, mids in build():
        tid = mids[0]
        prev = []
        for m, mid in zip(t["msgs"], mids):
            day, hr, mi, fname, faddr, body, unread, atts = m
            mine = faddr == ME[1]
            labels = [x for x in t["labels"] if x != "UNREAD"]
            if unread:
                labels.append("UNREAD")
            if mine and "DRAFT" not in labels:
                labels = ["SENT"] + [x for x in labels if x != "INBOX"]
            to = ["priya.nair@example.com"] if t["key"] == "priya" and mine else [persona.EMAIL]
            if mine:
                to = [t["msgs"][0][4]]
            atts = [dict(a, attachmentId=f"att-{mid}") for a in atts]
            con.execute(
                "INSERT INTO message (account_id,id,thread_id,internal_date,from_addr,from_name,to_addrs,cc_addrs,reply_to,"
                "subject,snippet,body_text,body_html,label_ids,rfc_message_id,rfc_references,attachments_json,scan_gen) "
                "VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                (mid, tid, _ms(day, hr, mi), faddr, fname, json.dumps(to), json.dumps([]), None,
                 t["subject"] if not prev else "Re: " + t["subject"].removeprefix("Re: "),
                 html.escape(body.replace("\n", " ")[:140]), body, _html(body), json.dumps(labels),
                 f"<{mid}@mail.example>", " ".join(prev), json.dumps(atts) if atts else None))
            prev.append(f"<{mid}@mail.example>")
        # AI-written rows, marked model=demo-sample
        con.execute("INSERT OR IGNORE INTO short_title (subject,title,model,cost_usd,created_at) VALUES (?,?,?,0,?)",
                    (t["subject"], t["title"], SAMPLE, now))
        con.execute("INSERT INTO list_preview (msg_id,text,model,cost_usd,created_at) VALUES (?,?,?,0,?)",
                    (mids[-1], t["preview"], SAMPLE, now))
        if t["summary"]:
            sh = hashlib.sha256("\n".join(sorted(mids)).encode()).hexdigest()
            con.execute("INSERT INTO summary (thread_id,source_hash,text,model,prompt_version,cost_usd,created_at) VALUES (?,?,?,?,?,0,?)",
                        (tid, sh, json.dumps({**t["summary"], "cut": False}), SAMPLE, "sample", now))
    con.execute("INSERT INTO draft_log (thread_id,gmail_draft_id,model,cost_usd,created_at) VALUES (?,?,?,0,?)",
                (thread_ids()["sent-draft"][0], "r-demo-draft-1", SAMPLE, persona.t(-30)))


def check(con):
    assert con.execute("SELECT count(*) FROM message_fts").fetchone()[0] >= 0
    hit = con.execute("SELECT count(*) FROM message WHERE rowid IN (SELECT rowid FROM message_fts WHERE message_fts MATCH '\"Lisbon\"')").fetchone()[0]
    assert hit >= 2, "full-text search finds the Lisbon threads"
    multi = con.execute("SELECT count(*) FROM (SELECT thread_id FROM message GROUP BY thread_id HAVING count(*) > 1)").fetchone()[0]
    assert multi >= 3
    # a thread summary only shows when its source_hash matches its message ids
    for tid, sh in con.execute("SELECT thread_id, source_hash FROM summary").fetchall():
        ids = sorted(r[0] for r in con.execute("SELECT id FROM message WHERE thread_id=?", (tid,)))
        assert sh == hashlib.sha256("\n".join(ids).encode()).hexdigest()
