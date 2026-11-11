# CLAUDE-blueprints.md — the shared UI blueprint index

Loaded in addition to `dashboard/CLAUDE.md` for **any** work that builds or changes
a UI element in the Hub. It is a companion file rather than a section in the parent
because `dashboard/CLAUDE.md` sits at 246 of its 250-line ceiling.

## The rule [BINDING]

**Before building any UI element in the Hub, read the blueprint index and use the
existing component if one fits.** The index is `/blueprints` when the Hub is running,
and `hub/blueprints/blueprints.json` when it is not.

Three ways to read it, all generated from the CSS on disk at call time:

| | |
|---|---|
| `/blueprints` | the page — live examples, markup, rules, the CSS behind each |
| `python -m blueprints.resolve [id]` | terminal, no server needed. This is usually the right one for an agent. |
| `GET /blueprints/api/blueprints.json?resolved=1` | the same thing as JSON |

`blueprints.json` alone deliberately carries **no CSS** — copied CSS text goes stale
in silence, so the styling is always read fresh off `base.css`, `chrome.css` and the
two stylesheets `static/js/theme-switch.js` injects at runtime. Read the resolved
form, not the raw file, when you need to know what a component looks like.

**The shared layer is seven sources, not two.** `base.css`, `chrome.css`,
`components.css`, the three origin files in `static/css/origins/` (`tabbed-3-pane.css`,
`entry-3-pane.css`, `tabbed-reader.css`) and the stylesheet
`theme-switch.js` builds as a string and injects into `<head>` — the real chrome,
`.hub-back`, `.module-launcher`, the whole `.theme-picker`, the `is-*` state
classes and the `--ctl-h` control-height system, lives only there. Scanning the
`.css` files alone left 14 shared classes invisible and every chrome blueprint
structurally incomplete. `extract.py` reads the injected CSS out of the JS
source; treat `theme-switch.js` as a CSS source, not as a script that happens
to ship. `SHARED` in `extract.py` is the one place all seven are named — a
source added there is excluded from the page-CSS line readout and picked up by
every check with no further wiring.

**Markup is never hand-authored.** Each entry carries either:

- `live` — a CSS selector for a real instance of the component **on the running
  `/blueprints` page**. The page clones that node for the preview and derives the
  paste-able markup from its `outerHTML`, so it cannot disagree with what ships.
  Every chrome component is built by `theme-switch.js` at runtime and appears in no
  template, which is exactly why the first pass invented all of it and every field
  was wrong: a `brand-mark` path that 404'd, a made-up surface glyph, a `⌘K` hint on
  a button that has never had one, launcher tiles with their SVG glyphs left out.
- `markup` + `markup_from` — for the three `base.css` components no page renders
  statically. Transcribed **verbatim** from the real construction site named in
  `markup_from`, never composed by hand.

For the four controls `theme-switch.js` mounts from nothing, `markup` is the empty
string: the correct answer to "what do I type" is *nothing*.

**The page has four tabs (2026-09-24), and every blueprint names its own with `tier`:**

| tab | holds | source |
|---|---|---|
| basics | the brand sheet (fonts, colour, spacing, radius, brand marks and module glyphs, all read off the live page and `window.MODULES`, never listed by hand) over the small parts: buttons, pills, tags, titles, fields, text tones | `tier: "basics"` |
| elements | parts a page composes: cards, tabs, tables, modals, timelines, lists, plus the known-debt and page-CSS line readout | `tier: "elements"` |
| modules | prebuilt chrome that mounts whole: top bar and its controls, module launcher, status strip, page shell, nav rail | `tier: "modules"` |
| pages | full-page origins and their derivatives (was the layouts tab) | `origins[]` |

`test_every_blueprint_has_a_tab` fails on an entry with no tier or a misspelt one, since
the page would silently drop its card.

**If you build something shared, it gets a blueprint in the same change.** Not the
next commit, not a follow-up task. The suite fails on a shared class with no
blueprint, which is the mechanism that makes this rule real rather than aspirational.

**Text with a control beside it is `hub-text-act` (2026-10-14).** An address, count or
status that ends in one chip or button goes in a `hub-text-act` line: the text wraps,
the control never shrinks, and on a full line the control drops under the text. The
text never goes inside the chip (a whole address in a `hub-link-chip` wrapped into a
slab); the chip label stays short (`map ↗`). No per-spot wrap patches in module CSS.

**Forge seat disclosure (2026-10-30).** A compact control under a draft seat's name
that opens the seat itself: `ax-open` is the chip (`aria-expanded`), `ax-body` spans the
seat's grid in the normal flow, never a popover, and its `ax-row`s are real buttons.
One seat is open at a time; Escape returns focus to the chip, an outside click closes.
It lives in `forge/frontend/draft.html` and `draft-page.jsx`, not the shared layer:
Forge loads no `base.css`, so no `hub-*` part can render there and `/blueprints` has no
entry for it. Its tags sit in `baselines.markup` on the same standing as other Forge
pages. Reuse this shape on any Forge page before building another disclosure.

**Forge champion page (2026-11-02).** `/forge/c/<champ>/<role>?arch=<id>`, layout A from
the Workbench set `forge-champion-page-layout`: two columns, the build side stays in
view. It lives in `forge/frontend/champion.html` and `static/champion.jsx`, `cp-*`
classes inlined in the template, and like every Forge page links no shared sheet. The
open seat's `ax-learn` link ("Learn <champ>") lands on the same role and archetype;
the page writes `?arch` back on pick, so a copied URL reopens that archetype. Its
archetype rows (`cp-arch`) are not draft-page's `ArchBody`: the picked layout shows
path text and win rate per row, which the seat body does not. Every value on it comes
from `/forge/api/champion/<champ>`, `catalog.json` or `runes.json`; an absent value
reads as missing, never a guess. `verify_frontend.py`'s `champion_link_pass` is its check.

## Why this exists

`tests/test_cobalt_button_standard.py` is the receipt. One button treatment got
copied into four module stylesheets and all four drifted — batch dropped the hover
fill, barback dropped the tomato flash and hardcoded a 12px radius, finances added a
colour transition. Four buttons, one theme, four behaviours, and nothing said a word,
because prose in a comment is not a check.

The measurement when the index shipped, 2026-08-31: **548 lines of shared CSS against
14,931 lines of module CSS.** `trips.css` alone is 4,014. Almost everything was being
re-authored per module.

## The checks

`hub/tests/test_blueprints.py`. Pure text over files on disk — no browser, no
server, so they run everywhere the suite does.

| | Fails when | Fix |
|---|---|---|
| existence | a blueprint names a class the CSS no longer has | update `blueprints.json` |
| copy | a module reproduces a blueprint's signature under a new name | use the shared component |
| tray | a shared class exists that no blueprint claims | write the blueprint |
| override | a module re-styles a blueprinted class in its own file | style your own class, or scope to the shared one |
| markup | markup names a class no blueprint owns, references an asset not on disk, or (with no `live` selector) omits a class the entry claims | copy it from `markup_from`, or give the entry a `live` selector |
| shared-part markup | a `<button>` or `<table>`, or an element whose class names a card or pill (`rail-card`, `qa-type-pill`), carries no class any blueprint owns; also fails when a `baselines.markup` line no longer matches anything | put the shared class on it (`hub-btn`, `hub-table`, `hub-card`, `hub-pill`) and scope page tweaks under it; drop fixed lines from the baseline and lower `markup_max` |
| new-file cap | a stylesheet outside `page_css_files` exceeds `starter_css_max` (40 lines) | build the page from shared components, or add the file to the roster and say why it needs CSS of its own |
| origin composes | a rule in an origin file bare-restyles a `base.css`/`chrome.css`/`components.css` blueprinted class instead of composing it | drop the restyle; the origin adds layout, it never repaints a part |
| origin scoping | a module rule bare-restyles an origin class, or one of its states (`active`, `is-open`, `is-full`, `is-reader`, `is-empty`, `is-zero`, `is-primary`) | qualify with a module class or `body.<page>` |
| origin copy | a module rule reproduces an origin rule's declaration set verbatim, or one of its signatures | link the origin, don't re-author it |
| derivative wiring | a derivative's template doesn't link its origin right after `components.css`, is missing one of the origin's `template_classes`, or its skeleton names an `id`/`data-`/Jinja token instead of being a plain read-off | fix the link position or the markup; the skeleton is captured, never authored |

`test_blueprint_origins.py` holds these four plus the existence and layouts-tab-is-generated
checks; `test_blueprints.py`'s existing eight are extended to union `origins[].classes` and
`.descendants`, so an origin class is caught by the same tray, override and copy machinery a
component class already gets, not a parallel system.

**Nine pre-existing, coincidental verbatim matches don't fail the origin-copy check.**
`food.css`'s `.col`/`.side-pane` and `purchases/style.css`'s three filled-accent-button rules
(against tabbed 3-pane), plus `food.css`'s `.side-pane`, purchases' `.pe-rail-list` and
`food-view.css`'s `.results`/`.scene-view` (the flex scroller idioms entry 3-pane also writes),
predate the origins and restate the same boring idioms it also writes, by chance, not by
copying it. They're baselined the way the other debt lists are — `baselines.origin_copies`
(9 entries) and `origin_copies_max` (9) in `blueprints.json`, checked by
`test_baselines_cannot_silently_grow` — so a sixth coincidence fails loudly instead of being
silently swallowed, and this ratchet stays separate from `copies_max`, which the design keeps
at 0 for a dropped signature.

**Scoping to a shared class is reuse, not drift.** The mechanical test the override
check applies: a rule is an override only when the **leftmost compound of one of its
comma-separated parts is made only of shared classes**. Qualify it with a module
class (`.frow-pip.hub-dot`), descend from one (`.work-grid .launch-tile`), scope it
to the page (`body.home .topbar`) or narrow it by attribute
(`[data-theme="cobalt"] .topbar`) and it is reuse. Re-declaring `.launch-tile` bare
is the thing that breaks. The eight modules carry page classes on `<body>` for
exactly this: `home`, `jobs`, `finances`, `trips`, `forge`, `jc`, `food`,
`purchases`.

### The debt baselines, and why there is no page-CSS line cap

As of 2026-09-09 `overrides_max`, `copies_max` and `undocumented_max` are all **0**,
so checks 2, 3 and 4 are not baselines any more — they fail on the first new
offender, full stop.

**The page-CSS line cap (`page_css_max`) was retired 2026-10-15.** It measured the
wrong thing: a page's own CSS (trips.css above all) is meant to be unique, and the
cap was raised about 25 times with "nothing to promote", so it never drove a
promotion. Reuse is guaranteed directly instead. The copy check catches a shared
component pasted under a new name; its stated ceiling was the component rebuilt
from scratch with different properties. The **shared-part markup check** closes
that ceiling from the markup side: a button, table, card or pill with no shared
class on it is a rebuild. `baselines.markup` holds the 269 that existed the day it
landed (debt, not reviewed exceptions); it only shrinks, and a fixed tag whose
line is still listed fails the suite until the line is dropped.

The rule the baselines taught still holds: raising `markup_max`, `starter_css_max`
or the roster is a deliberate, reviewable line in a diff — never a way to silence a
check.

**Before deleting any rule the override check flags, read what the page's template
actually links.** Only `food`, `purchases`, `ledger`, `recipes` and `blueprints` link
`chrome.css`; `jobs`, `finances`, `trips` and `jc` link `base.css` and nothing else;
the six `forge` templates link neither, and load no `theme-switch.js`. So a module
rule and its "identical twin" in the shared layer routinely **never load on the same
page**, and deleting the module copy leaves the component unstyled. The test is:
does the shared twin genuinely load here *and* win? Only then is the rule dead.
Otherwise it is live and it gets scoped. Note the injected half — `theme-switch.js`
appends `#hub-universal-css` last in `<head>`, so on a page that loads it the
injected declarations beat the page's own at equal specificity, which is the mirror
image of the same question.

## components.css, and the link-order hazard [BINDING]

`static/css/components.css` is the parts library: the treatment promoted out of a module under a
`hub-` name. `chrome.css` stays the page shell, `base.css` stays its three primitives. It is in
`SHARED`, so `module_stylesheets()` excludes it and a promotion drops the page-CSS line readout by
exactly the lines it moves.

**The head order is not uniform across the Hub, and assuming it is will invert a cascade silently.**
The design spec states chrome, base, components, themes, module. Seven pages do not do that: trips,
purchases, jobs, finances, checklists, work and jc all link their own stylesheet *before*
`base.css`. On those pages a promoted `.hub-x` beats a module rule at equal specificity, which is
the reverse of what the author of the module rule expected, and nothing errors.

Verified 2026-09-16: in all 21 templates that link `base.css`, the next line was `themes/vesper.css` (removed with Vesper 2026-11-03; it is now `components.css`, then `themes/cobalt.css`).
So `components.css` goes immediately after the `base.css` line, in every one of them, which gives
chrome, base, components, themes everywhere regardless of where the module sheet sits. On the seven
pages above, a module rule that must beat a promoted rule needs **higher specificity, not source
order**. The six `forge` templates link neither shared sheet and get nothing.

## Signatures, and what they cannot do

A `signature` is a **conjunction** of regexes: every pattern must match the same rule.
Any-match was tried and was too loose — `backdrop-filter: blur` alone flagged four
frosted-glass decorations that share one property with the modal and nothing else.

Stated plainly: **a module that reinvents a component from scratch with different
properties shares no signature and passes.** Nothing static can decide that an
arbitrary block of CSS "is a modal". What checks 2 and 4 do cover is the failure that
actually happened here — copy-paste-then-drift, and direct override of a shared class.

Check 5 has the same shape of ceiling. It can prove markup names only real classes
and references only shipped assets; it cannot prove the markup is what a page really
writes. That is what `live` is for — a captured node needs no check.

## Interaction with the theming spec

`THEMING-SPEC.md` Rule 1 freezes every theme file verbatim once created, so the theme
files are **excluded** from the module scan — they are allowed to speak about any
class. The cobalt button standard stays governed by its own test over
`themes/cobalt.css`; `/blueprints` links to it rather than re-implementing it.

Rule 2 (structural change lives once, in the shared layer) is exactly what this index
makes visible. A new component archetype still needs the per-theme audit that spec
describes.

**Per-theme view (2026-10-10).** `/blueprints` shows the shared rules plus only the
active theme's version of each piece (`extract.THEMES`, `extract.rules_for()` on each theme file,
`theme_css: {vesper, cobalt, liquid}` in `?resolved=1`), and re-renders on
`hub:themechange`. Under liquid each card also carries its layer badge and an "own
version" or "inherits shared" badge. Every entry has a `liquid_layer` (`glass` /
`opaque` / `solid`); a piece with no liquid rules needs a reason in the top-level
`liquid_inherits` map. `tests/test_themes.py` enforces the scoping, the layers,
the roster and the coverage, so a new blueprint fails there until it has liquid rules
or an inherit reason.

## The pages tab (was layouts): origins and derivatives (2026-09-23)

`/blueprints` has a second tab beside the component index above, and since this build it is
generated from the registry the same way the components tab is, not hand-curated. Four words,
used exactly as picked, everywhere from the registry keys to the page to the tests:

- **tabbed 3-pane** — the page shape: tabs down the left, a focus column of cards in the
  middle, a context rail of cards on the right, a status bar, and a phone shape (a slide-out
  tab drawer, a full-viewport context slide-over). Slug `tabbed-3-pane`.
- **entry 3-pane** (2026-09-25) — the page shape for a database of many things: a long list
  of entries down the left (grouped under pinned heads, one line each, keyboard-walkable),
  and the picked entry fills the rest: a compact head whose tabs are a stage track, plate
  cards, a context rail, a status bar; on a phone, master-detail under a pinned bar (back,
  N of M, previous/next). Slug `entry-3-pane`, prefix `hub-e3p-`. Pick it over tabbed 3-pane
  when the left column is the records themselves, not sections of them.
- **tabbed reader** (2026-09-29) — the page shape for reading and signing off documents:
  tabbed 3-pane's rail, shell and status bar, and the rest of the page is one reading pane
  holding a shelf (the section's documents) or a reader (one open document, held to a 78ch
  measure), with the item's actions pinned in the reader's bar and a comment strip that send
  back opens directly under the bar. The shelf
  docks beside the reader at 1400px and up, slides over it from a toggle at 901-1399px, and is
  master-detail on a phone. Slug `tabbed-reader`, prefix `hub-trd-`. It is the first origin that
  **extends** another: its registry entry carries `"extends": "tabbed-3-pane"`, a derivative
  links `tabbed-3-pane.css` then `tabbed-reader.css` (both after `components.css`), and it never
  restyles a `hub-t3p-*` class. `test_blueprint_origins.py` follows the chain: the wiring check
  wants every origin in it linked parent first, the chassis check adds the parent's
  `template_classes` where the child's skeleton kept them, and the composes check treats the
  parent's classes as off-limits to a bare restyle. Workbench is its first derivative.
- **icon wall** (2026-11-10): the page shape for a collection you act on tile by tile: one slab
  per category, a grid of square tiles (icon, level over max, count badge, name), and a Start
  button under each tile that has a next level. Maxed tiles dim, running ones get a green
  border; 3 columns at 640px. Source: Workbench set `clash-tracker-screen`, pick D; built in
  `hub/clash/frontend/static/clash.jsx` and `clash.css` (`.cx-wall`, `.cx-tile`).
- **builder timeline** (2026-11-10): a seven-day lane chart: one lane per builder plus the lab
  and the pet house, a bar per running timer that ends when the timer does (clipped at 7 days),
  a dashed "free" lane when idle, and a bar click opens an edit strip for the finish time.
  Pick B of the same set, used above the icon wall. Classes `.cx-gantt`, `.cx-lane`, `.cx-blk`.

- **origin** — the base a dashboard is built from: one stylesheet in `static/css/origins/`,
  one markup skeleton in `blueprints/origins/`, one entry in `blueprints.json`'s `origins`
  list. Editing the origin edits every derivative.
- **derivative** — a dashboard built on an origin. Its template links the origin stylesheet
  right after `components.css`, then its own page mods; `blueprints.json`'s `derivatives`
  list records the link.
- **page mods** — a derivative's own stylesheet. New classes freely; an origin class only
  when the rule is qualified by something the page owns (a module class, `body.<page>`).
  Never a bare restyle — that redefines the origin for every page that loads it, and a page
  mods sheet is sometimes loaded on more than its own page (trips already mounts
  `food-view.css`).

Trips is the first derivative: `static/css/origins/tabbed-3-pane.css` is the whole-page
chassis (rail, focus header, card stack, context rail, status bar, the phone drawer and
slide-over) read off the trips board and moved out of `trips.css` verbatim, in two passes.
`trips.css` kept only what is actually a trip fact or a trips-only tuning — the notice strip,
the per-tab split ratios, the map slot, the day rows in the sub-tab list — each qualified so
it reads as a page mod rather than a second copy of the chassis.

Jobs (`/jobs/`) is entry 3-pane's first derivative, and its skeleton was read off the rebuilt
page. The two origins share parts, not layout: both draw their cards as `hub-plate-card`, the
trips head plate promoted into `components.css` for the second origin. Jobs keeps its list
grouping, keyboard movement, stage state and phone flow in `jobs.jsx` (origins carry no JS),
and its page mods hold the job facts, the rail splitter and the plate body padding. Jobs'
theme hooks are `col`, `body`, `status`.

Each `origins[]` entry carries `purpose`, `use_when` and `dont`, a `skeleton` (read off a
real rendered page, never composed by hand, the same rule the component blueprints' `markup`
field already follows), and `theme_hooks` — the handful of class names the frozen theme
files still key on (`col`, `body`, `status`, `funnel`, `funnel-search`, `funnel-add`, `ftot`,
`lgroup-act`), carried in every derivative's markup beside the origin classes because
`THEMING-SPEC.md` Rule 1 freezes the files that read them.

**To add a derivative:** paste the origin's skeleton with the origin's shell as a direct
child of `<body>` (the viewport lock keys on that), link the origin file right after
`components.css`, add an entry to `blueprints.json`'s `derivatives` list (`dashboard`,
`origin`, `template`, `page_mods`, `body_class`, `href`), and write only page mods —
qualified, never a bare origin-class restyle. `python -m blueprints.resolve <origin-id>`
prints the origin the way it prints a component; the layouts tab shows it live, blank, in a
demo frame, with the current derivatives and their page-mods line counts underneath.

## See also

- `docs/archive/specs/2026-08-31-elements-blueprint-index-design.md` — design + adversarial review
- `docs/archive/specs/2026-09-17-layout-blueprints-origin-derivative-design.md` — the origin/derivative design, this section's source
- `[[wiki/patterns/hub-element-blueprints]]` — the vault-side note
- `[[wiki/decisions/onboard-elements-index]]` — why the infrastructure looks like this
