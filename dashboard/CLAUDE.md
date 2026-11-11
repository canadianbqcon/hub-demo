# CLAUDE.md — dashboard/ (Flask apps + dashboards)

Rules for code and content under `dashboard/`. Loaded when editing dashboard apps (trips, jobs, checklists, purchases, etc.) or their backing data.

Cross-module rules live here. Module-specific rules live in subfolder CLAUDE.md files — currently only `dashboard/jobs/CLAUDE.md` (3-stage jobs pipeline). When editing in a subfolder, that file loads in addition to this one.

**Gmail organization work:** load `dashboard/CLAUDE-gmail.md` in addition to this file. It holds the contact-check rule and the classification logic; the full label tree and the glance-file format sit beside it in `dashboard/CLAUDE-gmail-reference.md`.

**Offline behaviour:** load `dashboard/CLAUDE-hub-offline.md` in addition to this file. It holds the two network-first rules — the phone service worker and the last-good cache behind the calendar and money panels — and why neither may become cache-first.

**Any UI element work:** load `dashboard/CLAUDE-blueprints.md` in addition to this file. It holds the read-first rule for the shared blueprint index at `/blueprints` — build from an existing component before writing a new one, and a new shared element gets its blueprint in the same change. Hook-free but suite-enforced.

**No link-styled text as a control.** An action (show more, retry, reset, open) is a `.hub-btn`, never accent or underlined text (his words, 2026-11-08 send-back on mark 042217: "never have hyperlink text anywhere in my hub"). Older sites still styled that way turn up with a grep for `text-decoration: *underline` in hub CSS; convert any you touch.

**Page text is labels, never sentences [BINDING] (his rule, 2026-11-03 /finances marks).** Titles, subtitles, notes under a heading, `<summary>` lines, empty states and readouts are short phrases or figures (`shifts + unemployment`, `inputs`, `1.8× Sunday pool · $90 tips`), never a sentence explaining how something works or talking to him. The why lives in code comments and wiki nodes. A sentence on the page only when he asks for one there. **Not covered:** full descriptions, where the description is the content itself (a stored note, an item's description field, a research write-up, an expandable details body); those stay full text (his send-back on mark 041538:2).

**Trips work:** load `dashboard/CLAUDE-trips.md` in addition to this file. It holds the trip-planner duo pattern and the mandatory-field rules for every `data/trips.db` activity row.

**Scaffolding a new module:** load `dashboard/CLAUDE-new-module.md` in addition to this file. It's the worked blueprint — file layout, db.py/api.py conventions, launcher registration, frontend/CSS rules — distilled from `trips/`, the most-evolved module in the Hub.

## Hub conventions [BINDING]

- **Naming:** the app is "the Hub", modes are "dark" and "light". Skin names (vesper, cobalt) stay internal ids, never app identity; never dusk/dawn as mode strings.
- **Money shows exact cents** (`f"${x:.2f}"`) on every finance surface; rounding once grouped two interest charges into a phantom subscription.
- **At a glance:** never show a bucket label (`close`, `medium`) without the values or scale behind it; keep the bucket for colour only.
- **Order titles** (`purchases.db` `orders.item`) are the base model as a noun (`Anon M5`, `Crucial X10 Pro`); variant, capacity and bundle detail go to `notes`.
- **Stored text is proper case**; the Vesper lowercase look is CSS only.

## Verify on the live server [BINDING]

After any Hub template, JS, CSS or `.py` edit, `systemctl --user restart hub-dashboard.service` before claiming a fix (Flask caches compiled Jinja; bumping `?v=N` alone does nothing; never `pkill -f`, the cmdline is cwd-relative). Keep exposed mode (`DASHBOARD_EXPOSED=1`) if the launch env set it. "Nothing changed" from him means a serving gap: check page-route `Cache-Control: no-store`, a missed process restart, or a verification server started from the wrong checkout (`ls -l /proc/<pid>/cwd`). Verify the live port with a forged session cookie (`config.load_or_create_secret_key()` + `SecureCookieSessionInterface`), then screenshot in real Chrome and read the PNG. An audit covers only the states it opened (modals, drawers, hover, empty and error states, landscape phones). Tools: `bin/hub-viewport-audit.py`, `bin/hub-launcher-check.py`.

## Parallel sessions: claim Hub files [BINDING]

Two live sessions editing one Hub file clobber each other, and a session can verify against another's half-done edit. `<vault>/.claude/hooks/vault-hub-scope-gate.py` (PreToolUse on Edit/Write/MultiEdit/Bash) gives each session per-file claims under this folder; G below is that script.

- **Claim before the first edit:** `python3 G claim <file>...` with every file you plan to touch. Free files are claimed; a held file prints its holder, so order that step last. An edit of an unclaimed free file claims it too.
- **Release when a file is done:** after its edits are verified and any subagents writing it have finished, `python3 G release <file>` (or `--all`). Closing your pending file, or the session exiting, also releases.
- **The holder is named by session** (`PID n, session <name>`, read from `~/.claude/sessions/<pid>.json`). That name is the `SendMessage` address: to ask the holder for a change, message it directly; never guess a name from start times.
- **On a refusal:** park the step with `  - waiting on <label> (PID n, session <name>) for <file>`, do your other steps first, then run `python3 G wait <file>` with run_in_background and resume on its exit. Exit 3 means a wait cycle and you hold the newest claim: get your file consistent, release it, wait again.
- **Re-read after acquiring.** The file changed while you waited. `python3 G list` shows every claim and waiter.

## First-run setup on a new machine

Three gitignored files must be created by hand on each machine (grey connector dots in the Hub status strip mean one is missing): see `dashboard/CLAUDE-first-run.md`.

## Wiki–implementation sync

Wiki nodes that document *how the system works* (score formulas, endpoint shapes, DB schema, config values, feature behavior) are write-once by default — they're created during the build session, then subsequent sessions change the code without revisiting the wiki. This produces silent factual drift.

**Rule:** When any code or DB change affects a value, behavior, or formula documented in a wiki node, that wiki node **must be updated in the same operation** — not deferred. This is binding even when the wiki update feels cosmetic.

**How to apply this rule in practice:**

1. Before closing any session that changed `dashboard/` code or `data/trips.db` schema/values, read the `relationships` block of every changed file.
2. For each wiki node listed there, scan for any section that documents a value now changed by the code edit (formulas, rates, endpoint paths, feature flags, capacity limits, scoring weights, UI behavior).
3. If any wiki value is now stale: update it before declaring the session task done. Update `updated:` date in frontmatter.
4. If no wiki node documents the changed behavior: that's fine — nothing to do. The rule applies only when a wiki node explicitly documents the changed value.

**What counts as an "implementation value":**
- Mathematical formulas and their weights (`Score = 0.40 × P + 0.60 × C`)
- Endpoint paths, request/response shapes
- Port numbers, config defaults
- UI behavior that's documented (e.g. "clicking X does Y")
- Any number that would be wrong if a reader used the wiki instead of reading the code

**What does NOT trigger this rule:**
- Code refactors that don't change external behavior
- DB content changes (new rows, updated text) that aren't documented in any wiki methodology section
- Style / CSS changes

Root cause of this rule: discovered 2026-05-14 when `texas-trip-may-2026-research.md` still documented `Score = 0.55 × P + 0.45 × C` after the code had been changed to `0.40/0.60`. See [[wiki/problems/wiki-implementation-drift]].

## Dashboard code standards [BINDING]

When starting any session that involves writing or editing dashboard code (Python, SQL, or frontend JS/HTML/CSS), read:

- `wiki/notes/dashboard-code-structure.md` — canonical project layout, module boundaries, layer separation, naming conventions
- `wiki/notes/dashboard-code-quality-standards.md` — vibe-coding discipline, security, SQLite best practices, Python hygiene

For any session involving tests or CI setup, also read `wiki/notes/dashboard-testing-strategy.md`.

**Any frontend layout work also reads `wiki/patterns/dashboard-responsive-layout.md` before writing CSS.** Sam half-snaps browsers on 2560x1440 monitors, so **1280x1300 is the design target, not the maximised window**. Three rules, all binding: a viewport-locked panel gets `overflow-y: auto` and never `overflow: hidden`; a breakpoint fires at the width a column stops *fitting* (compute it from rail widths, gaps, padding and the narrowest content), never at the width it stops feeling roomy; and a component inside a column sizes off a `@container` query, not a viewport media query. A layout is not done until it has been rendered headless at 2560x1300 **and** 1280x1300, in its real interactive states, with zero clipped elements.

**Every database surface takes the three-pane shape [BINDING].** Left rail = the biggest separate things in that database, one row each, picked by. Middle = the real working space, the picked thing opened out into cards. Right strip = the supplementary read (progress, dates, a map), never the thing you came to change. The chassis is the **tabbed 3-pane origin** (`static/css/origins/tabbed-3-pane.css`, one entry in `blueprints.json`'s `origins` list): a new module links it after `components.css`, pastes its skeleton off the layouts tab of `/blueprints`, and registers as a derivative, rather than re-inventing the layout. Purchases' `.pe-*` classes (`.pe-body`, `.pe-rail`, `.pe-split[data-split=...]`, `.pe-context`) are the pre-origin chassis, not yet migrated onto it — reuse the origin, not purchases. A surface with no selection step is the exception, not a rail of one row. The second exception is a surface whose job is reading and signing off documents (Workbench): it takes the **tabbed reader** origin, which extends tabbed 3-pane and gives the open document the middle and right space, because a context strip beside a spec is the thing that squeezed the reader (decision 2026-09-29, `docs/specs/2026-09-29-workbench-reader-origin-design.md` in the vault). Full rule, the origin's classes, and the phone band: `wiki/patterns/dashboard-three-pane-layout.md`; the derivative contract: `CLAUDE-blueprints.md`.

**Nothing ships without a working phone view [BINDING].** The phone is not a later pass — it is one of the widths a change is finished at. So the render check above is **2560x1300, 1280x1300 and 390x844 minimum**, on every tab and sub-view the change touches, in their real interactive states, and you look at the screenshots rather than only reading the probe. Zero clip lines is the floor, not the bar: the phone failures that matter most produce no clipping at all — a board that fits and breaks every cell one character per line, a panel that scrolls inside 115px, a media query written for a phone but scoped to a band no phone matches, a desktop `max-width` cap that becomes dead gutter. Rule 4 and the phone-specific probes in `wiki/patterns/dashboard-responsive-layout.md` name them; `dashboard/hub/tests/test_halfwidth_layout.py` guards what is mechanical. New CSS that only ever ran at desktop width is an unfinished change, not a follow-up ticket.

**Running the whole Hub suite: one pytest per file, never one big run.** A single `pytest tests/` from `dashboard/hub` never finishes (killed at 40 min, 2026-10-13). Run `ls tests/test_*.py | xargs -P 6 -I{} timeout 600 python3 -m pytest -q {}` with the Hub up, and run `test_halfwidth_layout.py` on its own: it drives real Chrome over every trip tab, width and theme and takes about 34 min. `test_react_parity` can false-fail when the Hub is under that parallel load; rerun it alone before believing it.

These are research-backed standards all dashboard code must conform to. Read them before writing, not mid-session when a structural question surfaces.

## Hub asset pipeline — vendored libs and server-side JSX [BINDING]

Two rules, both load-bearing, both added 2026-08-19 when the Hub's page-load work moved
off the browser.

**No page loads a third-party library from a CDN.** react, react-dom, babel, leaflet,
maplibre-gl and pdf.js all live in `hub/static/vendor/`, pinned by version, and the Hub is
reached over a tailnet — it must render with no route to the public internet. `/static/vendor/`
is the one path served `immutable, max-age=1y` (carve-out at the top of `_no_cache_static`
in `app.py`), because a pinned build never changes under the same filename. To upgrade,
download the new version under a new filename and repoint; never edit a vendored file in place.

**Offline behaviour is governed by `CLAUDE-hub-offline.md`** — the service worker that
keeps the Hub readable on a phone off the tailnet, and the last-good cache behind the
calendar and money panels when the box itself has no route out. Both are network-first by
design; read that file before changing either, because the obvious "just cache it"
simplification breaks the no-stale-asset guarantee this section is built on.

**`.jsx` is transpiled server-side and served from `/jsx/<path relative to hub/>`** by
`hub/jsx_build.py`, cached on the source file's mtime and warmed at boot. Two things about it
are not optional:

- The transform must keep **preset-env**. It is what downlevels to ES5, and ES5 output is the
  only reason ten files that each open with `const {useState} = React;` do not collide — every
  Hub script shares one global scope. Modern output looks tidier and takes the home page down
  on the second file.
- The `<script>` tags must carry **`defer`**. The old `type="text/babel"` tags ran at
  DOMContentLoaded, i.e. after the deferred `theme-switch.js` that publishes `window.HubBack`
  and `window.HubTheme`. A plain `<script src>` runs during parse and renders chrome.jsx's
  topbar before those exist, which is how purchases grew a second back button.

There is still no build step and there must not be one: edit the `.jsx`, refresh, it is live
(see `wiki/problems/vesper-template-cache-stale-html` for the scar from breaking that).

Conditional GETs for every module's JSON API are handled once, app-wide, by `_conditional_json`
in `app.py` — do not add a per-blueprint copy. It is registered after the gzip hook on purpose:
Flask runs `after_request` in reverse registration order, so it hashes the uncompressed body and
a 304 short-circuits the compressor.

**`hub/public/` is the signed-out area** (added 2026-10-13, `hub/public_area.py`). Both the Hub
and the trips mirror serve it at `/public/<path>` with no sign-in, so it holds only page bodies a
visitor needs before signing in (login, the gate keypad, Lost Lands). Allowed kinds are the
`CONTENT_TYPES` table: `.jsx`, `.js`, `.css`, `.png`, `.webp`, `.woff2`; no symlinks. Files are
hand-written source, never generated or exported, and there are no data routes under `/public/`:
a public page talks only to `/gate`, `/gate/request` and `/login`. Shared Hub files a public page
may load stay at their real `/static/` URLs and are named one by one in `SHARED_STATIC`; add a
file there, never a folder (a whole-folder serve once leaked `vault_map_data.json`). The boundary
is `tests/test_public_area.py`'s route sweep, which fails when any route answers 200 signed out
without being on its app's public list; the fetch lint in the same file is only a backstop.

## Schema-touch reminder: STRICT conversion (opportunistic)

The warehouse contract (`data/CLAUDE.md`, written 2026-05-22) requires STRICT tables for new tables only. The four existing dashboard databases (`jobs.db`, `trips.db`, `purchases.db`, `checklists.db`) carry legacy loose-typed tables that should be converted as opportunity allows.

**Rule:** When touching a table's schema in any dashboard module (adding a column, changing a type, creating a new table, modifying constraints, fixing a column default), check if the table is already STRICT. If it isn't, propose converting it to STRICT as part of the same migration.

Conversion pattern, in one migration file:

```sql
-- +migrate up
CREATE TABLE <table>_strict (
    -- copy column definitions with explicit STRICT-compatible types
) STRICT;

INSERT INTO <table>_strict SELECT * FROM <table>;

DROP TABLE <table>;

ALTER TABLE <table>_strict RENAME TO <table>;

-- recreate indexes and triggers if any

-- +migrate down
-- (skip down if STRICT conversion is one-way; document the reason)
```

A pre-migration `.bak` (per the warehouse contract's backup discipline) is required before this runs.

**Don't surface this on every read.** Only fire the reminder when the work plan already involves a schema change on a non-STRICT table. The goal is opportunistic conversion, not interrupt-driven busywork.

Tracking lives in [[wiki/notes/claude-work-planner]] Backlog → "STRICT table backfill for legacy dashboard databases" (per-database checklist). Update it when a database is fully converted.

## Jobs module

Lives at `dashboard/hub/jobs/` (relocated 2026-05-25 from `dashboard/jobs/` — now part of the Hub port-5002 app; the legacy port-5001 mount has been removed). Governed by `dashboard/hub/jobs/CLAUDE.md` (3-stage pipeline: Stage 1 batch intake, Stage 2 research sweep, Stage 3 application prep). Per-ATS URL/JD-fetch detail in `dashboard/hub/jobs/ats-reference.md` (read on demand, not auto-loaded). When working in `dashboard/hub/jobs/`, that file loads automatically in addition to this one.

## Purchases module

Lives at `dashboard/hub/purchases/` (Hub port 5002). A three-pane research-and-decide surface for major purchases, rebuilt 2026-07-10 around Sam's real buying process (migration 006, spec + plan under `docs/`). No scoped CLAUDE.md — this section governs it.

- **Seven-stage pipeline.** A decision advances through `need → landscape → priorities → market → candidates → compare → verdict` (`decisions.stage` live values: the first six plus terminal `decided`/`cancelled`; migration 006 remapped the old `discovery`/`exploring`→`need`, `processing`→`candidates`). Each section carries its own status in `decisions.section_state` (JSON: `pending | researching | awaiting-you | done | skipped | stale | error`); a late upstream edit auto-marks downstream `done` sections `stale` (`_mark_downstream_stale`).
- **Research/understanding layer (the point of the rebuild).** `landscape` fills a **function map** (`dimensions`: per-spec explainer, full range, too-low/typical/high tiers with real values, and a his-fit zone), a **brand map** (`brands`), and credibility-graded **evidence** (`evidence`: claim + source + longevity + grade holds/weak/refuted). `market` fills **price-step curves** (`price_steps`: rungs with exact prices and a `knee` diminishing-returns flag — every rung always shown, never dimmed).
- **Priorities checkpoint.** The one mid-pipeline gate: `priorities` weights are proposed, then confirmed via `POST /api/decisions/<id>/confirm-priorities` (db `confirm_priorities` raises unless the section is `awaiting-you`; on success sets stage `market`).
- **Constraint rail (right pane).** Replaced the old ContextPane. The hard-constraint spec sheet: `constraints` grouped locked-above-proposed, showing **aggregate** `X/total fail` counts only (per-candidate fail flags live in the middle pane). Nothing in the rail ever hides, dims, or filters a constraint-failing candidate — they render at full detail with an additive flag.
- **/purchase skill drives it.** The vault skill `.claude/skills/purchase/SKILL.md` (Claude-only action skill) researches chat-first and writes every finding to `data/purchases.db` via a direct `purchases.db` import (the `~/.config/vault-api/code_path` → `dashboard/hub` pattern, same as `/todo`). Sam reads and decides on the dashboard.
- **Orders are their own store (migration 007).** The page has two halves, switched by a mode strip under the topbar: `decisions` (the pipeline above) and `orders` (every parcel). `orders` holds one row per thing bought — `decision_id` nullable, so a purchase needs no research behind it — plus the return window (`delivered_on` + `return_days` → a computed `return_by_effective`/`return_days_left`; a stored `return_by` overrides). The eight `order_*`/`ship_status`/`carrier`/`tracking_number` columns on `decisions` were backfilled into it and are **dead** — the verdict tab's owned block reads `decision.order`, so there is one source of truth for where a parcel is. `order_emails` is the Gmail scan's dedupe ledger. `POST /api/orders/scan` (`orders_mail.py`, self-check `python3 orders_mail.py`) reads recent order mail read-only and only ever fills a **blank** field, never corrects a typed one; it admits a message only when something physically ships, which is what keeps meal and download receipts out.
- **A pasted orders page is the second inlet (2026-09-09).** `orders_paste.py` (self-check `python3 orders_paste.py`) parses a copied Amazon "Your Orders" page into the same table under the same two rules as the mail scan: fills only a **blank** field, and moves `ship_status` forward only. It exists because the mail scan cannot see Amazon at all — those order emails do not arrive in `demo@example.com` (an order number, the product name and `from:amazon.com` all return zero across spam and trash), so every Amazon parcel sat at `ordered` forever. Matching is order number first, then distinctive words in the product name, which is what lets a paste land on a row created from a purchase decision where the vendor reads "INIU" and not "Amazon"; two plausible rows match nothing rather than guessing. `returned`/`cancelled` now outrank `delivered` in the shared status ladder, so a late delivery notice cannot undo a return. No UI inlet — Claude runs it on a paste; add a box in the rail if he starts pasting into the tab instead.
- **Orders is three panes (2026-09-05).** The reference implementation of the layout law above: the rail lists every order, the middle is the selected one as parcel / money / return / origin cards, the right strip carries the journey line, the dates and the destination map. `orders.delivery_address` + `delivery_lat`/`delivery_lng` (migration 008) is what the map pins; the address is geocoded at the write in `_geocode_delivery`, and a changed address drops the old point in the same write rather than leaving a pin on a door the parcel no longer goes to. **A live carrier position is not buildable and is not a missing account** — no carrier publishes a moving vehicle to an API. What exists is the scan-event trail (city-level facility events) through an aggregator like EasyPost or AfterShip, plus an approximate delivery-day area from FedEx refreshed every 30-60 minutes. So the third layer, if it is ever built, is a breadcrumb of where the parcel has been, not a dot moving toward the flat.
- **Frontend.** Classic-runtime JSX (no build step), `window.*` globals. New styling archetypes in `frontend/static/style.css` are **token-only** — no per-theme (vesper/cobalt/atrium) flourish files were touched, so the pipeline UI inherits every skin automatically.

When the schema, stage vocabulary, section-state semantics, or checkpoint behavior changes, update this section in the same operation (wiki–implementation sync rule above).

## Vault map module

Lives at `dashboard/hub/vault_map/` (Hub port 5002). A **read-only** surface for understanding the vault's structure by progressive drill-down (whole vault → single file purpose). Not an operational tool. No scoped CLAUDE.md — this section governs it.

- **Data layer is a cache.** `data/vault_map.db` (STRICT `map_node`) is wiped and repopulated in full by `db.py` `refresh()`, which walks the vault filesystem. No SCD/history — cache-overwrite only. Schema is owned by `data/migrations/vault_map/001_initial.sql`; never `CREATE` it in `db.py`.
- **Classification.** Every node gets a `node_function` from the five-function palette (knowledge / ingest / apps / ops / governance) inherited from its top-level folder, and a one-line `purpose` (folder → its `CLAUDE.md`; wiki file → frontmatter `summary`; other file → first heading or a generated by-type label). The folder skip-set and function map are module constants in `db.py` — tune them there.
- **Endpoints.** Blueprint at `/vault-map`: page route, `GET /api/tree` (full node list), `POST /api/refresh` (rebuild the cache). `{status: ok|error}` responses per the dashboard code standards.
- **Frontend is a deferred design session.** The interactive Miller-columns UI is built live with the user, not solo; until then the page route serves a plumbing stub. When the real frontend lands, it goes in `frontend/vault_map.html` + `frontend/static/`.

Onboarded via [[wiki/decisions/onboard-vault-map]]. When the schema, walker behavior, or any value above changes, update this section and the decision node in the same operation (wiki–implementation sync rule above).

## Mark mode

`dashboard/hub/marks/` lets Sam mark Hub UI issues for Claude to fix. `inject.py` (an `after_request` hook like `pull_refresh`) adds `static/js/marks.js` to every HTML page; that script puts a Mark cap in the top bar. The cap loads `/marks/frame?u=<path>`, which holds the tab capture and drawing layer (React body `marks/frontend/static/frame.jsx`) above the page in a same-origin iframe. `api.py` saves marks to vault `data/marks/` through `store.py` (per-session flock). `render.py` re-renders a shot in headless Chrome, and its requests carry `X-Hub-Render: 1` so the injector skips them. `cli.py` is the only path that closes (deletes) a mark; the vault `/marks` skill drives it. Essay marks skip the frame: the pop-out on a written answer in the jobs Application tab (`EssayPop` in `jobs/frontend/static/jobs-surfaces-b.jsx`) posts `kind: essay` marks with the highlighted `quote` and no screenshot, and the walk card shows the quote in place of a picture. Spec: `docs/specs/2026-10-12-hub-mark-mode-design.md`.

## Unified task store

`data/tasks.db` is the single source of truth for tasks. Everything else is a **projection** of a row: the work-planner markdown (`wiki/notes/claude-work-planner.md` + `-completed.md`), linked `wiki/tasks/*.md` nodes, linked Google Calendar events, and the Hub home TASKS + SCHEDULE panels. The engine is `dashboard/hub/tasks.py`; the one-time seed/reconciliation is `seed_tasks.py`. Design + locked decisions: `docs/archive/plans/2026-05-29-unified-task-sync.md`; decision record: [[wiki/decisions/unified-task-store]].

**Canonical id is `task_key`** (slug + short hex), stable across the schedule pip, TASKS panel, planner mirror, calendar link, and every `/api/tasks/*` boundary. The integer PK stays internal (warehouse contract). The old positional `{section}-{index}` id is retired — do not reintroduce it.

**Completion contract** — completing or reopening a task **anywhere** (schedule pip, TASKS checkbox, `/todo`, dashboard) routes through `tasks.complete()` / `tasks.reopen()`, which propagates to every linked surface:
1. Row flips `status` open↔done (+ `completed_date`).
2. Linked calendar event: `✓ ` title prefix + `Completed YYYY-MM-DD` description line, **edited in place** (`gcal.mark/unmark_event_complete`). Never delete or recreate the event.
3. Linked wiki node: `## Status` body flipped + frontmatter `updated:` bumped.
4. Both planner markdown files regenerate from the table.

**The planner markdown is a generated mirror.** Table writes rewrite the section bodies only (the frontmatter/intro preamble and the `## See also` / `## Source basis` footer are preserved). Within a section the canonical sort is: cluster by `group_label` (ungrouped first), then blocked sinks to the bottom of its cluster, then urgency floats up (`critical` → `quickwin` → none), then alpha. Do not hand-edit the planner for task changes — go through `/todo` or the dashboard, or the next `regenerate()` overwrites the edit.

**Task state:** `status` is `open`/`done`. Open tasks carry refining fields:
- `blocked` (0/1) — waiting on an external gate; renders a `Blocked.` description prefix and sinks within its cluster.
- `group_label` (TEXT, nullable) — tasks sharing a label cluster under a bold group sub-header inside their section, so multi-part work spun off one parent stays visibly together. `/todo` auto-assigns a shared label when one spiel becomes several tasks.
- `urgency` (TEXT, nullable: `critical` | `quickwin`) — the single-chip triage signal. `critical` = must-do, `quickwin` = high value-to-effort. Renders a `[critical]` / `[quick win]` tag in the planner and a colored chip on the dashboard; mostly set by auto-add processes, assignable to any task. `_norm_urgency` coerces unknown values to NULL.
- `input_level` (TEXT, nullable: `none` | `low` | `high`, migration 005) — how much of Sam a task needs before Claude can finish it. `none` = zero questions, `low` = up to three, `high` = full back-and-forth or only he can do it at all. Renders a colored pip (green/yellow/red) in the row's own grid column, left of the title; NULL renders a hollow pip meaning never triaged, which must stay distinguishable from `none` because `/tasks` runs the `none` queue unattended. `_norm_input_level` coerces unknown values to NULL. Orthogonal to `urgency`: urgency is how much it matters, `input_level` is how much of him it costs. Set on every add by `/todo`; consumed by `/tasks`.

The `deferred` tier was removed (migration 004, 2026-06-28). Do not reintroduce it.

**Schedule pips:** every Tomato (`colorId 11`) calendar event is a completable task — all-day deadlines **and** timed ones (timed deadlines, interviews, appointments). `tasks.sync_event` creates + links a row the first time any unseen Tomato event renders, **and reconciles the row's `due_date` on every later render** — so editing the event's time in the schedule moves the linked task's deadline too (regenerates the planner when it changes). Because the schedule editor edits the calendar event with `gcal.patch_event` (not a full `update_event`), an edit preserves `colorId` and the event stays a task; using `update_event` there would strip the Tomato marker and silently unlink the row. All-day tasks render at the top of the day; timed tasks render the same checkable pip in their own time slot (the schedule sorts all-day first, then chronologically by start time). Because every Tomato event becomes a linked task row, timed Tomato events also surface in the planner TASKS panel + markdown, exactly as all-day deadline events already do.

**Timed tasks carry their clock time in `due_date`.** A task's `due_date` (TEXT) holds a date-only string for all-day deadlines and the **full ISO datetime** for timed ones (`sync_event` keeps the event's `start_dt` verbatim for timed events; the memo pipeline passes a datetime). Nothing else parses `due_date`, so storing a datetime there is safe.

`_row_to_dict` derives two display fields from it: `due_target` (the instant the countdown runs out, via `_due_target()`) and `timed` (bool — has a clock time). For an all-day deadline the target is **midnight at the end of the due day** (next-day 00:00 local); for a timed task it's the datetime itself; `None` when there's no `due_date`. The server only fixes the target instant — the TASKS panel (`Tasks.jsx`) renders the **live countdown chip** off it: `Xd Yh` (≥1 day), `Yh` (<1 day), a real ticking `m:ss` inside the final hour, `overdue` (past target, filled-red variant). Done tasks and no-due-date tasks show no chip. A self-scheduling timer ticks every 1s while any active task is in its final hour (so `m:ss` moves), else every 30s.

**Dated tasks group into a top "scheduled" section.** On the active tab the panel pulls every task that carries a `due_target` — anything with a countdown chip, timed events **and** all-day deadlines alike — out of its normal section into a synthetic `scheduled` section at the top, sorted soonest-`due_target` first, and removes it from its normal section. Only tasks with no due date stay in their normal sections. The completed tab keeps the plain section grouping (a countdown on a done task is meaningless).

**Loose Ends (reserved section):** `SECTION_NAMES[0]` is `Loose Ends` (stored `loose ends`), the top section. It is the carryover pen for tasks stranded by a session that ended mid-work — auto-populated from orphaned `.pending/` files at session start, never a manual `tasks.add()` target. It is an ordinary task row otherwise (same completion contract). Behavior spec: `.claude/pending-spec.md` → "Loose Ends carryover"; decision node documents the rationale.

When changing the table schema, the propagation behavior, or any value documented here, update this section **and** the decision node in the same operation (per the wiki–implementation sync rule above).

## Notifications module

Lives at `dashboard/hub/notify/` (bell in the shared top bar, `data/notify.db`). Any module posts with `from notify import post, cancel` (`PYTHONPATH=..` from `hub/`); `post` never touches the network, pushes go out from the `notify-push` scheduler job, and a failing store must leave the top bar working. The call contract, key rules and fail-open rule are in `dashboard/hub/notify/CLAUDE.md`, which loads when you work there.

## Headless skill scheduler

See `dashboard/CLAUDE-scheduler.md` (jobs, trigger jobs, active machine, config pairing). Load it for any scheduler or scheduled-job work.
