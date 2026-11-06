# CLAUDE-gmail-reference.md — Gmail label taxonomy and glance-file format

Reference material split out of `CLAUDE-gmail.md` on 2026-08-31 (396 lines against the 250-line governance ceiling). Nothing here changed in the move. The operating rules — contact-check, decision types, classification, subagent parallelism, rectification — stay in `CLAUDE-gmail.md`; this file holds the static tree and formats those rules refer to.

## Label structure (as of 2026-05-24, updated 2026-05-25)

```
I. IMPORTANT              critical, non-reference; personal keys, alerts, high-urgency
II. Family + Friends      emails from known contacts (defer — needs contact list)
III. Notes                lists, keepsakes, references that fit no other type
IV. Job Apps
    a. Job Alerts         job board recommendation emails (LinkedIn, Indeed, Handshake, etc.) + friend-forwarded
                          job leads. Stage 1 ingest source for jobs dashboard. NOT for application
                          sent/viewed/rejected notifications — those go to b, c, or d.
    b. Applications       active applications, responses, interviews, offers (currently 0 — all cleared)
    c. Closed             explicit rejection or withdrawal confirmed
        /Apple            company sublabel (35 emails — 3 processes: Nov 2023, Jun–Oct 2024, May–Jul 2025)
        /Huel             company sublabel (4 emails — Apr 2026 process)
        /Order.co         company sublabel (18 emails — Jan 2026 process)
        /Sigma Computing  company sublabel (22 emails — 2 processes: Dec 2025, Feb–Apr 2026)
        /Taskrabbit       company sublabel (4 emails — Jan 2026 rejection)
        /Veeva            company sublabel (16 emails — process closed)
        [CVS: 2 emails — no sublabel (under 3+ threshold)]
        [KENDO: 1 email — no sublabel (under 3+ threshold)]
    d. Timed Out          applied but no response >1 month; not an explicit rejection — just silence
                          Rule: companies that applied to and received zero real human response → delete
                          those emails (don't file them — an application confirmation alone is not a process)
        [theprintspace: 1 email kept (shortlisted by Khyati Seth — real human response)]
        [Quanta: 1 email — Maria Mileva reached out directly]
        [Take Me to the Water: 2 emails — Brynn Bateman training materials exchange]
        [all others cleaned out 2026-05-25 — no real responses from those companies]
    e. Recommendations    entered a process because of a personal referral from someone known.
                          Double-tags: email gets BOTH this label AND the company's c.Closed/d.Timed Out label.
                          Confirmed recommendations (2026-05-25 audit):
                            - Ian Cole → AbelZeta internship (May 2024, in d. Timed Out)
                            - Nina Ford → Sigma Computing BDR (Dec 2025 + Feb 2026 intros, in c. Closed/Sigma)
V. Work
    Isshiki               all email related to Isshiki Matcha employment: onboarding, ops, scheduling,
                          payroll, vendor orders, HR docs, employer events, colleague correspondence
    AV Care               all email related to AV Care / Gary Gelbfish MD employment: onboarding, HR,
                          scheduling, payroll (Fingercheck, Viventium), colleague correspondence
    Juniper & Co         all email related to Juniper & Co (J&Co) NYC employment: SpotOn Teamwork
                          scheduling/clock-in, onboarding, shifts, payroll, colleague correspondence
                          (created 2026-06-05)
VI. Finances
    A. Personal           peer transfers; all 935 sorted 2026-05-25
        /Venmo            773 emails — all venmo.com payment notifications
        /Zelle            157 emails — TD Bank + Chase Zelle peer transfers (bank-agnostic)
        [root]            5 emails — PayPal (×4), Wealthfront (×1)
    B. Invoices
        1. Products
            [root]        single original receipt only — no duplicates
            a. Order Updates   processing follow-ups, second confirmations
            b. Shipping        tracking, shipped, delivered
        2. Services
            a. Transportation
                i.   Ride Share     Uber/Lyft rides where you are in the vehicle
                ii.  Travel         flights, long-distance trains (not hotels)
                iii. Misc           buses, MTA, scooters, city bikes
                iv.  Packages       Uber courier, package/parcel delivery services
            b. Food
                [root]        receipts — Uber Eats, DoorDash, restaurant direct
                i. Reservations    OpenTable, restaurant reservations (temporary)
            c. Housing        rent, hotels, Airbnb
            d. Tickets
                [root]        event tickets — shows, raves, movies (purchase confirmations)
                i. Ticket Transfers   tickets received from someone else (gifted, traded, reserved for you)
                ii. RSVPs             event invitations, Evite RSVPs, party confirmations
            e. Misc           catch-all; create new subfolder when a type accumulates
            f. Personal Care  grooming, haircuts, spa, beauty services
            g. Medical        healthcare payments, doctor/clinic receipts
            h. Utility        home-tied ongoing services: heating oil, electricity, home internet
            i. Waivers        participant agreements, liability waivers signed for activities
        3. Digital
            a. Subscriptions  recurring, free trials, game subscriptions
            b. Games          purchases, in-app only (no subscriptions)
            c. Misc           one-time digital purchases that are not games (apps, software, e-books, etc.)
        4. Banking
            a. Payment Info   payment confirmations — money actually moved (scheduled, received, sent)
            b. Account Notices alerts, security notices, payment due reminders (no money moved)
            c. Promo          promotional emails from card issuers
        5. Portfolio          trading and stock transactions (not tax docs)
        6. Customer Service
            [root]        support tickets, conversations
            a. Refunds        successful refunds, money back
        7. Education          tuition payments, school fees, academic services
    C. Discounts          discount emails containing an explicit code the user must manually enter. Account-applied offers (no code) → DELETE.
VII. Rewards & Gifts
    a. Digital            digital reward codes, virtual collectibles, free digital content
    b. Non-Digital        physical gift cards, tangible rewards
```

## Deferred folders (as of 2026-05-25)

- `Notes` root label (empty) — deferred, do not delete

## Sorted and closed (2026-05-25)

- `VI. Finances/A. Personal` — 935 emails sorted: /Venmo (773), /Zelle (157, bank-agnostic — TD Bank + Chase), root (5: PayPal ×4, Wealthfront ×1). No emails moved to Family + Friends — all senders are financial service domains.
- `VI. Finances/B. Invoices/2. Services/e. Misc` — 2 emails confirmed, both correctly placed (USPS eReceipt, Radical Storage luggage storage — both match the explicit e. Misc examples in classification rules)
- `V. Work/AV Care` — created 2026-05-25; 50 emails moved from I. IMPORTANT (Gary Gelbfish MD / AV Care employment: HR, scheduling, Fingercheck, Viventium, onboarding). Direct deposit credential email trashed.
- `VI. Finances/B. Invoices/2. Services/a. Transportation/iv. Packages` — 11 Uber Connect delivery courier receipts moved from Ride Share (Oct 2025–Jan 2026)
- `VI. Finances/B. Invoices/5. Portfolio/b. Account Notices` — created 2026-05-25; 3 Coinbase API key emails moved from Portfolio root

## Glance file format

Glance files are markdown notes written by Claude during the Gmail skill run. They live at `wiki/notes/job-glances/<company-slug>.md`. The dashboard reads them via `data/job-glances-index.json` (maps `message_id → company_slug`).

**Frontmatter:**
```yaml
---
type: job-glance
company: Acme Corp
company_slug: acme-corp
status: active
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

**Body format** (must follow this structure exactly — dashboard parses these fields by pattern):
```markdown
**Role:** [job title or empty string if not determinable]
**Applied:** [YYYY-MM-DD from email date header]
**Last activity:** [YYYY-MM-DD — plain-language description, e.g. "2026-05-23 — recruiter follow-up re: scheduling"]
**Reply needed:** [yes / no]

**TL;DR:** [1–2 sentence plain-language summary of where things stand]

**Key points:**
- [key fact or action item, under 12 words each]
- [2–5 bullets total]

**Links:**
- [descriptive label](url)
```

**Rules:**
- **One file per email.** `glance_slug` = `<company_slug>-<email_descriptor>`. `company_slug` = kebab-case of company name (lowercase, spaces/specials → `-`). `email_descriptor` = short label for this email's content: `application`, `case-study`, `offer`, `phone-screen`, `interview-request`, `follow-up`.
- TL;DR captures the narrative state for this specific email — not just what it said.
- Key points: only facts that affect what Sam should do or know. No filler.
- Links: extract every actionable URL from the body — job posting, application portal, scheduling link, etc.
- On re-process (same message ID already indexed): update `updated:` and `**Last activity:**` only. Do not overwrite TL;DR.

**Lifecycle:**
- **Created** during Phase 5.5 when an inbox email moves to Applications.
- **Updated** during Phase 5.5 on subsequent emails from the same company.
- **Deleted** during Phase 5.5 (CLOSE_PROCESS rectification) when a rejection is confirmed. Remove message IDs from `data/job-glances-index.json` at the same time.

**Index file** (`data/job-glances-index.json`): flat JSON object mapping Gmail message IDs to per-email glance slugs:
```json
{
  "18e2f3a4b5c6d7e8": "acme-corp-application",
  "18e2f3a4b5c6d7e9": "acme-corp-case-study",
  "18e9a1b2c3d4e5f6": "other-company-application"
}
```

One entry per message ID. Each message ID maps to its own unique slug — multiple emails from the same company get different slugs. The dashboard uses this for O(1) lookup when a user opens an email in the inbox panel.
