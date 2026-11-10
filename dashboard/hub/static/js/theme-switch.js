/* hub theme switch — loaded (defer) by every hub page, before topbar.jsx.
   Owns data-theme, data-surface and data-glass on <html>. The no-flash inline
   snippet (in each <head>) has ALREADY set them before first paint; this file
   wires runtime changes and exposes the API the top bar renders against
   (window.HubTheme, window.HubBack). It also injects the bar's stylesheet, holds
   the liquid scroll island and builds the refract lenses.

   It draws no controls. The bar, light/dark, theme picker, back and modules
   launcher are one React component in topbar.jsx (2026-10-12); the DOM-building
   copies that used to live here were its twin and are gone. */
(() => {
  var THEME_KEY = "hub.theme";
  /* glass is retired (glass.css deleted 2026-10-17); a stored "glass"
     now maps to liquid in current() and setTheme(). */
  var THEMES = ["liquid", "cobalt"];  /* vesper retired 2026-11-03; a stored vesper opens liquid */
  /* liquid's frost | solid level, stored apart from the theme. data-glass on
     <html> exists only while the theme is liquid. */
  var GLASS_KEY = "hub.glass";
  /* the slogan under the "hub" wordmark flavors with the active theme */
  var THEME_SLOGANS = { cobalt: "build loud." };
  var root = document.documentElement;

  function sloganFor(code) { return THEME_SLOGANS[code] || ""; }

  function current() {
    var t = root.getAttribute("data-theme");
    if (t === "glass") t = "liquid";
    return THEMES.indexOf(t) >= 0 ? t : "liquid";
  }
  function getGlass() {
    try { return localStorage.getItem(GLASS_KEY) === "solid" ? "solid" : "frost"; } catch { return "frost"; }
  }
  /* rung 3 bends the backdrop through an SVG lens, which only Blink honours inside
     backdrop-filter. Every iPhone browser is WebKit (CriOS included), and WebKit and Gecko drop
     the whole url() declaration, so they stay on frost. Checked before userAgentData because an
     overridden UA keeps Chromium's brands. */
  function blink() {
    var ua = navigator.userAgent;
    if (/iPhone|iPad|iPod|CriOS/.test(ua)) return false;
    var d = navigator.userAgentData;
    return d && d.brands ? d.brands.some(function (b) { return b.brand === "Chromium"; }) : /Chrome\/\d/.test(ua);
  }
  function applyGlass() {
    var g = getGlass();
    if (current() === "liquid") root.setAttribute("data-glass", g === "frost" && blink() ? "refract" : g);
    else root.removeAttribute("data-glass");
    // entering refract mid-session: the observer only fires on resize, so build lenses for the
    // already-tagged elements now, or their url(#lg-lens-*) points at nothing.
    if (root.getAttribute("data-glass") === "refract")
      document.querySelectorAll("[data-lens]").forEach(function (el) { scheduleLens(el.dataset.lens, el); });
  }
  function setGlass(level) {
    level = level === "solid" ? "solid" : "frost";
    try { localStorage.setItem(GLASS_KEY, level); } catch {}
    applyGlass();
  }
  function setTheme(code) {
    if (code === "glass") code = "liquid";
    if (THEMES.indexOf(code) < 0) code = "liquid";
    root.setAttribute("data-theme", code);
    applyGlass();
    try { localStorage.setItem(THEME_KEY, code); } catch {}
    document.dispatchEvent(new CustomEvent("hub:themechange", { detail: { theme: code } }));
  }

  /* A live theme switch needs no fetch at all: every page head loads one
     same-origin stylesheet declaring BOTH themes' faces, and an @font-face
     downloads only when a rule uses the family. The old ensureFonts() —
     window.HUB_FONTS plus a Google Fonts <link> injected on the flip — went with
     the last page to be self-hosted (2026-08-29). See static/vendor/fonts/. */

  /* read a theme's signature colors off a probe element that is not in the
     rendered page.

     It used to flip <html>'s data-theme, read the tokens off :root and flip back
     within the turn. That restyled the whole document twice per call, and since
     the theme files set --font it also started a download of the INACTIVE
     theme's webfonts on every page load — the exact waste that loading one
     theme's faces exists to avoid. The theme rules are plain [data-theme="x"]
     selectors, not :root-scoped, so a display:none div carrying both attributes
     resolves the same tokens while nothing on the page moves.

     The color tokens only resolve under [data-theme=X][data-surface=Y], so the
     probe mirrors the LIVE surface. An unauthored theme (no CSS rules yet) has
     --bg come back empty → authored:false drives the "soon" state. */
  var probeEl = null;
  function probe() {
    if (!probeEl?.isConnected) {
      probeEl = document.createElement("div");
      probeEl.style.display = "none";   // custom properties still resolve; no layout
      (document.body || root).appendChild(probeEl);
    }
    return probeEl;
  }
  function readColors(code) {
    var el = probe();
    el.setAttribute("data-theme", code);
    el.setAttribute("data-surface", root.getAttribute("data-surface") || "dark");
    var cs = getComputedStyle(el);
    var c = {
      accent: cs.getPropertyValue("--accent").trim(),
      bg: cs.getPropertyValue("--bg").trim(),
      fg: cs.getPropertyValue("--fg").trim()
    };
    c.authored = !!c.bg;
    return c;
  }
  function meta() {
    var m = {};
    for (let i = 0; i < THEMES.length; i++) m[THEMES[i]] = readColors(THEMES[i]);
    return m;
  }

  /* ---- injected picker stylesheet (token-based, one source for both pickers) ---- */
  function injectCss() {
    if (document.getElementById("hub-theme-picker-css")) return;
    var css =
      ".theme-picker{position:relative;display:inline-flex;font-family:var(--font-body);}" +
      ".theme-picker-btn{display:inline-flex;align-items:center;gap:var(--s-2);" +
        "padding:6px 10px;border:1px solid var(--line);border-radius:var(--r-card);" +
        "background:transparent;font-family:var(--font-body);font-feature-settings:var(--feat-meta);" +
        "font-size:var(--fs-footnote);letter-spacing:0.06em;color:var(--fg-dim);text-transform:lowercase;cursor:pointer;" +
        "transition:border-color 120ms ease-out,color 120ms ease-out,background 120ms ease-out;}" +
      ".theme-picker-btn:hover{border-color:var(--accent-dim);color:var(--fg);background:var(--bg-elev);}" +
      ".theme-picker-caret{font-size:var(--fs-caption);opacity:0.7;margin-left:1px;}" +
      ".theme-swatch{width:11px;height:11px;border-radius:var(--r-pill);border:1px solid var(--line-strong);" +
        "box-sizing:border-box;flex:0 0 auto;background:var(--accent);}" +
      ".theme-picker-menu{position:absolute;top:calc(100% + 6px);right:0;z-index:1100;min-width:148px;" +
        "display:flex;flex-direction:column;padding:4px;gap:2px;background:var(--bg-elev);" +
        "border:1px solid var(--line);border-radius:var(--r-card);box-shadow:var(--modal-shadow);}" +
      ".theme-picker-opt{display:flex;align-items:center;gap:var(--s-2);width:100%;" +
        "padding:7px 9px;border:0;border-radius:var(--r);background:transparent;cursor:pointer;" +
        "font-family:var(--font-body);font-size:var(--fs-footnote);letter-spacing:0.05em;color:var(--fg-dim);" +
        "text-transform:lowercase;text-align:left;transition:background 100ms ease-out,color 100ms ease-out;}" +
      ".theme-picker-opt:hover:not(.is-disabled){background:var(--bg-hover);color:var(--fg);}" +
      ".theme-picker-opt.is-active{color:var(--fg);}" +
      ".theme-picker-optname{flex:1 1 auto;}" +
      ".theme-picker-check{color:var(--accent);font-size:var(--fs-footnote);}" +
      ".theme-picker-soon{font-size:var(--fs-caption);letter-spacing:0.1em;color:var(--fg-faint);" +
        "border:1px solid var(--line);border-radius:var(--r-pill);padding:1px 5px;text-transform:uppercase;}" +
      ".theme-picker-opt.is-disabled{cursor:default;opacity:0.6;}" +
      ".theme-picker-opt.is-disabled .theme-swatch{background:var(--bg-elev-2);}" +
      ".theme-picker-glass{display:flex;align-items:center;justify-content:space-between;gap:var(--s-2);" +
        "margin-top:2px;padding:7px 9px 4px;border-top:1px solid var(--line-soft);" +
        "font-size:var(--fs-footnote);letter-spacing:0.05em;color:var(--fg-dim);text-transform:lowercase;}" +
      ".theme-picker-glass-btn{padding:2px 8px;border:1px solid var(--line);border-radius:var(--r-pill);" +
        "background:transparent;font-family:var(--font-body);font-size:var(--fs-caption);letter-spacing:0.05em;" +
        "color:var(--fg-dim);text-transform:lowercase;cursor:pointer;}" +
      ".theme-picker-glass-btn[aria-pressed=true]{color:var(--accent);border-color:var(--accent-dim);}" +
      /* control pane (topbar.jsx ControlPane): sectioned panel off the gear. Two
         classes on the menu so it outranks each theme's .theme-picker-menu width. */
      ".theme-picker-menu.control-pane-menu{width:300px;min-width:0;max-width:calc(100vw - 20px);box-sizing:border-box;" +
        "padding:14px;gap:12px;}" +
      ".cp-row{display:flex;align-items:center;justify-content:space-between;gap:var(--s-3);}" +
      ".cp-col{flex-direction:column;align-items:stretch;gap:8px;}" +
      ".cp-lbl{font-size:var(--fs-footnote);letter-spacing:0.08em;text-transform:uppercase;color:var(--fg-faint);}" +
      ".cp-seg{display:inline-flex;gap:2px;padding:3px;border-radius:var(--r-card);background:var(--bg-elev-2);}" +
      ".cp-seg-i{height:32px;padding:0 12px;border:0;border-radius:var(--r);background:transparent;cursor:pointer;" +
        "font-family:var(--font-body);font-size:var(--fs-footnote);color:var(--fg-dim);text-transform:lowercase;white-space:nowrap;}" +
      ".cp-seg-i:hover{color:var(--fg);}" +
      ".cp-seg-i[aria-pressed=true]{background:var(--bg);color:var(--fg);box-shadow:0 1px 3px rgb(0 0 0 / .18);}" +
      ".cp-themes{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;}" +
      ".cp-theme{display:flex;flex-direction:column;align-items:center;gap:6px;padding:10px 4px;border:1px solid var(--line);" +
        "border-radius:var(--r-card);background:transparent;cursor:pointer;font-family:var(--font-body);font-size:var(--fs-footnote);" +
        "color:var(--fg-dim);text-transform:lowercase;}" +
      ".cp-theme:hover:not(:disabled){color:var(--fg);background:var(--bg-hover);}" +
      ".cp-theme:disabled{cursor:default;opacity:0.5;}" +
      ".cp-theme .theme-swatch{width:20px;height:20px;}" +
      ".cp-theme.is-active{border-color:var(--accent);color:var(--fg);box-shadow:0 0 0 1px var(--accent);}" +
      ".cp-out-form{display:block;margin:0 -14px -14px;}" +
      ".cp-out{display:block;width:100%;padding:12px 14px;border:0;border-top:1px solid var(--line);background:transparent;" +
        "cursor:pointer;text-align:left;font-family:var(--font-body);font-size:var(--fs-subhead);color:var(--fg-dim);text-transform:lowercase;}" +
      ".cp-out:hover{color:var(--fg);background:var(--bg-hover);}" +
      ".control-pane-btn[aria-expanded=true]{color:var(--accent);border-color:var(--accent);}" +
      /* phone: the pane hangs off liquid's dock, which already blurs, and a
         backdrop-filter nested inside another one blurs nothing. The glass fill
         alone let the status strip read straight through the pane. */
      '@media (max-width:640px){[data-theme="liquid"] .theme-picker-menu.control-pane-menu{background:var(--bg-elev);}}';
    var el = document.createElement("style");
    el.id = "hub-theme-picker-css";
    el.textContent = css;
    document.head.appendChild(el);
  }

  /* ---- injected universal stylesheet — the ENTIRE topbar plus the controls, so
     every hub page renders one identical bar that can NEVER drift (it used to:
     each page redefined the brand/crumb sizes in its own CSS — home 36px, jobs
     38px, batch 19px). Now the full layout lives here, token-based, one source.
     Injected after each page's own stylesheet so it wins; page CSS must NOT
     redefine the topbar, brand, or crumb selectors. Canonical = home reference. ---- */
  function injectUniversalCss() {
    if (document.getElementById("hub-universal-css")) return;
    var css =
      /* iPhone notch and home bar, one place (2026-11-07). The home-screen app draws
         under the status bar (black-translucent, app.py), so phone chrome pads by
         these. Tokens, not env() at each use: the desktop phone view (topbar.jsx)
         sets them to an iPhone's 47/34 so it shows what the phone really does. */
      ":root{--safe-t:env(safe-area-inset-top,0px);--safe-b:env(safe-area-inset-bottom,0px);}" +
      /* ---- full topbar layout: brand lockup (left) + page crumb (right) ---- */
      /* min-width:0 is load-bearing, not tidiness. Every module wraps its page
         in a `.shell` grid, and a grid item's automatic minimum size is its
         MIN-CONTENT — so a long crumb sized the shell's only column to the
         bar's min-content and the whole document scrolled sideways on a phone
         (/food/brooklyn-nyc: a 495px document in a 360px viewport). The crumb
         already knows how to ellipsise; without this it never got the chance. */
      ".topbar{display:flex;align-items:center;justify-content:space-between;min-width:0;" +
        "padding:var(--s-2) var(--s-4) var(--s-2) var(--s-5);border-bottom:1px solid var(--line);" +
        "background:var(--bg);min-height:56px;}" +
      ".topbar-l{display:flex;align-items:center;gap:var(--s-5);min-width:0;}" +
      /* ONE height for every control in the bar (back, light/dark, theme, modules,
         sign-out). They used to size themselves from padding + their own font, so
         four fonts gave four heights. --ctl-h is the single source; the phone
         breakpoint below raises it to a 40px touch target. */
      ".topbar-r,.topbar-l{--ctl-h:32px;}" +
      /* universal back control — an edge TAB, not a boxed button (rig decision
         2026-09-03, option C). It is the bar's own left edge: full bar height,
         flush with the viewport, raised ground, one rule on its right; the bar
         drops its left padding on any page that carries it so the tab sits at
         x=0 and the wordmark starts after it. Square regardless of theme radius. */
      ".topbar:has(.hub-back){padding-left:0;}" +
      ".hub-back{display:inline-flex;align-items:center;justify-content:center;align-self:stretch;" +
        "width:44px;margin:calc(var(--s-2) * -1) 0;flex:none;padding:0;border:0;border-right:1px solid var(--line);" +
        "border-radius:0;background:var(--bg-elev);color:var(--fg-dim);" +
        "font-family:var(--font-display);font-size:var(--fs-body);line-height:1;cursor:pointer;" +
        "transition:background 150ms ease-out,color 150ms ease-out,border-color 150ms ease-out;}" +
      ".hub-back:hover{background:var(--accent);color:var(--on-accent);border-right-color:var(--accent);}" +
      ".topbar-l .hub-back+.brand-stack{margin-left:calc(var(--s-4) - var(--s-5));}" +
      ".brand-stack{display:flex;flex-direction:column;gap:2px;line-height:1;}" +
      ".brand-link{text-decoration:none;color:inherit;cursor:pointer;}" +
      /* margin:0 is load-bearing, not tidiness: the wordmark is an <h1> and the
         shared layer zeroes no UA margins, so without it the browser's 0.67em
         top and bottom made the bar 86px on any page whose own CSS did not
         happen to reset h1 (/work did not). Twin of the rule in chrome.css. */
      ".brand-wordmark{margin:0;font-family:var(--font-display);font-feature-settings:var(--feat-display);" +
        "font-weight:400;font-size:var(--fs-title);letter-spacing:0.04em;color:var(--fg);text-transform:lowercase;line-height:1;}" +
      ".brand-slogan{font-family:var(--font-display);font-feature-settings:var(--feat-meta);font-style:italic;" +
        "font-weight:400;font-size:var(--fs-caption);letter-spacing:0.06em;color:var(--accent);text-transform:lowercase;line-height:1;}" +
      /* brand mark — the hub tile sits to the LEFT of the wordmark+slogan lockup.
         The lockup's <a> is itself the column (.brand-stack.brand-link), so the
         mark rides as an absolutely-positioned ::before with a padding
         reservation: no wrapper element. The SVG carries its own blue
         field + white glyph, so it is theme-independent. */
      /* 32px is not a taste call: the glyph is drawn on a 4-unit grid in a 64
         box and goes soft at any size where that grid misses whole pixels (34
         and 40 both did). 32 is half scale, so every edge lands on a device
         pixel at 1x and the tile is 1:1 at 2x. Change only to another multiple
         of 16. */
      ".brand-stack.brand-link{position:relative;padding-left:calc(32px + var(--s-3));}" +
      ".brand-stack.brand-link::before{content:\"\";position:absolute;left:0;top:50%;" +
        "transform:translateY(-50%);width:32px;height:32px;border-radius:7px;" +
        "background:url(/static/assets/brand-mark.svg) center/contain no-repeat;}" +
      ".crumb-block{display:flex;flex-direction:column;gap:3px;min-width:0;padding-left:var(--s-4);" +
        "border-left:1px solid var(--line);margin-left:var(--s-3);}" +
      ".crumb{font-family:var(--font-display);font-feature-settings:var(--feat-display);font-weight:500;" +
        "font-size:var(--fs-body);color:var(--fg);letter-spacing:0.02em;text-transform:lowercase;line-height:1;" +
        "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}" +
      /* second crumb line — a live count or status under the page name. Twin of
         the rule in chrome.css; line-height:1 is what keeps it inside the 56px bar. */
      ".crumb-meta{font-family:var(--font-body);font-feature-settings:var(--feat-meta);font-style:italic;" +
        "font-size:var(--fs-footnote);line-height:1;color:var(--fg-dim);letter-spacing:0.01em;white-space:nowrap;}" +
      ".crumb-meta .sep{color:var(--fg-ghost);margin:0 6px;font-style:normal;}" +
      ".topbar-r{display:flex;align-items:center;gap:var(--s-2);position:relative;flex-shrink:0;}" +
      /* PHONE TOP BAR — rig decision E (2026-09-20, built 2026-09-23). The bar
         is identity only: back tab, mark, page name, one 48px row. Every control
         leaves it for a dock fixed to the bottom edge, in a fixed order (modules,
         light/dark, theme, trip access, then the page's own action pushed right).
         The old two-row bar spent 89px on itself, and 118px on /apply and /trips,
         where the extra button knocked the controls onto a third row. Half-screen
         and desktop are untouched: this whole block is phone-only. */
      "@media (max-width:640px){.topbar{flex-wrap:nowrap;gap:var(--s-3);box-sizing:border-box;" +
          "height:calc(48px + var(--safe-t));min-height:calc(48px + var(--safe-t));" +
          "padding:var(--safe-t) var(--s-4) 0;}" +
        ".topbar-l{flex:1 1 auto;min-width:0;gap:var(--s-3);}" +
        ".brand-wordmark,.brand-slogan,.crumb-meta{display:none;}" +
        /* the mark alone: the ::before sits in the padding, so the box is just its 32px */
        ".brand-stack.brand-link{padding-left:32px;min-height:32px;flex:none;}" +
        ".topbar-l .hub-back+.brand-stack{margin-left:0;}.hub-back{margin:0;}" +
        ".crumb-block{flex:1 1 auto;min-width:0;padding-left:0;margin-left:0;border-left:0;}" +
        /* the dock. position:relative is dropped for fixed, which still anchors
           the menus that hang off .topbar-r, so they only have to open upward. */
        ".topbar-r{--ctl-h:40px;position:fixed;left:0;right:0;bottom:0;z-index:1050;" +
          "height:calc(56px + var(--safe-b));padding:0 var(--s-3) var(--safe-b);" +
          "background:var(--bg-elev);border-top:1px solid var(--line);gap:var(--s-2);}" +
        "body{padding-bottom:calc(56px + var(--safe-b));}" +
        /* scrollIntoView and #anchor jumps land under the dock without this
           (a focused /apply row on phone Back sat fully behind it, 2026-09-25) */
        "html{scroll-padding-bottom:calc(56px + var(--safe-b));}" +
        /* right-handed: whatever the page added (+ new) and sign-out
           (its order:99 from the rule below) on the left, a spacer, then the chrome
           under the right thumb in desktop order (light/dark, theme, modules). */
        ".topbar-r>*{order:6;}.topbar-r>.module-launcher{order:104;}.topbar-r>.theme-picker{order:103;}" +
        ".topbar-r>.surface-toggle{order:102;}" +
        '.topbar-r::after{content:"";order:100;flex:1 1 auto;}' +
        ".topbar-r .theme-picker-menu{top:auto;bottom:calc(100% + 6px);left:auto;right:0;}" +
        /* glyphs, not words: the theme's own name costs ~70px of a 390px dock */
        ".theme-picker-label{display:none;}.theme-picker-btn{padding-left:9px;padding-right:9px;}}" +
      /* light/dark toggle: ICON form everywhere (☾/☀), rendered by topbar.jsx */
      ".surface-toggle,.theme-picker-btn,.launcher{height:var(--ctl-h);box-sizing:border-box;padding-top:0;padding-bottom:0;}" +
      /* modules: a drawn 2x2 grid at every size (topbar.jsx). 1 unit = 1px and 1px
         strokes on .5 coords, so every edge lands on a whole pixel; 16px of ink */
      ".launcher.module-launcher{width:var(--ctl-h);justify-content:center;padding-left:0;padding-right:0;}" +
      ".launcher-g.module-g{width:18px;height:18px;stroke-width:1;}" +
      /* modules fills the bar's height less one gap (--mod-g) above, below and to the
         right, so it never grows the bar and sits concentric with liquid's rounded
         island end (2026-10-17). It stretches to the content box, then the negative
         block margin eats the bar's padding down to the gap; --bar-py is that
         padding (liquid.css sets its own). 0,4,0 beats liquid's square-icon widths.
         Not in the phone dock: there it stays a dock control. */
      "@media (min-width:641px){" +
        ".topbar{--mod-g:12px;--bar-py:var(--s-2);padding-right:var(--mod-g);}" +
        ".topbar-r{align-self:stretch;}" +
        /* last in the bar, after sign-out's order:99, so the gap is to the bar's edge */
        ".topbar-r>.module-launcher{order:100;}" +
        ".topbar .launcher.launcher-icon.module-launcher{align-self:stretch;height:auto;width:auto;aspect-ratio:1;" +
          "margin-block:calc(var(--mod-g) - var(--bar-py));}}" +
      /* cobalt's 641-900 bar is 57px: a 12px gap left a 32px button beside 40px controls */
      '@media (min-width:641px) and (max-width:900px){:root:not([data-theme="liquid"]) .topbar{--mod-g:6px;}}' +
      /* DESKTOP BAR SIZE (cobalt): 76px bar, 44px controls, 48px mark (a
         multiple of 16, see the mark note above). Twin of the liquid block in
         liquid.css, which sizes its own bar. From 901 up only: narrower, these
         sizes cut the crumb to "che…". :root:not(liquid) lifts it over the
         plain-class rules later in this sheet and keeps it off liquid. */
      "@media (min-width:901px){" +
        ':root:not([data-theme="liquid"]) .topbar{min-height:76px;}' +
        ':root:not([data-theme="liquid"]) :is(.topbar-r,.topbar-l){--ctl-h:44px;}' +
        ':root:not([data-theme="liquid"]) .hub-back{width:56px;font-size:var(--fs-title);}' +
        ':root:not([data-theme="liquid"]) .brand-wordmark{font-size:var(--fs-large-title);}' +
        ':root:not([data-theme="liquid"]) .crumb{font-size:var(--fs-title);}' +
        ':root:not([data-theme="liquid"]) .crumb-meta{font-size:var(--fs-subhead);}' +
        ':root:not([data-theme="liquid"]) .brand-stack.brand-link{padding-left:calc(48px + var(--s-3));min-height:48px;}' +
        ':root:not([data-theme="liquid"]) .brand-stack.brand-link::before{width:48px;height:48px;border-radius:10px;}' +
        ':root:not([data-theme="liquid"]) .topbar :is(.surface-toggle,.theme-picker-btn,.launcher){padding-left:14px;padding-right:14px;font-size:var(--fs-subhead);}' +
        ':root:not([data-theme="liquid"]) .topbar :is(.surface-toggle-icon,.launcher-icon){padding:0;}' +
        ':root:not([data-theme="liquid"]) .topbar .surface-ico{font-size:var(--fs-body);}' +
        '}' +
      /* sign-out sits at the far right of the cluster, after modules */
      '.topbar-r [title="sign out"]{order:99;}' +
      ".surface-toggle{display:inline-flex;align-items:center;gap:var(--s-2);padding:6px 10px;" +
        "border:1px solid var(--line);border-radius:var(--r-card);background:transparent;" +
        "font-family:var(--font-body);font-feature-settings:var(--feat-meta);font-size:var(--fs-footnote);" +
        "letter-spacing:0.06em;color:var(--fg-dim);text-transform:lowercase;cursor:pointer;" +
        "transition:border-color 120ms ease-out,color 120ms ease-out,background 120ms ease-out;}" +
      ".surface-toggle:hover{border-color:var(--accent-dim);color:var(--fg);background:var(--bg-elev);}" +
      /* square, and a hard box: the sun glyph renders as a colour EMOJI on phones
         (iOS/Android substitute the emoji font for U+2600), which is far wider and
         taller than the moon and shoved the whole bar into a second row the moment
         you switched to light. The glyph now carries U+FE0E (text presentation) and
         the button no longer sizes to its content, so neither state can move it. */
      ".surface-toggle-icon{width:var(--ctl-h);padding:0;justify-content:center;overflow:hidden;}" +
      ".surface-ico{font-size:var(--fs-subhead);line-height:1;display:inline-block;font-variant-emoji:text;}" +
      /* icon-only launcher (the trips account link): same square box as the
         surface toggle, stroke glyph on currentColor like the fnav glyphs. */
      ".launcher-icon{width:var(--ctl-h);padding:0;justify-content:center;}" +
      ".launcher-g{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;}" +
      /* modules button (opens the box-cutout) */
      ".launcher{display:inline-flex;align-items:center;gap:var(--s-2);padding:6px 12px;" +
        "border:1px solid var(--line);border-radius:var(--r-card);background:transparent;" +
        "font-family:var(--font-body);font-feature-settings:var(--feat-meta);font-size:var(--fs-footnote);" +
        "letter-spacing:0.04em;color:var(--accent);text-transform:lowercase;cursor:pointer;" +
        "text-decoration:none;" +
        "transition:background 120ms ease-out,border-color 120ms ease-out,color 120ms ease-out;}" +
      ".launcher:hover{border-color:var(--accent-dim);background:var(--bg-elev);color:var(--fg);}" +
      /* the box-cutout grid modal */
      ".launch-scrim{position:fixed;inset:0;background:var(--launch-scrim);display:flex;" +
        /* 1200: above Leaflet's control layer (1000) so maps never paint over the modules popup */
        "align-items:flex-start;justify-content:center;padding-top:96px;padding-bottom:var(--s-4);" +
        "z-index:1200;backdrop-filter:blur(3px);}" +
      /* max-height + overflow-y at EVERY size, which the phone arm below has
         always had and the card never did. The card was sized by its tiles and
         clipped by overflow:hidden, so growing the launcher from 11 tiles to 13
         put the foot 29px past the fold at 1440x900 and the whole UTILITIES tier
         past it at 1024x768 — unreachable, because a fixed scrim gives nothing
         to scroll. Same failure the phone overlay was built to fix, arriving on
         the desktop side; chrome.css named this as the fix if it ever mattered.
         100% resolves against the scrim's content box, so the padding above and
         below is the card's breathing room and no viewport maths is duplicated. */
      ".launch-panel{width:min(720px,92vw);background:var(--bg-elev);border:1px solid var(--line-strong);" +
        "border-radius:var(--r-card);max-height:100%;overflow-y:auto;overflow-x:hidden;" +
        "box-shadow:var(--modal-shadow);}" +
      /* pinned so the title and the count stay put while the tiers scroll under
         them — the phone arm already did this; the card needs it for the same
         reason now that it scrolls. */
      ".launch-head{display:flex;align-items:baseline;justify-content:space-between;padding:var(--s-4);" +
        "border-bottom:1px solid var(--line);position:sticky;top:0;z-index:1;background:var(--bg-elev);}" +
      ".launch-head .lbl{font-family:var(--font-display);font-feature-settings:var(--feat-display);font-weight:500;font-size:var(--fs-title);color:var(--fg);" +
        "letter-spacing:0.02em;text-transform:lowercase;}" +
      ".launch-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line-soft);padding:1px;}" +
      ".launch-tile{display:flex;flex-direction:column;gap:var(--s-2);padding:var(--s-5) var(--s-4);" +
        "background:var(--bg-elev);border:0;text-align:left;cursor:pointer;transition:background 120ms ease-out;}" +
      /* hover = the "select the module" gesture: quiet hard-stop diagonal fill;
         cobalt.css overrides with its brutalist version. mirror of chrome.css. */
      ".launch-tile:hover{background:linear-gradient(135deg,var(--accent-faint) 50%,var(--bg-elev-2) 50%);}" +
      ".launch-tile.is-current{cursor:default;}" +
      /* tiered launcher — twin of chrome.css */
      ".launch-tier + .launch-tier{border-top:1px solid var(--line);}" +
      ".tier-label{font-family:var(--font-body);font-feature-settings:var(--feat-meta);font-weight:500;" +
        "font-size:var(--fs-caption);letter-spacing:0.18em;text-transform:uppercase;color:var(--fg-faint);padding:var(--s-4) var(--s-4) var(--s-2);}" +
      ".launch-grid.tier-home{grid-template-columns:1fr;}" +
      ".launch-tile.tile-home{flex-direction:row;align-items:center;justify-content:space-between;}" +
      ".launch-tile.tile-home .tile-name{font-size:var(--fs-large-title);}" +
      ".launch-tile.tile-home .tile-arrow{font-family:var(--font-body);font-size:var(--fs-title);color:var(--accent);line-height:1;}" +
      /* glyph + name on one line (treatment C) — twin of chrome.css. 20px is fixed
         everywhere including the wide home tile: the 1.2n+0.6 stroke grid the marks
         are drawn on only lands on whole pixels at 20px and 60px. */
      ".launch-tile .tile-row{display:flex;align-items:center;gap:var(--s-3);}" +
      ".launch-tile .tile-glyph{flex:0 0 auto;width:20px;height:20px;color:var(--fg-faint);" +
        "stroke:currentColor;fill:none;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round;" +
        "transition:color 120ms ease-out;}" +
      ".launch-tile:hover .tile-glyph{color:var(--fg-dim);}" +
      ".launch-tile .tile-name{font-family:var(--font-display);font-feature-settings:var(--feat-display);font-weight:500;font-size:var(--fs-title);color:var(--fg);" +
        "letter-spacing:0.02em;text-transform:lowercase;}" +
      /* phone-only dismiss; hidden on desktop, where the scrim gap and Escape
         already close the launcher. */
      ".launch-close{display:none;}" +
      /* ---- phone: the launcher becomes a full-bleed overlay ----
         As a floating card it did not fit. Ten to eleven tiles at two columns build
         a 1070-1190px panel, the scrim pinned its top 64px down inside an 844px
         viewport, and nothing scrolled: .launch-panel is overflow:hidden and a
         position:fixed scrim with visible overflow gives the user no way to reach
         what hangs below, so the bottom tier (vault-map) and the foot were simply
         unreachable on a phone. Now the panel IS the viewport and scrolls inside
         itself with the head pinned — same idiom as hub-slide-over.
         The max-height arm is the same bug from the other side: an iPhone in
         landscape is 844px WIDE, so a width-only query left it on the floating
         card in a 390px-tall viewport, still hanging 401px past the fold. 500px
         catches every phone in landscape (tallest ~430px) and no real desktop
         window. ponytail: a genuinely short desktop window (~600-700px tall) still
         clips the card, since the deliverable was "no desktop change".
         Keep last in this string: a media query adds no specificity, so source
         order is what makes it win over the .launch-* rules above. Twin of
         chrome.css's block; change both. Desktop untouched above 640px wide /
         500px tall. */
      /* soft header bands (Workbench pick 2026-10-11): four columns, one per group, each under a band tinted in its group color; rows keep the 20px glyph in that color. Selectors carry .launch-panel so cobalt's tile border, hover drop and current-tile stripes stay off the rows. Twin of chrome.css; change both. */
      ".launch-panel{width:min(1000px,94vw);padding-bottom:var(--s-5);}" +
      ".launch-cols{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;padding:var(--s-4) 12px 0;}" +
      ".launch-cols .g-today{--g:#e0a030;}.launch-cols .g-life{--g:#36b37e;}.launch-cols .g-career{--g:#5b8cff;}.launch-cols .g-system{--g:#a77bff;}" +
      ".launch-panel .launch-cols .launch-tier{border-top:0;}" +
      ".launch-panel .launch-cols .tier-label{margin:0 6px 8px;padding:8px 10px;border-radius:4px;font-size:var(--fs-footnote);font-weight:600;background:color-mix(in srgb,var(--g) 18%,transparent);color:color-mix(in srgb,var(--g) 55%,var(--fg));}" +
      ".launch-panel .launch-cols .launch-grid{grid-template-columns:1fr;gap:0;background:transparent;padding:0;}" +
      ".launch-panel .launch-cols .launch-tile{min-height:48px;padding:0 14px;justify-content:center;border:0;border-radius:4px;background:transparent;box-shadow:none;transform:none;}" +
      ".launch-panel .launch-cols .launch-tile:hover{background:var(--accent-faint);box-shadow:none;transform:none;}" +
      ".launch-panel .launch-cols .launch-tile.is-current{background:color-mix(in srgb,var(--accent) 32%,transparent);box-shadow:none;}" +
      ".launch-panel .launch-cols .tile-glyph{color:var(--g);}" +
      ".launch-panel .launch-cols .tile-name{font-size:var(--fs-body);}" +
      "@media (max-width:640px),(max-height:500px){" +
        ".launch-scrim{padding:0;align-items:stretch;}" +
        /* dvh so iOS Safari's collapsing toolbar cannot park the foot under it */
        ".launch-panel{width:100%;height:100vh;height:100dvh;border:0;border-radius:0;box-sizing:border-box;padding-top:var(--safe-t);" +
          "overflow-y:auto;-webkit-overflow-scrolling:touch;}" +
        ".launch-head{position:sticky;top:0;z-index:1;align-items:center;background:var(--bg-elev);}" +
        ".launch-close{display:inline-flex;align-items:center;min-height:44px;padding:0 var(--s-2);" +
          "border:0;background:transparent;cursor:pointer;font-family:var(--font-body);" +
          "font-feature-settings:var(--feat-meta);font-size:var(--fs-footnote);letter-spacing:0.06em;" +
          "text-transform:lowercase;color:var(--fg-dim);}" +
        ".launch-grid{grid-template-columns:repeat(2,minmax(0,1fr));}" +
        // last tile of an odd tier spans both columns, so two columns leave no
        // tile-shaped hole. Twin of chrome.css; change both.
        ".launch-grid>.launch-tile:last-child:nth-child(odd){grid-column:1/-1;}" +
        ".launch-tile .tile-row{min-width:0;}" +
        ".launch-tile .tile-name{min-width:0;font-size:var(--fs-body);overflow-wrap:anywhere;}" +
        ".launch-tile:last-child:nth-child(odd) .tile-name{font-size:var(--fs-body);}" +
        ".launch-panel .launch-cols{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:var(--s-4) 10px 0;}" +
        ".launch-panel .launch-cols .launch-tile{padding:0 10px;}" +
        ".launch-panel .launch-cols .tile-name{font-size:var(--fs-body);}" +
      "}";
    var el = document.createElement("style");
    el.id = "hub-universal-css";
    el.textContent = css;
    document.head.appendChild(el);
  }

  /* ---- surface (light/dark): ONE owner for the whole hub ----
     The light/dark control used to be hand-rolled in every page (its own button
     markup + click handler + storage key), which is how it drifted — some pages
     showed the home hub's ☾/☀ icon, others a dot + the word "dark"/"light", and
     vault-map even persisted to a different key ("hub:surface" vs the canonical
     "hub.surface") so the choice didn't carry across pages. Now this is the one
     owner: topbar.jsx's toggle calls HubTheme.surface, which persists to the one
     canonical key and fires hub:surfacechange. The page's pre-paint no-flash
     <head> snippet still seeds data-surface before first paint (it must, to avoid
     a flash); that's the only surface code left in a page. */
  var SURFACE_KEY = "hub.surface";
  var LEGACY_SURFACE_KEY = "hub:surface"; // old colon key — migrated away on write
  function currentSurface() {
    var s = root.getAttribute("data-surface");
    return (s === "light" || s === "dark") ? s : "dark";
  }
  function setSurface(s) {
    if (s !== "light" && s !== "dark") s = "dark";
    root.setAttribute("data-surface", s);
    try { localStorage.setItem(SURFACE_KEY, s); localStorage.removeItem(LEGACY_SURFACE_KEY); } catch {}
    document.dispatchEvent(new CustomEvent("hub:surfacechange", { detail: { surface: s } }));
  }
  function toggleSurface() { setSurface(currentSurface() === "dark" ? "light" : "dark"); }

  /* ---- universal back ----
     Every hub page except home gets one. It is a real "back" when there is somewhere
     in-hub to go back TO (a same-origin referrer), and falls up one path level
     otherwise — so a page opened cold from a bookmark still has a working control
     instead of a dead button. /food/denver-co -> /food -> /. */
  /* behaviour only; topbar.jsx renders the button against window.HubBack */
  function backVisible() {
    return location.pathname.replace(/\/+$/, "") !== "";   // home has nothing above it
  }

  function goBack() {
    var internal = false;
    try {
      const ref = new URL(document.referrer);
      internal = !!document.referrer && ref.origin === location.origin &&
                 ref.pathname !== location.pathname;
    } catch { internal = false; }
    if (internal && history.length > 1) { history.back(); return; }
    var parts = location.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
    parts.pop();
    location.href = `/${parts.join("/")}`;
  }

  /* liquid's top bar becomes an island once the page scrolls (set 13 pick). Home, /finances and
     /recipes scroll an inner region, not the document, so a document sentinel misses them: one
     capture-phase scroll listener sees both. A scroller under half the viewport tall or 40% wide is a
     menu, list or side rail, not the page (the /jobs context rail and /vault-map column flipped the bar
     on pages that never scroll, 2026-10-12). No layout is exempt: 3-pane pages scroll inside their panes,
     and any big pane past 24px marks the bar, held until every one is back at the top so two panes cannot flicker it.
     Other themes carry the attribute and ignore it. */
  function watchScroll() {
    if (watchScroll.on) return;
    watchScroll.on = true;
    var down = new Set();
    document.addEventListener("scroll", function (e) {
      var el = e.target === document ? document.scrollingElement : e.target;
      if (!el || el.clientHeight < window.innerHeight / 2 || el.clientWidth < window.innerWidth * 0.4) return;
      el.scrollTop > 24 ? down.add(el) : down.delete(el);
      down.forEach(function (d) { if (!d.isConnected) down.delete(d); });
      var bar = document.querySelector(".topbar");
      if (bar) bar.toggleAttribute("data-scrolled", down.size > 0);
    }, { capture: true, passive: true });
  }

  /* rung 3 lens (2026-10-10 spike): blur stays native in CSS, the SVG filter only displaces.
     The map is a rounded-rect edge band, displacement along the edge normal, strongest at the rim,
     R = x, G = y (port of lens_map in the vault's liquid-material-gen.py). A filter region is fixed
     px, so each tagged element gets its own filter, rebuilt when its box settles. */
  var LENSES = { bar: ".topbar", island: ".topbar-l", dock: ".topbar-r", drawer: ".hub-t3p-rail > .hub-nav-rail" };
  var LENS_BEZEL = 16, LENS_POWER = 2.2, LENS_SCALE = 18; // spike values: edge band px, falloff, bend px

  function lensMap(w, h, r, bezel) {
    var c = document.createElement("canvas");
    c.width = w; c.height = h;
    var ctx = c.getContext("2d"), img = ctx.createImageData(w, h), d = img.data;
    for (var j = 0; j < h; j++) for (var i = 0; i < w; i++) {
      var px = i + .5 - w / 2, py = j + .5 - h / 2;
      var qx = Math.abs(px) - (w / 2 - r), qy = Math.abs(py) - (h / 2 - r);
      var nx, ny, dist;
      if (qx > 0 && qy > 0) { var l = Math.hypot(qx, qy); dist = r - l; nx = qx / l; ny = qy / l; }
      else if (qx > qy) { dist = r - qx; nx = 1; ny = 0; }
      else { dist = r - qy; nx = 0; ny = 1; }
      var m = dist >= 0 && dist < bezel ? (1 - dist / bezel) ** LENS_POWER : 0;
      var k = (j * w + i) * 4;
      d[k] = 128 - (px < 0 ? -nx : nx) * m * 127;
      d[k + 1] = 128 - (py < 0 ? -ny : ny) * m * 127;
      d[k + 2] = 128; d[k + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    return c.toDataURL();
  }

  function buildLens(name, el) {
    var w = Math.round(el.offsetWidth), h = Math.round(el.offsetHeight);
    if (!w || !h || el.dataset.lensSize === w + "x" + h) return;
    el.dataset.lensSize = w + "x" + h;
    var r = Math.min(parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0, h / 2, w / 2);
    var svg = document.getElementById("lgLens");
    if (!svg) {
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.id = "lgLens";
      svg.setAttribute("aria-hidden", "true");
      svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
      document.body.appendChild(svg);
    }
    /* double-buffered: rewriting the filter the glass is drawn through left a frame or two with no map
       loaded yet, so the glass flickered right after the island settled (Sam 2026-10-17). The new
       map goes into the idle filter, and the element's --lg-lens-<name> flips to it once the map decodes */
    var id = "lg-lens-" + name + (el.style.getPropertyValue("--lg-lens-" + name).indexOf("-a)") >= 0 ? "-b" : "-a");
    var f = document.getElementById(id);
    if (!f) { f = document.createElementNS("http://www.w3.org/2000/svg", "filter"); f.id = id; svg.appendChild(f); }
    f.setAttribute("x", 0); f.setAttribute("y", 0); f.setAttribute("width", w); f.setAttribute("height", h);
    f.setAttribute("filterUnits", "userSpaceOnUse");
    f.setAttribute("color-interpolation-filters", "sRGB");
    var map = lensMap(w, h, r, Math.min(LENS_BEZEL, h / 2)), img = new Image();
    f.innerHTML = '<feImage href="' + map + '" x="0" y="0" width="' + w + '" height="' + h + '" result="m"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="m" scale="' + LENS_SCALE + '" xChannelSelector="R" yChannelSelector="G"/>';
    img.src = map;
    var flip = function () {
      // a newer build for this element took over meanwhile: leave its flip to it
      if (el.dataset.lensSize !== w + "x" + h) return;
      requestAnimationFrame(function () { requestAnimationFrame(function () { el.style.setProperty("--lg-lens-" + name, "url(#" + id + ")"); }); });
    };
    (img.decode ? img.decode() : Promise.resolve()).then(flip, flip);
  }

  /* rebuilds a lens 250ms after its box stops changing, so the radius is read after the island's
     200ms transition. Runs again on load: home's React bar is not in the DOM at DOMContentLoaded.
     ponytail: keyed on box size only; a theme flip that keeps the size but changes the radius
     keeps the old lens until the next resize. */
  var lensTimers = {}, lensRO = null;
  function scheduleLens(name, el) {
    clearTimeout(lensTimers[name]);
    lensTimers[name] = setTimeout(function () { if (root.getAttribute("data-glass") === "refract") buildLens(name, el); }, 250);
  }
  function mountLenses() {
    if (!window.ResizeObserver) return;
    lensRO = lensRO || new ResizeObserver(function (entries) {
      entries.forEach(function (e) { scheduleLens(e.target.dataset.lens, e.target); });
    });
    Object.keys(LENSES).forEach(function (name) {
      var el = document.querySelector(LENSES[name]);
      if (el && !el.dataset.lens) { el.dataset.lens = name; lensRO.observe(el); }
    });
  }

  /* liquid's scroll bar (hub-scrollbar-2 pick): its own files, shown only under liquid by its css */
  function mountScrollbar() {
    var css = document.createElement("link"); css.rel = "stylesheet"; css.href = "/static/css/liquid-scrollbar.css";
    var js = document.createElement("script"); js.src = "/static/js/liquid-scrollbar.js";
    document.head.append(css, js);
  }

  function autoMount() {
    injectCss();
    injectUniversalCss();
    mountScrollbar();
    watchScroll();
    mountLenses();
    window.addEventListener("load", mountLenses, { once: true });
  }

  window.HubBack = { visible: backVisible, go: goBack };

  applyGlass();
  window.HubTheme = { get: current, set: setTheme, glass: { get: getGlass, set: setGlass }, list: THEMES.slice(), meta: meta, injectCss: injectCss, slogan: () => sloganFor(current()), slogans: THEME_SLOGANS,
    surface: { get: currentSurface, set: setSurface, toggle: toggleSurface } };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoMount);
  } else {
    autoMount();
  }
})();

/* Pour (Workbench pick 2026-10-15): every expand/collapse in the Hub glides.
   One delegated listener instead of a wrapper in each component. On a click of
   anything carrying aria-expanded it measures the toggle's nearest three
   ancestors, lets the page re-render, then glides the nearest one whose height
   changed and fades its newly shown rows in, 30ms apart. <details> height is
   CSS (base.css); this only adds its row fade.
   Sections wrapped in <HubCollapse> (topbar.jsx) fade their rows out on close
   too; this listener stands aside for those. ponytail: an unwrapped toggle's
   close is the box gliding shut with its rows already gone; wrap it to fade
   them. Table-row toggles are skipped (a row group cannot clip its height). */
(() => {
  var OPEN = { duration: 420, easing: "cubic-bezier(.16,1,.3,1)" };
  // same settle as topbar.jsx's HubCollapse close: fast start, soft landing, longer for taller boxes
  var CLOSE_EASE = "cubic-bezier(.22,1,.36,1)";
  var closeMs = function (h) { return Math.min(560, Math.max(340, 280 + h * 0.25)); };
  var still = matchMedia("(prefers-reduced-motion: reduce)");
  var shown = function (el) { return el.getClientRects().length > 0; };
  var kids = function (el) { return [].slice.call(el.children); };

  function pourIn(els) {
    els.slice(0, 10).forEach(function (el, i) {
      el.animate([{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }],
        { duration: 460, easing: OPEN.easing, delay: 40 + i * 30, fill: "backwards" });
    });
  }

  document.addEventListener("click", function (e) {
    if (still.matches || !e.target.closest) return;
    var t = e.target.closest("summary, [aria-expanded]");
    if (!t) return;
    if (t.tagName === "SUMMARY") {
      var d = t.parentElement;
      if (d && d.tagName === "DETAILS" && !d.open) requestAnimationFrame(function () {
        if (d.open) pourIn(kids(d).filter(function (c) { return c !== t; }));
      });
      return;
    }
    if (t.closest("tr")) return;
    var boxes = [];
    for (var el = t.parentElement; el && boxes.length < 3 && el !== document.body; el = el.parentElement) {
      boxes.push({ el: el, h: el.getBoundingClientRect().height, was: new Set(kids(el).filter(shown)) });
    }
    // capture phase + rAF: measured before React's handler runs, re-measured after it rendered
    requestAnimationFrame(function () {
      var outer = boxes.length && boxes[boxes.length - 1].el;
      // a <HubCollapse> (topbar.jsx) already animating in here owns this toggle
      if (outer && document.getAnimations().some(function (a) {
        var el = a.effect && a.effect.target;
        return el && el.closest && el.closest(".hub-collapse") && outer.contains(el);
      })) return;
      for (var i = 0; i < boxes.length; i++) {
        var b = boxes[i], h1 = b.el.getBoundingClientRect().height;
        if (Math.abs(h1 - b.h) < 1) continue;
        b.el.animate([{ height: b.h + "px", overflow: "clip" }, { height: h1 + "px", overflow: "clip" }], h1 > b.h ? OPEN : { duration: closeMs(b.h - h1), easing: CLOSE_EASE });
        var fresh = kids(b.el).filter(function (c) { return !b.was.has(c) && shown(c); });
        if (fresh.length === 1 && fresh[0].children.length > 1) fresh = kids(fresh[0]);
        return pourIn(fresh);
      }
      // nothing changed height (a popover or menu): just pour in what appeared
      var p = boxes[0];
      if (p) pourIn(kids(p.el).filter(function (c) { return c !== t && !p.was.has(c) && shown(c); }));
    });
  }, true);
})();
