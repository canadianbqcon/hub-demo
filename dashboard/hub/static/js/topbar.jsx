/* The Hub top bar: ONE React component for every page (2026-10-12).

   It used to exist twice, a React copy here in chrome.jsx and a DOM-building copy
   in theme-switch.js, and each React app kept its own light/dark state and its own
   launcher on top. Now there is this file and nothing else.

   React pages (home, purchases, work) render <Topbar crumb="work" /> in their own
   tree. Every other page ships a <header class="topbar"> holding only its own
   extras, and the bottom of this file renders the same bar into it. Each extra
   carries data-slot saying where it goes:
     crumb  inside the crumb block: the page title itself, a pill, a section line
     lead   between the brand and the crumb (the phone section toggle on news, trips)
     left   after the crumb block (jobs' view modes)
     right  ahead of the controls; also where an untagged child lands
   They are MOVED into place, not copied, so ids and listeners a page script has
   already bound keep working.

   Wrapped in an IIFE because plain pages load it next to their own globals; only
   the names exported at the bottom leave it. Behaviour (theme, glass, surface,
   back) stays in theme-switch.js, which must load first; this file only renders. */
(() => {
const { useState, useEffect, useRef, useLayoutEffect } = React;

/* ---------------- useDialogA11y (shared) ----------------
   Modal accessibility in one place: focus trap + Escape-to-close + focus restore.
   Attach the returned ref to the dialog PANEL and give that panel
   role="dialog" aria-modal="true" and an aria-label. On open it moves focus into
   the dialog; Tab/Shift-Tab cycle within it (no escaping to the dimmed page
   behind the scrim); on close focus returns to the element that opened it.
   `active` gates it for self-rendering launchers that stay mounted when closed
   (pass the open flag); modals mounted only while open can omit it.
   Lives here because the launcher needs it on every page; exported as a global
   for the React pages' own dialogs. */
function useDialogA11y(onClose, active = true) {
  const ref = useRef(null);
  useEffect(() => {
    if (!active) return;
    const panel = ref.current;
    if (!panel) return;
    const prevFocus = document.activeElement;
    const focusables = () => Array.from(panel.querySelectorAll(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
    ));
    // move focus into the dialog (first field/control, else the panel itself)
    (focusables()[0] || panel).focus();
    const onKey = (e) => {
      if (e.key === "Escape") { onClose?.(); return; }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (!items.length) { e.preventDefault(); return; }
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (prevFocus?.focus) prevFocus.focus();
    };
  }, [active]);
  return ref;
}

/* re-render on a document event; the bar has no props that change */
function useDocEvent(name) {
  const [, bump] = useState(0);
  useEffect(() => {
    const on = () => bump((n) => n + 1);
    document.addEventListener(name, on);
    return () => document.removeEventListener(name, on);
  }, []);
}

/* ---------------- ControlPane ----------------
   One gear in the bar opens the panel holding light/dark, the theme, liquid's
   transparency and sign out (Workbench pick "Gear button, sectioned panel",
   2026-10-17; it replaced three separate bar controls). Behaviour stays in
   window.HubTheme. The wrapper keeps the .theme-picker class and the panel keeps
   .theme-picker-menu, so each theme's menu dress and the phone dock's upward
   menu rule carry over unchanged. An unauthored theme (meta().authored false)
   renders disabled. */
function ControlPane() {
  const VT = window.HubTheme;
  const S = VT.surface;
  useDocEvent("hub:surfacechange");
  const [open, setOpen] = useState(false);
  const [theme, setThemeState] = useState(() => VT.get());
  const [meta, setMeta] = useState(() => VT.meta());
  const [glass, setGlassState] = useState(() => VT.glass.get());

  // reflect changes made from anywhere (programmatic, other tab logic)
  useEffect(() => {
    const onChange = (e) => { setThemeState(e.detail.theme); setMeta(VT.meta()); };
    document.addEventListener("hub:themechange", onChange);
    return () => document.removeEventListener("hub:themechange", onChange);
  }, []);

  // outside-click + esc close
  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (!e.target.closest(".control-pane")) setOpen(false); };
    const onEsc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onEsc); };
  }, [open]);

  const toggle = () => { setMeta(VT.meta()); setOpen((o) => !o); }; // refresh swatches for live surface
  const pick = (code) => {
    if (!meta[code]?.authored) return;
    VT.set(code);
    setThemeState(code);
  };
  const setSurface = (s) => { S.set(s); setMeta(VT.meta()); };
  const setGlass = (g) => { VT.glass.set(g); setGlassState(g); };
  const light = S.get() === "light";

  return (
    <div className="theme-picker control-pane" data-open={open}>
      <button type="button" id="controlPaneBtn" className="launcher launcher-icon control-pane-btn"
        onClick={toggle} aria-haspopup="dialog" aria-expanded={open} aria-label="controls" title="controls">
        <svg className="launcher-g" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="2.8" />
          <path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2.1-1.2L14.2 3h-4l-.4 2.6a7 7 0 0 0-2.1 1.2l-2.3-.9-2 3.4 2 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2.1 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2.1-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" />
        </svg>
      </button>
      <HubCollapse open={open} float>
        <div className="theme-picker-menu control-pane-menu" role="dialog" aria-label="controls">
          <div className="cp-row">
            <span className="cp-lbl">mode</span>
            <span className="cp-seg" role="group" aria-label="mode">
              {/* U+FE0E keeps the sun a text glyph; the colour emoji is wider and jumps the row */}
              <button type="button" className="cp-seg-i" aria-pressed={light} onClick={() => setSurface("light")}>☀︎ light</button>
              <button type="button" className="cp-seg-i" aria-pressed={!light} onClick={() => setSurface("dark")}>☾︎ dark</button>
            </span>
          </div>
          <div className="cp-row cp-col">
            <span className="cp-lbl">theme</span>
            <div className="cp-themes" role="radiogroup" aria-label="theme">
              {VT.list.map((code) => {
                const m = meta[code] || {};
                return (
                  <button type="button" key={code} role="radio" aria-checked={code === theme}
                    className={`cp-theme${code === theme ? " is-active" : ""}`}
                    disabled={!m.authored} onClick={() => pick(code)}>
                    <span className="theme-swatch" style={{ background: m.accent || "transparent" }}></span>
                    <span>{code}</span>
                  </button>
                );
              })}
            </div>
          </div>
          {theme === "liquid" && (
            <div className="cp-row">
              <span className="cp-lbl">transparency</span>
              <span className="cp-seg" role="group" aria-label="transparency">
                <button type="button" className="cp-seg-i" aria-pressed={glass === "frost"} onClick={() => setGlass("frost")}>glass</button>
                <button type="button" className="cp-seg-i" aria-pressed={glass === "solid"} onClick={() => setGlass("solid")}>solid</button>
              </span>
            </div>
          )}
          {/* mark mode lives here, not in the bar (mark 2026-10-20 "move inside control panel").
              window.HubMark is set by marks.js, desktop pointers only, so a phone gets no row. */}
          {window.HubMark ? (
            <div className="cp-row">
              <span className="cp-lbl">mark</span>
              <span className="cp-seg">
                {/* glyph only: the row label already says mark (2026-11-03 mark: "mark this page" too long) */}
                <button type="button" className="cp-seg-i cp-mark" aria-label="Mark this page" title="mark this page"
                  onClick={() => { setOpen(false); window.HubMark.enter(); }}>
                  <svg className="mk-g" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20 L5.5 14.5 L15.5 4.5 L19.5 8.5 L9.5 18.5 Z" /><path d="M13.5 6.5 L17.5 10.5" /></svg>
                </button>
              </span>
            </div>
          ) : null}
          {/* only when the password gate is on (window.__HUB_EXPOSED__, served in
              /hub-modules.js). POST form so a prefetch can't sign you out. */}
          {window.__HUB_EXPOSED__ ? (
            <form method="POST" action="/logout" className="cp-out-form">
              <button type="submit" className="cp-out">sign out</button>
            </form>
          ) : null}
        </div>
      </HubCollapse>
    </div>
  );
}

/* ---------------- ModuleLauncher ----------------
   the box-cutout module switcher. Home is the mainstay block on top, then four
   columns by group. Tier comes from each module's `tier` field (hub_modules.py).
   Portalled to <body> so no page layout can clip or restack it. */
function isCurrentPath(href) {
  if (!href) return false;
  const here = window.location.pathname.replace(/\/+$/, "") || "/";
  const there = href.replace(/\/+$/, "") || "/";
  return here === there;
}
const LAUNCH_TIERS = [
  { key: "home", label: null },
  { key: "today", label: "today" },
  { key: "life", label: "life" },
  { key: "career", label: "career" },
  { key: "system", label: "system" },
];
function ModuleLauncher({ open, modules, onClose }) {
  const dref = useDialogA11y(onClose, open);
  if (!open) return null;
  const pick = (m) => {
    onClose();
    if (!m.href || isCurrentPath(m.href)) return;
    if (m.ext || !m.href.startsWith("/")) window.open(m.href, "_blank", "noreferrer");
    else window.location.href = m.href;
  };
  const sections = LAUNCH_TIERS.map((tier) => {
    const items = modules.filter((m) => m.tier === tier.key);
    if (!items.length) return null;
    const isHome = tier.key === "home";
    return (
      <div className={`launch-tier g-${tier.key}`} key={tier.key}>
        {tier.label ? <div className="tier-label">{tier.label}</div> : null}
        <div className={`launch-grid${isHome ? " tier-home" : ""}`}>
          {items.map((m) => (
            <button type="button" key={m.name}
              className={`launch-tile${isHome ? " tile-home" : ""}${isCurrentPath(m.href) ? " is-current" : ""}`}
              onClick={() => pick(m)}>
              {/* the glyph rides beside the name so the tile reads as a shape before
                  it reads as text. Decorative, so out of the a11y tree. m.icon is our
                  own constant from hub_modules.py, never user input. */}
              <span className="tile-row">
                {m.icon ? (
                  <svg className="tile-glyph" viewBox="0 0 24 24" aria-hidden="true"
                       focusable="false" dangerouslySetInnerHTML={{ __html: m.icon }} />
                ) : null}
                <span className="tile-name">{m.name}</span>
              </span>
              {isHome ? <span className="tile-arrow">→</span> : null}
            </button>
          ))}
        </div>
      </div>
    );
  });
  return ReactDOM.createPortal(
    <div className="launch-scrim" onClick={onClose}>
      <div className="launch-panel" ref={dref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="modules" onClick={(e) => e.stopPropagation()}>
        <div className="launch-head">
          <span className="lbl">modules</span>
          {/* phone-only dismiss: CSS shows it under 640px, where the overlay goes
              full-bleed and leaves no scrim to tap and no Escape key. */}
          <button type="button" className="launch-close" aria-label="close modules" onClick={onClose}>close</button>
        </div>
        {sections[0]}
        <div className="launch-cols">{sections.slice(1)}</div>
      </div>
    </div>,
    document.body
  );
}

/* ---------------- the bar ----------------
   brand lockup ("hub" over the active theme's slogan), the page's crumb, then the
   controls. `slots` is the page's own extras (see the top of this file); React
   pages pass `crumb` instead. An empty module list (the public trips mirror)
   leaves the launcher out rather than opening an empty grid. */
function TopbarInner({ crumb, slots }) {
  useDocEvent("hub:themechange");   // the slogan follows the theme
  const [launch, setLaunch] = useState(false);
  const lRef = useRef(null), cRef = useRef(null), rRef = useRef(null);
  useLayoutEffect(() => {
    if (!slots) return;
    const l = lRef.current, c = cRef.current, r = rRef.current;
    slots.lead.forEach((n) => { l.insertBefore(n, c); });
    slots.crumb.forEach((n) => { c.appendChild(n); });
    slots.left.forEach((n) => { l.appendChild(n); });
    const first = r.firstChild;
    slots.right.forEach((n) => { r.insertBefore(n, first); });
  }, []);
  const modules = window.MODULES || [];
  return (
    <>
      <div className="topbar-l" ref={lRef}>
        <a className="brand-stack brand-link" href="/" aria-label="home">
          <h1 className="brand-wordmark">hub</h1>
          <span className="brand-slogan">{window.HubTheme.slogan()}</span>
        </a>
        <div className="crumb-block" ref={cRef}>
          {crumb != null ? <span className="crumb">{crumb}</span> : null}
        </div>
      </div>
      <div className="topbar-r" ref={rRef}>
        <ControlPane />
        {modules.length ? (
          <button type="button" className="launcher launcher-icon module-launcher" aria-label="modules" title="modules"
                  onClick={() => setLaunch(true)}>
            {/* drawn, not the ⊞ character: no Hub font has U+229E, so the fallback font blurred it and set it off-centre */}
            <svg className="launcher-g module-g" viewBox="0 0 18 18" aria-hidden="true">
              <rect x="1.5" y="1.5" width="6" height="6" rx="1.5" /><rect x="10.5" y="1.5" width="6" height="6" rx="1.5" />
              <rect x="1.5" y="10.5" width="6" height="6" rx="1.5" /><rect x="10.5" y="10.5" width="6" height="6" rx="1.5" />
            </svg>
          </button>
        ) : null}
      </div>
      <ModuleLauncher open={launch} modules={modules} onClose={() => setLaunch(false)} />
    </>
  );
}

function Topbar({ crumb = "home" }) {
  return <header className="topbar"><TopbarInner crumb={crumb} /></header>;
}

/* ---------------- StatusStrip (shared, 2026-10-17) ----------------
   The bottom bar, one component like the top bar: clock · ambient date · the
   page's own context · connectors · build tag. It ticks itself, so a page never
   threads a `now` through. React pages pass their context as children; plain
   pages ship a <footer class="status"> holding only theirs and mount() below
   MOVES those nodes into the slot, so #statusMsg / #statusMeta writers keep
   working. Connectors show only where the page loaded window.CONNECTORS (home);
   elsewhere a missing gmail would read as a false "reconnect". */
const pad2 = (n) => String(n).padStart(2, "0");
function StatusInner({ children, nodes }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id); }, []);
  const ctx = useRef(null);
  useLayoutEffect(() => { if (nodes) nodes.forEach((n) => ctx.current.appendChild(n)); }, []);

  // 12-hour with the hub's lowercase a/p, never 24-hour: every module's own times read that way
  const h24 = now.getHours();
  const t = `${h24 % 12 || 12}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}${h24 < 12 ? "a" : "p"}`;
  const yr = now.getFullYear();
  // the same math as BriefingLogic.dayOfYear, inlined: most pages load no briefing.logic.js
  const jan1 = Date.UTC(yr, 0, 1);
  const doy = Math.round((Date.UTC(yr, now.getMonth(), now.getDate()) - jan1) / 86400000) + 1;
  const daysInYear = (Date.UTC(yr + 1, 0, 1) - jan1) / 86400000;
  const onejan = new Date(yr, 0, 1);
  const wk = Math.ceil((((now - onejan) / 86400000) + onejan.getDay() + 1) / 7);
  const day = ["sun","mon","tue","wed","thu","fri","sat"][now.getDay()];
  const mon = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"][now.getMonth()];

  const cx = window.CONNECTORS;
  // hub-dot (base.css) pairs the state color with its own visible text
  const dot = (ok, label) => (
    <span className="hub-dot" style={{ "--dot-color": ok ? "var(--accent)" : "var(--fg-ghost)" }}>{label}</span>
  );
  return (
    <>
      <span className="clock">{t}</span>
      <span className="ambient">{`${day} · ${mon} ${now.getDate()} · week ${wk} · day ${doy}/${daysInYear}`}</span>
      {children}
      {nodes ? <span className="status-ctx" ref={ctx} /> : null}
      {cx ? (
        <span className="src">
          {dot(cx.gcal, "gcal")}
          <span className="sep">·</span>
          {cx.gmail
            ? dot(true, "gmail")
            : <a className="reconnect hub-dot" style={{ "--dot-color": "var(--warn-dim)" }}
                 href="/api/gmail/auth" title="Gmail token expired — click to re-authorize">gmail · reconnect</a>}
          <span className="sep">·</span>
          {dot(cx.ynab, "ynab")}
        </span>
      ) : null}
      <span className="src">{`HUB · build 1.1 · ${location.pathname}`}</span>
    </>
  );
}

function StatusStrip({ children, id }) {
  return <footer className="status" id={id}><StatusInner>{children}</StatusInner></footer>;
}

/* ---------------- mount on plain pages ----------------
   flushSync so the bar is in the DOM before any later script (a page's own
   measure-the-bar code) goes looking for it. A header inside #root
   belongs to a React page, which renders its own. Login has no bar, only a
   [data-theme-picker] spot. */
function mount() {
  const bar = document.querySelector("header.topbar");
  if (bar && !bar.closest("#root")) {
    const slots = { lead: [], crumb: [], left: [], right: [] };
    // a page's inline <script> (trips' preview-exit guard) has already run; leave it out
    Array.from(bar.children).forEach((n) => {
      if (n.tagName !== "SCRIPT") (slots[n.dataset.slot] || slots.right).push(n);
    });
    bar.textContent = "";
    const root = ReactDOM.createRoot(bar);
    ReactDOM.flushSync(() => root.render(<TopbarInner slots={slots} />));
  }
  const foot = document.querySelector("footer.status");
  if (foot && !foot.closest("#root")) {
    const nodes = Array.from(foot.children).filter((n) => n.tagName !== "SCRIPT");
    foot.textContent = "";
    const root = ReactDOM.createRoot(foot);
    ReactDOM.flushSync(() => root.render(<StatusInner nodes={nodes} />));
  }
  const pickerSpot = document.querySelector("[data-theme-picker]");
  if (pickerSpot) {
    const root = ReactDOM.createRoot(pickerSpot);
    ReactDOM.flushSync(() => root.render(<ControlPane />));
  }
}

/* ---------------- HubCollapse (shared) ----------------
   Pour (Workbench pick 2026-10-15) for a React section that unmounts its body:
   <HubCollapse open={!collapsed}>...rows...</HubCollapse>. Opening glides the
   height up and pours the rows in; closing keeps the last rows mounted while
   they fade and the box glides shut, then unmounts. theme-switch.js's global
   toggle animator leaves any box holding a .hub-collapse to this.
   float: for a menu that sits over the page (position absolute/fixed). The
   wrapper takes no box (display: contents) and each child unrolls down from
   its top edge on open and rolls back up on close, since there is no page
   height to glide. */
const POUR_OPEN = "cubic-bezier(.16,1,.3,1)", POUR_CLOSE = "cubic-bezier(.22,1,.36,1)";
// a close settles like the open does (fast start, soft landing) and takes longer for a taller
// box; a fixed 300ms ease-in-out slammed a 1000px section shut (2026-10-15)
const pourCloseMs = (h) => Math.min(560, Math.max(340, 280 + h * 0.25));
function HubCollapse({ open, children, className, float }) {
  const [mounted, setMounted] = useState(open);
  const ref = useRef(null);
  const last = useRef(children);
  const first = useRef(true);
  if (open) last.current = children;
  if (open && !mounted) setMounted(true);
  useLayoutEffect(() => {
    if (first.current) { first.current = false; return; }
    const el = ref.current;
    if (!el) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { if (!open) setMounted(false); return; }
    if (float) {
      const menus = [...el.children];
      // keep the menu's own corner radius on the clip, or the corners go square mid-roll
      const frames = (m) => {
        const r = getComputedStyle(m).borderRadius || "0px";
        return [{ clipPath: `inset(0 0 100% 0 round ${r})`, opacity: 0.4, transform: "translateY(-4px)" },
                { clipPath: `inset(0 0 0 0 round ${r})`, opacity: 1, transform: "none" }];
      };
      const anims = menus.map((m) => open
        ? m.animate(frames(m), { duration: 320, easing: POUR_OPEN })
        : m.animate(frames(m).reverse(), { duration: 260, easing: POUR_CLOSE, fill: "forwards" }));
      if (open) for (const m of menus) [...m.children].slice(0, 10).forEach((r, i) => { anims.push(r.animate(
        [{ opacity: 0, transform: "translateY(-4px)" }, { opacity: 1, transform: "none" }],
        { duration: 360, easing: POUR_OPEN, delay: 30 + i * 20, fill: "backwards" })); });
      if (!open) { if (anims[0]) anims[0].onfinish = () => setMounted(false); else setMounted(false); }
      return () => anims.forEach((a) => { a.cancel(); });
    }
    const rows = [...el.children].slice(0, 10);
    const h = el.getBoundingClientRect().height;
    const anims = open
      ? [el.animate([{ height: "0px" }, { height: `${h}px` }], { duration: 420, easing: POUR_OPEN }),
         ...rows.map((r, i) => r.animate([{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }],
           { duration: 460, easing: POUR_OPEN, delay: 40 + i * 30, fill: "backwards" }))]
      : [el.animate([{ height: `${h}px` }, { height: "0px" }], { duration: pourCloseMs(h), easing: POUR_CLOSE, fill: "forwards" }),
         // rows stay readable while the edge sweeps over them, dimming only near the end
         ...rows.map((r) => r.animate([{ opacity: 1 }, { opacity: 0 }],
           { duration: pourCloseMs(h), easing: "cubic-bezier(.6,0,.9,.4)", fill: "forwards" }))];
    if (!open) anims[0].onfinish = () => setMounted(false);
    // a reopen mid-close cancels the fade-out, or its fill would keep the rows hidden
    return () => anims.forEach((a) => { a.cancel(); });
  }, [open]);
  if (!mounted) return null;
  // the clip margin lets a ring or focus outline drawn just outside a row show; a bare
  // clip cut the alert-line rings on Home in half (2026-10-21 mark "circle bug")
  return <div ref={ref} className={`hub-collapse${className ? ` ${className}` : ""}`}
    style={float ? { display: "contents" } : { overflow: "clip", overflowClipMargin: "4px" }}>{open ? children : last.current}</div>;
}

window.useDialogA11y = useDialogA11y;
window.Topbar = Topbar;
window.StatusStrip = StatusStrip;
window.HubCollapse = HubCollapse;
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
else mount();
})();
