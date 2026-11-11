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

/* ---------------- phone view ----------------
   The gear's "phone" row (his ask 2026-11-07): the desktop bar stays, and under it the
   same page runs at 390x844 in a same-origin iframe, so its phone CSS fires as on his
   phone. Remembered in localStorage, so it follows him page to page. Desktop top windows
   only: the iframe copy and phones never open one.
   ponytail: width media queries only; pointer:coarse rules do not fire in the frame. */
const PHONE_KEY = "hub.phoneview";
const phoneOk = () => window.top === window && !!window.matchMedia && matchMedia("(pointer:fine)").matches;
const phoneStored = () => { try { return localStorage.getItem(PHONE_KEY) === "1"; } catch { return false; } };
function phoneView(on) {
  try { if (on) localStorage.setItem(PHONE_KEY, "1"); else localStorage.removeItem(PHONE_KEY); } catch { /* per-viewer nicety */ }
  const html = document.documentElement;
  html.classList.toggle("hub-phone", on);
  let el = document.getElementById("hub-phone-view");
  if (!on) { if (el) el.remove(); return; }
  if (el) return;
  if (!document.getElementById("hub-phone-css")) {
    const s = document.createElement("style"); s.id = "hub-phone-css";
    // the bar rides above the overlay so the gear menu still opens over it; 1050 sits under the launcher (1200)
    s.textContent = "html.hub-phone,html.hub-phone body{overflow:hidden}" +
      "html.hub-phone header.topbar{position:relative;z-index:1100}" +
      // frosted glass over the page itself (his ask 2026-11-07: liquid glass, not flat black); the page
      // behind sits at the top with its theme wall, so the blur picks up its colour.
      "#hub-phone-view{position:fixed;left:0;right:0;bottom:0;z-index:1050;display:flex;justify-content:center;align-items:flex-start;padding:16px 0;box-sizing:border-box;overflow:hidden;" +
      "background:linear-gradient(135deg,rgba(255,255,255,.22),rgba(255,255,255,.04) 45%,rgba(255,255,255,.14)),color-mix(in srgb,var(--bg) 30%,transparent);" +
      "-webkit-backdrop-filter:blur(48px) saturate(190%);backdrop-filter:blur(48px) saturate(190%)}" +
      // where glass is turned off (liquid's solid setting, a11y modes) the blur goes, so the fill turns opaque
      ":root[data-glass=\"solid\"] #hub-phone-view{background:var(--bg)}" +
      // liquid solid: the theme's own colour wall (liquid.css body::before, same tokens), still not flat black
      ":root[data-theme=\"liquid\"][data-glass=\"solid\"] #hub-phone-view{background:radial-gradient(60% 60% at 10% 0%,rgb(var(--lg-hue-1) / var(--lg-wall-a1)),transparent 70%),radial-gradient(55% 65% at 95% 35%,rgb(var(--lg-hue-2) / var(--lg-wall-a2)),transparent 70%),radial-gradient(70% 50% at 40% 100%,rgb(var(--lg-hue-3) / var(--lg-wall-a3)),transparent 70%),var(--lg-wall-base)}" +
      "@media (prefers-reduced-transparency: reduce),(prefers-contrast: more),(forced-colors: active){#hub-phone-view{background:var(--bg)}}" +
      // the page lays out at a real 390x844 and the whole frame is scaled to the window height
      // (his ask 2026-11-07: fill the height but keep the phone's shape); fit() below sets the scale
      "#hub-phone-view .pv-phone{position:relative;flex:none}" +
      "#hub-phone-view iframe{position:absolute;left:0;top:0;width:390px;height:844px;box-sizing:content-box;transform-origin:0 0;border:1px solid rgba(255,255,255,.45);border-radius:48.33px;background:var(--bg);" +
      "box-shadow:inset 0 1px 0 rgba(255,255,255,.6),0 0 0 .5px rgba(0,0,0,.18),0 24px 70px rgba(0,0,0,.28)}" +
      // the phone's own hardware over the page: the island up top and the home bar at the foot
      "#hub-phone-view .pv-hw{position:absolute;left:0;top:0;width:392px;height:846px;transform-origin:0 0;pointer-events:none;z-index:1}" +
      // his phone is a notch iPhone (390x844 class), not an island (2026-11-08). The 47pt status
      // band is solid: on the phone it shows the root background, not the page's wall, so the
      // band takes the iframe's <html> colour (set in fillStatus). Positions measured off his
      // screenshot in points: clock 41-86, signal 285-303, 5G 309-331, battery 335-360.
      "#hub-phone-view .pv-status{position:absolute;left:1px;top:1px;width:390px;height:47px;border-radius:47.33px 47.33px 0 0;font-family:var(--font-body);font-weight:550;font-feature-settings:'tnum'}" +
      // Inter stands in for SF Pro (not on the PC); sizes are tier tokens scaled to his screenshot's
      // measured cap heights (clock 12.7pt, 5G 10.3pt, UC 4.7pt, battery digits 8.3pt). Judge it at
      // his real density: 2560x1271 at 1x, frame scale ~1.37. A 3x render hides heavy weights there.
      "#hub-phone-view .pv-time{position:absolute;left:40.5px;width:46px;top:17.33px;line-height:1;text-align:center;font-size:calc(var(--fs-body) * 1.17);font-weight:600;letter-spacing:-.01em}" +
      "#hub-phone-view .pv-sig{position:absolute;left:285.33px;top:18.67px;width:19.33px;height:13px;fill:currentColor}" +
      // 5G and the stacked UC are Inter outlines (wght 550-775), not text, each fitted on pixel difference
      // to his 3x screenshot (5 309.7-315.7, G 317-324.7, U 326.3-330.3 x 21.3-25.7, C 326-330.7 x 26.7-31.7).
      // Text could not hold the fit: at his 1.37 frame scale the browser snaps each tiny glyph to whole
      // pixels and hints it on its own, so U and C jumped and thickened (2026-11-09 mark). Paths scale exactly.
      // ponytail: regenerate from the font if the Hub font changes (fontTools, glyph boxes above).
      "#hub-phone-view .pv-5g{position:absolute;left:0;top:0;width:390px;height:47px;fill:currentColor}" +
      "#hub-phone-view .pv-bat{position:absolute;left:335.67px;top:19px;width:25px;height:13.67px;border-radius:4.33px;font-size:calc(var(--fs-caption) * 1.235);font-weight:700;font-feature-settings:normal;line-height:15.67px;text-align:center;letter-spacing:.33px;text-indent:-1.55px}" +
      "#hub-phone-view .pv-bat::after{content:'';position:absolute;right:-2.67px;top:5px;width:1.67px;height:4.33px;border-radius:0 2px 2px 0/0 2.17px 2.17px 0;background:var(--pv-fg);opacity:.5}" +
      // notch from the frame's top edge (over the 1px border) down to the band's foot, so its bottom
      // is flush with where the page starts (his call 2026-11-09), 162pt wide, its
      // outer fillets curving into the edge; the screen corners are the 13's 47.33pt
      "#hub-phone-view .pv-notch{position:absolute;left:50%;top:0;width:162px;margin-left:-81px;height:48px;border-radius:0 0 20px 20px;background:#000}" +
      "#hub-phone-view .pv-notch::before,#hub-phone-view .pv-notch::after{content:'';position:absolute;top:0;width:6px;height:6px;background:radial-gradient(circle at 0 100%,transparent 5.5px,#000 6px)}" +
      "#hub-phone-view .pv-notch::before{left:-6px}" +
      "#hub-phone-view .pv-notch::after{right:-6px;transform:scaleX(-1)}" +
      "#hub-phone-view .pv-home{position:absolute;left:50%;bottom:9px;width:134px;height:5px;margin-left:-67px;border-radius:3px;background:var(--fg);opacity:.85}" +
      "#hub-phone-view .pv-track{position:relative;width:8px;margin-left:10px;flex:none;border-radius:4px;background:rgba(255,255,255,.18);box-shadow:inset 0 0 0 .5px rgba(0,0,0,.12)}" +
      "#hub-phone-view .pv-thumb{position:absolute;left:0;right:0;border-radius:4px;background:rgba(128,128,128,.55);cursor:grab;touch-action:none}";
    document.head.appendChild(s);
  }
  window.scrollTo(0, 0);
  const bar = document.querySelector("header.topbar");
  el = document.createElement("div"); el.id = "hub-phone-view";
  el.style.top = `${bar ? Math.round(bar.getBoundingClientRect().bottom) : 0}px`;
  const f = document.createElement("iframe");
  f.title = "phone view";
  f.src = location.pathname + location.search + location.hash;
  const phone = document.createElement("div"); phone.className = "pv-phone";
  const hw = document.createElement("div"); hw.className = "pv-hw";
  hw.innerHTML = '<div class="pv-status"><span class="pv-time"></span>' +
    '<svg class="pv-sig" viewBox="0 0 19.33 13"><rect x="0" y="6.67" width="3.33" height="6.33" rx="1.5"/><rect x="5.33" y="4.67" width="3.33" height="8.33" rx="1.5"/>' +
    '<rect x="10.67" y="2.33" width="3.33" height="10.67" rx="1.5"/><rect x="16" y=".33" width="3.33" height="12.67" rx="1.5" opacity=".25"/></svg>' +
    '<svg class="pv-5g" viewBox="0 0 390 47"><path d="M312.983 31.56Q312.116 31.56 311.435 31.198Q310.753 30.835 310.352 30.202Q309.951 29.569 309.925 28.757H311.393Q311.419 29.173 311.637 29.498Q311.855 29.822 312.208 30.004Q312.56 30.186 312.983 30.186Q313.485 30.186 313.876 29.931Q314.266 29.677 314.488 29.227Q314.709 28.777 314.709 28.197Q314.709 27.607 314.479 27.146Q314.248 26.685 313.849 26.423Q313.45 26.161 312.929 26.161Q312.515 26.161 312.111 26.326Q311.707 26.49 311.468 26.755L310.09 26.52L310.577 21.41H315.716V22.818H311.836L311.563 25.547H311.611Q311.874 25.238 312.327 25.038Q312.78 24.837 313.309 24.837Q313.926 24.837 314.45 25.083Q314.974 25.328 315.362 25.776Q315.749 26.224 315.964 26.831Q316.179 27.439 316.179 28.161Q316.179 29.146 315.77 29.913Q315.361 30.681 314.641 31.121Q313.921 31.56 312.983 31.56Z M321.394 31.633Q320.192 31.633 319.285 30.999Q318.377 30.364 317.869 29.194Q317.36 28.024 317.36 26.419Q317.36 24.781 317.881 23.61Q318.401 22.439 319.301 21.811Q320.202 21.183 321.342 21.183Q322.061 21.183 322.684 21.428Q323.306 21.672 323.795 22.125Q324.284 22.577 324.598 23.197Q324.912 23.817 325.015 24.563H323.471Q323.362 24.145 323.171 23.813Q322.981 23.482 322.713 23.246Q322.445 23.01 322.107 22.887Q321.768 22.764 321.361 22.764Q320.647 22.764 320.084 23.184Q319.52 23.604 319.197 24.417Q318.874 25.23 318.874 26.406Q318.874 27.577 319.196 28.39Q319.518 29.203 320.087 29.627Q320.656 30.052 321.402 30.052Q322.079 30.052 322.579 29.744Q323.079 29.435 323.351 28.868Q323.622 28.301 323.622 27.53L323.981 27.598H321.57V26.202H325.092V27.408Q325.092 28.712 324.615 29.659Q324.138 30.606 323.305 31.119Q322.471 31.633 321.394 31.633Z M328.633 25.659Q327.988 25.659 327.504 25.462Q327.02 25.265 326.752 24.909Q326.484 24.553 326.484 24.078V21.285H327.622V23.999Q327.622 24.239 327.749 24.424Q327.876 24.61 328.103 24.716Q328.33 24.822 328.633 24.822Q328.938 24.822 329.165 24.716Q329.392 24.61 329.519 24.424Q329.646 24.239 329.646 23.999V21.285H330.784V24.078Q330.784 24.553 330.515 24.909Q330.245 25.265 329.761 25.462Q329.277 25.659 328.633 25.659Z M328.692 31.678Q328.002 31.678 327.455 31.388Q326.908 31.099 326.591 30.545Q326.274 29.992 326.274 29.202Q326.274 28.407 326.595 27.852Q326.915 27.298 327.463 27.009Q328.011 26.72 328.692 26.72Q329.144 26.72 329.532 26.837Q329.92 26.955 330.218 27.18Q330.515 27.405 330.704 27.731Q330.892 28.058 330.946 28.476H329.756Q329.725 28.293 329.639 28.148Q329.552 28.004 329.418 27.902Q329.284 27.799 329.107 27.746Q328.931 27.693 328.721 27.693Q328.339 27.693 328.058 27.871Q327.777 28.049 327.625 28.386Q327.474 28.723 327.474 29.202Q327.474 29.695 327.628 30.03Q327.783 30.366 328.061 30.536Q328.34 30.705 328.716 30.705Q328.926 30.705 329.101 30.652Q329.276 30.598 329.413 30.496Q329.55 30.394 329.639 30.249Q329.728 30.104 329.761 29.922H330.951Q330.915 30.248 330.75 30.56Q330.585 30.872 330.298 31.125Q330.011 31.378 329.609 31.528Q329.206 31.678 328.692 31.678Z"/></svg><span class="pv-bat"></span></div><div class="pv-notch"></div><div class="pv-home"></div>';
  phone.appendChild(f);
  phone.appendChild(hw);
  el.appendChild(phone);
  const track = phoneScrollbar(f, el);
  el.appendChild(track);
  document.body.appendChild(el);
  fillStatus(f, hw, el);  // after the append: its clock stops once el is out of the document
  const fit = () => {
    if (!el.isConnected) return window.removeEventListener("resize", fit);
    // 392x846: the 390x844 page plus the frame's 1px border; 32: the overlay's top and bottom padding
    const s = Math.max(0.3, (el.clientHeight - 32) / 846);
    phone.style.width = `${392 * s}px`;
    phone.style.height = track.style.height = `${846 * s}px`;
    f.style.transform = hw.style.transform = `scale(${s})`;
  };
  window.addEventListener("resize", fit);
  fit();
}

/* The status band over the frame: his phone's 24h clock, kept live, and the band and text
   colours read off the framed page's <html> (re-read each load, so light/dark follows).
   ponytail: signal and 5G are fixed glyphs; battery is the PC's own level, 100 without one. */
function fillStatus(f, hw, box) {
  const band = hw.querySelector(".pv-status"), time = hw.querySelector(".pv-time"), bat = hw.querySelector(".pv-bat");
  let level = 100;
  const paintBat = () => {
    const fg = getComputedStyle(band).color;
    bat.textContent = level;
    // three digits: a size down with room at both ends; one or two sit left of centre, as on iOS
    const full = level >= 100;
    bat.style.fontSize = full ? "calc(var(--fs-caption) * 1.05)" : "";
    bat.style.letterSpacing = full ? "0" : "";
    bat.style.textIndent = full ? "0" : "";
    bat.style.setProperty("--pv-fg", fg);  // the nub is the band's text colour; the digits are cut out in the band's own
    bat.style.background = `linear-gradient(90deg,${fg} ${level}%,color-mix(in srgb,${fg} 50%,transparent) ${level}%)`;
    bat.style.color = band.style.backgroundColor || "#000";
  };
  const tick = () => {
    if (!box.isConnected) return clearInterval(iv);
    const d = new Date();
    time.textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  const iv = setInterval(tick, 5000);
  tick();
  if (navigator.getBattery) navigator.getBattery().then((b) => { level = Math.round(b.level * 100); paintBat(); }).catch(() => {});
  const colours = () => {
    let d;
    try { d = f.contentDocument; } catch { return; }
    if (!d || !d.documentElement) return;
    const cs = getComputedStyle(d.documentElement);
    band.style.backgroundColor = cs.backgroundColor;
    band.style.color = cs.getPropertyValue("--fg").trim() || "#fff";
    paintBat();
  };
  f.addEventListener("load", colours);
  // light/dark flipped from the gear re-themes the framed page; follow it
  document.addEventListener("hub:surfacechange", () => setTimeout(colours, 50));
}

/* The frame's own scrollbars are hidden and this bar beside the frame stands in for them
   (his pick 2026-11-07: scrollbar outside the phone frame). It follows whichever scroller
   in the frame moved last, else the biggest one, and dragging or wheeling it scrolls that.
   ponytail: one bar; two side-by-side scrolling panes show only the last one touched. */
function phoneScrollbar(f, box) {
  const track = document.createElement("div"); track.className = "pv-track";
  const thumb = document.createElement("div"); thumb.className = "pv-thumb";
  track.appendChild(thumb);
  let cur = null, picked = false;
  const doc = () => { try { return f.contentDocument; } catch { return null; } };
  const scrolls = (n) => n.scrollHeight > n.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(n).overflowY);
  function pick(d) {
    let best = d.scrollingElement, area = 0;
    d.querySelectorAll("body *").forEach((n) => {
      if (n.clientHeight * n.clientWidth > area && scrolls(n)) { best = n; area = n.clientHeight * n.clientWidth; }
    });
    const root = d.scrollingElement;
    return root && root.scrollHeight > root.clientHeight + 1 && root.clientHeight * root.clientWidth >= area ? root : best;
  }
  function draw() {
    const d = doc();
    if (!d || !d.body) return;
    if (!cur || !cur.isConnected || !picked) cur = pick(d);
    const th = track.clientHeight, sh = cur.scrollHeight, ch = cur.clientHeight;
    thumb.style.display = sh > ch + 1 ? "" : "none";
    const h = Math.max(24, th * ch / sh);
    thumb.style.height = `${h}px`;
    thumb.style.top = `${(th - h) * (cur.scrollTop / Math.max(1, sh - ch))}px`;
  }
  f.addEventListener("load", () => {
    const d = doc();
    if (!d) return;
    picked = false; cur = null;
    // an iPhone's notch and home-bar insets (390x844 class: 47 top, 34 bottom). A desktop
    // frame has none, so without these the view looked right while the phone was not
    // (2026-11-07). Overrides the --safe-t/--safe-b tokens in theme-switch.js.
    d.documentElement.style.setProperty("--safe-t", "47px");
    d.documentElement.style.setProperty("--safe-b", "34px");
    const s = d.createElement("style");
    // #sb-layer: liquid draws its own bars there (liquid-scrollbar.js), not as native scrollbars
    s.textContent = "*{scrollbar-width:none!important}*::-webkit-scrollbar{display:none!important}#sb-layer{display:none!important}";
    d.head.appendChild(s);
    d.addEventListener("scroll", (e) => {
      const t = e.target === d ? d.scrollingElement : e.target;
      if (t && t.nodeType === 1) { cur = t; picked = true; }
      draw();
    }, true);
    draw();
  });
  track.addEventListener("wheel", (e) => { if (cur) { cur.scrollTop += e.deltaY; e.preventDefault(); } }, { passive: false });
  thumb.addEventListener("pointerdown", (e) => {
    if (!cur) return;
    const y0 = e.clientY, top0 = cur.scrollTop;
    const ratio = (cur.scrollHeight - cur.clientHeight) / Math.max(1, track.clientHeight - thumb.offsetHeight);
    thumb.setPointerCapture(e.pointerId);
    const move = (m) => { cur.scrollTop = top0 + (m.clientY - y0) * ratio; };
    const up = () => { thumb.removeEventListener("pointermove", move); thumb.removeEventListener("pointerup", up); };
    thumb.addEventListener("pointermove", move);
    thumb.addEventListener("pointerup", up);
    e.preventDefault();
  });
  // React pages fill in after load and grow; a slow poll keeps the thumb honest until the view closes
  const iv = setInterval(() => { if (!box.isConnected) clearInterval(iv); else draw(); }, 500);
  return track;
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
  const [phone, setPhone] = useState(() => phoneOk() && phoneStored());
  useEffect(() => { if (phone) phoneView(true); }, []); // reopen on each page while it is on
  const setPhoneView = (on) => { phoneView(on); setPhone(on); setOpen(false); };

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
          {phoneOk() ? (
            <div className="cp-row">
              <span className="cp-lbl">view</span>
              <span className="cp-seg" role="group" aria-label="view">
                <button type="button" className="cp-seg-i" aria-pressed={!phone} onClick={() => setPhoneView(false)}>desktop</button>
                <button type="button" className="cp-seg-i cp-phone" aria-pressed={phone} onClick={() => setPhoneView(true)}>phone</button>
              </span>
            </div>
          ) : null}
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

/* ---------------- NotifyBell ----------------
   The notification bell (Workbench pick "Module icon tiles", 2026-11-10). Fetches
   /notify/api/list after mount, on focus and every 60 s while visible, each fetch
   cut at 8 s. A failed fetch keeps the last count and the pane says "unavailable";
   a 401 clears both. Titles, bodies and sources are React text only; the one
   innerHTML is the module icon from window.MODULES. NotifyBoundary keeps a render
   fault in here from taking the rest of the bar with it. */
/* Pages do not link chrome.css (theme-switch.js injects the bar's rules), so the bell carries its own
   copy, the twin of the .nb block in chrome.css. Edit both. */
const NB_CSS = `.nb { position: relative; display: flex; align-items: center; }
.nb-btn { position: relative; color: var(--fg); }
.nb-g { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.nb-pane { position: absolute; top: calc(100% + 14px); right: 0; width: 380px; max-width: calc(100vw - 20px); box-sizing: border-box; padding: 8px; z-index: 1100;
  border-radius: 24px; background: var(--lq-frost-fill, var(--bg-elev));
  backdrop-filter: blur(var(--lq-frost-blur, 40px)) saturate(180%); -webkit-backdrop-filter: blur(var(--lq-frost-blur, 40px)) saturate(180%);
  box-shadow: var(--lg-ov-rim, none), var(--lq-menu-shade, none); color: var(--fg); }
.nb-head { display: flex; align-items: center; gap: 10px; padding: 8px 10px 10px; font-size: 13px; }
.nb-head > b { font-family: var(--font-display); font-size: 15px; }
.nb-fail { color: var(--fg-dim); font-size: 12px; }
.nb-all { margin-left: auto; background: none; border: 0; color: var(--fg-dim); font: inherit; font-size: 12px; cursor: pointer; padding: 4px 6px; border-radius: 8px; }
.nb-all:hover { color: var(--fg); background: var(--line-soft); }
.nb-list { max-height: min(70vh, 520px); overflow: auto; }
.nb-grp { margin: 8px 10px 4px; font-size: 11px; letter-spacing: .06em; color: var(--fg-dim); }
.nb-row { display: flex; align-items: center; gap: 12px; padding: 9px 10px; border-radius: 14px; color: var(--fg-dim); text-decoration: none; }
.nb-row:hover { background: var(--line-soft); }
.nb-row.is-unread { color: var(--fg); }
.nb-row b { font-weight: 500; font-size: 14px; overflow-wrap: anywhere; }
.nb-row.is-unread b { font-weight: 650; }
.nb-tx { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.nb-body { font-size: 12px; color: var(--fg-dim); overflow-wrap: anywhere; }
/* source = the module's own launcher glyph in a glass tile, the row's visual anchor; accent tint while unread */
.nb-ic { flex: none; width: 36px; height: 36px; border-radius: 12px; display: grid; place-items: center; color: var(--fg-dim);
  background: var(--line-soft); box-shadow: inset 0 0 0 1px var(--line); }
.nb-ic svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; display: block; }
.nb-ic .nb-dot { fill: currentColor; stroke: none; }
.nb-row.is-unread .nb-ic { color: var(--accent); background: color-mix(in srgb, var(--accent) 18%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent); }
.nb-when { font-size: 12px; color: var(--fg-dim); white-space: nowrap; font-variant-numeric: tabular-nums; align-self: flex-start; margin-top: 4px; }
/* delete: a quiet x over the time on hover or focus; always shown where there is no hover (touch) */
.nb-item { position: relative; }
.nb-del { position: absolute; top: 6px; right: 6px; width: 32px; height: 32px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 10px;
  background: var(--bg-elev); color: var(--fg-dim); cursor: pointer; opacity: 0; }
.nb-del svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; }
.nb-item:hover .nb-del, .nb-del:focus-visible { opacity: 1; }
.nb-del:hover { color: var(--fg); background: var(--line-soft); }
.nb-del:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
@media (hover: none) { .nb-del { opacity: 1; top: 4px; right: 0; width: 44px; height: 44px; background: none; } .nb-row { padding-right: 44px; } }
.nb-badge { position: absolute; top: -3px; right: -5px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: var(--accent);
  color: var(--bg); font-size: 11px; font-weight: 700; line-height: 18px; text-align: center; box-shadow: 0 0 0 2px var(--bg); box-sizing: border-box; }
/* phone: the controls are a bottom dock, so the pane opens upward as a sheet */
@media (max-width: 640px) {
  .nb { position: static; }
  .nb-pane { position: fixed; top: auto; left: 12px; right: 12px; bottom: calc(var(--dock-gap, 16px) + 72px); width: auto; max-width: none; max-height: 62vh; overflow: auto; background: var(--bg-elev); }  /* solid on the phone, as the control pane does */
  .nb-list { max-height: none; overflow: visible; }
  .nb-all { min-height: 44px; padding: 0 12px; }  /* phone tap target */
}`;
if (!document.getElementById("nb-css")) {
  const st = document.createElement("style"); st.id = "nb-css"; st.textContent = NB_CSS; document.head.appendChild(st);
}
const NB_DOT = { __html: '<circle class="nb-dot" cx="12" cy="12" r="3"/>' };
function nbWhen(iso) {
  const d = new Date(iso), ms = Date.now() - d.getTime();
  if (!(ms >= 0)) return "";
  const m = Math.floor(ms / 60000);
  if (m < 1) return "now";
  if (m < 60) return m + "m";
  if (m < 1440) return Math.floor(m / 60) + "h";
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return "yesterday";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function nbIcon(source) {
  const mods = window.MODULES || [];
  const hit = mods.find((m) => m.name === source) || (source === "clash" ? mods.find((m) => m.name === "gaming") : null);
  return hit && hit.icon ? { __html: hit.icon } : NB_DOT;
}
/* post() allows a Hub path or an https link; a row that reached the store some other way gets no link.
   Control characters and spaces are refused because browsers strip them ("/\t/x" would become "//x"). */
function nbHref(raw) {
  if (typeof raw !== "string" || /[\x00-\x20\x7f]/.test(raw)) return "";
  return /^https:\/\/[^\/\\]/i.test(raw) || /^\/(?![\/\\])/.test(raw) ? raw : "";
}
function NotifyRow({ it, onRead, onDelete }) {
  const url = nbHref(it.url), ext = /^https:/i.test(url);
  /* an unread Hub link goes through /notify/go/<id>, which marks it read on the server and then
     redirects, so click, middle-click and new tab all mark it first. An https link opens directly
     (a new tab may not carry the Hub session) and, like a row with no link, is marked by a POST. */
  const via = url && !ext && !it.read;
  const href = via ? "/notify/go/" + it.id : url || "#";
  const click = (e) => {
    if (!url) e.preventDefault();
    if (!it.read) onRead(it.id, !via);
  };
  const aux = (e) => { if (e.button === 1 && !it.read) onRead(it.id, !via); };  // middle-click skips onClick
  /* the delete button sits beside the link, not in it (a button inside an <a> is invalid and would follow the link) */
  return (
    <div className="nb-item">
      <a className={"nb-row" + (it.read ? "" : " is-unread")} href={href} onClick={click} onAuxClick={aux}
         target={ext ? "_blank" : undefined} rel={ext ? "noopener" : undefined}>
        <span className="nb-ic" title={String(it.source)}>
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" dangerouslySetInnerHTML={nbIcon(it.source)} />
        </span>
        <span className="nb-tx"><b>{String(it.title)}</b>{it.body ? <span className="nb-body">{String(it.body)}</span> : null}</span>
        <span className="nb-when">{nbWhen(it.due_at)}</span>
      </a>
      <button type="button" className="nb-del" onClick={() => onDelete(it.id)} aria-label={"delete " + String(it.title)} title="delete">
        <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M4 4l8 8M12 4l-8 8" /></svg>
      </button>
    </div>
  );
}
function NotifyBellInner() {
  const [open, setOpen] = useState(false);
  const [st, setSt] = useState({ unread: 0, items: [], failed: false });
  const wRef = useRef(null), bRef = useRef(null);
  const gen = useRef(0);   // bumped at the start and end of every mark
  const busy = useRef(0);  // marks in flight; a list fetch is applied only when none overlapped it
  const last = useRef(0);  // the newest mark; only its answer is applied, since an older one may predate it
  const apply = (d) => setSt({ unread: Number(d.unread) || 0, items: Array.isArray(d.items) ? d.items : [], failed: false });

  useEffect(() => {
    let dead = false;
    const load = async () => {
      if (document.visibilityState !== "visible") return;
      const c = new AbortController(), t = setTimeout(() => c.abort(), 8000), g = gen.current;
      try {
        const r = await fetch("/notify/api/list", { signal: c.signal, credentials: "same-origin" });
        if (r.status === 401) { if (!dead) setSt({ unread: 0, items: [], failed: false }); return; }
        if (!r.ok) throw new Error("list " + r.status);
        const d = await r.json();
        if (!dead && g === gen.current && !busy.current) apply(d);
      } catch (e) {
        if (!dead) setSt((s) => ({ ...s, failed: true }));
      } finally { clearTimeout(t); }
    };
    load();
    const iv = setInterval(load, 60000);
    window.addEventListener("focus", load);
    return () => { dead = true; clearInterval(iv); window.removeEventListener("focus", load); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (wRef.current && !wRef.current.contains(e.target)) setOpen(false); };
    const onEsc = (e) => { if (e.key === "Escape") { setOpen(false); if (bRef.current) bRef.current.focus(); } };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onEsc); };
  }, [open]);

  const send = (path, ids) => {  // the POST answers with the fresh list, which replaces any fetch it overlapped
    gen.current++; busy.current++;
    const me = ++last.current, c = new AbortController(), t = setTimeout(() => c.abort(), 8000);  // a hung POST must not freeze the bell
    fetch(path, { method: "POST", signal: c.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }) })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null)
      .then((d) => { clearTimeout(t); busy.current--; gen.current++; if (d && !busy.current && me === last.current) apply(d); });
  };
  const readLocal = (ids) => setSt((s) => {
    const hit = s.items.filter((i) => !i.read && ids.includes(i.id)).length;
    return { ...s, unread: Math.max(0, s.unread - hit), items: s.items.map((i) => (ids.includes(i.id) ? { ...i, read: true } : i)) };
  });
  const mark = (ids) => send("/notify/api/read", ids);
  const onRead = (id, post) => { gen.current++; readLocal([id]); if (post) mark([id]); };
  const onDelete = (id) => {  // no confirm, as he asked: the row goes at once
    gen.current++;
    setSt((s) => ({ ...s, unread: Math.max(0, s.unread - s.items.filter((i) => i.id === id && !i.read).length),
      items: s.items.filter((i) => i.id !== id) }));
    send("/notify/api/delete", [id]);
  };
  const readAll = () => {  // the ids shown, from one snapshot: a row that came due since stays unread
    const ids = st.items.filter((i) => !i.read).map((i) => i.id);
    if (ids.length) { readLocal(ids); mark(ids); }
  };
  const fresh = st.items.filter((i) => !i.read), older = st.items.filter((i) => i.read);
  const n = st.unread;
  return (
    <div className="nb" ref={wRef} data-open={open}>
      <button type="button" ref={bRef} className="launcher launcher-icon nb-btn" onClick={() => setOpen((o) => !o)}
        aria-haspopup="dialog" aria-expanded={open} aria-label={"notifications, " + n + " unread"} title="notifications">
        <svg className="nb-g" viewBox="0 0 18 18" aria-hidden="true"><path d="M9 2.2c-2.6 0-4.5 2-4.5 4.6v2.7L3 12.3h12l-1.5-2.8V6.8C13.5 4.2 11.6 2.2 9 2.2Z" /><path d="M7.2 14.4a1.9 1.9 0 0 0 3.6 0" /></svg>
        {n ? <span className="nb-badge">{n > 99 ? "99+" : n}</span> : null}
      </button>
      <HubCollapse open={open} float>
        <div className="nb-pane" role="dialog" aria-label="notifications">
          <div className="nb-head"><b>notifications</b>
            {st.failed ? <span className="nb-fail">unavailable</span> : null}
            {n && !st.failed ? <button type="button" className="nb-all" onClick={readAll}>mark all read</button> : null}</div>
          <div className="nb-list">
            {fresh.length ? <p className="nb-grp">new</p> : null}
            {fresh.map((i) => <NotifyRow key={i.id} it={i} onRead={onRead} onDelete={onDelete} />)}
            {older.length ? <p className="nb-grp">earlier</p> : null}
            {older.map((i) => <NotifyRow key={i.id} it={i} onRead={onRead} onDelete={onDelete} />)}
            {!st.items.length && !st.failed ? <p className="nb-grp nb-empty">nothing yet</p> : null}
          </div>
        </div>
      </HubCollapse>
    </div>
  );
}
class NotifyBoundary extends React.Component {
  constructor(p) { super(p); this.state = { bad: false }; }
  static getDerivedStateFromError() { return { bad: true }; }
  render() { return this.state.bad ? null : this.props.children; }
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
        {modules.length ? <NotifyBoundary><NotifyBellInner /></NotifyBoundary> : null}
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
            : <a className="hub-btn hub-dot reconnect" style={{ "--dot-color": "var(--warn-dim)" }}
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
