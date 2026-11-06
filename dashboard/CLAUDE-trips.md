# CLAUDE-trips.md — the trips module (planner duo + activity rows)

Extracted verbatim from `dashboard/CLAUDE.md` on 2026-08-29, when that file crossed the
250-line governance ceiling. Load this in addition to `dashboard/CLAUDE.md` for any work on
the trips planner, `data/trips.db`, or the trips dashboard.

## Trip-planner duo pattern

Every active trip planner in `wiki/notes/` is a **two-file duo**, not a single file:

| File | Slug pattern | Holds |
|---|---|---|
| Logistics planner | `<destination>-trip-<month>-<year>.md` | Route, dates, flights, lodging/Airbnb codes, crew + contacts, house rules, transport, calendar links — the **rigid logistics** layer |
| Research / activities | `<destination>-trip-<month>-<year>-research.md` | Activity triage, food sections, scheduling constraints, rating methodology — the **modular fillers** layer |

The two files are linked via a `part-of` edge from research → logistics. Per-option score data (per activity row) lives in the trips dashboard DB (`data/trips.db`), not in either file; the research note is for methodology and category triage only.

**Why duo:** activity research grows fast (categories × options × notes) and routinely exceeds the 50–300 line atomic limit on its own, while logistics stays compact (one screen). Forcing them into one file produces either a too-long combined file or thin coverage of activities. Splitting also preserves the [[wiki/concepts/rigid-logistics-modular-fillers]] mental model — the two layers have different change frequencies (logistics locks early, activities churn until departure) and different readers (logistics = quick lookup for confirmation codes; research = comparison shopping during planning).

**Standard going forward:**
- New trip planners are created in duo form from day one — never as a single file. Even short trips get both halves so the structure scales without retroactive splits.
- The logistics file is the canonical entry point (linked from `index.md`, `wiki/notes/upcoming-schedule-*.md`, and elsewhere). The research file is reached via the `part-of` link or its own index entry.
- The research file may carry `audit_ignore: [linecount-high]` with a comment referencing the duo when it legitimately needs to exceed 300 lines. The logistics file should stay well under.

**Reference duo:** [[wiki/notes/texas-trip-may-2026]] (logistics, ~81 lines) + [[wiki/notes/texas-trip-may-2026-research]] (research, ~311 lines).

## Trips dashboard activity rules

Every activity row in `data/trips.db` must be fully researched and populated before it is added. A stub (name-only or address-only entry) is never acceptable — it degrades the dashboard's utility and creates silent data gaps.

**Required fields for every activity:**

| Field | What it needs |
|---|---|
| `location` | Full street address (number, street, city, state, zip) |
| `description` | 3–5 sentences: what it is, why it's worth visiting, key facts (cost, style, hours context) |
| `url` | Official website or best available link |
| `notes` | Practical tips: best time, reservations, ordering advice, parking, caveats |
| `cost` | Numeric (use approximate midpoint: $=5, $$=25, $$$=60) |
| `operating_days` | e.g. "Daily", "Mon–Sat", "Wed–Sun" |
| `operating_hours` | e.g. "10AM–10PM" or day-specific string |
| `lat` / `lng` | Geocoordinates for map rendering |
| `score_p` | Group preference fit, 1–10 |
| `score_c` | Community consensus (NYC-calibrated), 1–10 |
| `score` | Blended: `0.25 × score_p + 0.75 × score_c` |
| `tags` | JSON array of category tags matching existing conventions |

**The activities list renders grouped by category bucket.** `paintActivityRows` derives the bucket from `tags` — the first capitalized entry, skipping `Time Sensitive`, which is a flag that co-occurs with a real bucket and is never a section of its own. Rows with no capitalized tag land in "Other", which is the visible signal that a row was tagged wrong. There is deliberately no `category` column: the bucket is already derivable from `tags`, and a second source of truth would drift. Bucket vocabulary (from the Austin + Denver tag data): Nature / City / Food / Nightlife / Activities / Music / Arts/Culture / Sightseeing / Events / Shopping.

**Enforcement rule:** When adding any activity to the DB (whether via direct SQL, the API, or the UI), immediately research and populate all required fields in the same operation. If a field cannot be researched in the same session, do not add the row — defer until it can be done completely. No half-entries, no placeholder rows. `/audit --full` enforces this retroactively via the `activity-mandatory-fields` check, which flags any activity row with a NULL required field.

**When the user names an activity informally** (e.g. "add cheba's hut"), treat the name as a search hint, not a final value. Resolve the correct full name, verify the Austin location, and populate all fields from research before writing to the DB.

## Guest trip intake

A guest on the public mirror (port 5003) can send in a whole trip through one form and later revise it. Spec: `docs/specs/2026-10-12-friend-trip-intake-form-design.md` (vault).

- **Storage.** `trip_intake` (migration 025): one row per submission with the cleaned `payload`, the `diff` against the live trip at submit time, `status` (`pending` | `approved` | `rejected` | `superseded`) and `research_status` (`''` | `queued` | `running` | `done` | `failed`). A resubmit supersedes the guest's older pending row for that trip.
- **Row identity.** A row already in trips.db is keyed `db:<id>`, a row the guest added `new:<uuid>`. There is no mapping table; after apply a new row is simply a `db:` row on the next prefill.
- **Guest routes** (`trips/api_intake.py`, guest-only, 404 on Hub): `GET /trips/<trip_id>/intake` (form, prefilled with the live trip plus the guest's unapplied submission) and `POST /trips/api/trips/<trip_id>/intake`. They live under `/trips/`, never `/gate/`, because `/gate` skips the login and trip-scope check. The POST is the mirror's one content write: `_read_only_gate` allows exactly that path shape, the body cap is raised to 64 KB for it alone, and it is limited to 20 per guest per hour, counted from `trip_intake`.
- **Hub queue.** `GET /trips/api/intakes`, `POST /trips/api/intakes/<id>/approve|reject`, withheld from the mirror. The crew page (`/trips/crew`, `trips/frontend/static/crew.jsx`, Hub only, 404 on the mirror) lists pending submissions with their diff, alongside code requests, members and denied codes; the trips landing's `crew` link shows the waiting count. It replaced the top-bar ◉ popover (`trip-access.js`, deleted 2026-10-17).
- **Apply** (`intake.apply`): one connection, one transaction, no LLM. A changed field is written only if the DB still holds the value the guest saw; otherwise it is skipped and listed under `conflicts` in `apply_log`. Any error rolls everything back and the intake stays pending. Added activities are never written here: approval sets `research_status='queued'`, because of the activity rules above.
- **Research** (`/trip-intake` skill, scheduler job `trip-intake`, 07:00 and started on approve): runs under `--permission-mode dontAsk` with only WebSearch, WebFetch and `python3 "<code>/dashboard/hub/trips/intake.py" ...` (`claim-next`, `research-write <id> -`, `finish <id> done|failed`). Guest text reaches it only inside UNTRUSTED markers. `research-write` refuses a row missing any required activity field.
- **Not automated:** `/stays` and `/flights` on guest-supplied housing and flights (they would browse guest URLs with broad tools); run them by hand on approved rows.
