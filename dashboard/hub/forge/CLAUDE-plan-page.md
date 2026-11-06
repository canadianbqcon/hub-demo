# CLAUDE-plan-page — dashboard/hub/forge

The plan step of the builder. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The plan page: what you bring, how you level, where you walk, who you ban

Step three, `#step3`, rendered entirely by `static/loadout.js` and styled by
`static/loadout.css`. Both are shared with the saved-build overlay, which renders
the same shapes read-only through `planHTML()` — one shape read in two places is
one shape; two renderers typed in two files are two shapes a week later.

Same rule as the rune page above it: **authored and displayed, never exported.**
The client imports item sets and nothing else, so a summoner pair, a skill order
and a jungle path are read off the saved build and typed in by hand.

**Three of the four ride inside the set, one does not.** Spells, ability levels and
pathing are a `plan` object on the set row, whitelisted in `api_save_set()` beside
`runes` and normalised on every read by `normalisePlan()` — an old set has no
`plan` at all and a hand-edited one can have half of one, so nothing trusts the
shape on the way in. An all-empty plan saves as `null` rather than a key full of
blanks.

**Bans are keyed by CHAMPION, not by set** — the only thing in the tool not keyed
by `(name, patch)`. A ban answers "who beats this champion", which has nothing to
do with which items you bought, so every set on a champion reads one list and
forking a set forward to a new patch does **not** fork the bans with it. Own store
(`data/forge-bans.json`), own two endpoints (`GET`/`PUT /api/bans/<champ>`), keyed
by champion name lowercased. Values are catalog champion keys, ints. Bans save the
moment you pick one and never ride the set's autosave: a build you never saved
should still be able to record that Kayle is unplayable into this champion.
Rejected: per-set ban lists and one global list. Settled, do not re-raise.

**The max order is read off the grid, never typed.** Four rows by eighteen columns,
one ability per level; `maxOrder()` ranks an ability by the level its fifth point
lands on. A typed max order and a grid can disagree and then neither is
trustworthy. The one rule the grid enforces itself is Riot's: the ultimate is legal
at 6, 11 and 16 and nowhere else, and those three levels take nothing else. The
five-point cap on a basic ability is the one rule the grid cannot *show*, so it is
said out loud in `#planSub` rather than swallowing the click and looking broken.

**A path is an ordered list of camp chips plus a note**, and the note takes the
library's existing sentence shape ("Take this `<trigger>`") — a route with no
trigger is the same gap the item shelves had before notes existed. The section
shows on `role === 'jungle'` and nowhere else: a path on a mid set is noise, and
the role is the only thing that makes it noise. Rejected: free-text paths.
Settled, do not re-raise.

The nine summoner spells are **hardcoded** in `loadout.js`, ids and image filenames
verified against ddragon `data/en_US/summoner.json` filtered to mode CLASSIC. The
list has not moved in years and the page is tuned for weight. Nothing new goes in
`static/catalog.json`.

### The layout is an information architecture, not a way to fill space

`.planpage` is two columns: `minmax(340px, 420px)` for what you **pick** (spells,
bans — short rows that each carry one figure) and `minmax(0, 860px)` for what you
**sequence** (the 18-column grid, a route). It shipped as four full-bleed cards
holding content that stopped at 40% of their width, and the fix is not a
page-level `max-width` — that would fight the house full-bleed style. Two columns
cap the page near 1300px on their own. Collapses to one at 1180px, where the grid
column can no longer hold 18 legible cells beside a picker.

Three smaller things the first pass got wrong, all fixed in `loadout.css`:

* **The ultimate rule is a COLUMN, so it is drawn as one.** Levels 6/11/16 carry a
  gold wash top to bottom (`.pl-sk[data-ult]`, set on every row, not just R).
  Transparent `.off` cells read as three random holes in Q/W/E and three floating
  boxes in R — the rule was right and the execution taught nothing.
* **The route and the camp pool were the same pills** separated by a dashed rule.
  The route now sits in a raised well under a `ROUTE` label; the pool is a flat
  `ADD A STEP` tray on the card ground. A pool pill is an offer, not a step.
* **A path name is sized to a name** (`clamp(180px, 26ch, 300px)`) with Delete
  beside it, not a 1500px field with its delete button a screen away.

### Figures: three of the four elements have one, and the fourth says so

Every element on this page is now read beside its measurement, in the **rune
picker's existing vocabulary** — the `.srcbar` header, the fixed figure tracks,
`.wpa .up/.down/.thin`, `wrClass` against the champion's own base win rate. A
second figure shape on a third surface is the failure that avoids.

| Element | Source | Figure |
|---|---|---|
| Summoner spells | coachless | WPA + sample, per spell, in a lane |
| Summoner spells | lolalytics | the one top PAIR, printed **under** the list |
| Ability levels | lolalytics | skill order (per level) and skill priority |
| Bans | lolalytics | the twelve worst matchups, worst first, one click to ban |
| Jungle pathing | — | **nothing exists**, and the card's why-line says so |

Four things that are settled and cost real time to establish:

* **coachless has no skill-order and no matchup data.** Eleven endpoint names
  probed across three controllers, all misses, and their own nav is builds /
  items / runes / spells / leaderboard. Do not go looking again.
* **The spell endpoint is `ChampionWinprob/GetGlobalSummonerSpellStatistics`**,
  found by recording coachless' own XHRs in a browser. It takes the ordinary
  `commonFilters` plus `pairedSpell` (sent as null) and returns the same shape
  items and runes already bake to. Thin by nature: a jungler runs Flash and Smite
  in ~100% of games, so most rows come back as a dash. That is the reading.
* **lolalytics publishes ONE summoner pair, not a per-spell breakdown.** It is
  rendered as a pair line and must never move into a per-spell lane, where it
  would read as a figure for that spell.
* **The counters table is not on the build page.** The build page renders the
  counters *headings* and never the rows; the table lives on `/counters/`, which
  `bake_lolalytics.py` now loads as a second page in the same browser. A counters
  miss degrades to an empty list and hides the block rather than sinking the
  runes and items that did land.

Both bakes write into files the API **already serves** (`/api/stats`,
`/api/lolalytics`), so this feature needed no new endpoint. `forge.html` passes
the two nodes and its own formatters into `mountPlan()` rather than `loadout.js`
copying them — a second `fmtWpa` in a second file is a second answer to "is +0.5
good" the first week one of them changes.
