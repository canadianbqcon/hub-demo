/* Mark mode entry: a "Mark this page" row in the gear's control pane (window.HubMark below); a bar
   with no control pane gets the old cap first in .topbar-r, and no bar at all a fixed cap.
   Click opens /marks/frame for this page. Plain JS, fail open: a throw leaves the page untouched. */
(() => {
  try {
    if (!window.matchMedia || !matchMedia("(pointer:fine)").matches) return;
    // top-level pages only: inside the mark-mode frame the frame page owns the UI, and
    // previews and warm-up iframes elsewhere are not pages he marks
    if (location.pathname.indexOf("/marks/frame") === 0 || window.top !== window) return;
    if (!document.querySelector('link[href*="marks.css"]')) {
      const l = document.createElement("link");
      l.rel = "stylesheet"; l.href = "/static/css/marks.css";
      document.head.appendChild(l);
    }
    const PENCIL = '<svg class="mk-g" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20 L5.5 14.5 L15.5 4.5 L19.5 8.5 L9.5 18.5 Z"/><path d="M13.5 6.5 L17.5 10.5"/></svg><span>Mark</span>';
    function make() {
      var b = document.createElement("button");
      b.className = "mk-entry"; b.type = "button"; b.setAttribute("aria-label", "Mark"); b.innerHTML = PENCIL;
      b.addEventListener("click", enter);
      return b;
    }
    // the layer is drawn straight over this page, no iframe copy, so nothing on it reloads;
    // Exit on the same page just removes the layer
    // the hash too: hash-routed pages (jobs #app/939) replay and pin per view
    const here = () => location.pathname + location.search + location.hash;
    // a link followed in Cursor mode loads a new page: the session rides sessionStorage and mark mode reopens there
    const store = (k, v) => { try { if (v === undefined) return sessionStorage.getItem(k); if (v === null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch { return null; } };
    function enter(carried) {
      if (document.documentElement.classList.contains("mk-inpage")) return;
      const go = () => { window.top.location = `/marks/frame?u=${encodeURIComponent(here())}`; };
      if (!window.React || !window.ReactDOM) return go(); // no React on this page: the old full-page frame
      document.documentElement.classList.add("mk-inpage");
      const named = typeof carried === "string" ? Promise.resolve({ session: carried })
        : fetch("/marks/api/session").then((r) => r.json()).catch(() => ({}));
      named.then((j) => {
        // the session name is fixed on entry, so a retried first save lands in the same session
        if (j.session) document.body.setAttribute("data-session", j.session); else document.body.removeAttribute("data-session");
        if (j.session) store("mk.session", j.session);
        if (typeof carried !== "string") store("mk.next", null);
        const ui = window.MarksFrameUI = window.MarksFrameUI || {};
        ui.close = close; ui.live = true;
        if (ui.mount) return ui.mount();
        const s = document.createElement("script");
        s.src = "/jsx/marks/frontend/static/frame.jsx"; s.onerror = () => { close(); go(); };
        document.body.appendChild(s); // mounts itself on load
      });
    }
    // Exit from the frame: true when it ended on this page and the frame is gone; false sends the top window there
    function close(u) {
      if (u && u !== here()) return false;
      const ui = window.MarksFrameUI;
      if (ui.root) { ui.root.unmount(); ui.root = null; }
      store("mk.session", null); store("mk.next", null);
      document.documentElement.classList.remove("mk-inpage");
      return true;
    }
    // the gear's control pane (topbar.jsx ControlPane) draws the Mark row from this
    window.HubMark = { enter: () => enter() };
    function place() {
      if (document.querySelector(".control-pane")) return true;
      var bar = document.querySelector(".topbar-r");
      if (!bar || document.querySelector(".mk-entry")) return !!bar;
      bar.insertBefore(make(), bar.firstChild);
      return true;
    }
    function fixed() {
      if (document.querySelector(".mk-entry")) return;
      var b = make(); b.classList.add("mk-entry--fixed");
      document.body.appendChild(b);
    }
    const carried = store("mk.session");
    if (carried) enter(carried);
    if (place()) return;
    // Forge has no Hub top bar at all, so there is nothing to wait for
    if (/^\/forge(\/|$)/.test(location.pathname)) return fixed();
    // React pages mount the bar later: watch up to 5s, then fall back to a fixed cap at bottom right
    const mo = new MutationObserver(() => { if (place()) { mo.disconnect(); clearTimeout(t); } });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    const t = setTimeout(() => { mo.disconnect(); fixed(); }, 5000);
  } catch { /* fail open */ }
})();
