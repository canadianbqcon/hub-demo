/* liquid scroll bar (Workbench hub-scrollbar-2 pick, 2026-10-19: "Stretching droplet in the liquid groove").
   Loaded on every page by theme-switch.js; liquid-scrollbar.css shows it only while the theme is liquid,
   and other themes keep their native bars.
   Each scroller's native bar is hidden and a rail is drawn over its right edge: a permanent frosted groove
   with a clear glass droplet in it. A scroller marked data-sb-out gets its rail just past its right edge instead. The droplet runs on one per-frame spring, never per scroll event: a mouse
   wheel moves the page in fixed steps, and a thumb set straight from each step jumps. It glides to where the
   page is and stretches with the glide's own speed, so it swells and settles without spikes.
   A scroller inside a card (Workbench hub-scrollbar-in-card pick, 2026-10-20: "Rim that lights only while you
   scroll", with the wide grip) gets a second kind of bar: a thin lit stretch of the card's right rim, nearly dark
   at rest, lit while the card scrolls or the pointer is on it, over an 18px grip that swells into a pill on hover
   and glides the card to wherever the rim is pressed. */
(function () {
  var K = 320, C = 2 * Math.sqrt(K);   // critically damped: settles without overshoot
  var layer = document.createElement("div"); layer.id = "sb-layer"; document.body.appendChild(layer);
  var bars = [], doc = document.scrollingElement, PAD = 26;   // PAD keeps a rim bar clear of the card's rounded corners
  function scrollable(el) {
    // cheap layout checks first; a pane that hides its own bar (scrollbar-width:none) keeps it hidden
    if (el.scrollHeight <= el.clientHeight + 4 || el.clientHeight <= 120) return false;
    var s = getComputedStyle(el);
    return /(auto|scroll)/.test(s.overflowY) && s.scrollbarWidth !== "none";
  }
  // inside a card: the scroller or a near ancestor is a rounded box with its own fill or glass. The page never is.
  function card(sc) {
    if (sc === doc) return null;
    for (var el = sc, i = 0; el && el !== document.body && i < 5; el = el.parentElement, i++) {
      var s = getComputedStyle(el);
      if (parseFloat(s.borderTopLeftRadius) >= 10 && (!/rgba\(0, 0, 0, 0\)|transparent/.test(s.backgroundColor) || s.backdropFilter !== "none")) return el;
    }
    return null;
  }
  function make(sc) {
    sc.classList.add("sb-host");
    var cd = card(sc);
    var rail = document.createElement("div"); rail.className = "sb-rail" + (cd ? " sb-sub" : "");
    rail.innerHTML = '<div class="sb-thumb"><i class="sb-spec"></i></div>';
    layer.appendChild(rail);
    var b = { sc: sc, cd: cd, rail: rail, thumb: rail.firstChild, y: null, vy: 0, s: 0, drag: false, out: sc.hasAttribute("data-sb-out"), quiet: 0 };
    (sc === doc ? window : sc).addEventListener("scroll", function () { b.quiet = performance.now() + 900; run(); }, { passive: true });
    if (cd) {
      cd.addEventListener("pointerenter", function () { rail.classList.add("sb-near"); });
      cd.addEventListener("pointerleave", function () { rail.classList.remove("sb-near"); });
      // a press on the rim itself (not the thumb) glides the card to that spot
      rail.addEventListener("pointerdown", function (e) {
        if (e.target !== rail) return;
        var g = geo(b), r = rail.getBoundingClientRect();
        sc.scrollTo({ top: (e.clientY - r.top - g.th / 2) / Math.max(1, g.H - g.th) * g.max, behavior: "smooth" });
      });
    }
    rail.addEventListener("pointerenter", function () { rail.classList.add("sb-hover"); });
    rail.addEventListener("pointerleave", function () { rail.classList.remove("sb-hover"); });
    b.thumb.addEventListener("pointerdown", function (e) {
      e.preventDefault(); b.thumb.setPointerCapture(e.pointerId); rail.classList.add("sb-drag"); b.drag = true;
      var y0 = e.clientY, s0 = sc.scrollTop;
      function mv(ev) { var g = geo(b); sc.scrollTop = s0 + (ev.clientY - y0) * g.max / Math.max(1, g.H - g.th); }
      function up() { rail.classList.remove("sb-drag"); b.drag = false; b.thumb.removeEventListener("pointermove", mv); b.thumb.removeEventListener("pointerup", up); }
      b.thumb.addEventListener("pointermove", mv); b.thumb.addEventListener("pointerup", up);
    });
    // a scroller that changes width with the page unchanged (mail's list widening as a thread closes) re-places its rail
    if (sc !== doc) sized.observe(sc);
    bars.push(b); run();
  }
  // the page itself scrolls on a phone: the rail runs between the top bar and the dock
  function rect(b) { return b.sc === doc ? { top: 90, height: innerHeight - 180, right: innerWidth } : b.sc.getBoundingClientRect(); }
  function geo(b) {
    var sc = b.sc, r = rect(b), pad = b.cd ? PAD : 6, H = r.height - 2 * pad;
    return { r: r, pad: pad, H: H, th: Math.max(b.cd ? 24 : 36, H * sc.clientHeight / sc.scrollHeight), max: sc.scrollHeight - sc.clientHeight };
  }
  function layout(b) {
    var g = geo(b), rail = b.rail;
    // a scroller that left the page, or no longer overflows, loses its rail
    if (!g.r.height || !b.sc.isConnected || g.max <= 4) { rail.style.display = "none"; return null; }
    rail.style.display = "";
    // a card's rail is centred on the card's right rim (its 18px grip straddles the edge)
    var left = b.cd ? b.cd.getBoundingClientRect().right - 9 : g.r.right + (b.out ? 2 : -14);
    rail.style.top = (g.r.top + g.pad) + "px"; rail.style.height = g.H + "px"; rail.style.left = left + "px";
    b.thumb.style.height = g.th + "px";
    return g;
  }
  var running = false, last = 0;
  function run() { if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); } }
  function frame(now) {
    var dt = Math.min(1 / 30, (now - last) / 1000) || 1 / 60, live = false; last = now;
    bars.forEach(function (b) {
      var g = layout(b); if (!g) return;
      var target = g.max > 0 ? b.sc.scrollTop / g.max * (g.H - g.th) : 0;
      if (b.y === null || b.drag) { b.y = target; b.vy = 0; }
      else { b.vy += (K * (target - b.y) - C * b.vy) * dt; b.y += b.vy * dt; }
      // the spring can carry a fast flick past the end: hold the thumb inside its track and drop that speed
      var span = g.H - g.th;
      if (b.y < 0 || b.y > span) { b.y = Math.max(0, Math.min(span, b.y)); b.vy = 0; }
      // stretch eases toward the glide speed (px/s), so a wheel step swells and settles in one smooth curve
      b.s += (Math.min(1, Math.abs(b.vy) / 800) - b.s) * (1 - Math.exp(-dt / 0.09));
      // it never grows the thumb past the track, and grows from the end it is nearest, so it stays inside
      b.s = Math.min(b.s, Math.max(0, (g.H / g.th - 1) / 0.4));
      b.thumb.style.transformOrigin = "50% " + (span > 0 ? b.y / span * 100 : 50).toFixed(1) + "%";
      var busy = now < b.quiet;
      b.rail.classList.toggle("sb-live", busy || b.drag);
      if (busy || Math.abs(target - b.y) > 0.3 || Math.abs(b.vy) > 2 || b.s > 0.004) live = true; else { b.y = target; b.vy = 0; b.s = 0; }
      // the translate property, not transform: transform sits inside the scale, so a stretched thumb's offset was scaled too and it overshot the track
      b.thumb.style.translate = "0 " + b.y.toFixed(2) + "px";
      b.rail.style.setProperty("--sb-v", b.s.toFixed(3));
    });
    if (live) requestAnimationFrame(frame); else running = false;
  }
  function scan() {
    queued = false;
    if (!doc.classList.contains("sb-host") && doc.scrollHeight > innerHeight + 4) make(doc);
    document.querySelectorAll("body *").forEach(function (el) {
      if (!el.classList.contains("sb-host") && el.id !== "sb-layer" && !el.closest("#sb-layer") && scrollable(el)) make(el);
    });
  }
  // pages render their panes after load, so scan on the frame after any change: a poll left the
  // native bar showing until its next tick. Content that grows without a DOM change (images) still
  // shows up through the resize observer, and the slow poll is the backstop.
  var queued = false;
  var sized = new ResizeObserver(function () { run(); });
  function soon() { if (!queued) { queued = true; requestAnimationFrame(scan); } run(); }
  scan();
  new MutationObserver(soon).observe(document.body, { childList: true, subtree: true });
  new ResizeObserver(soon).observe(document.body);
  addEventListener("resize", soon);
  setInterval(soon, 3000);
})();
