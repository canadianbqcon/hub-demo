# CLAUDE.md — dashboard/hub/barback/ (J&Co shift-companion surface)

Scoped rules for the barback module. For cross-module dashboard rules (wiki–implementation sync, code standards, STRICT conversion), see `dashboard/CLAUDE.md` — it loads in addition to this file when you work here.

This module lives under the Hub dashboard (port 5002). Since the 2026-07-29 J&Co merge it owns **data + behaviour only, not a page**: `barback.jsx` renders the **bar back** tab of the juniper & co umbrella (`dashboard/hub/jc/`, route `/jc/#barback`) and nothing else — the React copy of the topbar, status strip, module launcher and the one-way "Batch prep →" link are all gone, because that duplicated chrome is exactly what made this surface and batch prep read as two products. It mounts lazily off the umbrella's `jc:tab` event so starting a run (and the archival sweep that rides along with it) does not fire on every page view. `/barback/` 308-redirects to `/jc/#barback`; `/barback/api/barback/*` and `/barback/static/*` are otherwise unchanged. It is the **second UI onto `work.db`** — the first being `batch_prep` ([[wiki/decisions/onboard-jc-batch-prep]]). Onboarded via [[wiki/decisions/onboard-barback-dashboard]].

## The sub-tabs ARE the runs [BINDING]

Three sub-tabs — **opening · closing · stock check** — each of which starts (or resumes) that template's run for the current bar-day and shows its list directly. There is no date heading, no weekday strip and no run-card layer in between. Sam works a shift already knowing which shift it is, so making him answer the calendar first was friction: *"It's not gonna read based on day. I just get to select what I need to do."* (2026-07-29).

- **Do not reintroduce a day-driven view.** No bar date, no weekday, no cadence strip in the UI. That is the thing that was removed.
- **Low boy fill is not a fourth tab.** It renders as a `<details>` section *inside* the opening tab, at the **top**, above the shift steps — it is the first thing done on the floor. Collapsed by default with its unit tally on the summary, which is what lets it lead without 67 product rows drowning the steps beneath it (same altitude rule as the section below, applied to the UI instead of the data).
- **A counted row carries its own back-to-zero (`.row-clear`), and that is the clear you reach for mid-count.** Non-negotiable since the tap cycle stopped wrapping: `0→1→2→3→0` used to let an over-tap fix itself by tapping on, but counting to 99 has no roof, so without a per-row ✕ a mis-tap is stuck. It renders only above 0, `stopPropagation`s so it never doubles as a row tap, and shares `.sweep-clear`'s 44px thumb target. **Clear all is a different control** — the whole-list wipe, confirm-gated, and it stays **last**, under the sweep. It has now cost real counted data twice when it sat anywhere prominent; do not promote it.
- **The tab key IS the template key.** `BB_TABS` in `barback.jsx` maps `opening_barback` / `closing_barback` / `stock_check` straight to labels; adding a mapping layer just creates a second thing to keep in step.
- Progress (`n/total`, `n to grab`) is computed **client-side** from the run's own items via `BarbackLogic.summarizeProgress` / `summarizeFill`. There is no server-side summary endpoint any more — `GET /today`, `db.get_today`, `_progress` and `_fill_tally` were deleted with the day view, because everything they computed was already derivable from the run the client is holding.

## work.db is not owned here [BINDING]

`db.py` only opens connections and queries. The schema lives in `<vault-code>/db/migrations/work/` and is applied via the migration helper. Never `CREATE`/`ALTER` work.db from this module — add a forward-only migration under `db/migrations/work/00N_*.sql` instead, with a pre-migration `.bak`. Migration 014 added the five tables this module owns: `checklist_template`, `checklist_template_item`, `checklist_run`, `checklist_run_item`, `stock_raw_item`. The pre-migration backup is `data/work.db.bak-pre-migration-014-2026-06-19`.

## Template-to-run snapshot model [BINDING]

Starting a run snapshots the active template's items into `checklist_run_item` rows at that moment. Later template edits or re-seeds **never mutate an in-flight run** — the run carries its own `text_snapshot` / `detail_snapshot` / `section` / `deadline` / `priority` copies. "Incomplete" is NOT stored as a status value: it is derived at read time (`status='archived'` AND any child `run_item.state` still `'open'`). A run transitions `active → archived` when explicitly completed or when lazy archival fires on read (bar date has passed and no items remain open).

## Checklist altitude: shift steps vs item-level fill [BINDING]

`opening_barback` holds **shift steps** ("ice in all wells", "syrups", "help bartenders with setup"). `lowboy_fill` holds the **item-level restock** — every individual product, batch, syrup and juice that goes into the low boy. These never merge **as templates**: a 50-row product list interleaved into the opening checklist drowns the steps that actually gate the shift. Opening's own row names the step; the detail lives in the nested fill run.

The two are separate runs with separate state machines even though the UI shows them on one tab — the nesting is presentational (a collapsed `<details>` under opening), and a fill row never becomes a `checklist_template_item` of `opening_barback`.

The list is a mirror of the live `storage_*` tree and is **re-synced whenever that tree is edited** — it does not track it automatically. Last sync 2026-09-02, after the recipe-location sweep: 81 rows over 78 products. Every `lowboy_fill` row is **one countable product**, read as **`<product> - <brand>`** where `text` is the product and `detail` is the brand. A row that groups several products ("Cold Foams", "Lucky Ox Sparkler", "Can Sodas") cannot say which member is short, which defeats counting — those were split into their members 2026-07-29, and rows that name a *shelf* rather than a product (the whole `3B. Prepped Service Bottles` section) were removed for the same reason. Regression test: `test_lowboy_fill_is_its_own_template_not_folded_into_opening`. The brand is what identifies the thing on the shelf. Never use can-art or shelf-position shorthand ("the Kraken can", "the santa-pants can") as the stored descriptor — that is how Sam *describes* a product he can't name, not what it is. Look the product up and store the real name. Regression test: `test_lowboy_fill_is_its_own_template_not_folded_into_opening`.

## Three state models on one `state` column [BINDING]

The `kind` column on `checklist_template` drives three distinct state machines, all stored in the same `checklist_run_item.state` TEXT column:

- `kind='duty'` — binary: `state` is `'open'` or `'done'`. Rests at `'open'`. Used for opening and closing shift checklists.
- `kind='stock'` — three-state: `state` is `'open'`, `'good'`, `'low'`, or `'out'`. Rests at `'open'`. Used for the stock check against `stock_raw_item`. The "Low not out" distinction maps to the J&Co operational standard (from [[wiki/notes/jc-staff-policies]]).
- `kind='fill'` — counted: `state` is a number `'0'`–`'99'`, and it **is** how many units of that product to grab. Rests at `'0'`. Tapping a row **adds one and never wraps**, clamped at `_FILL_MAX` (`db.next_fill_state`, mirrored by `nextFillState` in `barback.logic.js` — keep the two in step). Because there is no wrap, the way back to zero is always an explicit control, never another tap: the row's own ✕, or Clear all for the whole run. Used by `lowboy_fill` since migration 017; the wrap was dropped 2026-08-16.

The API and UI enforce which state values are valid per kind (`_STATES_BY_KIND` / `_RESTING_BY_KIND` in `db.py`). Never allow a duty item to reach `'good'`/`'low'`/`'out'`, a stock item to reach `'done'`, or a fill item to reach anything outside `0-3`.

**A fill run has no completion.** It is a survey, not a checklist: its rows rest at `'0'` and never leave an `'open'` state, so `_refresh_completed` skips it and `completed_at` is never stamped. The number that matters is `_fill_tally` — rows owing something, and total units owed. `complete` is always `False` for a fill run in the Today summary.

**`seed_checklists.py` upserts `kind`.** The seeder's `lowboy_fill` tuple must stay `"fill"` — leaving it `"duty"` silently reverts migration 017 on the next re-seed. Regression test: `test_seed_creates_four_templates`.

## Grouped shelf ↔ counted product [BINDING]

The storage tree and the fill checklist describe the same shelves at different altitudes, and **neither wording is flattened into the other.** The tree keeps the bar's shorthand, because that is how you read a shelf walking past it: Fridge 3 · Bottom is `Service bottles` / `Clarified Drinks`, Fridge 4 · Bottom is `Canisters`. The checklist splits those into countable products, because a row saying "Canisters" cannot say which canister is empty.

`storage_item_cover(item_id, product)` (migration 019) records which products a grouped row stands for. The map is `_COVERS` in `seed_checklists.py`; `_seed_covers` rebuilds the table on every seed.

- **`product` is a name, not a foreign key.** The seeder deletes and re-inserts every `checklist_template_item` each run, so ids on that side are not stable and a FK would break on the next re-seed.
- **Both ends are re-validated every seed, never trusted.** The checklist is re-seeded from code, the tree is hand-edited in the UI, so they drift independently. An unresolved grouped label or an unknown product prints a `WARN` and drops that one link — no dangling row, and no near-match guessing. An unlinked shelf must stay visibly unlinked.
- **A grouped label with no established members gets no rows.** `Bottled Batches` (renamed from `Clarified Drinks` in the 2026-09-02 sweep) is absent on purpose under either name: the clarified batches that come upstairs are already counted on Fridge 2 · Bottom, as is every refrigerated bottled batch Sam named that day, and nothing records what the label separately holds.
- Regression tests: `test_covers_link_grouped_shelf_to_individual_products`, `test_covers_skipped_when_storage_tree_absent` (the link degrades to a no-op where the storage tables don't exist).

Domain record: [[wiki/notes/jc-lowboy-map]].

## Low boy grab sweep [BINDING]

Counting exists to produce the **sweep**: the grab list at the bottom of a fill run, grouped by the storage area you collect from, so a restock is one pass per area instead of running front-back-front-side. `db.grab_sweep` builds it.

- Shelf-level locations come from `ingredient_location` (seeded by `seed_lowboy_location.py` off the storage map in `storage_note` — never guessed from a product name; substring matching once sent "Lemon" to the Lowboy by matching "Lemongrass").
- `_AREA_BY_PREFIX` groups those shelves into the coarse rooms you walk between, and `_SWEEP_ORDER` is the walk order. Both are `db.py` config constants for the same reason `CADENCE` is — a DB table is schema overhead for a value that changes a few times a year.
- **An unplaced product is never guessed at and never dropped.** It collects under an explicit `Unsorted` area, which always sorts last and is the signal that `seed_lowboy_location.py` needs a row for it. 9 of the 78 products are deliberately unplaced today.
- **Every prefix a location string can start with must appear in `_AREA_BY_PREFIX`.** One that does not falls to `Unsorted`, which is indistinguishable from never having been placed — so a shelf rename in the seeder silently unplaces everything on that shelf. `Keg fridge` (the 2026-08-17 rename of `Back fridge`), `Back rack` and `Front freezer shelf` were all missing until 2026-09-02, walking **18 placed products as unplaced**. Regression test: `test_every_seeded_location_maps_to_a_walk_area`.
- **`seed_lowboy_location.py` clears by the `note` it owns, not by the keys it is about to write.** Deleting only what gets re-inserted leaves a dead row behind on every rename or removal; six had accumulated by 2026-09-02, one of them pointing at a shelf the alcohol-room flatten had deleted.
- The sweep loads automatically with the run (not behind a button like the stock Low/Out summary) because it is the reason the counting exists.
- **Every sweep line clears from the sweep itself** — each item carries its `checklist_run_item.id` as `item_id`, and the `✕` on the line sets that row to `'0'` through the same `PUT /run/item/<id>` the row above uses. Before 2026-07-29 the only way off the grab list was tapping the row in the counted list up to three times to cycle `1 → 2 → 3 → 0`, which is not a thing you do one-handed mid-restock. It is a **per-line button, not a whole-row tap** — a brushed row while walking the bar must not wipe a count — and it reuses the run's optimistic tick plus its `onSaved` sweep reload rather than a second write path. No new endpoint. Regression test: `test_sweep_item_id_clears_the_line_off_the_sweep`.

## 05:00 bar-day offset and lazy archival [BINDING]

A "bar date" runs from 05:00 local to 04:59 the next calendar day. `db.py` derives the current bar date at request time with a fixed 05:00 offset — no timezone DB, no stored config. Archival is **lazy**, and since 2026-07-29 it hangs off **`start_run`**, not off a summary read: any touch of the run layer first closes out runs left active on an earlier bar-day. It moved because its old trigger (`get_today`, the Today-tab read) was deleted with the day view; a run-layer concern belongs on the run-layer entry point, not on whichever endpoint happens to be called first. No background worker, no cron job.

## CADENCE: deleted 2026-07-29

`CADENCE` / `compute_cadence` are gone. They fed the weekday strip, which went with the day-driven view. Nothing was lost with them: every rule the constant held is recorded in the vault in more detail than it carried — ghost ice Tue/Thu/Sat and the downstairs-clean deadlines in [[wiki/notes/jc-staff-policies]] → "Recurring cadences", the Tuesday condense-juice-and-syrups in [[wiki/notes/jc-closing-duties]] and [[wiki/notes/jc-opening-duties]], the Tuesday bottle-cover soak in [[wiki/notes/jc-barback-trainer]]. **Do not reintroduce a weekday constant here.** The bar's rhythm is wiki knowledge; this module tracks runs.

## Reference view: deleted 2026-07-29

The Reference tab is **gone** — the prose renderer for the J&Co wiki notes, the staff-policy/POS sections, the prep→cocktail dependency map, `GET /reference`, `GET /dependencies`, `db.render_reference`, `db.dependency_map`, the escape-first markdown subset, and `barback.reference.jsx` were all deleted. Sam chose deletion from a three-option question that spelled out exactly what dies with it, over a recommendation to keep it as a fourth tab. The notes themselves are untouched in the vault; only this surface onto them is gone. **Do not rebuild it without being asked.**

## Access posture [BINDING]

Reach `/jc/` (the page that hosts this tab) over the **private tailnet** (Tailscale phone → PC), never Tailscale Funnel — Funnel exposes the whole 5002 port and would leak the jobs tracker (salary/company/interview data). Same posture as `/batch`. PC/WSL host needs a one-time Windows portproxy (`Windows:5002 → <wsl-ip>:5002`) + firewall allow; the server already binds `0.0.0.0`.

## API + envelope

Blueprint `bp`, `url_prefix="/barback"`. All JSON responses use the `{status: ok|error}` envelope per the dashboard code standards. The blueprint's `/` is a 308 to `/jc/#barback` — it serves no template of its own.

Five endpoints, all under `/barback/api/barback/`: `POST /run` (start-or-resume by template key; fires archival), `GET /run/<id>`, `PUT /run/item/<id>`, `GET /run/<id>/sweep`, `GET /run/<id>/lowout`. `/today`, `/reference` and `/dependencies` were deleted 2026-07-29.

## Running the tests

`test_barback.py` **cannot be collected from the repo root.** Nine sibling `dashboard/hub/*/db.py` modules shadow each other on a flat `sys.path`, so a root-level `pytest` resolves `import db` to the wrong module (`AttributeError: module 'db' has no attribute '_conn'`). Run it from this directory:

```
cd <vault-code>/dashboard/hub/barback
PYTHONPATH=<vault-code>/dashboard:<vault-code>/dashboard/hub python3 -m pytest test_barback.py -q
```

Pure frontend logic has its own node runner: `cd frontend/static && node barback.tick.test.js`. The repo-root tripwire suite (`pytest tests/ dashboard/hub/tests/ dashboard/hub/batch_prep/test_prep_day.py`) does not cover this module and passes independently.

## Wiki–implementation sync

When the snapshot model, state model, bar-day offset, cadence constant, renderer behavior, access posture, or any value above changes, update this file **and** [[wiki/decisions/onboard-barback-dashboard]] + `data/CLAUDE.md` in the same operation (per the cross-module sync rule in `dashboard/CLAUDE.md`).
