# CLAUDE.md — dashboard/hub/forge

The Item Set Forge: a League of Legends item-set editor with coachless.gg's WPA
statistics read alongside it, served at `/forge`.

Listed on the Hub `/artifacts` page under **Projects** (a self-hosted project,
not a claude.ai Artifact) rather than getting a launcher tile. Deliberate — the
`/artifacts` catalog is Sam's list of "things I made", and this is one.

**"Build a league build" always means a saved set here [BINDING]**, never a doc, note or
Artifact. Write through `POST http://127.0.0.1:5002/forge/api/sets` (never hand-edit
`data/forge-sets.json`); saving under an existing `(name, patch)` replaces it, so check for an
existing set first and correct it. Patch is the ddragon version read off `/forge/api/sets`;
resolve every item id against `forge/frontend/static/catalog.json`; research goes into item
notes and `runes.alts`. Verify by screenshot at `/forge/c/<Display%20Name>/<role>#<set-id>`
(the ddragon key renders an empty page). An imported guide is a base: import its values
faithfully, then expect his edits on top, offer defensible off-guide options, and never
re-import over his changes.

## Six surfaces

| URL | Surface | File |
|---|---|---|
| `/forge/` | champion landing page: a build-shelf card per pool champion, then every other champion as a tile linking to its champion page | `landing.html` |
| `/forge/patch` | the **patch note**, its own surface | `patch.html` |
| `/forge/stats` | **his own record** off OP.GG: rank, season history, champion pool, recent games | `stats.html` |
| `/forge/c/<champ>` and `/forge/c/<champ>/<role>` | that champion's **build list**, every saved set grouped by patch | `champion.html` |
| `/forge/c/<champ>/<role>/build` and `/forge/edit` | the **three-step builder**: items, rune page, plan | `forge.html` |
| `/forge/draft` | the **draft assistant**: live champ select from `lcu_poller.py`, two pick lists, then build and game plan once he locks | `draft.html` |

## Where the rest of this lives

This file was 1,682 lines, six times the 250-line governance ceiling, so
everything past the first fifth was being underweighted at read time. The
detail now sits in companions beside it. Load the one that covers what you
are touching; the two binding rules and the gotcha list stay here.

| File | What it covers |
|---|---|
| `CLAUDE-landing.md` | The champion landing page and what a card carries |
| `CLAUDE-plan-page.md` | The plan step of the builder |
| `CLAUDE-chrome.md` | The bar, the page frame and the theme |
| `CLAUDE-patch.md` | The patch note and the patch page |
| `CLAUDE-patch-strip.md` | The patch strip the builder carries |
| `CLAUDE-build-surface.md` | The build surface and the shop read out of it |
| `CLAUDE-items-and-runes.md` | Items, keystones and the rune picker |
| `CLAUDE-stat-rail.md` | The stat rail and its two columns |
| `CLAUDE-data-sources.md` | Where the numbers come from, and what is derived |
| `CLAUDE-authoring.md` | Authoring a set: blocks, alternatives, notes, versions |
| `CLAUDE-draft.md` | The Draft page, its feed rules and the trait rules |

## The data leaves from the head, and a second visit costs nothing [BINDING]

Every page pays for itself in round trips, not in compute: the Flask side answers
every route here in under 25 ms, and the whole of what made the tool feel slow was
bytes on the wire and how many serial hops they took.

Three rules hold that, and all three are easy to undo by accident.

- **The data preflight lives in the `<head>`, above the stylesheets.** Each page opens
  with `<link rel="modulepreload">` for its imports and an inline `<script>` that
  starts every fetch into `window.__FORGE`; the module at the bottom awaits those
  promises instead of calling `fetch` itself. Two reasons it sits where it sits. An
  inline `<script type="module">` does not fetch its imports until the whole document
  has parsed and does not run its body until they land, so a fetch written at the
  bottom leaves on the third serial round trip. And a *classic* inline script is
  blocked on every stylesheet declared before it, so the preflight below the two
  `<link rel=stylesheet>` lines cost a further hop for CSS it never reads.
  **A new page-boot fetch goes in the preflight, not next to the code that uses it.**
- **Nothing here is served `no-store`.** `no-store` and `no-cache` both forbid serving
  a stale file; only `no-store` also forbids keeping one, which is what had the 424 KB
  catalog re-downloading on every single page view. The Hub's `_no_cache_static` hook
  says `no-cache`, `app.py` gzips text and JSON on the way out, and `forge/api.py`
  hashes each `/forge/api/*` body into an `ETag` and answers `304` on a match. The
  per-request file read stays — a re-bake still shows without a restart, it just costs
  300 bytes instead of a quarter of a megabyte when nothing moved.
- **A warm-up must drain the body it fetches.** `prefetchCatalog()` in
  `build-overlay.js` warms `api/stats`, `api/lolalytics`, `api/diff` and the catalog
  while the shelf sits idle, small ones first. Each one reads its body (`.blob()`,
  `.json()`): a response whose body is never read is **not** committed to the HTTP
  cache, so a bare `fetch()` spends the bytes and warms nothing.

Second visit, 25 Mbit / 25 ms emulated: front door 120 ms, champion 93 ms, builder
238 ms, 3 KB transferred. A first-ever visit to the builder is still catalog-bound at
about a second — 259 KB gzipped, of which 318 KB raw is base64 WebP icons that no
compressor can touch. Splitting those into a binary sprite is the only lever left on
that number and it has not been pulled: the catalog is cached until the next bake and
the front door prefetches it on idle, so the cold path is once per patch.

## Art is drawn at the size it exists, never larger [BINDING]

Every blurry icon in this tool has had the same cause: a CSS box wider than the
pixels behind it. Two were found at once on 2026-08-18 —

- **Champion portraits** were baked into `catalog.json` at 32x32 and drawn at 62px
  on a landing card and 72px on the champion page. Fixed by pointing at Data
  Dragon's own 128x128 art instead of baking a thumbnail, which also took ~128 KB
  out of the catalog. `build_assets.py` does the same now, so a re-bake keeps it.
- **The five rune tree emblems** were stretched from 32x32 to 46px in the builder's
  `.treepick`. **32x32 is the only size Riot ships them in.** Data Dragon, the raw
  CommunityDragon game assets, the plugin assets and `perkstyles.json`'s asset map
  were all checked; the asset map holds full-bleed banner JPGs, not emblems. So the
  emblem is drawn at 32px inside a 56px button and cannot go bigger without
  upscaling. Do not "fix" this by making it larger again.

Keystones and minor runes are 256x256 on Data Dragon and have plenty of headroom.

`verify_frontend.py` enforces this: it reads every rendered `<img>` on the front
door, the build list and the builder, and fails on any whose `clientWidth` exceeds
its `naturalWidth`. Adding art larger than its source will fail the harness.

## Things that will bite

- **`role` is an int enum and `5` is not a lane.** 0 top, 1 jungle, 2 mid, 3 bot,
  4 support, **5 = every role aggregated**. Measured against one-role champions
  (Jinx returns bot-only counts at 3, Thresh support-only at 4, and both tie
  their own total at 5). Treating 5 as a role silently blends every lane's
  builds into one list.
- **`mainTree` must be the keystone's own tree** when calling
  `Rune/GetRunesForKeystoneAndTree`. A secondary tree returns different rows
  depending on which tree is primary, so a hardcoded `8000` returns wrong rows
  for any non-Precision keystone and nothing errors.
- **The current patch is paywalled server-side** (403, global and per-champion
  alike). `bake_stats.py` walks back from the newest patch until one answers
  200. There is no client-side way around it, so the figures always trail live
  by a patch. That gap is what a lolalytics scrape would fill; not built yet.
- **A pool champion enters through `POOL` in `bake_stats.py`.** That pool is his
  builder shelf and coachless' full per-champion bake. Since 2026-11-04 the plain
  `bake_lolalytics.py` run covers the pool's roles plus every champion-role at or
  above `ROLE_FLOOR` in the matchups store (`build_jobs`, 292 roles), so every
  champion he locks in on the Draft page gets an item and rune build. To add a pool
  champion: add the Riot id, run `bake_stats.py --champ "<name>"`, then
  `bake_lolalytics.py --champ "<name>"`.
- **`bake_stats.py --champ` used to CLOBBER the rest of the pool.** It built a
  fresh `out` and wrote it, so one champion's leg replaced a nine-champion file
  with a one-champion file, silently and with an exit code of 0. Fixed 2026-08-25
  by `seeded_champions()`, which seeds from the file on disk when the patch label
  matches and starts clean when it does not — the same last-good-file behaviour
  `bake_lolalytics.py` already had. Its two asserts are in `demo()`; keep them.
- **Units:** `wpaOverall`, `winrateExpected`, `winrateObserved` are percentage
  points. `occurrenceRelative` is a percent summing to ~100 across the champion's
  items. `averagePurchaseTime` is **milliseconds**.
- **WPA alone is not a ranking.** The highest-WPA item on any champion is
  reliably a low-sample outlier — on Viego jungle the top four by raw WPA are
  all under 1% of games. The UI encodes this: sample size sets the edge width,
  anything under `MIN_GAMES` renders grey instead of coloured, and the panel
  says so in words. Do not add a "sort by WPA" that drops the sample column.
- **No literal non-ASCII in anything the page renders.** Comments may keep their
  box-drawing; template and string literals use `\uXXXX`. Inherited from the
  artifact era and still worth keeping.
- **`<base href="/forge/">` is load-bearing in all three pages.** The builder is
  served at a THREE-segment path (`/forge/c/Viego/jungle/build`), so without it
  every relative fetch — the catalog, `api/stats`, the shared modules — resolves
  against `/forge/c/Viego/jungle/` and 404s.
- **A set is stamped with the LIVE Data Dragon patch (`catalog.ver`, trimmed to
  two parts), not `STATS.patch`.** coachless trails the game by a patch, so
  stamping the statistics patch filed a set saved today under 16.15 while the game
  was on 16.16. `shortPatch()` in `static/itemset.js` does the trim.
- **The two-step pipeline saves the same `(name, patch)` twice by design**, so the
  builder tracks `OWNED` — the row this session is writing — and skips the
  "already has a patch X version, replace it?" confirm for it. Without that, every
  build asks you to confirm overwriting your own step-one save.
- **Switching keystones leaves the three primary rows exactly as they are.** Every
  figure on them is re-read under the new keystone, which is the reading you
  switched keystones to see, but the picks themselves are yours. Re-seeding them
  from most-taken (what it did until 2026-08-18) silently overwrote a deliberate
  choice every time you compared two keystones; blanking them, the version before
  that, was worse still. Only a **tree** switch clears the rows, because the runes
  under it are different runes. A keystone coachless never broke down (under ~the
  sample floor) has no reading at all; the status line says so rather than showing
  three silent dashes.
- **Two health shard icons are crossed at the source and must stay crossed.**
  5001 Health Scaling uses `StatModsHealthPlusIcon.png` (a heart with a rising
  arrow) and 5011 Health uses `StatModsHealthScalingIcon.png` (a bare heart).
  Riot's filenames are swapped relative to the art. Community Dragon's
  id -> iconPath mapping agrees with the art, and the art is what a player
  recognises: the arrow means scaling. Do not "fix" these back to their filenames.
- **A shard slot is `shard:<row>`, whose first character is also `s`.** The
  secondary-rune branch tests `slot[0] === 's'`, so it caught every shard click
  until the full-prefix test was moved above it: `+slot[1]` came out `NaN`, the
  shard was pushed into `R.sec` instead of `R.shards`, and both halves broke at
  once. Test `startsWith('shard:')` first, always.
- **lolalytics has no JSON API and its numbers are not in the server HTML.**
  `ax.lolalytics.com/mega/` is 404 and a network sniff of the live page shows
  zero XHR for the build data. Only the 22-icon "highest win build" summary is in
  the SSR markup; the 128-icon rune grid and the item tables render on Qwik
  hydration out of a serialised state blob. A real browser is not optional, which
  is why this is a bake and not a live server-side scrape.
- **The two patch numbering schemes do not agree.** Data Dragon serves
  `16.16.1` while Riot's notes for the same patch are titled **26.16** — the
  notes major is the calendar year, Data Dragon's is the old sequential season
  count. `bake_patchnotes.py` does not hardcode the offset; it guesses both
  majors against both slug shapes (`league-of-legends-patch-26-16-notes` and
  `patch-26-16-notes`) and accepts only a page that declares the patch it is
  for, so a redirect to some other article cannot pass as a hit.
- **`html.parser` lowercases attribute names**, so Riot's `dateTime` on the
  `<time>` element arrives as `datetime`. Read both.
- **Community Dragon rejects the default `urllib` agent with a 403.**
  `build_runes.py` sends a browser `User-Agent`. Data Dragon does not care.
- **The `Edit` tool cannot match a block of `forge.html` that mixes literal
  box-drawing in a comment with `\uXXXX` escapes in a template literal.** The
  escape-swapping retry does not handle a string containing both. Use a Python
  line-range splice for those.
- **Do not go back to re-rendering a rune column on a click.** `innerHTML` on
  `#primaryCol` is the shape of the bug described above: it destroys the button
  under the pointer mid-gesture. `verify_frontend.py` asserts zero element
  removals under `#step1` across a click-through, and that the pressed button
  keeps focus.
- **Verify by loading the page cold, in a fresh browser context with no
  localStorage.** Driving the dropdowns and screenshotting the result is how the
  empty landing state went unnoticed for a whole build: every screenshot was taken
  of a page that had already been put into a state you cannot reach by opening it.
  `verify_frontend.py` is that pass, written down and runnable. HTML5 drag cannot
  be driven from Playwright, so it fires the drop handlers with a live
  `DataTransfer` and reads the result back out of localStorage.
- **The clip check measures a settled page, never a loading one.** `settled_clip()`
  in `verify_frontend.py` waits on `document.fonts.status` and every image being
  complete, then reads twice 150ms apart and only fails on a clip that survives
  both; a first-read-only hit prints as a settling artefact instead of going red.
  It reported a 44px BODY overflow once and then passed fifty-odd runs across four
  probe designs, including a 25ms sampler installed at document start. The layout
  cannot produce it: swept from 1300px down to 400px of viewport height, body
  `scrollHeight` equals `clientHeight` at every step, because the last grid row is
  `minmax(0, 1fr)` and absorbs whatever the rows above take. A reading the steady
  state cannot produce was taken before the state was steady. Do not answer a
  layout check that goes red at random by lengthening its sleep — wait on the
  condition, and make the failure print what the page was still doing.
