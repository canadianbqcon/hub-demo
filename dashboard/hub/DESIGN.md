# Design

## Overview

The Hub renders through a token system layered as `[data-theme][data-surface]`. **Theme** picks the identity (`liquid` — the primary theme and cold-start default; `vesper`; `cobalt`); **surface** picks `dark` or `light`. **All Hub UI work is designed in liquid** (his call, 2026-10-17): designs, Workbench previews and new styling target Liquid Glass; vesper and cobalt are not design targets. **Every UI change is verified under liquid in light and dark** (screenshot and read both) before it counts as done; liquid fixes go in the module's CSS under `[data-theme="liquid"]`, since `themes/liquid.css` is frozen. Every module links the shared chrome and reads tokens — it never hardcodes color, spacing, or radius. New modules mirror an existing frontend's `<head>` (chrome.css, base.css, then the theme CSS files) and style exclusively through `var(--*)`. **A module that renders a Leaflet map also links `static/css/map.css`, after the theme files** — it carries the whole Leaflet chrome (zoom bar, tooltip, tile treatment in both surfaces) and is the reason no module writes a `.leaflet-*` rule of its own. Marks that belong to one map (pins, route strokes, zoom-dependent variants) stay in that module's stylesheet and outrank it on specificity.

## Color (tokens, not literals)

Consume these; do not redefine them. Values below are the `vesper` theme for reference.

| Token | Role | vesper·dark | vesper·light |
|---|---|---|---|
| `--bg` | page ground | `#1a1f3a` | `#fdf3df` |
| `--bg-elev` / `--bg-elev-2` | raised panels, cards | `#232846` / `#2a3052` | `#f6e8c6` / `#f0dba8` |
| `--bg-hover` | hover fill | `#2a3052` | `#f6e8c6` |
| `--fg` … `--fg-ghost` | text ramp (full → ghost) | `#f4dcb0` → 0.24α | `#231848` → 0.22α |
| `--line` / `--line-soft` / `--line-strong` | borders | tinted α | tinted α |
| `--accent` / `--accent-dim` / `--accent-faint` | primary action, selection, links | `#a4b3d8` | `#3a4878` |
| `--warn` / `--alert` / `--good` | semantic state (separate from accent) | `#e8cc88` / `#e07878` / `#a8c488` | `#a87818` / `#a83838` / `#5a7825` |
| `--violet-label` | category / label hue | `#b094d4` | `#5a3878` |

Register is **product → Restrained**: accent for actions/selection/state only, never decoration. Semantic (`--warn/--alert/--good`) is separate from the accent and does not count as it. Body text must clear 4.5:1 on all four theme×surface combos.

## Typography

Family comes from the theme (`--font`, `--font-display`, `--font-body`) — vesper ships Cormorant Garamond / Fraunces (serif); other themes differ, so never hardcode a face.

**Size: six tiers, Apple text styles (picked 2026-10-17, Workbench set `hub-type-scale`).** Every font size is one of these tokens, defined in `static/css/base.css` (repeated in `forge/frontend/static/forge-base.css`, since forge pages do not load base.css). Pick the tier by the role the text plays, not by how it looks next to its neighbour:

| Token | px | Role |
|---|---|---|
| `--fs-caption` | 11 | eyebrows, uppercase labels, timestamps, legal-small |
| `--fs-footnote` | 13 | secondary lines, metadata, table cells in dense views |
| `--fs-subhead` | 15 | controls, list rows, compact UI text |
| `--fs-body` | 17 | reading copy |
| `--fs-headline` | 17 semibold | row and card titles at body size |
| `--fs-title` | 22 | section and card headings |
| `--fs-large-title` | 34 | page heroes, big numbers |

`tests/test_type_tiers.py` fails on any px/rem/em font size outside `trips/frontend/hallmark/`, `lostlands-open.html`, vendor and test fixtures (bespoke brochure type). The 2026-10-17 rollout snapped every old size to the nearest tier (ties up), so body copy mostly landed on subhead. The role pass (2026-10-17, Workbench `hub-role-pass-check`) moved paragraph copy to `--fs-body` (blueprint intro and card purposes, vault-map panel purpose, food summaries, batch method steps, `.hub-block-text`, liquid checklist descriptions) and news card titles to `--fs-headline`; dialog messages, empty-state hints and list rows stay at subhead by role. Tabular numerals for any aligned digits via `--feat-tnum`. Prose caps at 65–75ch; dense tables may run wider.

## Spacing & Radius

Spacing scale: `--s-1:4 --s-2:8 --s-3:12 --s-4:16 --s-5:20 --s-6:24 --s-7:32`. Radii: `--r:2` (controls), `--r-card:4` (panels), `--r-pill:999` (chips). Lay groups out with flex/grid + `gap`, not per-element margins.

## Components

Standard affordances, consistent vocabulary screen to screen. Cards only where they're the right affordance — never nested.

**Card fill [BINDING] (2026-11-10, from the Game Hub slab):** under liquid every card paints `background:var(--lq-card)` with `box-shadow:var(--lq-slab-shade)`. `--lq-card` is translucent fill under a 150deg wash from `--lg-hue-1` into `--lq-card-h2`. Every page is the standard Apple blue (per-module hues dropped 2026-11-10; brand apps forge, ledger and barback keep their own), so all three wallpaper hues are one blue and the second colour comes from `--lq-card-h2`: indigo `94 92 230` on both surfaces (Workbench picks `hub-card-light` and `hub-card-dark`, 2026-11-11). Dark keeps the `/gaming` `.gx-slab` strength (washes `.20` / `.26` to 70%, over `rgb(28 28 30 / .72)`); light is washes `.18` / `.22` to 75% over white `.72`. /gaming follows the Hub's light/dark with its slabs taking the light fill in game hues. Hover on a clickable card uses `--lq-card-hi`. Defined in `themes/liquid.css` section 16, which lists every card class; a new card class joins that list (or uses the token in its own rule), never a solid `--bg-elev`. Page panes, list columns and headers take it too. A card nested in a card is cleared (`background:none`) so the wash never stacks; inner tiles stay solid. Blueprint layer: `tinted`. Chips (`--r-pill`) for categories/state. Every interactive element carries default/hover/focus states through the tokens. Status band height is `--status-h`.

## Always the same

Universal chrome looks and behaves identically on every page, in every theme, at every width. A page never codes it, styles it, or opts out of it: the behavior lives in one shared file, and a page only ships its own extras.

The top bar is ONE React component, `static/js/topbar.jsx` (2026-10-12; before that a React copy in `chrome.jsx` and a DOM-building copy in `theme-switch.js` drifted apart). React pages (home, purchases, work) render `<Topbar crumb="work" />`. Every other page ships `<header class="topbar">` holding only its extras, loads react + react-dom (deferred) and `/jsx/static/js/topbar.jsx` after `theme-switch.js`, and topbar.jsx draws the bar into it. Each extra carries `data-slot`: `crumb` (the page title, a pill, a section line), `lead` (between brand and crumb: the phone section toggle), `left` (after the crumb block: jobs' view modes), `right` (ahead of the controls; untagged lands here). Extras are moved, not copied, so ids and listeners a page script bound stay live.

| Element | What the page ships | Where it is built (the only place to change it) |
|---|---|---|
| Top bar (`.topbar`, `.topbar-l`, `.topbar-r`) | `<header class="topbar">` with its `data-slot` extras | `static/js/topbar.jsx`; CSS in `static/css/chrome.css`, liquid sticky + island in `static/css/themes/liquid.css` section 11 |
| Island on scroll (`.topbar[data-scrolled]`) | nothing | `watchScroll()` in `static/js/theme-switch.js` |
| Brand wordmark + slogan | nothing | `TopbarInner` in `topbar.jsx` (slogan from `HubTheme.slogan()`) |
| Back button | nothing | `BackButton` in `topbar.jsx` (behavior `window.HubBack`) |
| Light/dark toggle, theme picker, sign-out, modules launcher | nothing | `topbar.jsx`; surface persisted by `HubTheme.surface`; module list and the sign-out flag from `/hub-modules.js` (`hub_modules.py`, `DASHBOARD_EXPOSED`) |
| Phone view (gear → view: desktop / phone, desktop pointers only) | nothing | `phoneView()` in `topbar.jsx`: the page laid out at 390x844 in a same-origin iframe under the bar, scaled as a whole to the window height so the phone's shape holds (`fit()`, refit on resize), with an iPhone's 47px notch and 34px home-bar insets set on the frame (`--safe-t`/`--safe-b`, theme-switch.js) and its island and home bar drawn over it, on a frosted-glass backdrop over the page (liquid solid: the theme's colour wall; a11y modes: plain background), kept on across pages in `localStorage` `hub.phoneview`; the frame's own bars (native and liquid's `#sb-layer`) are hidden and `phoneScrollbar()` draws one just outside its right edge, following the last-scrolled pane |
| Phone dock (`.topbar-r` under 900px) | nothing | `injectUniversalCss()` in `theme-switch.js` |

**The one exception is Forge** (`/forge`, four pages): a project, not part of the Hub, reached from artifacts links, with its own bar and theme system. It stays out until a Hub "side tools" module exists.

Rules:

- **No layout exemptions.** A rule that turns universal chrome off for one page type (3-pane, a reader, a map page) is the bug, not a feature. The 3-pane exemption keyed on the class existing anywhere in the DOM, so `/blueprints` (which renders 3-pane specimens) and phone `/news`, `/workbench` lost the sticky bar (2026-10-12).
- **Never restyle a universal element in module CSS.** Need it to differ? Change the shared file, for every page.
- **Guarded by the registry, not a hand list.** `tests/test_liquid_topbar_scroll.py` reads every module from `hub_modules.py`, so registering a module puts it under the check: the bar exists, is sticky, turns into the island when the page or a big pane scrolls, and comes back flush at the top; and every page has exactly one bar with back (not on home), brand, crumb, toggle, theme picker and modules, with no page script throwing.
- **Adding a new universal element:** build it in `topbar.jsx` (bar parts) or `theme-switch.js` (behavior, injected CSS), add its row here, and extend the registry-driven test.

## Motion

Timing and touch rules live in the vault node `wiki/patterns/apple-liquid-glass-pattern.md`, sections "Motion: expand and collapse mirror each other" and "Touch and motion": hover and press feedback is quick (about 100–250ms) and answers the press, not the release; anything that opens or closes plays the same motion both ways, a slower mirrored ease with no overshoot on anything that sizes a neighbour (the mail pane runs 620–680ms). Conveys state (hover, selection, reveal), never decorates. No page-load choreography — the Hub loads into a task. Every transition has a `prefers-reduced-motion: reduce` fallback.

## Absolute bans (inherited)

No side-stripe accent borders, gradient text, default glassmorphism, hero-metric templates, identical card grids, or per-section eyebrow/numbered scaffolding. These are the AI-slop tells the Hub explicitly avoids.
