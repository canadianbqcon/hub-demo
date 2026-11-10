# CLAUDE-chrome — dashboard/hub/forge

The bar, the page frame and the one pinned theme. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## One shell, six surfaces

Every surface carries the **same shell**: a static `<header class="topbar">` as the first body child (the Hub's `topbar.jsx` upgrades it, the same recipe as J&Co's `barback.html`), then the search, rail and status pill rendered by `ForgeUI.Bar` in
`static/forge-bar.jsx` (one component, so a section added there lands on every page).
Picked on Workbench 2026-11-05 (set `forge-hub-shape-layout`, B "Left rail, like Jobs";
before/after check `forge-hub-shape-layout-ship`): the Hub's shape in Forge's colours.

    bar:     the Hub's top bar (back, crumb `forge · <page>`, control pane, module launcher)
    search:  one wide bar under the header, across rail and page (mark 2026-11-05-175436 #1)
    rail:    Champions / Patch / Stats / Draft · page action (when the page has one) · Pool (landing only) · + Set with no champion
    pill:    the page's .meta chips · build totals (landing) · FORGE · /forge/   (fixed, bottom centre)

- **The rail holds the sections.** `.navtabs` lives in the rail now, not the header
  (`verify_frontend.py` and `test_forge_api.py` key on that class; the patch check keys on the Hub's `.topbar .module-launcher`).
- **The search** (`.fs-search`, its own grid row 2 on scrolling pages, named row
  `[search]` in the builder) filters the landing cards and pool list in place; on every other
  page it is a GET to the landing page with `?q=`, which landing reads as its first filter.
- **Pool counts use the role chips' rule** (`isCurrent` in `landing.jsx`): a set carried
  forward or an outdated Auto set does not count, so the rail and the chips agree.
- **No explainer blurb at the top of a page.** The landing opens on the role tabs and
  the cards, with no heading or paragraph saying what the page is for; only a loading
  or empty-pool line may sit there. Patch and Stats keep only their data heading (patch
  and date; Riot ID, level and season record) with no prose under it (approved 2026-11-05). Sam sent this back twice (mark
  2026-11-05-173522 #1: "remove the blurb at top, again, theres no reason"). A rebuild
  of any Forge page does not bring one back.
- **The page's own action is the header pill** (`act`: "New set", "Riot's notes",
  "On OP.GG"); the builder has none. "Set with no champion" is the rail tile on every page.
- **The `.meta` chips moved into the status pill**; an empty one is `display: none`.
- **Frame.** On the five scrolling pages `#forge-root` is the grid (`272px` rail, page),
  overriding the inline `display: contents` two templates carry; `.wrap` drops its
  max-width and takes `grid-template-columns: minmax(0, 1fr)`, or a wide child pushes the
  page sideways on a phone. The header no longer sticks, so `--topbar-h` is 0.
- **The builder** stays locked to the viewport: `forge.html`'s body grid gains a `[rail]`
  column beside `head..pane`, a named `[search]` row under `[bar]`, and a named `[rail]`
  row used under 900px. Its bottom 64px is
  the status pill's band. On a phone the search and the pill go and the rail keeps only the
  four sections, since the pane is what the height is for.
- **Narrow widths.** Under 900px the rail folds into a strip above the page (the tile on
  one row, the four sections under it; the search stays its own row above) and the pool list goes; under 640px the
  header pill goes and the sections stack icon over label.

`forge.html`'s body grid uses **named** lines
(`[bar] auto [rail] auto [head] auto [steps] auto [pane] minmax(0,1fr)`), and the two step
panes share `grid-row: pane`. That was once `grid-row: 3` — a row *number* — so adding
`.buildhead` silently dropped both panes into the step nav's row. Add a row here by naming
it, never by counting.

## The bakes run themselves — three times a patch, anchored to the drop

Every "Re-run when a patch lands" in the table below is now a scheduled job:
`forge-rebake` in `scheduler.py`, registered once a day at 06:00 in
`scheduler-config.json` — the standard slot for sweeps with no reason to run at a
particular hour (see `dashboard/CLAUDE.md`). The tick fetches Data Dragon's version list and does
nothing else unless a milestone is owed, so a day when nothing moved costs one
HTTP call. Once a day is enough because the cadence is anchored to **detection**,
not to Riot's publish timestamp: the first tick that sees a new version bakes on
the spot and stamps that date as `landed`, and `day1` and `week1` count from
there. Checking more often would move the drop bake a few hours earlier and
change nothing else, since the numbers it is fetching are thin either way on day
zero -- that is what the `day1` bake is for.

**Three bakes a patch, not one, because a patch lands and then it settles.** Day
one's win rates are a few thousand games of people first-timing the changes; a
week in they are the numbers you would actually build against. `FORGE_MILESTONES`
is `drop` / `day1` / `week1` — offsets in days from the detected drop — and the cycle
repeats on Riot's two-week cadence for free, because it is anchored to the patch
that actually shipped rather than to a fortnightly timer. A fixed timer was the
other option and it drifts: patches slip, and a timer that started aligned ends
up baking mid-patch and missing the next drop by days.

**Milestones are recorded by name, not by a timer**, in
`data/forge-rebake-state.json` (`patch`, `landed`, `done`). A Hub that was off
for a week owes both follow-ups on its next tick instead of skipping them. And a
milestone is only spent if something actually baked — a run where every bake
failed leaves the state untouched, so the next tick retries rather than marking
a patch handled that never was.

**Rebaking on page open was the other candidate and it is worse twice over.**
`bake_lolalytics.py` drives a headless Chrome for ~5 minutes at 4 workers, so the
Forge would block on it every visit, and it would re-scrape to re-derive numbers
that cannot have changed since the last visit. The staleness that matters is
patch-shaped, so the trigger is patch-shaped.

The baked patch is read off `data/forge-patch-notes.json` rather than
`catalog.json` on purpose: that file is written by a script in the job's own
list, and keying the check on something the job cannot advance would make it
fire every single tick forever.

**The item catalog is in the job, which is what makes the job complete.**
`bake_catalog.py` is a copy of `build_assets.py` from
`Downloads/lol-item-set-forge`, retargeted to write `frontend/static/catalog.json`
directly instead of the `baked.json` the standalone artifact build reads. The
Downloads copy is left alone; keep the two in sync by hand if that build is ever
revived. Before this, the shop was the one bake nobody could automate, so a patch
that added an item left the item list behind until someone remembered — and an
auto-rebake with a manual step in it is not an auto-rebake. `catalog_stale` on
the run record survives as a failure signal: with the bake in the list, the only
way the catalog can now trail the live patch is that its bake failed.

One bake failing never costs the others — they read different sources, and a 403
on coachless says nothing about whether Riot's notes page answered. The cadence,
the catch-up, the retry and the failure isolation are covered by seven tests in
`dashboard/hub/tests/test_scheduler.py`.

## Layout

| File | What it is |
|---|---|
| `api.py` | Blueprint at `/forge`. `/` (landing), `/c/<champ>/<role>` and `/edit` (editor), plus `GET/POST /api/sets`, `DELETE /api/sets/<id>`, `GET /api/stats`, `GET /api/lolalytics`, `GET /api/landing`, `GET /api/patchnotes`, `GET /api/diff`, `GET /api/me`. No `init()` — reads the vault via `vault_root()`, the purchases pattern. |
| `bake_stats.py` | Pulls coachless item + rune WPA into `data/forge-stats.json`, plus per-summoner-spell WPA (`spells`) for the plan page. Re-run when a patch lands. ~2 min for the pool. |
| `notes_read.py` | The reading layer over the baked notes: `gist()`, `compare()`, `change_verdict()`, `triage()`, and `enrich()` which applies all four. Pure functions, no I/O; called from `/api/patchnotes`. Self-check: `python3 notes_read.py`. |
| `opgg_me.py` | Sam's own record off OP.GG's open MCP server (`https://mcp-api.op.gg/mcp`, no key). `decode()` turns its Python-class-shaped text blob back into dicts, `fetch()` folds the profile and match calls into one object with the per-game averages already taken, `read()` adds the 15-minute disk cache. Served by `/api/me`. Self-check: `python3 opgg_me.py`. |
| `frontend/stats.html` | The Stats surface: rank cards, season strip, champion pool table, recent-games feed. Reads `/api/me` only. |
| `frontend/patch.html` | The patch surface: the tally, the section tabs, and one card per entry. Reads `/api/patchnotes` only. |
| `bake_patchnotes.py` | Pulls Riot's own patch notes for the live patch into `data/forge-patch-notes.json`, served by `/api/patchnotes`. Stdlib fetch + BeautifulSoup, seconds. Re-run when a patch lands. Parser covered by `dashboard/hub/tests/test_forge_patchnotes.py`. |
| `bake_lolalytics.py` | Pulls lolalytics' live-patch win rate and pick rate into `data/forge-lolalytics.json` for the pool's roles plus every champion-role at or above `ROLE_FLOOR` (`build_jobs`), served by `/api/lolalytics`. Runes are baked twice: keystone-blind at `runes`, and per keystone at `runesByKeystone.<id>` for every keystone clearing `KEYSTONE_PICK_FLOOR`. Also the plan page's `plan` block (summoner pair, skill priority, skill order) off the build page and `counters` off a second `/counters/` page. Headless system Chrome. Roles are scraped concurrently, `--workers` at a time (default 4, each its own Chrome): measured 4m52s for the 33-role pool at 4, 18m51s at 1. Re-run when a patch lands. |
| `build_runes.py` | Pulls the Data Dragon rune tree into `frontend/static/runes.json`. **Run before `bake_stats.py`** — the keystone→tree map comes from it. |
| `bake_glyphs.py` | Bakes the stat rail's 21 glyphs into the `GLYPH` literal in `forge.html`: fetches Riot's 20x20 texticons, crops to the art, normalises every one to a 40px long side centred on a 44px canvas, prints the block. `--check` asserts size, crop, uniformity and centring on the shipped block. Only re-run if Riot redraws a glyph. |
| `bake_catalog.py` | Bakes the ranked-SR item shop into `frontend/static/catalog.json` — the item list, icons as base64 WebP, champion portraits as Data Dragon URLs, and the five-rule cull that keeps Arena and ARAM items out. **Run before `bake_passives.py`** and `build_diff.py`, both of which resolve against it. Downloads ~200 icons and re-encodes them, a couple of minutes. |
| `bake_passives.py` | Bakes the item passives WITH their numbers into `data/forge-item-passives.json`, served by `/api/passives` and merged over the catalog's `ps` blocks client-side by `applyPassives()` in `itemset.js`. Reads Riot's own `items.cdtb.bin.json` + `lol.stringtable.json` (about 49 MB, stdlib fetch, seconds). `--check` asserts the shipped file carries no unresolved token and joins to the catalog. Re-run when a patch lands. |
| `build_diff.py` | Diffs two Data Dragon patches into `data/forge-patch-diff.json`, filtered to items the pool actually buys. Re-run when a patch lands. |
| `frontend/landing.html` | The landing page: the build shelves, and nothing above them. Reads `/api/landing`, `runes.json` (the keystone art every shelf row is drawn with) and `/api/sets` — the last one is what lets a shelf row **pop the build overlay in place** instead of navigating. Prefetches the catalog on idle; never blocks on it. |
| `frontend/champion.html` | The build list. Reads `/api/landing`, `/api/sets` and `runes.json`, and mounts the shared overlay module. |
| `frontend/static/build-overlay.js` + `.css` | The saved-build overlay — runes on the left, the item set on the right, Copy JSON / Edit / copy-forward / Delete under it. Shared, because two surfaces raise it: the build list, and the landing shelf, which pops it without leaving the page. Owns the lazy catalog fetch (`catalog()`) and `prefetchCatalog()`. The CSS is its own file rather than part of `forge-base.css`, because the builder loads that too and has its own `.hovercard` geometry. |
| `frontend/forge.html` | The two-step builder. One file, vanilla, `type="module"` for top-level await. |
| `frontend/static/forge-base.css` | Palette, controls, the shell (header, left rail, status pill; see "One shell, six surfaces") and the patch strip. Shared by every page. |
| `frontend/static/forge-bar.jsx` | The shell below the Hub bar: search, left rail (with the page action) and status pill. Rendered by each page's React body. The Hub bar itself is the static header in each page. |
| `frontend/static/patchstrip.js` | The patch strip's markup: `changeHTML` (the icon) and `changeCardHTML` (what it opens on hover). |
| `frontend/static/itemset.js` | The client's item-set JSON shape and `shortPatch()`. Shared by the builder (writes it) and the build list (reads a saved set back out and offers the same Copy JSON) — one contract typed in two files is one contract that drifts. |
| `frontend/static/catalog.json` | The item catalog, generated by the original `build_assets.py` in `Downloads/lol-item-set-forge`. Item icons are base64 at 48px (drawn at 46-48px, so 1:1). Champion portraits are **Data Dragon URLs, not payload** — they were baked at 32px and drawn at 62-72px, which is where the blur came from; the CDN serves the same art at 128px for free. |
| `verify_frontend.py` | The module's cold-verify harness: fresh browser context, no localStorage, every surface. Run it against a live Hub after any frontend change. |

## One pinned theme: Hub Liquid Glass in Rift colours

Forge has one theme and no picker (2026-11-09; the old five-theme picker, `forge-themes.css` and
the `forge:theme` key are gone). Each page's `<head>` pins `data-theme=liquid`, `data-glass=frost`,
`data-surface=dark` with a plain script (same as J&Co), links the Hub CSS (`base`, `components`,
`cobalt`, `liquid`) **before** `forge-base.css`, and loads `hub-modules.js`, `theme-switch.js` and
`topbar.jsx` deferred after React.

- **`html[data-theme][data-surface]` in `forge-base.css` is the retint.** Specificity (0,2,1) beats
  the Hub theme's (0,2,0) token block, so the Hub's `--bg --line --accent --danger --font` do not
  recolour Forge's content; it also sets the Hub-only tokens (`--fg*`, `--bg-elev*`, `--chrome`,
  `--lg-*` wallpaper and glass fills) in Rift cyan and gold.
- **The static header sits outside `#forge-root`.** `mount()` upgrades any `header.topbar` outside
  `#root`; a React-rendered one would race it.
- **Phone:** the fixed status pill sits above the Hub dock (`bottom: calc(12px + var(--dock-h))`).
- **Contrast is tested** - `tests/test_forge_themes.py` parses the OKLCH in `forge-base.css` and
  asserts every pair the tokens' real usage demands (`--dim` is 11px label text on `--surface`).
- `.btn-primary:hover` reads `--on-accent` (declared in `forge-base.css` `:root`).
