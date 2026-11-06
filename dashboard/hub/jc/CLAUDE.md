# CLAUDE.md — dashboard/hub/jc/ (the Juniper & Co umbrella page)

Scoped rules for the J&Co umbrella. For cross-module dashboard rules see `dashboard/CLAUDE.md`; it loads in addition to this file.

## What this module is

One page, route `/jc/`, three primary tabs — **bar back** (`#barback`), **batch prep** (`#batch`), **the map** (`#map`). Bar back leads and is the default tab (swapped with batch prep 2026-07-29 at Sam's request); `DEFAULT_TAB` in `jc.js` must stay in step with the first button in `#jcTabs`, and the panel that ships un-`hidden` in `jc.html` must be that same one, or the pre-JS paint shows the wrong section. Created 2026-07-29 by merging the two standalone J&Co boards, which until then were separate pages with separate chrome, the storage map buried as a third stop inside batch prep, and a one-way "Batch prep →" link out of barback with nothing pointing back.

This module owns **the shell and nothing else**: `jc.html` (the page), `static/jc.js` (the primary tab controller), `static/jc.css` (the tab bars and panels). It has no database, no data API and no business logic.

## The payload contract [BINDING]

Both payloads stay in their own modules — `batch_prep/` and `barback/` — and keep their own data APIs (`/batch/api/batch/*`, `/barback/api/barback/*`) and their own static assets, which this page links to directly. Nothing is duplicated here.

The **only** coupling between the shell and a payload is one event:

```js
document.dispatchEvent(new CustomEvent("jc:tab", { detail: { tab } }))
```

fired on every tab switch, plus `window.JcTabs.current()` for a payload that boots after the shell's first fire (both run off `DOMContentLoaded`, shell first — so a payload must read the live tab once at init as well as listen). That is how a panel hydrates lazily: `batch.js` loads the storage map on first `#map`, `barback.jsx` mounts on first `#barback` — which, now that bar back is the default tab, is on load for a hash-less `/jc/`, so today's opening run starts on page view. That is accepted: it is the landing surface. The laziness still earns its keep for a visit that deep-links `#batch` or `#map`, which never mounts barback at all. Do not reach into another panel's DOM, and do not add a second cross-module hook — extend the event.

## Uniformity rules [BINDING]

The whole point of the merge is that the three sections stop looking like three products. So:

- **One tab language, three legible levels.** `.jc-tabs` picks the section, `.jc-subtabs` picks the view inside it (batch: recipes/prep day; bar back: opening/closing/stock check — there, the sub-tab IS the run), and batch's existing `.recipe-tabs` pill picks drinks/preps below that. Each level must differ from its neighbours on **indicator shape**, not just size — level 1 underlines in the display face, level 2 fills a neutral (`--fg`) chip in small caps on an elevated strip, level 3 fills an accent pill. Two levels drawn as the same control at two font sizes do not read as a hierarchy (first cut did exactly that and Sam called it: "the tabs … are too similar"), and two levels both filled in `--accent` collide the same way. No bottom nav, no per-panel tab bar of its own invention.

- **The sticky stack is measured, never declared [BINDING].** Four layers pin in order — topbar, `.jc-tabs`, `.jc-subtabs`, batch's `.recipe-controls` — each offset by the summed height of the ones above. Those heights are **not** knowable as literals (the topbar is 88px on desktop and 67px on mobile; the display face changes with the theme), so `jc.js`'s `measure()` writes the real `getBoundingClientRect` heights into `--topbar-h` / `--jc-tabs-h` / `--jc-subtabs-h` on load, on resize, on tab switch and on `document.fonts.ready`. Do not replace them with constants. Two traps this page already fell into: a guessed `--topbar-h: 60px` against an 88px bar left a band of page scrolling through the gap above the tab bar, and `html,body { height:100% }` (in `batch.css`) capped `<body>`'s box at one viewport so every sticky *direct child of body* silently stopped sticking past 100vh while deeper sticky elements kept working. It is `min-height` now — do not put it back.

- **The topbar is sticky here and only here.** The Hub's shared `.topbar` is `position:static` on every page; `jc.css` overrides it because this is the only page with a sticky stack underneath that depends on it staying put. Making it sticky globally is a change to every other surface — not in scope unless asked.
- **The shell owns all chrome.** Topbar, crumb, surface toggle, theme picker and module launcher are the global vanilla ones (`theme-switch.js`). A panel must not render its own copy — barback used to, in React, and that duplication was the single loudest source of the two surfaces feeling unrelated.
- **A payload stylesheet may not style the document.** `batch.css` and `barback.css` share one page now. No bare `body`, `*` or element selectors in either; scope to the panel or to the module's own classes. Barback's old `body { font: … }` reset would have restyled the other two sections out from under them.

## Access posture

Same as the surfaces it replaced: reach `/jc/` over the private tailnet, never Tailscale Funnel — Funnel exposes all of port 5002 and would leak the jobs tracker.
