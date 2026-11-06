/* mark mode frame page body (React). Ported from static/js/marks-frame.js: same DOM, classes and request bodies.
   The page is a full-viewport iframe#mk-frame (kept in the template) with a drawing layer and the bottom pill
   as its body siblings, so both are portalled into <body> exactly where the plain script appended them.
   The engine below keeps the plain script's mutable state and DOM measuring; React only draws from its snapshot.
   Fails open: an error leaves the framed page untouched. */
window.MarksFrameUI = window.MarksFrameUI || {};
(() => {
  const { useState, useEffect, useLayoutEffect, useRef } = React;

  const TOOLS = [
    ["Cursor", '<path d="M6 3.5 L6 18 L10 14.2 L12.8 20.5 L15.2 19.4 L12.5 13.3 L18 13 Z"/>'],
    ["Box", '<rect x="4" y="5" width="16" height="14" rx="1.5" stroke-dasharray="3 2.4"/>'],
    ["Element", '<rect x="3.5" y="3.5" width="12" height="12" rx="1.5"/><path d="M12 12 L20.5 15 L16.8 16.8 L15 20.5 Z"/>'],
    ["Arrow", '<path d="M5 19 L18 6"/><path d="M10.5 6 H18 V13.5"/>'],
    ["Pen", '<path d="M4 17 C7 9 10 20 13 12 S18 6 20 9"/>'],
    ["Link", '<path d="M10 14 L14 10"/><path d="M8.5 11.5 L6.5 13.5 A3.2 3.2 0 0 0 11 18 L13 16"/><path d="M15.5 12.5 L17.5 10.5 A3.2 3.2 0 0 0 13 6 L11 8"/>'],
  ];
  const EXIT_X = '<path d="M6 6 L18 18"/><path d="M18 6 L6 18"/>';
  const STYLE = ["font-family", "font-size", "font-weight", "color", "background-color", "padding", "margin", "gap", "border-radius", "display"];
  const MAX_SHOTS = 24 * 1024 * 1024; // under the server's 25MB cap: the dev server resets rather than answer 413

  // ---- pure helpers ----
  function selOf(el) {
    const parts = [];
    let n = 0;
    while (el && el.nodeType === 1 && n < 5) {
      if (el.id) { parts.unshift(`#${CSS.escape(el.id)}`); break; }
      let s = el.tagName.toLowerCase();
      if (typeof el.className === "string" && el.className.trim())
        s += `.${el.className.trim().split(/\s+/).map((c) => CSS.escape(c)).join(".")}`;
      let i = 1, p = el;
      while ((p = p.previousElementSibling)) if (p.tagName === el.tagName) i++;
      parts.unshift(`${s}:nth-of-type(${i})`);
      el = el.parentElement; n++;
    }
    return parts.join(" > ");
  }
  // a shape as SVG path data: shared by the layer and the canvas that draws it on the full shot
  function shapePath(kind, pts) {
    const a = pts[0], b = pts[pts.length - 1];
    let d = `M${a.x} ${a.y}`;
    if (kind === "pen") return pts.slice(1).reduce((s, p) => `${s} L${p.x} ${p.y}`, d);
    d += ` L${b.x} ${b.y}`;
    if (kind === "arrow") {
      const t = Math.atan2(b.y - a.y, b.x - a.x), h = 14;
      d += " M" + (b.x - h * Math.cos(t - 0.45)) + " " + (b.y - h * Math.sin(t - 0.45)) + " L" + b.x + " " + b.y +
        " L" + (b.x - h * Math.cos(t + 0.45)) + " " + (b.y - h * Math.sin(t + 0.45));
    }
    return d;
  }
  function bounds(pts, pad) {
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const x = Math.min.apply(null, xs) - pad, y = Math.min.apply(null, ys) - pad;
    return { x, y, w: Math.max.apply(null, xs) + pad - x, h: Math.max.apply(null, ys) + pad - y };
  }
  const norm = (a, b) => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) });
  const png = (c) => new Promise((ok) => c.toBlob(ok, "image/png"));
  function pageStore(w) { // ponytail: small non-look localStorage entries only, 1 KB each and 16 KB total
    const out = {};
    let total = 0;
    try {
      for (let i = 0; i < w.localStorage.length; i++) {
        const k = w.localStorage.key(i), v = w.localStorage.getItem(k);
        if (k.indexOf("hub.") === 0 || v.length > 1024 || total + v.length > 16384) continue;
        out[k] = v; total += v.length;
      }
    } catch { /* storage blocked: the re-render opens the default view */ }
    return out;
  }
  // over the live page the layer and pill share its document: point hits skip them
  const ours = (e) => !!e.closest?.(".mk-layer, .mkA-pill, .mk-entry");
  function post(url, body) {
    return fetch(url, { method: "POST", body }).then((r) => {
      if (r.status >= 400 && r.status < 500 && r.status !== 401 && r.status !== 429) return { status: r.status };
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  // ---- engine: the plain script's state and measuring; `bump` asks React to redraw from snap() ----
  function createEngine(fr, bump, els) {
    let stream = null, vid = null, capOn = false;
    let session = document.body.getAttribute("data-session") || null;
    const marks = [], queue = [];
    let drag = null, note = null, flushing = null;
    let rejected = 0, lastUrl = "/", exitArmed = false, grabbing = 0, leaving = null;
    // over a live page the count carries across a followed link (marks.js clears it on a fresh entry)
    let nextN = 1;
    try { if (fr.live) nextN = +sessionStorage.getItem("mk.next") || 1; } catch { /* storage blocked: labels restart at 1 */ }
    let tool = "box", linkPick = null, hover = null;

    const win = () => fr.contentWindow;
    // a page that navigated off the Hub cannot be read: fall back to the last Hub page seen
    function curUrl() { try { const l = win().location; return (lastUrl = l.pathname + l.search + l.hash); } catch { return lastUrl; } }

    // DOM context: elementsFromPoint on a 3x3 grid across the rect
    function elements(r, lead) {
      const d = fr.contentDocument, w = win(), seen = lead ? [lead] : [];
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
        const x = r.x + r.w * (i + 0.5) / 3, y = r.y + r.h * (j + 0.5) / 3;
        d.elementsFromPoint(x, y).forEach((e) => {
          if (seen.indexOf(e) < 0 && !ours(e) && e !== d.body && e !== d.documentElement && e.id !== "root" && e.id !== "app") seen.push(e);
        });
      }
      return seen.slice(0, 6).map((e) => {
        const cs = w.getComputedStyle(e), st = {}, b = e.getBoundingClientRect();
        STYLE.forEach((k) => { st[k] = cs.getPropertyValue(k); });
        return { selector: selOf(e), tag: e.tagName.toLowerCase(), text: (e.textContent || "").trim().slice(0, 80),
          html: e.outerHTML.slice(0, 500), rect: { x: b.x, y: b.y, w: b.width, h: b.height }, style: st };
      });
    }

    // scrolling boxes: the window plus any inner pane the page scrolls
    function scrollable(e, w) {
      const s = w.getComputedStyle(e);
      return /auto|scroll/.test(s.overflowY + s.overflowX) && (e.scrollHeight > e.clientHeight || e.scrollWidth > e.clientWidth);
    }
    const topAt = (p) => fr.contentDocument.elementsFromPoint(p.x, p.y).find((e) => !ours(e)) || null;
    // the scrolling boxes around viewport point p, innermost first
    function panesAt(p) {
      const w = win(), d = fr.contentDocument, out = [];
      for (let e = topAt(p); e && e !== d.body && e !== d.documentElement; e = e.parentElement) if (scrollable(e, w)) out.push(e);
      return out;
    }
    // a mark's scroll offset: the window plus every box it sits in. A box is re-found by selector after the page reloads
    function offset(m) {
      const w = win(), o = { x: w.scrollX, y: w.scrollY };
      (m.panes || []).forEach((q) => {
        if (!q.el.isConnected) try { q.el = fr.contentDocument.querySelector(q.sel) || q.el; } catch { /* bad selector: keep the dead ref */ }
        if (q.el.isConnected) { o.x += q.el.scrollLeft; o.y += q.el.scrollTop; }
      });
      return o;
    }
    // a mark is pinned to the smallest element that held its whole rect, as fractions of that
    // element's box, so a window resize that reflows the page carries the mark with it.
    // ponytail: falls back to page coordinates when the element is gone or has no size
    function anchorOf(r) {
      const d = fr.contentDocument, w = win();
      for (let e = topAt({ x: r.x + r.w / 2, y: r.y + r.h / 2 }); e && e !== d.body && e !== d.documentElement; e = e.parentElement) {
        if (scrollable(e, w)) return null; // a scroll box's own rect ignores its scroll: page coordinates track that
        const b = e.getBoundingClientRect();
        if (b.width && b.height && b.left <= r.x + 1 && b.top <= r.y + 1 && b.right >= r.x + r.w - 1 && b.bottom >= r.y + r.h - 1)
          return { el: e, sel: selOf(e), b: { x: b.left, y: b.top, w: b.width, h: b.height } };
      }
      return null;
    }
    function anchorBox(m) {
      const a = m.anchor;
      if (!a) return null;
      if (!a.el.isConnected) try { a.el = fr.contentDocument.querySelector(a.sel) || a.el; } catch { /* bad selector */ }
      if (!a.el.isConnected) return null;
      const b = a.el.getBoundingClientRect();
      return b.width && b.height ? b : null;
    }
    // map a save-time viewport point through the anchor's old box onto its box now
    const remap = (a, b, p) => ({ x: b.left + (p.x - a.b.x) * b.width / a.b.w, y: b.top + (p.y - a.b.y) * b.height / a.b.h });
    const view = (m) => {
      const b = anchorBox(m);
      if (b) { const a = m.anchor, p = remap(a, b, a.r); return { x: p.x, y: p.y, w: a.r.w * b.width / a.b.w, h: a.r.h * b.height / a.b.h }; }
      const o = offset(m); return { x: m.page.x - o.x, y: m.page.y - o.y, w: m.page.w, h: m.page.h };
    };
    // a mark scrolled out of its box is hidden, so it never floats over the header
    function shown(m, r) {
      const q = m.panes?.[0];
      if (!q?.el.isConnected) return true;
      const b = q.el.getBoundingClientRect();
      return r.x < b.right && r.x + r.w > b.left && r.y < b.bottom && r.y + r.h > b.top;
    }
    // saved marks are kept in page coordinates (viewport + every scroll offset); only the current page's are drawn
    function savedMarks() {
      const out = [], u = curUrl();
      try { win().scrollX; } catch { return out; } // page off the Hub: no pins
      marks.forEach((m, i) => {
        if (m.url !== u) return;
        const o = offset(m), r = view(m);
        let at = r, path = null, box = null;
        if (!shown(m, r)) return;
        if (m.pts) {
          const b = anchorBox(m);
          const v = b ? m.anchor.pts.map((p) => remap(m.anchor, b, p)) : m.pts.map((p) => ({ x: p.x - o.x, y: p.y - o.y }));
          path = shapePath(m.kind, v);
          at = v[m.kind === "link" ? v.length - 1 : 0];
        } else box = r;
        out.push({ key: i, path, box, label: m.n || "•", at });
      });
      return out;
    }
    // marks taken but not yet on disk: still being shot, or queued for upload
    const pending = () => grabbing + queue.length;
    function status() {
      if (!pending()) exitArmed = false;
      // Exit pressed while saving over a live page: the layer is hidden, and the real exit runs once the queue is empty
      if (leaving && !pending()) { clearInterval(leaving); leaving = null; exit(); return; }
      bump();
    }

    // ---- tab capture: a held getDisplayMedia stream, any failure falls back to server re-render ----
    function stopCap() {
      if (stream) stream.getTracks().forEach((t) => { t.stop(); });
      if (vid) vid.remove();
      stream = vid = null; capOn = false; bump();
    }
    function startCap() {
      try {
        const md = navigator.mediaDevices;
        if (!md?.getDisplayMedia || !("requestVideoFrameCallback" in HTMLVideoElement.prototype)) return;
        md.getDisplayMedia({ video: { displaySurface: "browser", width: { ideal: innerWidth * devicePixelRatio }, height: { ideal: innerHeight * devicePixelRatio } },
          preferCurrentTab: true, selfBrowserSurface: "include" }).then((s) => {
          const t = s.getVideoTracks()[0];
          if (t?.getSettings().displaySurface !== "browser") { s.getTracks().forEach((x) => { x.stop(); }); return; }
          vid = document.createElement("video");
          vid.muted = true; vid.srcObject = s;
          vid.style.cssText = "position:fixed;left:0;top:0;width:2px;height:2px;opacity:0;pointer-events:none";
          document.body.appendChild(vid);
          stream = s; capOn = true; bump();
          t.addEventListener("ended", stopCap);
          return vid.play();
        }).catch(() => { stopCap(); /* declined: stay on re-render */ });
      } catch { stopCap(); }
    }
    // a video frame captured after the hidden layer was painted (two rAFs). A static tab sends frames
    // ~600ms apart, so counting two callbacks under a 600ms timeout grabbed the box about half the time;
    // the timeout only keeps a tab that sends nothing from hanging the save
    const freshFrame = () => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => {
      const t0 = performance.now(), t = setTimeout(ok, 2000);
      const f = (now, md) => { if (md.captureTime == null || md.captureTime > t0) { clearTimeout(t); ok(); } else vid.requestVideoFrameCallback(f); };
      vid.requestVideoFrameCallback(f);
    })));
    // resolves {full} as a PNG blob with the mark drawn on it like a highlighter, or null to fall back
    // to re-render; the server cuts the before crop from it (a padded frame around rect r, frame viewport coords)
    function grab(r, s) {
      if (!stream || !vid?.videoWidth) return Promise.resolve(null);
      els.layer.style.visibility = els.pill.style.visibility = "hidden";
      return freshFrame().then(() => {
        const sx = vid.videoWidth / innerWidth, sy = vid.videoHeight / innerHeight;
        const full = document.createElement("canvas"); full.width = vid.videoWidth; full.height = vid.videoHeight;
        const fx = full.getContext("2d"); fx.drawImage(vid, 0, 0);
        const ink = getComputedStyle(document.documentElement).getPropertyValue("--mk-ink").trim() || "#E5173F";
        fx.strokeStyle = fx.fillStyle = ink;
        // paths are scaled by the transform, so their width is set after it; the rect is scaled by hand
        if (s.pts) {
          fx.scale(sx, sy); fx.lineJoin = fx.lineCap = "round";
          const d = new Path2D(shapePath(s.kind, s.pts));
          fx.globalAlpha = 0.3; fx.lineWidth = 12; fx.stroke(d);
          fx.globalAlpha = 1; fx.lineWidth = 2; fx.stroke(d);
        } else {
          fx.globalAlpha = 0.18; fx.fillRect(r.x * sx, r.y * sy, r.w * sx, r.h * sy);
          fx.globalAlpha = 1; fx.lineWidth = 2 * Math.max(sx, sy); fx.strokeRect(r.x * sx, r.y * sy, r.w * sx, r.h * sy);
        }
        // toBlob gives null on a canvas too big to encode: fall back to re-render
        return png(full).then((b) => (b ? { full: b } : null));
      }).catch(() => null).then((res) => {
        els.layer.style.visibility = els.pill.style.visibility = ""; return res;
      });
    }

    // ---- upload: sequential. A 4xx refusal drops that one mark, except 401 (login expired) and
    // 429, which stay queued like a Hub outage; 413 resends it without its shots (server re-renders) ----
    function flush() {
      if (flushing) return flushing;
      flushing = (function next() {
        if (!queue.length) return Promise.resolve();
        const m = queue[0];
        // the frame page carries the session name; cid lets the server spot a retried save
        const fd = new FormData();
        if (session) m.meta.session = session;
        fd.append("meta", JSON.stringify(m.meta));
        if (m.shots && m.shots.full.size > MAX_SHOTS) { m.shots = null; m.meta.capture = "rerender"; }
        if (m.shots) fd.append("full", m.shots.full, "full.png");
        return post("/marks/api/mark", fd).then((j) => {
          if (j.status === 413 && m.shots) { m.shots = null; m.meta.capture = "rerender"; return next(); }
          queue.shift();
          if (j.status) { rejected++; marks.splice(marks.indexOf(m), 1); }
          else {
            session = j.session || session; m.n = j.n; nextN = j.n + 1;
            try { if (fr.live) sessionStorage.setItem("mk.next", nextN); } catch { /* storage blocked */ }
          }
          status(); return next();
        });
      })().catch(() => { /* Hub down: stay queued, retry on next save or Exit */ }).then(() => { flushing = null; status(); });
      return flushing;
    }

    // ---- tools and comment ----
    const dropDrag = () => { if (drag) { drag = null; bump(); } };
    const dropHover = () => { if (hover) { hover = null; bump(); } };
    const dropPick = () => { if (linkPick) { linkPick = null; bump(); } };
    const closeNote = () => { if (note) { note = null; bump(); } };
    function underPointer(p) {
      const e = topAt(p);
      return e && e !== fr.contentDocument.body && e !== fr.contentDocument.documentElement && e.id !== "root" && e.id !== "app" ? e : null;
    }
    // the saved mark of this page under the pointer (newest wins); unsaved marks have no number to link to
    function markAt(p) {
      const u = curUrl();
      let hit = null;
      marks.forEach((m) => {
        if (m.url !== u || m.n == null) return;
        const r = view(m);
        if (shown(m, r) && p.x >= r.x - 6 && p.x <= r.x + r.w + 6 && p.y >= r.y - 6 && p.y <= r.y + r.h + 6) hit = m;
      });
      return hit;
    }
    // s = {kind, r (viewport rect), pts (arrow/pen/link, viewport), live ({r} or {d}: the shape to keep drawn), lead, linked_to}
    function openNote(s) {
      const r = s.r;
      note = { s, label: nextN + queue.length, // the server numbers marks; this is its next number
        left: Math.max(8, Math.min(r.x, innerWidth - 390)), top: Math.max(8, Math.min(r.y + r.h + 10, innerHeight - 130)), inp: null };
      bump();
    }
    function pickElement(p) {
      const e = underPointer(p);
      if (!e) return;
      hover = null;
      const b = e.getBoundingClientRect(), r = { x: b.x, y: b.y, w: b.width, h: b.height };
      openNote({ kind: "element", r, live: { r }, lead: e });
    }
    function pickLink(p) {
      const m = markAt(p);
      if (!m || (linkPick && linkPick.m === m)) return;
      const r = view(m);
      if (!linkPick) { linkPick = { m, r }; bump(); return; }
      const f = linkPick.m, fr0 = view(f);
      const c = (q) => ({ x: q.x + q.w / 2, y: q.y + q.h / 2 });
      linkPick = null;
      // the link mark sits on the second mark and points back at the first ("make this match that")
      openNote({ kind: "link", r, pts: [c(fr0), c(r)], linked_to: f.n });
    }
    function onDown(e) {
      try {
        if (e.button !== 0 || note) return;
        window.focus();
        const p = { x: e.clientX, y: e.clientY };
        if (tool === "element") return pickElement(p);
        if (tool === "link") return pickLink(p);
        els.layer.setPointerCapture(e.pointerId);
        drag = { a: p, pts: [p], r: norm(p, p), d: `M${p.x} ${p.y}` };
        bump();
      } catch { drag = null; }
    }
    function onMove(e) {
      try {
        const p = { x: e.clientX, y: e.clientY };
        if (drag) {
          if (tool === "box") drag.r = norm(drag.a, p);
          else {
            const last = drag.pts[drag.pts.length - 1];
            if (tool === "arrow") drag.pts = [drag.a, p];
            else if (Math.hypot(p.x - last.x, p.y - last.y) >= 3 && drag.pts.length < 600) drag.pts.push(p);
            drag.d = shapePath(tool, drag.pts);
          }
          bump();
        } else if (tool === "element" && !note) {
          const t = underPointer(p);
          if (!t) return dropHover();
          const b = t.getBoundingClientRect();
          hover = { x: b.x, y: b.y, w: b.width, h: b.height };
          bump();
        }
      } catch { dropDrag(); }
    }
    function onUp(e) {
      try {
        if (!drag) return;
        const d = drag, p = { x: e.clientX, y: e.clientY };
        drag = null;
        if (tool === "box") {
          const r = norm(d.a, p);
          if (r.w < 4 || r.h < 4) bump(); else openNote({ kind: "box", r, live: { r: d.r } });
          return;
        }
        const pts = tool === "arrow" ? [d.a, p] : d.pts.concat([p]);
        const bb = bounds(pts, 6);
        // ponytail: a click without a drag is too short to be a line; 8px for arrows, 3 samples for pen
        if (tool === "arrow" ? Math.hypot(p.x - d.a.x, p.y - d.a.y) < 8 : pts.length < 3) bump();
        else openNote({ kind: tool, r: bb, pts, live: { d: d.d } });
      } catch { dropDrag(); }
    }
    // the framed page still scrolls while the layer is over it. Hub pages scroll an inner pane, not the
    // window, so the wheel goes to the innermost box under the cursor that can still move that way
    function onWheel(e) {
      try {
        let dx = e.deltaX, dy = e.deltaY;
        const k = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? innerHeight : 1;
        dx *= k; dy *= k;
        const t = panesAt({ x: e.clientX, y: e.clientY }).filter((el) =>
          (dy > 0 && el.scrollTop + el.clientHeight < el.scrollHeight - 1) || (dy < 0 && el.scrollTop > 0) ||
          (dx > 0 && el.scrollLeft + el.clientWidth < el.scrollWidth - 1) || (dx < 0 && el.scrollLeft > 0))[0];
        (t || win()).scrollBy(dx, dy);
      } catch { /* page off the Hub: nothing to scroll */ }
    }
    function save() {
      const s = note.s, r = s.r, comment = note.inp.value.trim(), w = win(), d = fr.contentDocument;
      // every scrolled pane, so the server re-render can put the page back where it was
      const scrolled = [].filter.call(d.querySelectorAll("*"), (e) => e.scrollTop || e.scrollLeft).slice(0, 20)
        .map((e) => ({ sel: selOf(e), x: e.scrollLeft, y: e.scrollTop }));
      const meta = { cid: Date.now().toString(36) + Math.random().toString(36).slice(2, 8), url: curUrl(), title: d.title, viewport: { w: w.innerWidth, h: w.innerHeight }, dpr: w.devicePixelRatio,
        scroll: { x: w.scrollX, y: w.scrollY, panes: scrolled }, kind: s.kind, rect: r, comment, capture: "rerender", elements: elements(r, s.lead),
        // theme, surface and glass, so a server re-render looks like what he saw
        look: { theme: d.documentElement.getAttribute("data-theme"), surface: d.documentElement.getAttribute("data-surface"), glass: d.documentElement.getAttribute("data-glass") },
        // the page's remembered view (open tab, picked day), so a re-render opens the same tab
        store: pageStore(w) };
      if (s.pts) meta.points = s.pts;
      if (s.linked_to != null) meta.linked_to = s.linked_to;
      closeNote();
      // the mark rides the boxes under its centre, so it moves with their content
      const m = { url: meta.url, kind: s.kind, n: null, meta,
        panes: panesAt({ x: r.x + r.w / 2, y: r.y + r.h / 2 }).map((e) => ({ el: e, sel: selOf(e) })) };
      const o = offset(m), pg = (p) => ({ x: p.x + o.x, y: p.y + o.y });
      m.page = { x: r.x + o.x, y: r.y + o.y, w: r.w, h: r.h }; m.pts = s.pts?.map(pg);
      const an = anchorOf(r);
      if (an) m.anchor = Object.assign(an, { r, pts: s.pts });
      grabbing++; status();
      grab(r, s).then((shots) => {
        if (shots) { meta.capture = "tab"; }
        m.shots = shots; grabbing--;
        marks.push(m); queue.push(m); flush(); status();
      });
    }

    // ---- Exit and keys ----
    // a mark still saving holds Exit: the button asks "Exit anyway?" and a second Exit drops it.
    // The question clears itself once everything lands
    function exit() {
      // over a live Hub page the saves carry on in the background: hide now, finish the exit when they land
      // (2026-11-03 mark: "the saves stop me, can you just save in the background"). A Hub outage retries every 5s.
      if (pending() && fr.live) { if (!leaving) { leaving = setInterval(flush, 5000); flush(); } bump(); return; }
      if (pending() && !exitArmed) { exitArmed = true; flush(); status(); return; }
      // origin-anchored: a framed path like "//evil.com" must not become a protocol-relative URL
      stopCap();
      const u = curUrl();
      // opened over a Hub page (marks.js) and still on it: drop the frame, no reload
      if (window.MarksFrameUI.close?.(u)) return;
      top.location = location.origin + u;
    }
    function key(e) {
      try {
        // layer handed back to the page: its keys are the page's own
        if (e.isComposing || (tool === "cursor" && !note)) return;
        // stopPropagation: over a live Hub page its own Escape handlers share this document
        if (e.key === "Enter" && note) { e.preventDefault(); e.stopPropagation(); save(); }
        else if (e.key === "Escape") {
          e.preventDefault(); e.stopPropagation();
          if (note) closeNote(); else if (drag) dropDrag(); else if (linkPick) dropPick(); else exit();
        }
      } catch { closeNote(); dropDrag(); }
    }
    // a tool button picks the tool; Cursor hands the page back (layer off) until another tool is picked
    function pickTool(name) { dropDrag(); dropHover(); dropPick(); tool = name; bump(); }

    // ---- follow the framed page: pins, scroll, keys ----
    function onFrameLoad() {
      try {
        closeNote(); dropDrag(); curUrl();
        // capture: a pane's scroll does not bubble, and this also catches the window's
        fr.contentDocument.addEventListener("scroll", bump, { capture: true, passive: true });
        fr.contentDocument.addEventListener("keydown", key, true);
        win().addEventListener("resize", bump); // a reflow moves the anchors: redraw the pins
        bump();
      } catch { /* cross-origin page: pins stay hidden */ }
    }
    // a followed link unloads the live page itself: hold it while a mark is still saving
    const holdUnload = (e) => { if (pending()) e.preventDefault(); };
    if (fr.live) addEventListener("beforeunload", holdUnload);
    // the live page outlives the layer: take its listeners back off on Exit
    function detach() {
      fr.contentDocument.removeEventListener("scroll", bump, { capture: true });
      fr.contentDocument.removeEventListener("keydown", key, true);
      try { win().removeEventListener("resize", bump); } catch { /* page gone */ }
      removeEventListener("beforeunload", holdUnload);
    }

    return {
      onDown, onMove, onUp, onWheel, startCap, exit, key, pickTool, onFrameLoad, detach,
      setInp(el) { if (note) note.inp = el; },
      snap() {
        const saved = marks.length - queue.length, n = pending(); // refused marks were already taken out of marks
        const saving = n > 0 && (grabbing > 0 || !!flushing);
        return { tool, drag, hover, linkPick, note, capOn, exitArmed, saving, n, away: !!leaving,
          count: n ? `${n} unsaved` : `${saved} saved${rejected ? `, ${rejected} refused` : ""}`,
          warn: !saving && (n > 0 || rejected > 0), saved: savedMarks() };
      },
    };
  }

  // ---- view ----
  const place = (r) => ({ left: `${r.x}px`, top: `${r.y}px`, width: `${r.w}px`, height: `${r.h}px` });
  const Pin = ({ label, x, y, saved }) => (
    <span className={`mk-pin${saved ? " mk-saved" : ""}`} style={{ left: `${x}px`, top: `${y}px` }}>{label}</span>
  );
  const Glyph = ({ d }) => <svg className="mk-g" viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: d }} />;

  function Frame({ fr }) {
    const [, setTick] = useState(0);
    const layerRef = useRef(null), pillRef = useRef(null);
    const els = useRef({ layer: null, pill: null }).current;
    const eng = useRef(null);
    if (!eng.current) eng.current = createEngine(fr, () => setTick((t) => t + 1), els);
    const E = eng.current, S = E.snap();

    useLayoutEffect(() => { els.layer = layerRef.current; els.pill = pillRef.current; }, []);
    // a press on the bar is the bar's own: the page underneath never sees it, so an open menu
    // stays open while he picks a tool (2026-11-03 mark). preventDefault on mousedown keeps focus put.
    useEffect(() => {
      const el = pillRef.current;
      const own = (e) => { e.stopPropagation(); if (e.type === "mousedown") e.preventDefault(); };
      ["pointerdown", "mousedown", "touchstart"].forEach((t) => el.addEventListener(t, own));
      return () => ["pointerdown", "mousedown", "touchstart"].forEach((t) => el.removeEventListener(t, own));
    }, []);
    useEffect(() => {
      document.body.setAttribute("data-react-mounted", "marks-frame");
      document.addEventListener("keydown", E.key, true);
      if (fr.live) { E.onFrameLoad(); return E.detach; }
      fr.addEventListener("load", E.onFrameLoad);
      if (fr.contentDocument && fr.contentDocument.readyState === "complete" && fr.contentWindow.location.href !== "about:blank")
        fr.dispatchEvent(new Event("load"));
      return () => { document.removeEventListener("keydown", E.key, true); fr.removeEventListener("load", E.onFrameLoad); };
    }, []);
    // the comment field takes focus when a note opens
    const noteKey = S.note;
    useLayoutEffect(() => { if (noteKey?.inp) noteKey.inp.focus(); }, [noteKey]);

    const live = S.note?.s.live;
    const liveBox = (r, style) => <div className="mk-box mk-box--live" style={Object.assign(place(r), style)} />;
    const d = S.drag;
    const layer = (
      <div className={`mk-layer${S.tool === "cursor" ? " mk-layer--off" : ""}${S.away ? " mk-away" : ""}`} ref={layerRef}
        onPointerDown={E.onDown} onPointerMove={E.onMove} onPointerUp={E.onUp} onWheel={E.onWheel}>
        <svg className="mk-svg" aria-hidden="true">
          {d && S.tool !== "box" && <path d={d.d} />}
          {live?.d && <path d={live.d} />}
          {S.saved.filter((s) => s.path).map((s) => <path key={s.key} d={s.path} className="mk-saved" />)}
        </svg>
        {d && S.tool === "box" && liveBox(d.r)}
        {live?.r && liveBox(live.r)}
        {S.hover && liveBox(S.hover, { pointerEvents: "none" })}
        {S.linkPick && liveBox(S.linkPick.r)}
        {S.saved.map((s) => [
          s.box && <div key={`b${s.key}`} className="mk-box mk-box--saved mk-saved" style={place(s.box)} />,
          <Pin key={`p${s.key}`} label={s.label} x={s.at.x} y={s.at.y} saved />,
        ])}
        {S.note && (
          <div className="mk-note" style={{ left: `${S.note.left}px`, top: `${S.note.top}px` }}>
            <Pin label={S.note.label} x={0} y={0} />
            <div>
              <input className="mk-field" type="text" aria-label="Comment" ref={E.setInp} />
              <p className="mk-hint">Enter saves · Esc discards</p>
            </div>
          </div>
        )}
      </div>
    );
    const pill = (
      <div className={`mkA-pill${S.away ? " mk-away" : ""}`} ref={pillRef}>
        {TOOLS.map(([name, g]) => (
          <button key={name} className={`mk-tool${S.tool === name.toLowerCase() ? " is-on" : ""}`} type="button"
            data-tool={name.toLowerCase()} aria-label={name} onClick={() => E.pickTool(name.toLowerCase())}
            title={name === "Cursor" ? "Use the page: click its buttons and links" : undefined}>
            <Glyph d={g} /><span>{name}</span>
          </button>
        ))}
        <span className="mk-sep"></span>
        <button className="mk-tool mk-capbtn" type="button" hidden={S.capOn} onClick={E.startCap}
          title="Shoot marks from this tab, so open menus show. Off, the server re-renders the page">Capture tab</button>
        <span className="mk-cap" hidden={!S.capOn}><i className="mk-dot"></i><b>Capturing</b></span>
        <span className={`mk-count${S.saving ? " is-saving" : ""}${S.warn ? " is-warn" : ""}`}>
          {S.saving ? <><i className="mk-spin" aria-hidden="true"></i>Saving <b>{S.n}</b></> : S.count}
        </span>
        <button className={`mk-exit${S.exitArmed ? " is-armed" : ""}`} type="button" onClick={E.exit}>
          <Glyph d={EXIT_X} /><span>{S.exitArmed ? "Exit anyway?" : "Exit"}</span>
        </button>
      </div>
    );
    return <>{ReactDOM.createPortal(layer, document.body)}{ReactDOM.createPortal(pill, document.body)}</>;
  }

  // fail open: an error leaves the framed page untouched
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { bad: false }; }
    static getDerivedStateFromError() { return { bad: true }; }
    componentDidCatch(e) { console.error("marks frame", e); }
    render() { return this.state.bad ? null : this.props.children; }
  }

  function mount() {
    // marks.js over a live page has no iframe: the page itself stands in for the frame's window and document
    const fr = window.MarksFrameUI.live ? { live: true, contentWindow: window, contentDocument: document } : document.getElementById("mk-frame");
    if (!fr) return;
    // the root is detached: the layer and pill are portalled into <body> beside the iframe; kept so an in-page Exit can unmount it
    const root = window.MarksFrameUI.root = ReactDOM.createRoot(document.createElement("div"));
    root.render(<Boundary><Frame fr={fr} /></Boundary>);
  }
  window.MarksFrameUI.mount = mount;
  mount();
})();
