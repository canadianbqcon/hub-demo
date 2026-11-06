/* Shared Hub chrome, loaded by every React surface (home, purchases, work):
   trip card, news card, resizable stack, always-see tab. The top
   bar, the status strip and useDialogA11y live in topbar.jsx, which every page
   loads, React or not. Modified for Flask static serving:
   asset paths updated.

   The today-briefing subsystem that used to live here (day view, weather,
   briefing caps, ~940 lines) moved to today.jsx on 2026-07-29. Only the home
   page consumes it, so purchases and work were each loading it for nothing.
   Keep it that way: anything home-only belongs in today.jsx, not here.
*/

const { useState, useEffect } = React;

/* ---------------- relAgo ----------------
   honest relative-time label off an epoch-ms timestamp (e.g. window.GENERATED_AT).
   pass the ticking `now` Date so the label updates live as time passes. */
function relAgo(thenMs, now) {
  if (!thenMs) return "—";
  const secs = Math.max(0, Math.floor((now.getTime() - thenMs) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/* ---------------- SplitterBar ----------------
   thin horizontal handle the user drags to resize adjacent stacked panels.
   onDrag fires with deltaY (pixels) while the user holds the mouse down. */
function SplitterBar({ onDrag }) {
  const onMouseDown = (e) => {
    e.preventDefault();
    let lastY = e.clientY;
    const move = (ev) => {
      const delta = ev.clientY - lastY;
      lastY = ev.clientY;
      if (delta !== 0) onDrag(delta);
    };
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };
  return (
    // Mouse-drag resize only, not focusable or keyboard-operable, so the
    // separator role (which requires aria-valuenow/min/max once focusable)
    // would be a half-implemented ARIA widget — plain div instead.
    <div
      className="splitter"
      onMouseDown={onMouseDown}
      title="drag to resize"
    />
  );
}

/* ---------------- ResizableStack ----------------
   vertical stack of N children with N-1 draggable splitters between them.
   layout is share-based: each child gets a flex-grow ratio. dragging a
   splitter steals ratio from one neighbour and gives it to the other.

   props:
     id            — namespaces localStorage for persisted ratios
     initialRatios — array of N floats; defaults to equal share
     minRatio      — floor each panel can shrink to (default 0.06 = 6% of stack)
*/
const { useRef } = React;
function ResizableStack({ id, children, initialRatios, minRatio = 0.06 }) {
  const stackRef = useRef(null);
  const kids = React.Children.toArray(children);
  const n = kids.length;

  const storageKey = id ? `hub.stack.${id}` : null;
  const [ratios, setRatios] = useState(() => {
    if (storageKey) {
      try {
        const stored = JSON.parse(localStorage.getItem(storageKey));
        if (Array.isArray(stored) && stored.length === n) return stored;
      } catch {}
    }
    if (initialRatios && initialRatios.length === n) return initialRatios;
    return new Array(n).fill(1 / n);
  });

  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(ratios)); } catch {}
  }, [ratios, storageKey]);

  const onDrag = (idx, deltaPx) => {
    if (!stackRef.current) return;
    const totalH = stackRef.current.offsetHeight;
    if (totalH <= 0) return;
    const dr = deltaPx / totalH;
    setRatios((rs) => {
      const next = rs.slice();
      const sum = rs[idx] + rs[idx + 1];
      let a = rs[idx] + dr;
      let b = rs[idx + 1] - dr;
      if (a < minRatio) { b = sum - minRatio; a = minRatio; }
      if (b < minRatio) { a = sum - minRatio; b = minRatio; }
      next[idx] = a;
      next[idx + 1] = b;
      return next;
    });
  };

  if (n === 1) {
    return <>{kids[0]}</>;
  }

  return (
    <div className="resizable-stack" ref={stackRef}>
      {kids.map((c, i) => (
        <React.Fragment key={i}>
          <div className="rs-cell" style={{ flex: `${ratios[i]} ${ratios[i]} 0` }}>
            {c}
          </div>
          {i < n - 1 && <SplitterBar onDrag={(d) => onDrag(i, d)} />}
        </React.Fragment>
      ))}
    </div>
  );
}

/* ---------------- AlwaysSeeTab ----------------
   Generic, dashboard-agnostic pinned drawer. A one-line handle under the topbar;
   expands as an overlay on top of the scroll region (never pushes content down);
   no scrim (close via chevron or Esc). Opens by default on the first load of each
   new local day, then respects the user's toggle for the rest of that day. */
function AlwaysSeeTab({ storageKey, summary, now, children }) {
  const BL = window.BriefingLogic;
  const openKey = `hub.ast.${storageKey}.open`;
  const dayKey = `hub.ast.${storageKey}.day`;
  const todayStr = BL.localDayString(now);

  const [open, setOpen] = useState(() => {
    let storedDay = null, persisted = false;
    try {
      storedDay = localStorage.getItem(dayKey);
      persisted = localStorage.getItem(openKey) === "1";
    } catch {}
    const shouldOpen = BL.shouldDefaultOpen(storedDay, persisted, todayStr);
    return shouldOpen;
  });

  // New-day check, keyed on the ticking date string. Fires once when the day
  // flips (idempotent via the stored-day compare), so a session left open across
  // midnight re-opens. Not mount-only; GENERATED_AT never changes post-load.
  useEffect(() => {
    let storedDay = null;
    try { storedDay = localStorage.getItem(dayKey); } catch {}
    if (storedDay !== todayStr) {
      setOpen(true);
      try { localStorage.setItem(dayKey, todayStr); localStorage.setItem(openKey, "1"); } catch {}
    }
  }, [todayStr]);

  // Esc closes.
  useEffect(() => {
    if (!open) return;
    const onEsc = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [open]);

  const toggle = () => {
    setOpen((o) => {
      const next = !o;
      try {
        localStorage.setItem(openKey, next ? "1" : "0");
        localStorage.setItem(dayKey, todayStr);
      } catch {}
      return next;
    });
  };

  return (
    <div className={`always-see${open ? " is-open" : ""}`}>
      <button type="button" className="ast-handle" onClick={toggle} aria-expanded={open}>
        <span className="ast-summary">{summary}</span>
        <span className="ast-chevron">{open ? "▴" : "▾"}</span>
      </button>
      <HubCollapse open={open} float>
        <div className="ast-panel">
          <div className="ast-panel-inner">{children}</div>
        </div>
      </HubCollapse>
    </div>
  );
}

/* ---------------- TripCard ---------------- */
function TripCard({ trip }) {
  return (
    <div className="panel fixed">
      <div className="panel-head">
        {/* h3 — nested under the "schedule" column head, not a peer section */}
        <h3 className="panel-title">next trip</h3>
        <span className="panel-meta">→ trips</span>
      </div>
      <div className="panel-body">
        {trip ? (
          <a className="trip" href={trip.url || "/trips/"}>
            <div>
              <div className="trip-days">{trip.days}<span className="trip-days-unit">days</span></div>
            </div>
            <div>
              <div className="trip-dest">{trip.dest}</div>
              <div className="trip-window">
                {trip.window}{trip.nights ? ` · ${trip.nights} night${trip.nights === 1 ? "" : "s"}` : ""}
                {trip.with?.length ? ` · with ${trip.with.join(", ")}` : ""}
              </div>
            </div>
            <span className="trip-arrow" aria-hidden="true">→</span>
            {trip.window ? (
              <div className="trip-facts">
                <div className={`trip-fact${trip.flight ? "" : " is-open"}`}><span className="trip-fact-k">flight</span>{trip.flight || "not booked"}</div>
                <div className={`trip-fact${trip.stay ? "" : " is-open"}`}><span className="trip-fact-k">stay</span>{trip.stay || "not booked"}</div>
              </div>
            ) : null}
          </a>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------- NewsCard ----------------
   Same shape as TripCard: a headline count on the left, the digest's first
   line on the right, the whole row a link to /news/. news is null until
   /api/home resolves (see App.jsx's progressive fetch), same as trip. */
function NewsCard({ news }) {
  return (
    <div className="panel fixed">
      <div className="panel-head">
        <h3 className="panel-title">news</h3>
        <span className="panel-meta">→ news</span>
      </div>
      <div className="panel-body">
        {news ? (
          <a className="news-summary" href="/news/">
            <div>
              <div className="news-count">{news.clusters_today}<span className="news-count-unit">stories</span></div>
            </div>
            <div>
              <div className="news-line">{news.digest_line || "no digest yet"}</div>
            </div>
            <span className="news-arrow" aria-hidden="true">→</span>
          </a>
        ) : null}
      </div>
    </div>
  );
}

Object.assign(window, { relAgo, SplitterBar, ResizableStack, AlwaysSeeTab, TripCard, NewsCard });
