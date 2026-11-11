# Dashboard Theming System — Design Spec

Status: draft for review · 2026-06-05 (rewritten for Hub 5002) · not committed (vault manual-commit rule)

**Design-first gate is in force: no dashboard code until this spec is approved.**

This is a full rewrite. The prior draft targeted the dead port-5001 lavender app and is discarded. Everything below targets the **Hub port-5002 dashboard** only.

## 1. Goal

Swap the whole Hub dashboard's look from a small library of saved themes, like a Minecraft resource pack: pick a theme `code`, the entire UI reskins instantly — no reload, no regeneration. Each theme ships **light (light) + dark (dark)** by reusing Vesper's existing light/dark axis. Switching is **non-destructive** (every theme is a saved file, no look is ever lost), and the **last-used theme persists** across sessions.

## 2. Target — Hub 5002 only

The system covers the **Hub app at `dashboard/hub/`** (Flask, port 5002). Surfaces in scope:

| Surface | File(s) | CSS today |
|---|---|---|
| **home** | `templates/index.html` (React/Babel; JSX in `static/js/*.jsx`) | `static/css/vesper.css` — primitives at `:root`, semantic tokens under `[data-surface]` |
| **jobs** | `jobs/frontend/jobs.html` | `jobs/frontend/static/jobs.css` — semantic tokens at `:root` (=dark) + `[data-surface="light"]` override |
| **login** | `templates/login.html` | in scope |
| **trips** | `trips/frontend/*.html` | `trips/frontend/static/{trips,trips-landing}.css` |
| **purchases** | `purchases/frontend/*.html` | `purchases/frontend/static/style.css` |
| **work** | `work/frontend/*.html` | `work/frontend/static/work.css` |
| **checklists** | `checklists/frontend/*.html` | `checklists/frontend/static/{base,style}.css` |
| **finances** | `finances/frontend/*.html` | `finances/frontend/static/finances.css` |
| **barback** | `barback/frontend/*.html` | `barback/frontend/static/barback.css` |
| **vault-map** | `vault_map/frontend/vault_map.html` | inline `<style>` in the HTML |

**Off-limits / dead:** the legacy **port-5001** app (`dashboard/frontend/` — hub, trips, purchases, the soft-lavender look) is complete dead legacy. It is **not** touched, restyled, or referenced by this system.

## 3. Binding architecture rules (user-stated, non-negotiable)

### Rule 1 — Every theme is frozen VERBATIM once created.

A finished theme is a CSS **file you never touch again**; it reapplies identically forever. A theme is never re-derived from extracted tokens (that drifts). One file per theme (`vesper.css` / `cobalt.css` / `atrium.css`), each a self-contained frozen skin. This reverses the earlier "one shared themes file" idea.

### Rule 2 — UX/UI changes propagate respectfully to all themes.

Dashboard markup, layout, and behavior live in **one shared, theme-agnostic layer** (the surface shells + their structural/component CSS, which reference only the token vocabulary for color and type). A structural change there reaches every theme at once. Each theme supplies only the **token values** (plus any genuinely bespoke flourish CSS) over that shared structure.

Honest limit: a genuinely **new component archetype** needing a bespoke per-theme flourish requires a one-line-per-theme pass. So the build bakes in a **"theme audit on new archetype"** step: when a new archetype lands, walk each theme file and confirm it's styled.

## 4. Roster (final — user-confirmed 2026-06-05)

Exactly **three** themes. Nothing outside this list is built.

| `code` | Name | Modes | How it's produced |
|---|---|---|---|
| `vesper` | Vesper | light + dark | **The `jobs.css` palette, for both modes.** Home and jobs had drifted into two palettes; the user picked the jobs palette from a visual comparison. The vesper theme = jobs values, and **home is rebuilt to match it** (the safe baseline). |
| `cobalt` | Cobalt | light + dark | Authored fresh in Vesper vocab, then frozen. Old draft values used the wrong vocab (`--text/--surface/--border`) — re-expressed and **re-confirmed against the brand on build**. |
| `atrium` | Atrium | light + dark | Same: authored fresh (Broadsheet editorial direction), re-expressed in Vesper vocab, re-confirmed on build. |
| `liquid` | Liquid Glass | light + dark | Added 2026-10-10 (`themes/liquid.css`, spec vault `docs/specs/2026-10-09-liquid-glass-blueprints-design.md`). Apple Liquid Glass: glass only on chrome (topbar, rail, launcher panel, detail panel, toast, QR sheet), every other piece solid Apple system surfaces, per-module wallpaper hue. Cards are the exception since 2026-11-10: translucent and tinted with the wallpaper hue, and in light mode faded from blue into indigo (the Game Hub slab, `liquid.css` section 16, `hub/DESIGN.md` "Card fill"); their blueprints carry layer `tinted`. Each blueprint's layer is `liquid_layer` (`glass` / `opaque` / `solid`) in `hub/blueprints/blueprints.json`. A stored `glass` theme maps to `liquid`; `:root[data-glass="frost"|"solid"]` (stored as `hub.glass`) is the Glass / Solid row in the picker, shown only under liquid; in Blink browsers Glass upgrades to `data-glass="refract"` (SVG lens maps on the bar, island, dock and drawer). **Frozen 2026-10-10** at `liquid.css?v=2` (Rule 1): a later change is a new theme or a new frozen version, never an in-place edit. |

**Live roster (2026-11-03):** `theme-switch.js` `THEMES = ["liquid", "cobalt"]`. Vesper was retired 2026-11-03: its file moved to `static/css/themes/archive/vesper.css` (linked by no page; restore by linking it back and re-adding the code to the roster, the head snippets and the mirror allowlists), and a stored `vesper` choice now opens liquid. Before that the roster was `["vesper", "cobalt", "liquid"]`, mirrored in every page's head snippet (`test_themes.py::test_theme_roster_matches`). Atrium was never shipped; the retired glass theme's `glass.css` was deleted 2026-10-17 (linked by no page); a stored `glass` choice now opens liquid. `/blueprints` shows only the active theme's version of each piece, with its layer badge (`theme_css` in `?resolved=1`).

Removed and **not** built: `classic` (Claude-invented), `press`, `riso`, `deco`, `botanica` (proposals the user declined 2026-06-05).

**No hard-coded default.** On load the dashboard applies the **last-used theme** (from storage). Cold start only — no prior choice stored — falls back to **`liquid`** (since 2026-10-12; before that `vesper`, then briefly `cobalt` in the page snippets). Every page head snippet and `setTheme`'s invalid-code fallback in `theme-switch.js` use `liquid`.

**Liquid is the primary theme (2026-10-12).** Every UI change is built for liquid first and verified under liquid in both light and dark before it ships; the other themes only have to stay unbroken. Module-level liquid fixes go in the module's own CSS scoped to `[data-theme="liquid"]`, never into the frozen `liquid.css` (Rule 1).

## 5. Token contract — Vesper's existing vocabulary

The contract is **Vesper's existing token names**, not a new invented vocabulary. Every Vesper surface already consumes these; a theme is the set of values bound to them per mode. Cobalt and atrium supply values for **these** names (re-expressing their old `--text/--surface/--border` palettes into this vocab).

**Color / semantic** (the names home and jobs share today):
```
--bg --bg-elev --bg-elev-2 --bg-hover
--line --line-soft --line-strong
--fg --fg-mute --fg-dim --fg-faint --fg-ghost
--chrome
--accent --accent-dim --accent-faint
--warn --warn-dim
--alert --alert-dim
--good --good-dim
--violet-label
```
**Home-only extras** (home references these; jobs does not — themes still supply them):
```
--panel-head-line --launch-scrim --modal-shadow --select-chevron --tomato --tomato-dim
--feat-display --feat-text --feat-meta --feat-tnum   /* font-feature-settings axes */
```
**Type families:** `--font` / `--font-display` (Cormorant Garamond) · `--font-body` (Fraunces).

**Mode-invariant structure** (lives once, not per theme/mode): `--r --r-card --r-pill`, `--s-1…--s-7`, `--status-h`, and surface layout knobs (`--funnel-w`, `--rail-w` on jobs).

A theme that omits a home-only extra simply lets home fall back; the build confirms each theme file covers the full set home actually reads so nothing renders unstyled.

## 6. Mechanism — `[data-theme] × [data-surface]`

Two independent axes on `<html>`:

- **`data-surface="light|dark"`** — the existing light/dark axis (already shipped; jobs uses it, home uses it). **Kept as-is.**
- **`data-theme="vesper|cobalt|atrium"`** — the new theme axis layered on top.

The semantic token values are supplied by the **theme files** at the cross of the two axes:

```css
/* vesper.css */
[data-theme="vesper"][data-surface="dark"] { --bg:#1a1f3a; --fg:#f4dcb0; … }
[data-theme="vesper"][data-surface="light"] { --bg:#fdf3df; --fg:#231848; … }
```

Surfaces (home, jobs, login) consume only `--bg`, `--fg`, … — they are blind to which theme/surface combination set them. Mode-invariant structure (spacing, radius, fonts) stays in a shared base so it isn't duplicated three times.

**Separate file per theme (Rule 1):** `vesper.css`, `cobalt.css`, `atrium.css`. Each is self-contained and loaded on every Hub page. A finished file is frozen.

**Switch logic — `theme-switch.js` (tiny, no deps), loaded on every page:**
- On load: read `localStorage` theme + surface; default theme = last-used, cold-start = `liquid` (§4); surface default = last-used / OS `prefers-color-scheme`. Set both attributes on `<html>`.
- `setTheme(code)` / `setSurface(m)` write the attribute and persist to `localStorage`.
- A 3-line inline head snippet on each page sets both attributes **before first paint** (no flash of unthemed content).

**Persistence:** `localStorage`, per-browser, instant. The last pick persists with no reset (explicit user requirement). Theme *definitions* live in the committed CSS files; cross-device active-choice sync is out of scope for v1.

## 7. Vesper theme definition — the jobs palette (canonical, both modes)

The `vesper` theme uses the **`jobs.css` values verbatim** for both modes. These are the canonical values (sourced from `jobs/frontend/static/jobs.css` `:root` = dark and `[data-surface="light"]`):

**DARK:**
```
--bg:#1a1f3a; --bg-elev:#232846; --bg-elev-2:#2a3052; --bg-hover:#2a3052;
--line:rgba(240,216,168,0.14); --line-soft:rgba(240,216,168,0.08); --line-strong:rgba(240,216,168,0.28);
--fg:#f4dcb0; --fg-mute:rgba(244,220,176,0.88); --fg-dim:rgba(244,220,176,0.72);
--fg-faint:rgba(244,220,176,0.48); --fg-ghost:rgba(244,220,176,0.24);
--chrome:#3a4878; --accent:#a4b3d8; --accent-dim:#8a9bc8; --accent-faint:#6a7ba8;
--warn:#e8cc88; --warn-dim:#b89858; --alert:#e07878; --alert-dim:#a05050;
--good:#a8c488; --good-dim:#789558; --violet-label:#b094d4;
```

**LIGHT:**
```
--bg:#fdf3df; --bg-elev:#f6e8c6; --bg-elev-2:#f0dba8; --bg-hover:#f6e8c6;
--line:rgba(58,48,104,0.16); --line-soft:rgba(58,48,104,0.08); --line-strong:rgba(58,48,104,0.32);
--fg:#231848; --fg-mute:rgba(35,24,72,0.84); --fg-dim:rgba(35,24,72,0.66);
--fg-faint:rgba(35,24,72,0.42); --fg-ghost:rgba(35,24,72,0.22);
--chrome:#b0a070; --accent:#3a4878; --accent-dim:#5a6898; --accent-faint:#8898c8;
--warn:#a87818; --warn-dim:#c89848; --alert:#a83838; --alert-dim:#c86868;
--good:#5a7825; --good-dim:#7a984a; --violet-label:#5a3878;
```

**Shared (jobs `:root`):** `--font`/`--font-display: "Cormorant Garamond","Fraunces",Georgia,serif`; `--font-body: "Fraunces",Georgia,serif`; `--r:2px; --r-card:4px; --r-pill:999px`; `--s-1…7: 4/8/12/16/20/24/32px`; `--status-h:36px`.

Home's home-only extras (`--feat-*`, `--panel-head-line`, `--launch-scrim`, `--modal-shadow`, `--select-chevron`, `--tomato`) are carried into the vesper theme so home keeps its typographic refinement; jobs ignores the ones it doesn't read.

## 8. Cobalt / Atrium

Authored fresh in **Vesper vocab** (§5 names), one frozen file each, both modes. Their prior draft palettes were written in the wrong vocabulary and are **not** locked here — they get re-expressed into Vesper vocab and their look **re-confirmed with the user at build time** (per [[wiki/patterns/communication-preferences]] and the "Claude suggestions ≠ user decisions" rule). Direction notes retained: cobalt = brutalist blue (square corners, thick borders, offset shadow flourish); atrium = Broadsheet editorial (Playfair display, crimson accent, hairline rules, no elevation). Dark palettes tuned for WCAG AA text contrast, then frozen.

## 9. Surface wiring

| Surface | Action |
|---|---|
| **jobs** (`jobs.css`) | Canonical palette **source** — values feed the vesper theme file. Jobs continues to consume `--bg/--fg/--line/…`; once the theme file supplies them at `[data-theme][data-surface]`, jobs' own `:root`/`[data-surface]` token blocks are replaced by the theme load (component/layout CSS in `jobs.css` stays). |
| **home** (`vesper.css`) | **Rebuilt to the jobs palette.** Home's surface-scoped semantic token blocks (`[data-surface="light"]`/`[data-surface="dark"]`) are replaced by consumption of the theme-supplied tokens, so home renders the jobs palette and matches jobs. Home's component/layout CSS and `--feat-*` typography stay. |
| **login** (`login.html`) | In v1. Same treatment — consume theme tokens so it reskins with home + jobs. |
| Theme picker | A small picker UI (route + control) lets the user choose a theme; renders a representative cutout per theme, click → `setTheme`, surface toggle re-skins in place. Built after the three themes exist. |

Net-new files: `vesper.css` / `cobalt.css` / `atrium.css` (theme files), `theme-switch.js` (apply/persist + no-flash snippet), and the picker page assets.

## 10. Scope — resolved

v1 surfaces: home + jobs + login (2026-06-05). **Extended 2026-07-08:** the `glass` theme's material treatment now covers all 8 remaining modules (trips, purchases, work, checklists, finances, barback, vault-map) (glass retired; `glass.css` deleted 2026-10-17, liquid replaced it). Cobalt/atrium remain home+jobs+login scope only unless separately extended.

## 11. Execution mode (on approval)

- **Subagent-driven** (superpowers `subagent-driven-development`), per handoff.
- **No git commits** — the vault manual-commit rule overrides any plan step that says to commit; leave the tree dirty.
- **No worktree** — the dashboard needs gitignored data/credentials in the main tree.
- After the vesper baseline is solid: re-confirm cobalt/atrium looks, then build them + the picker.

## 12. Build order (gated on approval)

1. Establish the `[data-theme]×[data-surface]` mechanism + shared mode-invariant base + `theme-switch.js` (no-flash snippet, last-used persistence, cold-start `vesper`).
2. Build **`vesper.css`** from the §7 jobs palette (both modes). Wire **jobs** to consume it (token blocks → theme), then **rebuild home** to consume it so home and jobs match. Verify home+jobs render identical palette in both modes.
3. Re-confirm + author **cobalt** and **atrium** (Vesper vocab, both modes, flourish), freeze each as its own file.
4. Build the picker; wire switching + persistence.
5. QA: every surface × every theme × mode — contrast (WCAG AA), focus states, status chips.

## 13. Before implementation, read

- `dashboard/CLAUDE.md` "Dashboard code standards" → `wiki/notes/dashboard-code-structure.md` + `wiki/notes/dashboard-code-quality-standards.md`.
- Consider `/onboard-domain`: a dashboard-wide theme layer + picker route + a new governance home may warrant infrastructure onboarding. Evaluate at build start.

## 14. Cleanup (on ship)

Migrate the design rationale into a `wiki/decisions/` node (likely via onboard-domain), log in `log/log.md`, delete the throwaway comparison artifact `docs/theme-compare.html`, the `.pending/` scratchpad, and the handoff.
