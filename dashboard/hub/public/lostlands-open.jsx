/* The open Lost Lands page body (2026-10-13): React port of the inline script that
   used to sit in lostlands-open.html. The hallmark module itself (hallmark.js ->
   window.TripHallmark[trip.id]) is unchanged: it still returns an HTML string from
   render(ctx) and wires it in wire(root, ctx), so this file only does what the
   inline script did, in the same order. Template globals: LL_ASSET, LL_TRIP. */
(() => {
const { useEffect, useRef } = React;

/* Same contract as the inline script: ticks live in localStorage under
   trips.hallmark.<trip id>, this browser only. */
function makeCtx(t) {
  const KEY = `trips.hallmark.${t.id}`;
  const ticks = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; } };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  return {
    trip: t, crew: t.members || [], esc, todayISO, viewer: "", isGuest: true,
    ticks: ticks(),
    ticked: (k) => !!ticks()[k],
    tick: (k, on) => { const v = ticks(); if (on) v[k] = on === true ? 1 : on; else delete v[k]; try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* private mode */ } },
    reload: () => location.reload(),
  };
}

/* A render error shows the same words the load fallback does. */
class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("lostlands-open", e); }
  render() { return this.state.failed ? <div className="ll-open-s">The page failed to load. Reload while you have signal.</div> : this.props.children; }
}

function Body() {
  const t = window.LL_TRIP, h = window.TripHallmark?.[t.id];
  const root = useRef(null), off = useRef(null);
  useEffect(() => {
    const el = root.current;
    if (!h) { el.textContent = "The page failed to load. Reload while you have signal."; return; }
    const ctx = makeCtx(t);
    el.innerHTML = h.render(ctx) || "";
    const counts = () => {
      el.querySelectorAll("[data-hmcount]").forEach((c) => {
        const boxes = el.querySelectorAll(`[data-hmtick][data-hmgroup="${c.dataset.hmcount}"]`);
        let n = 0;
        boxes.forEach((b) => { if (b.checked) n++; });
        c.textContent = boxes.length ? `${n} of ${boxes.length}` : "";
        c.classList.toggle("docount-all", boxes.length > 0 && n === boxes.length);
      });
    };
    el.querySelectorAll("[data-hmtick]").forEach((b) => {
      b.checked = ctx.ticked(b.dataset.hmtick);
      b.onchange = () => { ctx.tick(b.dataset.hmtick, b.checked); counts(); };
    });
    counts();
    if (typeof h.wire === "function") { try { h.wire(el, ctx); } catch (e) { console.error("hallmark wire", e); } }
    el.setAttribute("data-react-mounted", "lostlands-open");

    /* Offline. The worker is served from under this page's own path (LL_ASSET is
       <that path>f/), so it controls this page and nothing else on the site. */
    const base = window.LL_ASSET.replace(/f\/$/, "");
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).then(() => navigator.serviceWorker.ready).then(() => {
        if (off.current) off.current.textContent = "Saved on this phone. It opens with no signal from this same link.";
      }).catch(() => { if (off.current) off.current.textContent = ""; });
    }
  }, []);
  return (
    <main className="ll-open">
      <h1 className="ll-open-h" data-llopen-title>{h ? h.title || "" : ""}</h1>
      <div className="ll-open-s" data-llopen-sub>{h ? h.sub || "" : ""}</div>
      <div className="ll-open-off" data-llopen-off ref={off}></div>
      <div className="hm" data-llopen-root ref={root}></div>
    </main>
  );
}

const host = document.getElementById("ll-react-root");
host.textContent = "";  // the template's static copy is only the load fallback
ReactDOM.createRoot(host).render(<Boundary><Body /></Boundary>);
})();
