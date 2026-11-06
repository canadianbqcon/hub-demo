# CLAUDE-gmail.md — Gmail organization rules

Governs how Claude classifies and sorts emails during Gmail audit and triage sessions. Load this file whenever doing any Gmail folder work (reading, moving, creating labels, auditing).

## Contact-check rule [BINDING]

Before classifying any email, check the sender address and name against `wiki/contacts/`. If the sender matches a known contact, treat it as personal correspondence — do not sort it as a commercial/transactional email regardless of subject line.

**How to apply:** grep `wiki/contacts/` for the sender domain or name before assigning a folder. A match means the email belongs in `II. Family + Friends` or `I. IMPORTANT`, not in a finance or service bucket.

## Label structure

The full folder tree, the deferred folders, and the sorted-and-closed record live in `CLAUDE-gmail-reference.md`.

## Decision types

Every email gets exactly one decision. Apply these after reading the full body:

**MOVE** — email belongs in a label, no user input needed. Determine exact label path from the label structure below. If sender domain is in `approved-senders.txt` (non-unsubscribed line): move silently without surfacing.

**KEEP** — email must stay in inbox. Record why, and whether a date trigger should later move it. See "Keep tracking" section below.

**UNSUBSCRIBE** — user should not be receiving this. See "Unsubscribe safety check" section below.

**DELETE** — no archive value, nothing useful, nothing actionable.

**YOUR CALL** — genuinely ambiguous after reading the full body. Use rarely — not for things that are mildly uncertain. Surface with a plain-English summary and explicit options.

**SECURITY ALERT** — treat as its own category regardless of age. Group all security alerts together in the output (separate from other buckets). Apply the age rule in the "Security alert triage" section below.

## Keep tracking

Emails marked KEEP are recorded in `.claude/skills/gmail/known-inbox.json` so they are skipped on future runs. Entry schema:

```json
{
  "MESSAGE_ID": {
    "status": "keep",
    "reason": "plain-English reason for keeping",
    "type": "flight_credit | rewards | other",
    "processed": "YYYY-MM-DD",
    "trigger_date": "YYYY-MM-DD or null",
    "trigger_type": "date_passed | event_arrival | manual",
    "destination": "label path to file it in once it is settled, \"trash\", or null",
    "task_key": "the planner task the keep waits on, or absent",
    "subject": "email subject line",
    "sender": "sender domain"
  }
}
```

**A keep must say what clears it [BINDING].** Every new KEEP records a `destination` (where it goes once settled) and, when a planner task was created for it, that task's `task_key`. The hourly gmail-lane sweep (`automations/gmail_lane.py` `sweep_keeps`) works through every keep: its task done → moved to `destination` and dropped (a `"trash"` or missing destination is asked on the Automations page instead; the keep sweep never trashes on its own); no open task and past `trigger_date`, or 7 days after `processed` when there is none → shown on the Automations page with its keep reason, where a keep click restarts the 7 days; gone from the inbox → dropped. Before keeping, ask whether the email is already settled and should be filed now instead (see the Venmo request and account-notice edge cases).

**Trigger types:**
- `date_passed` — auto-move when today >= trigger_date. Legacy only — no new entries of this type (flights and Airbnb now MOVE immediately).
- `event_arrival` — keep until a follow-up confirms delivery. Flag manually.
- `manual` — only move on explicit user instruction. Use for: flight credits.

On any Gmail triage run, check existing entries: if `trigger_type == "date_passed"` and `trigger_date <= today`, add to the AUTO-MOVE queue and remove the entry from JSON after moving.

## Correction-learning loop

Every answer Sam gives is logged to `.claude/skills/gmail/gmail-decisions.jsonl` (keyed on sender domain): overrides, agreements with the proposal, and answers to a YOUR CALL (since 2026-10-12; before that only overrides were logged). Both writers log: the Automations page on every click, and `/gmail` at Phase 6. Once a domain's newest **3 answers agree**, a **proposed rule** is filed; nothing acts on it until he confirms it on the Automations **rules** tab (since 2026-10-24; spec `docs/specs/2026-10-22-gmail-rules-tab-design.md` in the vault). A confirmed rule is surfaced as `[learned: N answers]`.

What it changes:
- **Hourly gmail-lane** (`automations/gmail_lane.py`): training is keyed by **(sender domain, kind)**, where `kind` is the model's short label for what the email is (receipt, promo, shipping...). Old answers with no kind count for their domain only until a new answer adds one. Once a pair's rule is confirmed the lane acts in full, even with the job's `auto_move` off: a learned **MOVE** moves, a learned **DELETE** trashes, a learned **KEEP** keeps. A model MOVE for a domain with a confirmed `files_without_asking` rule also moves. Never for a contact match or a review-only label (`I. IMPORTANT`, `II. Family + Friends`, `IV. Job Apps`) on a move. A trained delete is **refused** (the row waits, with the reason) for a contact, a security-sounding kind, or a live review-only label. UNSUBSCRIBE, SECURITY ALERT and YOUR CALL always wait: the lane never unsubscribes. Each run first re-judges waiting rows whose training changed, so his answer clears look-alike siblings.
- **Rules store** (`automations/rules.py`, table `rule`, migration 007): every learned rule (note, streak, file-without-asking sender, finance payee) is proposed, then confirmed, rejected, edited or turned off by him; `rules.discover()` files proposals after each lane run and recheck. A rejected or off rule comes back only from answers after that click, under a fresh `@decided_at` source_ref. Undoing a decision a rule made turns the rule off. Every decision row carries `rule_id`/`rule_rev`, or none for the model's own call.
- **Notes:** a note typed on /mail or the Automations page is appended (dated) to the item and stored in `gmail_note` with its email; its reach (`once`, `standing`, `both`) is judged per note and can be re-picked on the /mail note line. A standing note becomes a proposed rule; only confirmed note rules reach the lane's prompt. A noted email is left for the next /gmail run, never re-judged. A note can also select one typed follow-up (`automations/followups.py`: `craft_update`, `keep_until_superseded`, `ack_then_trash`), each with its own allowlist; nothing from an email body is ever executed.
- **Decision log and undo** (`automations/decisions.py`): every automatic and human effect across Gmail, finance categories and finance memos is a `decision` row in `data/automations.db`, written pending before the effect and finished after. Undo reverses one from its recorded label delta (trash is untrashed, then the old labels restored) and refuses with a conflict when he has since changed the message by hand. Undoing a rule-made call turns that rule off; undoing the model's own call blocks that (domain, kind) until three fresh answers agree, and writes no training row. Fix = undo, then his answer through the normal page path, so only his answer is training. Endpoints: `POST /automations/api/decisions/<id>/undo` and `/fix` (`{answer, fix_key}`).
- **`/gmail`:** the learned answer is only proposed; execution stays behind the Phase 6 confirm gate. If `/gmail` is ever run headless, the draft-only permission boundary still applies.

Stabilized keeps graduate: a domain kept 3 times in a row is proposed as a `files_without_asking` rule by the `/gmail` promotion block (`rules.sender_answers` gates it), and acts only once he confirms it. `approved-senders.txt` now holds only `# unsubscribed` lines. Full mechanics + schema: `.claude/skills/gmail/schema.md` → "gmail-decisions.jsonl".

## Unsubscribe safety check

To unsubscribe from an email:
1. Pull the unsubscribe URL: prefer HTTPS URL from the `List-Unsubscribe` header over mailto. If header absent, find the unsubscribe link in the body.
2. Extract the base domain of the URL and compare to the sender domain. **Match = SAFE. Mismatch (URL shortener, redirect, unknown domain) = FLAGGED.**
3. Do not execute on FLAGGED URLs — surface to user with the raw URL only.
4. For SAFE URLs: `GET` the URL. Confirm `status_code == 200` or response URL contains `confirm`/`success`/`unsubscribe`. After success: trash the email. Append sender domain to `approved-senders.txt` with `# unsubscribed YYYY-MM-DD` comment.

## Classification rules

**Products root vs. Order Updates:** `1. Products` is PHYSICAL items only — things that ship to a physical address. A Products email always comes with a shipping leg (unless the item was purchased in person). Only the first receipt goes in root. Follow-ups (processing confirmations, second receipts) go in `a. Order Updates`. Shipping/tracking go in `b. Shipping`. Digital purchases (apps, software, e-books, one-time digital content, eGift cards, electronic gift cards, any "digital delivery" item) do NOT go here — see `3. Digital/c. Misc` or `b. Games` as applicable. An eGift card is electronic — it goes in Digital, not Products. When in doubt: if it doesn't ship to a door, it's not Products.

**Digital/c. Misc:** One-time digital purchases that are not games and not subscriptions. Examples: mobile apps, productivity software, e-books, one-time software licenses. Decision tree: recurring? → `a. Subscriptions`. Game/in-app? → `b. Games`. Everything else digital → `c. Misc`.

**Travel vs. Housing:** Hotels and Airbnb go in `c. Housing`. Travel is flights and long-distance trains only.

**Ride Share vs. Food Delivery:** Ride Share = you are in the vehicle (Uber/Lyft rides). Uber Eats, DoorDash, food delivery = the food comes to you → `b. Food [root]`. The transport is incidental; what you bought is food.

**Ride Share vs. Travel vs. Transport Misc vs. Packages:**
- Ride Share (`i`): Uber/Lyft rides where you're in the car
- Travel (`ii`): flights, intercity/long-distance trains, long-distance buses (FlixBus)
- Misc (`iii`): MTA, city buses, scooters, city bikes
- Packages (`iv`): Uber courier, parcel delivery, package pickup services

**Services vs. Utility distinction:** Services (`2. Services`) = paying someone to provide something outside your home. Utility (`h. Utility`) = services tied to your home address (heating oil, electricity, home internet). Rule of thumb: would you stop paying this if you moved? Yes → Utility. No → Services.

**In-flight ancillary purchases (WiFi, snacks, bag fees billed separately):** The ticket = `a. Transportation/ii. Travel`. Anything purchased on top of the ticket (in-flight WiFi, airport lounge, in-flight food) → `e. Misc`. Not Travel — travel is getting from A to B. These are services provided en route.

**Payment Info vs. Account Notices:** Payment Info = money actually changed hands (payment confirmed, received, scheduled to send). Account Notices = informational with no current money movement (payment DUE reminders, statements, security notices, balance alerts). A payment due reminder is a notification, not a transaction → Account Notices.

**Games:** `b. Games` is for transactional and account emails: purchases, in-app purchases, game subscriptions, game account notices, in-game event notifications, receipt emails from game companies. Subscription-style billing for a game still goes in `b. Games` — not `a. Subscriptions`. **Exception: promotional and discount emails about games do NOT go in `b. Games` — they go in `C. Discounts`.** The "game over everything" rule applies only to transactional/account email types, not to sale alerts or marketing. A Steam "X is on sale" email → Discounts. A Steam "you purchased X" confirmation → Games. Do not ask the user — apply this rule directly.

**Rewards & Gifts vs. Discounts:** Discounts are offers. Rewards & Gifts are things already earned or given — codes, virtual collectibles, free bundles.

**Discount code vs. account-applied offer:** Only MOVE to `C. Discounts` if the email contains an explicit discount code — an alphanumeric string the user types at checkout (e.g. "Use code SAVE20 at checkout"). Account-applied offers — "first month free", automatic credits, "click to activate" buttons, Uber One promos, "benefit applied to your account" — DELETE. The benefit lives on the account, not in the email; once the user saw the notification in their inbox, the email has no further value. Coded discounts filed in `C. Discounts` are subject to the Phase 2.5 expiration sweep: any email whose code's stated expiry date has passed → DELETE.

**Services/e. Misc policy:** Do not delete this folder. It's a permanent catch-all for one-off service receipts that don't fit existing buckets (e.g. USPS postage, luggage storage). When a specific type starts accumulating, propose a new named subfolder at that point — don't pre-create buckets speculatively.

**Always read the full email body — no exceptions [BINDING]:** Never classify on sender + subject alone. Read the full body of every single email before making any decision. Sender and subject are hints, not answers. This applies regardless of how obvious the classification seems. Contact-check runs before any other classification.

**Newsletters:** If the user reads a newsletter via a dedicated app or external platform (not Gmail), treat inbox emails as duplicates and queue for unsubscribe. The inbox is for action items, not content consumption.

**Event ticket pending fulfillment:** If a ticket purchase is confirmed but tickets are not yet delivered (e.g., "tickets available N weeks before the event"), keep the purchase confirmation in inbox until ticket delivery arrives. Once delivered, move the original confirmation to B. Invoices/2. Services/d. Tickets.

**Future flight credits:** Airlines bank credits in the user's account automatically — no email action required to redeem them at booking. A "future flight credit" notification is informational only. Move to B. Invoices/2. Services/a. Transportation/ii. Travel after reading. Exception: if the credit email shows an expiry date <30 days out, surface it to the user before filing.

## Security alert triage

Security alert emails (login notifications, new device detected, password change, etc.) from any platform:
- **≤1 day old:** Keep in inbox — user may still be aware and acting.
- **>1 day old:** Delete. User either handled it at the time or recognized it as their own action.
- **Exception:** If the alert references a device, browser, or location inconsistent with the user's known activity, keep it regardless of age.
- **During skill runs:** Group ALL security alerts into one batch before acting. Present to user — they will know immediately if any look suspicious. After confirmation, delete cleared ones.

## Subagent parallelism for Phase 4 [BINDING]

Phase 4 (reading all new emails) is the bottleneck and the textbook sub-agent fit: each email is an independent **read-and-classify unit** with a high junk ratio (read the full body, keep a one-line decision). This section instantiates the vault dispatch contract — full decision lens and contract spine in `wiki/patterns/sub-agent-usage.md`. The split is the safety boundary: **sub-agents read and classify only; all execution and all writes stay in the main thread** (Phases 5.5–9). This is the read-fans-out / write-stays-inline rule applied.

**When to fan out:** more than ~40 new emails. At or below that, classify inline — the orchestration overhead isn't repaid. Skip sub-agents entirely for a targeted re-check of a small ID set.

**How to spawn:**

Split the new email IDs into batches of ~40. Fire all batches in parallel — one Agent call per batch (`subagent_type=general-purpose`), all calls in a single message. Each batch prompt carries:
1. Instruction to **Read** `dashboard/CLAUDE-gmail.md`, `dashboard/CLAUDE-gmail-reference.md` (the label tree a classifier needs to name a destination) and `.claude/skills/gmail/approved-senders.txt` itself. Sub-agents have file access — do NOT paste these inline; reading the live files is cheaper than repeating them in every batch prompt and avoids drift.
2. The batch of email IDs to process.
3. The auth + body-extraction pattern (from `.claude/skills/gmail/references/code-patterns.md`).
4. The objective, scope boundary, output schema, and self-verify step below.

**Objective:** for each ID in the batch, fetch the message, read the full body, run the `wiki/contacts/` contact-check, and assign exactly one decision per the classification rules.

**What the sub-agent must NOT do (read-only boundary — this is load-bearing):**
- Do NOT label, move, archive, delete, or unsubscribe any email. No Gmail write calls of any kind.
- Do NOT write glance files, calendar events, or `known-inbox.json`. Those are main-thread phases (5.5, 5.6, 8) and must not run in parallel.
- Do NOT spawn further sub-agents (no recursion).
- Do NOT skip an email because the sender/subject "looks obvious" — read every body, no exceptions.

**Self-verify before returning:** confirm every ID in the assigned batch appears exactly once in the output array, each with a non-empty `decision`. If any ID is missing or undecided, fix it before returning. A dropped ID is an email silently lost from triage.

**Output schema each subagent returns (one object per email, as a JSON array):**
```json
{
  "id": "message_id",
  "subject": "subject line",
  "sender": "sender domain",
  "decision": "MOVE | KEEP | UNSUB | DELETE | YOUR_CALL | SECURITY_ALERT",
  "label": "full label path (for MOVE decisions only)",
  "summary": "one-line plain-English content summary",
  "unsub_url": "https://... (for UNSUB only — HTTPS preferred over mailto)",
  "unsub_safe": true,
  "trigger_date": "YYYY-MM-DD or null",
  "trigger_type": "date_passed | event_arrival | manual | null",
  "destination": "label to move to when trigger fires, or null"
}
```

**Merging:** collect all agent responses, deduplicate by `id` (should never overlap), sort by decision bucket. If a batch errors or returns fewer objects than IDs sent, re-fetch that batch — never skip emails. From the merged list the **main thread** runs everything that writes: Phase 5.5 (glance files), Phase 5.6 (calendar events), then Phases 6–9 (present, execute, track, log). Sub-agents contributed decisions only; no write has happened yet at merge time.

## Email-at-a-glance — skill behavior [BINDING]

Before deleting or moving any informational email (policy updates, announcements, credit notifications, legal notices, account summaries), output a one-line summary:
`[sender] — [plain-language summary, no jargon]`
Then proceed with the action. If the summary surfaces something action-required, mark it IMPORTANT first and wait for user direction.

## Unsubscribe workflow — approved senders list

During cleaning skill runs, batch all promotional/marketing emails by sender domain. Present the full list; user marks which senders to keep receiving. Approved senders stored at `.claude/skills/gmail/approved-senders.txt` (one domain per line). Future runs skip approved senders with no re-prompting. To remove a sender from the list, user tells Claude explicitly.

## Work/Isshiki classification rules

- Emails **to or from** any `@isshikimatcha.com` address → Work/Isshiki
- Employer events with "Isshiki" in subject (Posh, Eventbrite, etc.) → Work/Isshiki
- Work-related correspondence from Isshiki staff using personal email addresses (e.g. priya@example.com) → Work/Isshiki when subject/attachment confirms work context
- Payroll, schedules, inventory, HR, wholesale orders for Isshiki → Work/Isshiki
- Loulou is a related Isshiki entity — emails referencing Loulou → Work/Isshiki
- Resumes sent to Sam in Isshiki context (e.g. Olga's friend resumes) → Work/Isshiki
- W-2, W-4, direct deposit setup → Work/Isshiki (not Finances — these are HR, not transaction receipts)

## Job Apps classification rules

**c. Closed vs. d. Timed Out:** Closed = explicit rejection or confirmed withdrawal. Timed Out = no response after >1 month with no follow-up. Never use Closed as a catch-all for old applications.

**a. Job Alerts (formerly d. Job Site Recs, merged 2026-05-25):** Any email recommending job listings — from a job board (LinkedIn, Indeed, Handshake, etc.) OR from a personal contact forwarding a lead. NOT for application confirmation/status emails from those same platforms — those go to b. Applications or c. Closed. NOT for personal referrals where someone formally introduces you to a hiring contact — those go to e. Recommendations (with the company label as the secondary tag).

**e. Recommendations:** An email qualifies for this label when a known person personally introduces or refers Sam into a job process — i.e., they email a hiring contact directly on Sam's behalf, or forward an internal opportunity from their workplace with intent for Sam to apply. A friend forwarding a cold recruiter email or a job posting URL does NOT qualify — that's a. Job Alerts. Apply this label to the intro/referral email only, not the whole thread; the thread carries the company label (c. Closed, d. Timed Out, b. Applications).

**Company sublabels (3+ rule):** Only create a company sublabel if the company has 3 or more emails in that status bucket. 1–2 emails = application + rejection with no real back-and-forth; no sublabel needed. 3+ emails = a process worth tracking separately. Emails carry BOTH the status label and the company sublabel simultaneously — these are additive Gmail labels, not folder moves.

**Multi-process cadence:** When the same company appears at multiple points in time, read the timeline to split processes. The first email that marks a definitive rejection/closure ends Process 1. Emails arriving after that rejection mark Process 2. If Process 2 reaches its own closure (rejection), all its emails belong in c. Closed under the same company sublabel. If Process 2 has no closure yet (still waiting), those emails are NOT in c. Closed — they belong in b. Applications or e. Timed Out depending on activity. Count emails per closed process together when applying the 3+ rule — a company with 2 closed processes where Process 1 has 14 emails and Process 2 has 8 = 22 total = qualifies for one company sublabel.

**LinkedIn application notifications:** From `jobs-noreply@linkedin.com` — classify by actual status:
- "Your application was sent to X" + no rejection → b. Applications (active) or e. Timed Out (>1 month)
- "Your application was viewed by X" → same logic
- "Your application to X" with rejection language → c. Closed
- Social notifications from `notifications-noreply@linkedin.com` → NOT job-related; leave in inbox or delete

## Edge cases by email type

**Flight — any itinerary (round trip or outbound only):** MOVE to `VI. Finances/B. Invoices/2. Services/a. Transportation/ii. Travel` immediately. Future dates do not trigger a KEEP — file it now. Date is not relevant to the filing decision.

**Future flight credit:** Airlines bank credits automatically — no email action required. Move to Travel after reading. Exception: if credit shows an expiry date <30 days out, surface to user before filing. `type` = `flight_credit`, `trigger_type` = `manual`.

**Venmo payment request (someone requests money from Sam, or a reminder of one):** Not a KEEP. Log the request to `data/owed.db` (`dir = -1`, person, what, amount, incurred = request date; skip when a matching open row already exists, a reminder included), then MOVE to `VI. Finances/A. Personal/Venmo`. The owed row is what tracks it.

**Card locked, card reissued, account notice with nothing to do:** Not a KEEP. MOVE to `VI. Finances/B. Invoices/4. Banking/b. Account Notices`. When it does carry a to-do (update cards on file), create the planner task and file the email; the task carries the to-do, not the inbox.

**Airbnb:** MOVE to `VI. Finances/B. Invoices/2. Services/c. Housing` immediately on receipt. No KEEP, no date trigger.

**Active job application:** MOVE to `IV. Job Apps/b. Applications` immediately. Write a glance file (see "Glance file format" section). Do not KEEP in inbox — the Phase 2.5 rectification sweep handles closure when a rejection arrives.

**Event ticket — purchase confirmed:** MOVE to `VI. Finances/B. Invoices/2. Services/d. Tickets` immediately. Future event dates do not trigger a KEEP. If the ticket has already transferred to someone else, move to `d. Tickets/i. Ticket Transfers` instead.

**Rewards email (e.g. Epic-style credits):** Read the email to find amount and expiry. Keep in inbox as actionable if expiry is within 30 days; summarize amount + expiry clearly. Otherwise move to `VII. Rewards & Gifts`.

**Retargeting email with no List-Unsubscribe header:** Do not assume unsubscribe. Surface to user: "no unsubscribe header — move to Discounts or find the unsubscribe link in the body?"

**Email from known contact (matched in wiki/contacts/):** Do not classify as commercial. Flag as `II. Family + Friends` or `I. IMPORTANT`. Contact-check runs before any other classification.

**Borderline sender (user might want it):** Do not assume unsubscribe. Put in YOUR CALL with options.

**Discount email, sender in approved-senders.txt:** Move to `VI. Finances/C. Discounts` silently — but only if the email contains an explicit discount code. Account-applied offers from approved senders → DELETE regardless of approved-senders status. The approved-senders list does not override the code/no-code rule.

## Glance file format

The glance-file format lives in `CLAUDE-gmail-reference.md`.

## Temporary homes — rectification rules

"Temporary homes" are labels or known-inbox.json entries that are provisional — they expect a status change in the future. The rectification phase (Phase 2.5) checks every temporary home on every skill run.

| Home type | Where it lives | Rectification trigger | Action |
|---|---|---|---|
| `IV. Job Apps/b. Applications` | Gmail label | Rejection email detected (inbox or within Applications) | Move all company emails → `c. Closed`; create company sublabel if 3+; delete glance file + index entries |
| `IV. Job Apps/d. Timed Out` | Gmail label | New inbox email from same company domain | Surface to user: re-engage → move back to Applications, write/update glance; confirmed rejection → move to Closed; no action → leave in Timed Out |
| `type: "ticket_pending"` | known-inbox.json | Delivery/transfer email arrives in inbox batch | Move kept confirmation → `d. Tickets/i. Ticket Transfers`; update tracking |
| `type: "date_passed"` with fired trigger | known-inbox.json | `trigger_date <= today` | Already handled in Phase 3; skip in Phase 2.5 |
| `type: "flight_credit"` with expiry <30d | known-inbox.json | Expiry date approaches | Surface to user in Phase 6 as a reminder; no auto-move |

**Detection heuristics for Application rejections:**

Rejection signals (check body and subject, case-insensitive):
- "unfortunately", "regret to inform", "not moving forward", "decided to move forward with other candidates", "position has been filled", "not the right fit", "we have closed", "no longer considering", "another candidate", "will not be moving forward", "will not be proceeding", "will not be advancing", "will not be extending", "won't be moving forward", "won't be proceeding", "won't be advancing", "unable to offer"

**Signals must carry the verb, not just the negation.** The list used to hold the bare fragments `"will not be"` and `"won't be"`, which match ordinary automated-mail boilerplate — Apple's footer reads "replies will not be read", and that alone flagged every Apple email in the inbox as a rejection. Measured against the live mailbox on 2026-07-26: those two fragments produced 9 false positives across 126 emails in `c. Closed` and all 4 hits in `b. Applications`, including a *Sigma Computing interview confirmation* and two Clipboard application receipts, while catching zero rejections the longer phrasings miss. The expanded forms above caught all 5 real rejections in `c. Closed` (allwhere, Sigma, Huel, Order.co, Taskrabbit) with no false positives. When adding a signal, require the phrase that only appears in a rejection; a bare negation will match footers, scheduling reminders, and privacy boilerplate.

A single signal in an email from the same sender domain as any Applications email is sufficient to trigger a `CLOSE_PROCESS` decision. Present the signal phrase to the user in the RECTIFICATION section so they can confirm before execution.

**Timed Out re-engagement:** match on sender domain. If domain of incoming inbox email matches domain of any Timed Out entry, surface it — do not silently move.
