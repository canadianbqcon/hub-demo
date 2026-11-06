"""Glossary terms and the per-application term matcher."""
from __future__ import annotations

from .db_core import _conn


# ── Glossary ──────────────────────────────────────────────────────────────────

_GLOSSARY_SEED = [
    # sourcing
    (
        "ATS",
        "Applicant Tracking System — software employers use to collect, filter, and manage job applications. Many ATS systems auto-reject resumes that don't match keywords, so mirroring the job posting language matters.",
        "sourcing",
    ),
    (
        "Cold application",
        "Applying to a job without a referral or prior contact at the company. Lower response rate than warm/referred applications.",
        "sourcing",
    ),
    (
        "Referral",
        "When a current employee submits your application internally. Usually bypasses ATS screening and gets faster human review.",
        "sourcing",
    ),
    (
        "Headcount",
        "The approved number of people a team is allowed to hire. A role being posted means headcount is approved; a role being 'paused' usually means headcount was frozen.",
        "sourcing",
    ),
    (
        "Pipeline",
        "The pool of candidates being considered for a role at any given time. Being 'in the pipeline' means your application is active.",
        "sourcing",
    ),
    (
        "Req",
        "Short for requisition — a single open job posting tied to one approved headcount slot. A company can open multiple reqs for the same role title.",
        "sourcing",
    ),
    # compensation
    (
        "Base salary",
        "Fixed annual cash compensation before bonuses, equity, or other extras. This is what's guaranteed regardless of company or personal performance.",
        "compensation",
    ),
    (
        "OTE",
        "On-Target Earnings — total expected pay if you hit performance targets, combining base + bonus. Common in sales and ops roles. Ask what % of people actually hit OTE.",
        "compensation",
    ),
    (
        "Total comp",
        "Everything: base + bonus + equity + benefits. The number that matters for comparing offers — base alone is often misleading.",
        "compensation",
    ),
    (
        "RSU",
        "Restricted Stock Unit — company stock granted to you on a vesting schedule. Not cash until they vest and you sell. Value fluctuates with the stock price.",
        "compensation",
    ),
    (
        "Stock options",
        "The right to buy company stock at a fixed 'strike price'. Valuable if the stock price is above the strike; worthless if below. Common at startups.",
        "compensation",
    ),
    (
        "ESPP",
        "Employee Stock Purchase Plan — lets you buy company stock at a discount (often 10–15%) through payroll deductions. Usually only at public companies.",
        "compensation",
    ),
    (
        "Vesting schedule",
        "The timeline over which equity becomes yours. Common: 4-year schedule with a 1-year cliff. You own nothing until the cliff, then vest monthly/quarterly after.",
        "compensation",
    ),
    (
        "Cliff",
        "The minimum time you must stay before any equity vests. Standard is 1 year. If you leave before the cliff, you get nothing from that grant.",
        "compensation",
    ),
    (
        "Refresh / refresh grant",
        "Additional equity granted after you've been at the company for a while, to keep retention incentives active as earlier grants vest out.",
        "compensation",
    ),
    (
        "Sign-on bonus",
        "One-time cash paid when you join. Often has a clawback clause — if you leave within 1–2 years, you may owe it back (pro-rated or full).",
        "compensation",
    ),
    (
        "Clawback",
        "A provision that lets the employer take back previously paid compensation (bonuses, sign-ons) if you leave early or under certain conditions.",
        "compensation",
    ),
    (
        "401(k)",
        "US employer-sponsored retirement savings plan. Contributions are pre-tax. Many employers match a % of contributions — free money; always check the match and vesting.",
        "compensation",
    ),
    (
        "ESOP",
        "Employee Stock Ownership Plan — a retirement plan where the company contributes shares of itself. Common at private companies as a long-term ownership incentive.",
        "compensation",
    ),
    # work arrangements
    (
        "Hybrid",
        "A split between remote and in-office work. The split varies widely — '2 days in office' vs '4 days in office' are both 'hybrid'. Always confirm the specific expectation.",
        "arrangements",
    ),
    (
        "WFH",
        "Work From Home — used interchangeably with 'remote' in casual speech, but technically means working from your residence rather than a company site.",
        "arrangements",
    ),
    (
        "Distributed",
        "A team or company where employees work from multiple locations, often across time zones. Implies async-first culture and less overlap time.",
        "arrangements",
    ),
    (
        "In-person / onsite",
        "Required to be physically present at a company location. No remote option.",
        "arrangements",
    ),
    # interviews
    (
        "Phone screen",
        "A short (15–30 min) call with a recruiter to confirm basics: role fit, compensation alignment, availability. Usually first step before any real interviews.",
        "interviews",
    ),
    (
        "Gating round",
        "An interview specifically designed to eliminate candidates before moving to the full loop. Often a case study, skills test, or senior interview.",
        "interviews",
    ),
    (
        "Loop",
        "A set of back-to-back interviews (often 3–5) in one day or close succession. Completing the 'loop' means you've met all the interviewers.",
        "interviews",
    ),
    (
        "Debrief",
        "The internal meeting where interviewers share their assessments and make a hire/no-hire decision after your loop.",
        "interviews",
    ),
    (
        "Behavioral interview",
        "Questions about past experience: 'Tell me about a time when…'. Designed to predict future behavior from past actions.",
        "interviews",
    ),
    (
        "STAR method",
        "Situation, Task, Action, Result — the standard framework for answering behavioral questions. Structure your answers in this order for clarity.",
        "interviews",
    ),
    (
        "Case interview",
        "A problem-solving interview where you're given a business scenario to analyze. Common at consulting, ops, and strategy roles.",
        "interviews",
    ),
    (
        "Take-home assessment",
        "A project or test you complete outside the interview room. Can range from 1 hour to multi-day. Ask about time expectations upfront.",
        "interviews",
    ),
    (
        "Panel interview",
        "Multiple interviewers in the room at once, asking questions simultaneously or in rotation.",
        "interviews",
    ),
    (
        "Competency-based interview",
        "Similar to behavioral — structured around specific competencies (leadership, communication, analysis) the role requires.",
        "interviews",
    ),
    # roles & structure
    (
        "IC",
        "Individual Contributor — a non-manager role where you do hands-on work rather than managing people. Most entry/mid-level roles are IC roles.",
        "roles",
    ),
    (
        "TL",
        "Team Lead — often an IC who also coordinates the work of peers without formal management authority. Scope varies a lot by company.",
        "roles",
    ),
    (
        "PM",
        "Product Manager — owns the roadmap and direction for a product. Not to be confused with Project Manager, who coordinates execution of work.",
        "roles",
    ),
    (
        "W-2",
        "Standard US employee status — the employer withholds taxes. Benefits like health insurance and 401k are usually available. Most 'full-time' jobs are W-2.",
        "roles",
    ),
    (
        "1099 / contractor",
        "Independent contractor status — you pay your own taxes (self-employment tax), no benefits from the employer. Higher hourly rate is often required to break even.",
        "roles",
    ),
    (
        "Temp",
        "Temporary employee — fixed-term contract, often through a staffing agency. No guarantee of extension. Sometimes converts to full-time.",
        "roles",
    ),
    # culture & hr
    (
        "PIP",
        "Performance Improvement Plan — a formal document given when an employer is documenting underperformance. In many companies, a PIP precedes termination. Being on a PIP is a serious signal.",
        "culture",
    ),
    (
        "Churn / attrition",
        "The rate at which employees leave a company. High churn is a red flag — it often signals poor management, low pay, or toxic culture.",
        "culture",
    ),
    (
        "Glassdoor rating",
        "Aggregate employee reviews on Glassdoor. Below 3.0 is a warning sign. Look at recent reviews (last 6 months) more than the overall average.",
        "culture",
    ),
    (
        "Recommend %",
        "The % of Glassdoor reviewers who would recommend the company to a friend. Below 60% is generally concerning.",
        "culture",
    ),
    (
        "Onboarding",
        "The process of integrating a new hire — paperwork, training, introductions, and ramping up to full productivity. Good onboarding is a culture signal.",
        "culture",
    ),
    (
        "Span of control",
        "The number of direct reports a manager oversees. A manager with 15+ reports usually can't give much individual attention.",
        "culture",
    ),
    # business / ops jargon
    (
        "KPI",
        "Key Performance Indicator — a measurable value used to track progress toward a goal. Ops roles often own specific KPIs (e.g., response time, error rate).",
        "business",
    ),
    (
        "OKR",
        "Objectives and Key Results — a goal-setting framework. Objective = qualitative goal; Key Results = measurable outcomes that define success.",
        "business",
    ),
    (
        "SLA",
        "Service Level Agreement — a defined commitment for response time or quality (e.g., 'respond to tickets within 4 hours'). Common in ops and account management.",
        "business",
    ),
    (
        "Stakeholder",
        "Anyone with an interest in a project's outcome — could be a customer, another team, or leadership. Ops roles typically manage many stakeholders.",
        "business",
    ),
    (
        "Cross-functional",
        "Involving people from multiple teams or departments. Common in ops roles: 'you'll work cross-functionally with product, sales, and engineering'.",
        "business",
    ),
    (
        "Escalation",
        "Routing an issue to a higher level of authority when it can't be resolved at the current level. Knowing when and how to escalate is a key ops skill.",
        "business",
    ),
    (
        "Run rate",
        "Annualized pace of a metric based on current data. E.g., if you closed $500k in Q1, your run rate is $2M/year.",
        "business",
    ),
    (
        "P&L",
        "Profit and Loss — the financial statement showing revenue, costs, and net profit over a period. 'P&L ownership' means you're responsible for a budget's bottom line.",
        "business",
    ),
    # dashboard-specific
    (
        "Priority score",
        "The dashboard's blended score: Role Fit (45%) + Compensation (25%) + Culture (15%) + Arrangement (15%). Ranges 0–10.",
        "dashboard",
    ),
    (
        "Role fit (score_role)",
        "AI-assessed fit of the role against your candidate profile. 8–10: strong match. 5–7: transferable with gaps. 1–4: weak fit or structural issue.",
        "dashboard",
    ),
    (
        "Comp score",
        "Derived from salary midpoint: $10k = 1 point, capped at 10. Missing salary → neutral 5/10 (which undercounts the role — always enter salary if known).",
        "dashboard",
    ),
    (
        "Arrangement score",
        "Remote = 10, Onsite = 0, Hybrid scales by days remote. Used as one factor in the priority score.",
        "dashboard",
    ),
    (
        "Culture score",
        "Average of Glassdoor overall rating, recommend %, and work-life balance score — all normalized to 0–10. Blank if no data entered.",
        "dashboard",
    ),
]


def _seed_glossary(conn) -> None:
    existing = conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
    if existing > 0:
        return
    conn.executemany(
        "INSERT INTO glossary (term, definition, category) VALUES (?, ?, ?)",
        _GLOSSARY_SEED,
    )


def list_glossary() -> list[dict]:
    with _conn() as conn:
        _seed_glossary(conn)
        rows = conn.execute("SELECT * FROM glossary ORDER BY category, term").fetchall()
    return [dict(r) for r in rows]


def _app_search_text(app_id: int, conn) -> str:
    app = conn.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not app:
        return ""
    research = conn.execute(
        "SELECT content FROM company_research WHERE application_id = ?", (app_id,)
    ).fetchall()
    parts = [
        app["role"] or "",
        app["work_arrangement"] or "",
        app["employment_type"] or "",
        app["notes"] or "",
        app["priority_reason"] or "",
        app["red_flags"] or "",
        app["location"] or "",
    ]
    parts.extend(r["content"] for r in research if r["content"])
    return " ".join(parts)


def _term_patterns(term: str, definition: str):
    import re

    patterns = []
    # Split on "/" or "(" to get individual searchable fragments
    fragments = [
        p.strip() for p in re.split(r"[/(]", term) if p.strip() and len(p.strip()) > 1
    ]
    for frag in fragments:
        patterns.append(re.compile(r"\b" + re.escape(frag) + r"\b", re.IGNORECASE))
    # For pure abbreviations (2–6 all-caps), also match the full form from the definition
    if re.match(r"^[A-Z0-9]{2,6}$", term.strip()) and " — " in definition:
        full_form = definition.split(" — ")[0].strip()
        if full_form and full_form.lower() != term.lower():
            patterns.append(
                re.compile(r"\b" + re.escape(full_form) + r"\b", re.IGNORECASE)
            )
    return patterns


def get_app_glossary(app_id: int) -> list[dict]:
    with _conn() as conn:
        _seed_glossary(conn)
        text = _app_search_text(app_id, conn)
        rows = conn.execute("SELECT * FROM glossary ORDER BY category, term").fetchall()
    if not text:
        return []
    matched = []
    for row in rows:
        d = dict(row)
        for pat in _term_patterns(d["term"], d["definition"]):
            if pat.search(text):
                matched.append(d)
                break
    return matched


def set_glossary_known(term_id: int, known: bool) -> dict | None:
    with _conn() as conn:
        conn.execute(
            "UPDATE glossary SET known = ? WHERE id = ?", (1 if known else 0, term_id)
        )
        row = conn.execute("SELECT * FROM glossary WHERE id = ?", (term_id,)).fetchone()
    return dict(row) if row else None


def delete_glossary(term_id: int) -> bool:
    # Permanent "forget" — the term won't resurface for any application. The glossary is a
    # global table matched per-app by text, and _seed_glossary only seeds an empty table, so
    # a deleted row stays gone. Reachable only from the known section's second confirm.
    with _conn() as conn:
        cur = conn.execute("DELETE FROM glossary WHERE id = ?", (term_id,))
    return cur.rowcount > 0
