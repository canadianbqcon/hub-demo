"""jobs.db: about 40 applications across every stage, research, stories, interview prep."""
import json

DB = "jobs"
EXPECT = {"applications": 38, "company_research": 40, "application_process_steps": 30, "stories": 5,
          "interview_qa": 14, "skills": 10, "interviewers": 4, "glossary": 10, "form_fields": 6,
          "resumes": 2}

SAMPLE = "[sample output] Summaries, fit note and research on this row are model-written sample text. "

# industry -> (what the company does, day to day, tools, stage/size, culture vibe)
IND = {
    "logistics": ("runs regional freight and last-mile delivery for mid-size retailers",
                  "Owns weekly dock-to-stock and on-time-delivery reporting, chases root causes with the warehouse leads, and proposes slotting changes.",
                  "SQL, Excel, a BI tool, a warehouse management system", "Series C, about 900 people", "Direct, metrics-heavy, quiet on weekends."),
    "health": ("operates outpatient clinics and the scheduling software behind them",
               "Builds capacity and no-show dashboards for clinic managers and reviews staffing against demand each month.",
               "SQL, Tableau, Excel, an EHR export", "Private, about 1,400 people", "Mission-driven, slower decisions, good benefits."),
    "retail": ("is a regional home-goods retailer with 60 stores and a growing web shop",
               "Forecasts store demand, tunes replenishment parameters, and reports markdown performance to merchandising.",
               "SQL, Python, Excel, an ERP", "Public, about 3,000 people", "Buttoned-up, seasonal crunches, clear ladders."),
    "fintech": ("sells payments and reconciliation tools to small businesses",
                "Monitors payout operations, writes the incident reviews, and automates the manual reconciliation queue.",
                "SQL, Python, Looker, ticketing system", "Series B, about 250 people", "Fast, ambiguous, high ownership."),
    "saas": ("makes workflow software for operations teams",
             "Works with customers on rollout, turns support patterns into product requests, and runs the quarterly health review.",
             "SQL, a CRM, spreadsheets, a BI tool", "Series B, about 180 people", "Friendly, remote-first, writing-heavy."),
    "food": ("supplies produce and prepared food to restaurants and cafeterias",
             "Plans daily routes and inventory, tracks spoilage, and reports margin by account to the owners.",
             "Excel, SQL, route planning software", "Family-owned, about 400 people", "Early starts, practical, loyal staff."),
    "energy": ("installs and services rooftop solar for homeowners",
               "Tracks install pipeline, permit cycle times and crew utilisation, and flags jobs at risk of slipping.",
               "SQL, Excel, Power BI, a field-service app", "Series D, about 1,100 people", "Growth pressure, supportive managers."),
    "civic": ("is a city transit agency's operations planning office",
              "Analyses ridership and on-time performance, supports schedule changes, and prepares board briefings.",
              "SQL, R, GIS tools, Excel", "Public agency, about 600 people", "Stable, process-driven, public-facing."),
}

# company, role, status, industry, source, location, arrangement, type, sal_min, sal_max, priority, role score, years
APPS = [
    # offer
    ("Tidewater Freight", "Senior Operations Analyst", "offer", "logistics", "Referral", "Chicago, IL", "hybrid", "Full-time", 92000, 108000, "high", 9, 4),
    # interviewing
    ("Northgate Clinics", "Operations Analyst II", "interviewing", "health", "LinkedIn", "Chicago, IL", "hybrid", "Full-time", 84000, 98000, "high", 8, 3),
    ("Brightfield Retail", "Supply Chain Analyst", "interviewing", "retail", "Company site", "Evanston, IL", "hybrid", "Full-time", 80000, 94000, "high", 8, 3),
    ("Lumen Payments", "Payments Operations Analyst", "interviewing", "fintech", "Recruiter", "Remote (US)", "remote", "Full-time", 90000, 112000, "medium", 7, 3),
    ("Copper Ridge Solar", "Business Operations Analyst", "interviewing", "energy", "Recruiter", "Chicago, IL", "hybrid", "Full-time", 78000, 92000, "medium", 7, 2),
    ("Orchard Lane Foods", "Logistics Coordinator", "interviewing", "food", "Indeed", "Cicero, IL", "onsite", "Full-time", 62000, 72000, "low", 6, 2),
    # applying / applied
    ("Harbor & Pine", "Operations Analyst", "applying", "logistics", "Company site", "Chicago, IL", "hybrid", "Full-time", 82000, 96000, "high", 9, 3),
    ("Stackwell", "Customer Operations Analyst", "applied", "saas", "Referral", "Remote (US)", "remote", "Full-time", 85000, 100000, "high", 8, 3),
    ("Meridian Transit Authority", "Service Planning Analyst", "applied", "civic", "Government board", "Chicago, IL", "onsite", "Full-time", 74000, 88000, "medium", 7, 2),
    ("Fernhill Health", "Scheduling Analytics Associate", "applied", "health", "LinkedIn", "Oak Park, IL", "hybrid", "Full-time", 70000, 82000, "medium", 6, 1),
    ("Quillon", "Revenue Operations Analyst", "applied", "saas", "Wellfound", "Remote (US)", "remote", "Full-time", 88000, 104000, "medium", 7, 3),
    ("Greywater Logistics", "Inventory Analyst", "applied", "logistics", "Indeed", "Joliet, IL", "onsite", "Full-time", 68000, 78000, "low", 6, 2),
    ("Seabright Energy", "Field Operations Analyst", "applied", "energy", "Company site", "Naperville, IL", "hybrid", "Full-time", 76000, 90000, "medium", 7, 2),
    ("Bluebird Market", "Demand Planning Analyst", "applied", "retail", "LinkedIn", "Chicago, IL", "hybrid", "Full-time", 79000, 93000, "medium", 7, 3),
    # ready (hidden from the funnel, shown in the review queue)
    ("Foxglove Software", "Implementation Analyst", "ready", "saas", "Company site", "Remote (US)", "remote", "Full-time", 78000, 90000, "medium", 7, 2),
    ("Alder & Finch", "Operations Associate", "ready", "retail", "Company site", "Chicago, IL", "hybrid", "Full-time", 66000, 76000, "low", 6, 1),
    # researching
    ("Summit Parcel", "Network Planning Analyst", "researching", "logistics", "Referral", "Chicago, IL", "hybrid", "Full-time", 86000, 102000, "high", 8, 3),
    ("Kestrel Medical Supply", "Procurement Analyst", "researching", "health", "LinkedIn", "Schaumburg, IL", "hybrid", "Full-time", 72000, 86000, "medium", 6, 2),
    ("Pioneer Grocers", "Store Operations Analyst", "researching", "retail", "Indeed", "Chicago, IL", "onsite", "Full-time", 70000, 80000, "medium", 6, 2),
    ("Loomtree", "Business Analyst, Operations", "researching", "saas", "Wellfound", "Remote (US)", "remote", "Full-time", 82000, 98000, "medium", 7, 3),
    ("Ironside Fabrication", "Production Planner", "researching", "logistics", "Indeed", "Elgin, IL", "onsite", "Full-time", 64000, 76000, "low", 5, 2),
    ("Waypoint Rail", "Operations Research Analyst", "researching", "civic", "Company site", "Chicago, IL", "hybrid", "Full-time", 88000, 106000, "high", 8, 4),
    ("Sunmark Solar", "Permitting Operations Analyst", "researching", "energy", "LinkedIn", "Remote (US)", "remote", "Full-time", 76000, 90000, "medium", 7, 2),
    ("Dovetail Kitchens", "Supply Operations Analyst", "researching", "food", "Referral", "Chicago, IL", "hybrid", "Full-time", 74000, 86000, "medium", 7, 2),
    # intaking
    ("Cobalt Freight Systems", "Operations Data Analyst", "intaking", "logistics", "Sweep", "Chicago, IL", "hybrid", "Full-time", 80000, 95000, "medium", 0, 3),
    ("Linden Hospital Group", "Capacity Analyst", "intaking", "health", "Sweep", "Chicago, IL", "onsite", "Full-time", 76000, 90000, "medium", 0, 3),
    ("Pennywhistle", "Marketplace Operations Analyst", "intaking", "saas", "Sweep", "Remote (US)", "remote", "Full-time", 84000, 98000, "medium", 0, 3),
    ("Marlowe Home", "Replenishment Analyst", "intaking", "retail", "Sweep", "Chicago, IL", "hybrid", "Full-time", 72000, 84000, "low", 0, 2),
    ("Ashgrove Utilities", "Asset Operations Analyst", "intaking", "energy", "Sweep", "Aurora, IL", "onsite", "Full-time", 74000, 88000, "low", 0, 3),
    ("Tern Aviation Services", "Ground Operations Analyst", "intaking", "logistics", "Sweep", "Chicago, IL", "onsite", "Full-time", 78000, 92000, "medium", 0, 3),
    # rejected
    ("Redwood Distribution", "Operations Analyst", "rejected", "logistics", "Indeed", "Chicago, IL", "onsite", "Full-time", 70000, 82000, "medium", 7, 3),
    ("Atlas Wholesale", "Supply Planner", "rejected", "retail", "LinkedIn", "Chicago, IL", "hybrid", "Full-time", 74000, 86000, "medium", 7, 4),
    ("Nimbus Health Analytics", "Operations Analyst", "rejected", "health", "Recruiter", "Remote (US)", "remote", "Full-time", 88000, 104000, "high", 8, 4),
    ("Cedar & Stone Hospitality", "Operations Manager Trainee", "rejected", "food", "Indeed", "Chicago, IL", "onsite", "Full-time", 58000, 66000, "low", 5, 1),
    ("Vireo Mobility", "Fleet Analyst", "rejected", "civic", "Company site", "Chicago, IL", "hybrid", "Full-time", 76000, 90000, "medium", 7, 3),
    ("Plumtree Payments", "Operations Associate", "rejected", "fintech", "Wellfound", "Remote (US)", "remote", "Full-time", 72000, 84000, "low", 6, 2),
    # ignored
    ("Granite Peak Staffing", "Account Coordinator", "ignored", "saas", "Indeed", "Chicago, IL", "onsite", "Contract", 48000, 56000, "low", 3, 1),
    ("Oakhaven Properties", "Facilities Analyst", "ignored", "civic", "Indeed", "Gary, IN", "onsite", "Full-time", 60000, 68000, "low", 4, 2),
    ("Zephyr Direct", "Operations Specialist", "ignored", "retail", "LinkedIn", "Remote (US)", "remote", "Full-time", 52000, 60000, "low", 3, 1),
]

# application index -> days since applied
APPLIED_AGO = {0: 32, 1: 24, 2: 22, 3: 19, 4: 26, 5: 17, 6: 3, 7: 9, 8: 11, 9: 6, 10: 8, 11: 12, 12: 5, 13: 4,
               30: 40, 31: 36, 32: 29, 33: 33, 34: 27, 35: 21}

REASONS = {30: "no_reason_given", 31: "candidate_withdrew", 32: "technical_gap", 33: "comp_misalignment",
           34: "headcount_change", 35: "weak_customer_signal"}

SKILLS = [
    ("SQL", "data", "strong", "Window functions, CTEs, query tuning on a warehouse of about 40M rows."),
    ("Excel / Sheets modelling", "data", "strong", "Forecast workbooks, scenario tables, lookups at scale."),
    ("Python (pandas)", "data", "working", "Cleaning, reconciliation scripts, small automations."),
    ("Tableau", "data", "working", "Operational dashboards for a six-person team."),
    ("Power BI", "data", "learning", "Two reports built; modelling still slow."),
    ("Demand forecasting", "operations", "working", "Moving-average and seasonal baselines; no formal ML models."),
    ("Inventory and replenishment", "operations", "strong", "Reorder points, safety stock, cycle counts."),
    ("Vendor management", "operations", "strong", "Scorecards, quarterly reviews, escalations."),
    ("Process mapping", "operations", "working", "Swimlanes and handoff analysis."),
    ("Stakeholder communication", "soft", "strong", "Weekly summaries to ops leadership."),
    ("Team scheduling", "soft", "strong", "Built the shift rota for a 14-person bar team."),
    ("R", "data", "learning", "Coursework level; two plots shipped."),
]

STORIES = [
    ("Cut stockouts by rebuilding the reorder points", "Weekly stockouts on fast-moving items were costing the team about six hours of rework a week.",
     "Own the fix without new tooling.", "Pulled 18 months of usage, recalculated reorder points per item by lead time and variance, and set a monthly review.",
     "Stockouts on the top 40 items fell from 11 a month to 3 within two months.", ["inventory", "analysis", "impact"]),
    ("Vendor scorecard that changed a contract", "Three suppliers shared one rating, so late deliveries were invisible in renewals.",
     "Build a scorecard leadership would trust.", "Defined on-time, in-full and defect rates, backfilled a year of data, and reviewed it with each vendor.",
     "One supplier's renewal was renegotiated with a 4 percent price cut and a delivery penalty clause.", ["vendors", "stakeholders"]),
    ("Taught a shift team a new close-out routine", "Close-out took 55 minutes and cash was off twice a month.",
     "Shorten close-out without more staff.", "Mapped the routine, moved two steps earlier in the shift, wrote a one-page checklist, and trained everyone in one week.",
     "Close-out dropped to 30 minutes and cash variances stopped for the next quarter.", ["process", "leadership", "hospitality"]),
    ("Fixed a reporting error before it reached the board", "A weekly summary double-counted returns after a system change.",
     "Catch and correct it without losing trust.", "Traced the join, showed the finance lead the two numbers side by side, and added a reconciliation check to the pipeline.",
     "Corrected the last six weeks and the check has caught two later errors.", ["data quality", "communication"]),
    ("Built the shift rota that ended last-minute swaps", "Swaps were arranged by text and shifts were routinely uncovered.",
     "Make coverage predictable.", "Collected availability monthly, built a rota template with rules for closing pairs, and published two weeks ahead.",
     "Uncovered shifts fell from about four a month to under one.", ["scheduling", "people"]),
    ("Automated the weekly ops summary", "Writing the summary took about three hours of copy-pasting every Friday.",
     "Free the time for analysis.", "Scripted the queries and a template, kept a manual review step.",
     "Summary now takes 20 minutes and goes out the same afternoon.", ["automation", "reporting"]),
]

TEMPLATES = [
    ("intro", "Walk me through your background.", "Two minutes: operations analyst at a distribution firm, nights running a bar team, what I want next."),
    ("motivation", "Why this company and why this role?", "Name one specific thing the company does that fits my work, then one thing about the role."),
    ("behavioral", "Tell me about a time you used data to change a decision.", "Use the reorder-points story. Numbers first."),
    ("behavioral", "Tell me about a disagreement with a stakeholder.", "Use the vendor scorecard story."),
    ("situational", "A report shows a sudden 20 percent drop. What do you do first?", "Check the data pipeline and definitions before any story about the business."),
    ("technical", "How would you find duplicate records in a large table?", "Group by the natural key, count over one, then decide the survivor rule."),
    ("culture", "How do you like to receive feedback?", "Early, specific, written, then a short call."),
    ("ask_them", "What does success look like in the first 90 days?", "Also ask about the data they trust least."),
]

GLOSSARY = [
    ("OTIF", "On time, in full: share of orders delivered on the promised date with the full quantity.", "operations"),
    ("Safety stock", "Extra inventory held to cover demand or lead-time variability.", "operations"),
    ("Cycle count", "Counting a rotating slice of inventory instead of everything at once.", "operations"),
    ("S&OP", "Sales and operations planning: the monthly meeting that aligns demand and supply plans.", "operations"),
    ("SLA", "Service-level agreement: a promised performance target with consequences.", "operations"),
    ("CTE", "Common table expression: a named subquery that makes long SQL readable.", "data"),
    ("Window function", "SQL calculation across related rows without collapsing them.", "data"),
    ("Cohort analysis", "Comparing groups by when they started to see how behaviour changes over time.", "data"),
    ("ETL", "Extract, transform, load: moving data from source systems into a warehouse.", "data"),
    ("MAPE", "Mean absolute percentage error, a common forecast accuracy measure.", "data"),
    ("ATS", "Applicant tracking system: the software employers use to manage applications.", "hiring"),
    ("Take-home", "An assessment done on your own time and submitted before the interview.", "hiring"),
]

INTERVIEWER_NAMES = [("Dana Whitfield", "Hiring manager"), ("Rohan Mehta", "Senior analyst"), ("Joyce Lindqvist", "Recruiter"),
                     ("Calvin Ortega", "Director of operations"), ("Mei Tanaka", "Analytics lead"), ("Brooks Hendry", "Recruiter")]


def _lines(*xs):
    return "\n".join(xs)


def seed(con, rnd, persona):
    ex = con.execute
    ids = []
    rich = set()
    for i, (co, role, status, ind, src, loc, arr, typ, lo, hi, pri, score, yrs) in enumerate(APPS):
        what, day, tools, stage, vibe = IND[ind]
        has_detail = status in ("offer", "interviewing", "applying", "applied", "ready", "researching", "rejected") and i not in (15,)
        if has_detail:
            rich.add(i)
        applied = persona.d(-APPLIED_AGO[i]) if i in APPLIED_AGO else ""
        created = persona.d(-(APPLIED_AGO.get(i, 4 + (i * 3) % 17) + 3))
        updated = persona.d(-((i * 2) % 9 + (1 if status in ("applying", "applied", "interviewing", "offer") else 3)))
        req = _lines(f"{yrs}+ years in operations, supply chain or business analysis", "Strong SQL and spreadsheet skills",
                     "Comfortable presenting findings to non-technical teams", f"Experience with {tools.split(',')[0]} reporting")
        nice = _lines("Python or R for analysis", "Exposure to forecasting or inventory planning", "Experience in a regulated or high-volume environment")
        closed = status in ("rejected", "ignored")
        row = dict(
            company=co, role=role, status=status, priority=pri, source=src, job_url=f"https://example.com/careers/{co.lower().replace(' ', '-').replace('&', 'and')}/{1000 + i * 7}",
            salary_min=float(lo), salary_max=float(hi), date_applied=applied, notes=(SAMPLE if has_detail and score else "") + ("Referred by Priya." if src == "Referral" else ""),
            created=created, updated=updated, location=loc, priority_reason=("Close to home and the work is the work I want." if pri == "high" else ""),
            score_role=score, work_arrangement=arr, employment_type=typ,
            red_flags=("Posting has been open for 60+ days." if i % 7 == 3 else ""), red_flags_risk=("low" if i % 7 != 3 else "medium") if score else "",
            culture_rating=round(3.2 + (i * 7 % 17) / 10, 1) if has_detail else None,
            culture_recommend=(55 + (i * 11) % 40) if has_detail else None,
            culture_work_life=round(3.0 + (i * 5 % 15) / 10, 1) if has_detail else None,
            requirements=req if score else "", nice_to_haves=nice if score else "", years_required=yrs,
            listing_posted_date=persona.d(-(APPLIED_AGO.get(i, 6) + 8)),
            closed_well="", closed_didnt="", closed_differently="", closed_reason=REASONS.get(i, "no_reason_given") if closed else "",
            closed_date=persona.d(-(APPLIED_AGO.get(i, 5) // 2 + 1)) if closed else "",
            company_summary=f"{co} {what}. {stage}." if score else "", role_summary=(f"{role} at {co}: {day}" if score else ""),
            fit_score=float(round(55 + score * 4.5 + (i % 5), 1)) if score else None,
            fit_reason=(f"Matches the operations and SQL background; {vibe.lower()}" if score else ""),
            approved_at=persona.d(-1, "09:10:00") if status == "ready" else "", submit_log="", ats_posting_id="", ats_host="", canonical_url="", screenshot_path="",
        )
        if i in (30, 33):
            row.update(closed_well="Clear screen call; the recruiter engaged with the forecasting example.",
                       closed_didnt="Gave a vague answer on salary range early.", closed_differently="State the range first and ask theirs.")
        if i == 31:
            row.update(closed_well="Strong first call.", closed_didnt="", closed_differently="")
        cols = ",".join(row)
        cur = ex(f"INSERT INTO applications ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        ids.append(cur.lastrowid)

    # skills and stories
    skill_ids = [ex("INSERT INTO skills (name,category,level,notes,created,updated) VALUES (?,?,?,?,?,?)",
                    (n, c, lv, nt, persona.d(-90), persona.d(-10))).lastrowid for n, c, lv, nt in SKILLS]
    story_ids = [ex("INSERT INTO stories (title,situation,task,action,result,tags,created,updated) VALUES (?,?,?,?,?,?,?,?)",
                    (t, s, ta, a, r, json.dumps(tg), persona.d(-60), persona.d(-12))).lastrowid
                 for t, s, ta, a, r, tg in STORIES]
    for term, definition, cat in GLOSSARY:
        ex("INSERT INTO glossary (term,definition,category,known) VALUES (?,?,?,?)", (term, definition, cat, 1 if cat != "hiring" and len(term) < 6 else 0))
    tmpl_ids = []
    for n, (qt, q, a) in enumerate(TEMPLATES):
        tmpl_ids.append(ex("INSERT INTO interview_qa (application_id,question_type,question,answer,is_template,sort_order,created,updated) VALUES (NULL,?,?,?,1,?,?,?)",
                           (qt, q, a, n, persona.d(-60), persona.d(-30))).lastrowid)

    # research, skills, stories, steps, interviewers per detailed application
    steps_for = {
        "offer": [("Application submitted", "submitted", "complete"), ("Recruiter screen", "screen", "complete"),
                  ("Hiring manager interview", "interview", "complete"), ("Panel with the team", "panel", "complete"),
                  ("Offer review and negotiation", "offer", "active")],
        "interviewing": [("Application submitted", "submitted", "complete"), ("Recruiter screen", "screen", "complete"),
                         ("Hiring manager interview", "interview", "pending"), ("Final round", "panel", "pending")],
        "applying": [("Application drafted", "submitted", "active")],
        "applied": [("Application submitted", "submitted", "complete"), ("Recruiter screen", "screen", "pending")],
    }
    for i in sorted(rich):
        app_id = ids[i]
        co, role, status, ind = APPS[i][0], APPS[i][1], APPS[i][2], APPS[i][3]
        what, day, tools, stage, vibe = IND[ind]
        rr = [
            ("role", "summary", f"{role} at {co}. {day}"),
            ("role", "day_to_day", day),
            ("role", "tools", f"Expect {tools}."),
            ("company", "stage", f"{stage}."),
            ("company", "size", stage.split(",")[-1].strip().capitalize() + "."),
            ("culture", "vibe", vibe),
            ("culture", "green_flags", _lines("Clear job ladder posted publicly", "Managers named on the careers page")),
            ("culture", "red_flags", "Posting language leans on 'fast-paced'; ask about on-call or weekend coverage."),
            ("compensation", "base", f"Posted band ${APPS[i][8]:,.0f} to ${APPS[i][9]:,.0f}."),
            ("role", "environment", "Terms in the posting and in employee reviews: " + ", ".join(
                [GLOSSARY[(i + k) % 10][0] for k in range(3)]) + ". Worth a quick refresher before the screen."),
            ("process", "steps", "Recruiter screen, hiring manager conversation, team panel, then offer."),
        ]
        if status in ("interviewing", "offer"):
            rr += [("intel", "hypothesis", f"{co} probably hired for this role to cover a growth gap; reporting is likely manual today."),
                   ("intel", "sample_questions", _lines("How would you investigate a spike in late deliveries?", "Describe a time you pushed back on a number.")),
                   ("prep", "gap", "Prepare a clean example of automating a recurring report."),
                   ("prep", "standout", "Lead with the reorder-points result; it maps to their problem.")]
        for cat, sub, content in rr:
            ex("INSERT INTO company_research (application_id,category,subcategory,content,created) VALUES (?,?,?,?,?)",
               (app_id, cat, sub, content, persona.d(-(APPLIED_AGO.get(i, 5) + 2))))
        for k in range(3 + i % 3):
            sid = skill_ids[(i + k * 3) % len(skill_ids)]
            ex("INSERT OR IGNORE INTO application_skills (application_id,skill_id,gap,notes) VALUES (?,?,?,?)",
               (app_id, sid, ("low", "medium", "high")[(i + k) % 3], ""))
        for k in range(2):
            ex("INSERT OR IGNORE INTO application_stories (application_id,story_id,notes) VALUES (?,?,?)",
               (app_id, story_ids[(i + k * 2) % len(story_ids)], "Lead story" if k == 0 else ""))
        for n, (label, stype, st) in enumerate(steps_for.get(status, [])):
            ex("INSERT INTO application_process_steps (application_id,step_order,label,step_type,status,notes,created,updated) VALUES (?,?,?,?,?,?,?,?)",
               (app_id, n, label, stype, st, "", persona.d(-30), persona.d(-(APPLIED_AGO.get(i, 5) - n * 3 if st == "complete" else 2))))
        if status in ("interviewing", "offer"):
            for k in range(2):
                nm, rl = INTERVIEWER_NAMES[(i + k) % len(INTERVIEWER_NAMES)]
                ex("INSERT INTO interviewers (application_id,name,role,linkedin_url,background,notes,created) VALUES (?,?,?,?,?,?,?)",
                   (app_id, nm, rl, "", f"{rl} at {co}; background in operations and analytics.", "Likes concrete numbers." if k == 0 else "", persona.d(-6)))
        if status in ("applied", "applying", "interviewing") and i % 2 == 0:
            ex("INSERT INTO resume_notes (application_id,section,note,char_limit,created) VALUES (?,?,?,?,?)",
               (app_id, "summary", f"Lead with inventory and vendor results; mention {tools.split(',')[0]} first.", 320, persona.d(-8)))

    # stale steps for the dashboard: one waiting on him, one waiting on them
    ex("INSERT INTO application_process_steps (application_id,step_order,label,step_type,status,notes,created,updated) VALUES (?,?,?,?,?,?,?,?)",
       (ids[4], 1, "Take-home: staffing model exercise", "assessment", "pending", "Due before the next call.", persona.d(-14), persona.d(-9)))
    ex("UPDATE application_process_steps SET updated=? WHERE application_id=? AND status='pending'", (persona.d(-16), ids[5]))

    # cover letters, interview prep
    for i in (0, 1, 6):
        ex("INSERT INTO cover_letters (application_id,tone,angle,draft,created,updated) VALUES (?,?,?,?,?,?)",
           (ids[i], "plain", "inventory results",
            f"Hello,\n\nI am applying for the {APPS[i][1]} role at {APPS[i][0]}. At Larkspur Labs I rebuilt reorder points for the top 40 items and cut monthly stockouts from 11 to 3. "
            "I would like to bring the same approach to your team.\n\nThanks for reading,\nSam Rivera",
            persona.d(-20), persona.d(-18)))
    for i in (1, 2):
        for n, (qt, q, a) in enumerate(TEMPLATES[:6]):
            ex("INSERT INTO interview_qa (application_id,source_template_id,question_type,question,answer,notes,is_template,sort_order,created,updated) VALUES (?,?,?,?,?,?,0,?,?,?)",
               (ids[i], tmpl_ids[n], qt, q, a + f" Tie it to {APPS[i][0]}.", "", n, persona.d(-8), persona.d(-5)))

    # the review queue: two ready applications with a form and drafted answers
    forms = [
        [("First name", "first_name", "input_text", 1, [], 0, "Sam", ""), ("Last name", "last_name", "input_text", 1, [], 0, "Rivera", ""),
         ("Email", "email", "input_email", 1, [], 0, persona.EMAIL, ""), ("Phone", "phone", "input_text", 1, [], 0, persona.PHONE, ""),
         ("Are you legally authorized to work in the US?", "work_auth", "radio", 1, [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}], 0, "1", ""),
         ("Why do you want to work on implementation at Foxglove?", "why_us", "textarea", 1, [], 0,
          "Rolling out workflow tools to operations teams is what I already do informally at Larkspur Labs. I would like to do it as the job.",
          "I like helping teams adopt new tools and want to do it full time.")],
        [("First name", "first_name", "input_text", 1, [], 0, "Sam", ""), ("Last name", "last_name", "input_text", 1, [], 0, "Rivera", ""),
         ("Email", "email", "input_email", 1, [], 0, persona.EMAIL, ""),
         ("How did you hear about this job?", "source", "input_text", 0, [], 0, "Company careers page", ""),
         ("Describe a process you improved.", "improved", "textarea", 1, [], 0, "", "")],
    ]
    for app_idx, fields in zip((14, 15), forms):
        for n, (lbl, nm, ft, req, opts, demo, val, draft) in enumerate(fields):
            fid = ex("INSERT INTO form_fields (application_id,ord,label,name,field_type,required,options_json,is_demographic) VALUES (?,?,?,?,?,?,?,?)",
                     (ids[app_idx], n, lbl, nm, ft, req, json.dumps(opts), demo)).lastrowid
            if val or draft:
                ex("INSERT INTO answers (application_id,form_field_id,value,rewritten,draft) VALUES (?,?,?,?,?)",
                   (ids[app_idx], fid, val, 1 if draft else 0, draft))
    ex("UPDATE applications SET notes=? WHERE id=?", (SAMPLE + "Drafted answers are sample output; review before sending.", ids[14]))
    # base resumes (no application): the files come from files() below
    for path, variant, label in BASE_RESUMES:
        ex("INSERT INTO resumes (application_id,file_path,variant,label,notes,created,updated) VALUES (NULL,?,?,?,?,?,?)",
           (path, variant, label, "Sample file for the demo.", persona.d(-40), persona.d(-12)))
    # frozen record of what was sent
    for app_idx in (7, 6):
        for n, (q, ft, a) in enumerate([("Email", "input_email", persona.EMAIL), ("Why this role?", "textarea", "My work has been the same problem from the other side: making operations numbers trustworthy."),
                                        ("Earliest start date", "input_text", "Two weeks after an offer")]):
            ex("INSERT INTO sent_answers (application_id,ord,question,field_type,answer,draft,edited,rewritten,sent_at) VALUES (?,?,?,?,?,?,?,?,?)",
               (ids[app_idx], n, q, ft, a, a, 0, 0, persona.d(-APPLIED_AGO.get(app_idx, 3), "10:00:00")))


BASE_RESUMES = [("data/resumes/base/sam-rivera-analytics.pdf", "analytics", "Analytics base"),
                ("data/resumes/base/sam-rivera-operations.pdf", "operations", "Operations base")]


def _pdf(lines):
    """One-page text PDF, stdlib only."""
    text = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(
        "(" + l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") '" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def files(root, rnd, persona):
    for path, variant, label in BASE_RESUMES:
        f = root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_pdf([persona.NAME, f"{label} resume (sample file)", persona.EMAIL, "",
                            "Every line of this demo is placeholder data."]))


def check(con):
    got = {r[0] for r in con.execute("SELECT DISTINCT status FROM applications")}
    assert {"intaking", "researching", "applied", "interviewing", "offer", "rejected", "ignored", "ready"} <= got, got
    assert con.execute("SELECT count(*) FROM applications").fetchone()[0] >= 38
