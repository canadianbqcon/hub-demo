# CLAUDE.md — dashboard/hub/jc/ (the Juniper & Co page)

Scoped rules for `/jc/`. Cross-module dashboard rules: `dashboard/CLAUDE.md`.

## What this module is

Since 2026-11-09 `/jc/` serves `frontend/barback.html`, a straight copy of the "Juniper & Co Bar Back" artifact (https://claude.ai/artifact/5AnPuUnsJuryqS91PoCft9): six tabs, open · close · batch prep · cocktails · map · stock, all data embedded in the page as `window.JC`. Sam asked for it to replace the old three-tab umbrella (Hub topbar, bar back from `barback/`, batch prep and map from `batch_prep/`), copied in as a page, not linked as an artifact. The old shell (`jc.html`, `jc.js`, `jc.css`) and its parity scenario were deleted; `git log` has them.

- **Served with `send_from_directory`, never `render_template`.** The file is the artifact's markup verbatim; running it through Jinja would break on any `{{` in its script.
- **State lives in the browser.** The page looks for `window.claude.use("db")`; the Hub does not provide one, so it runs its own local mode (localStorage under `jc:*`, sync chip reads "this device"). Phone and iPad do not share a board. The fix, if wanted, is a small shim that implements the `doc().update/set/onSnapshot` and `collection().add/orderBy().limit().onSnapshot` calls against a Hub endpoint.
- **Board saves per device, by choice.** Sam confirmed 2026-11-09 the page is his alone; no shared store wanted.
- **Hub top bar in J&Co colours (2026-11-09).** The artifact's own header was swapped for `<header class="topbar">` mounted by `topbar.jsx`, with the Hub head (fonts, base/components/theme CSS, React, `hub-modules.js`, `theme-switch.js`). Three page-specific rules hold it together:
  - The theme is **pinned to liquid (frost) + dark** in the head script, never read from `hub.theme`: a J&Co Liquid Glass (his call, 2026-11-09). The token block retints Liquid's wallpaper (`--lg-wall-base`, `--lg-hue-1..3`: juniper, brass, sea green) and glass fills (`--lg-fill`, `--lg-thick-fill`, `--lg-ov-fill`) juniper. The page `body` is transparent so the wallpaper shows, and the bar has no background of its own, so it renders as glass.
  - On phones the tab row's `top` is `--bar-b`, the bar's measured bottom edge. The Liquid bar is 56 or 64px tall depending on width and floats down about 10px for ~0.8s after a scroll, so it is measured on scroll, resize and the bar's `transitionend`.
  - One `html[data-theme][data-surface]` token block (specificity 0,2,1, above every theme's 0,2,0) sets the Hub tokens to juniper/brass/Special Elite and keeps the four names the Hub shares with the page (`--bg`, `--line`, `--line-strong`, `--r`) at the page's values.
  - On phones (≤719px) the Hub parks its controls in a bottom dock (`--dock-h`), so the page's tab row moves up to sit sticky under the bar instead of stacking two bars at the bottom.
  - The sync chip rides in the bar's right slot (`data-slot="right"`).
  - The bar spans the full window. The launcher is pinned to 44×44. The Hub sizes it as a bar-height square (`theme-switch.js`, `align-self:stretch` + `aspect-ratio:1`). With the bar in a plain block instead of a grid shell, the bar's height is not definite at layout time, so the button laid out at ~20px but drew at 51px and hung past the right edge (cut off, and a sideways scroll). The ledger had the same fault and was fixed by making its `.shell` a grid. The override needs the full `.launcher.launcher-icon.module-launcher` selector to outrank it. Checked clean at 390, 700, 800, 1024, 1440, 1920.
  - The Hub mark and "hub" wordmark are replaced by the J&Co sorrel (`static/sorrel.png`, extracted byte-for-byte from the artifact's own header image); the link still goes home. Selectors start `html .topbar` to outrank `theme-switch.js`'s injected sheet, which loads later.
- **No initials gate (2026-11-09, his ask).** The artifact's "Who is on?" screen, the initials chip and the per-row initials tags are gone; `state.who` is fixed to `BQ` so the event log and ice log still carry a name.
- **Week bar reads real shifts (2026-11-09).** The Open/Close day strip is an hour grid (2pm to 4am per day) fed by `GET /jc/api/shifts?from=&to=`, which reads J&Co rows of `earnings_scheduled_shifts` in `earnings.db` (filled by the calendar shift sync). The only server data the page reads; no shifts means every day shows "off". Neither Opening nor Closing has a steps meter any more (his call).
- **Content edits** (recipes, stock list, duties) go in `window.JC` inside `barback.html`. It no longer reads `work.db`, so edits made through the old `barback/` and `batch_prep/` data APIs do not show here.

`/barback/` and `/batch/` still 308 here; their modules, APIs and `work.db` tables are untouched but have no page of their own any more.

## Access posture

Reach `/jc/` over the private tailnet, never Tailscale Funnel: Funnel exposes all of port 5002 and would leak the jobs tracker.
