/* App — owns the clock tick and the home panels. The top bar (surface toggle,
   theme picker, module launcher) is the shared <Topbar> from topbar.jsx. */

const { useState: appUseState, useEffect: appUseEffect } = React;

// Stable empty defaults so every panel renders an instant skeleton while /api/home
// is in flight — and so a referentially-new array isn't handed down on each 1s
// clock tick (which would make Tasks' sync effect re-fire).
const EMPTY_SCHEDULE = [];
const EMPTY_CARDS = [];
const EMPTY_SUBS = [];
const EMPTY_TASKS = [];
const EMPTY_SNAPSHOTS = {};

// One titled home panel. A title is optional: most components draw their own head.
function Panel({ section, title, children, className = "" }) {
  return (
    <section className={`lp ${className}`} data-section={section}>
      {title ? <header className="lp-head"><h2 className="lp-title">{title}</h2></header> : null}
      {children}
    </section>
  );
}

function App() {
  const [now, setNow] = appUseState(() => new Date());
  // Set whenever /api/home fails so a dead endpoint reads as broken instead of
  // silently rendering the same empty skeleton as a genuinely-empty day.
  const [apiError, setApiError] = appUseState(false);
  // Which day the today zone is focused on (YYYY-MM-DD). Defaults to today; the
  // header's arrows and the forward Schedule both drive it. Ephemeral — resets to
  // today on reload.
  const localDayStr = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  const [selectedIso, setSelectedIso] = appUseState(() => localDayStr(new Date()));

  // Progressive load. The shell document inlines null data (see _shell_data in
  // app.py), so this starts null and fetches /api/home after first paint. If a
  // build ever inlines live data again (window.SCHEDULE set), we adopt it directly
  // and skip the fetch.
  const [home, setHome] = appUseState(() =>
    window.SCHEDULE != null
      ? {
          SCHEDULE: window.SCHEDULE, TRIP: window.TRIP, NEWS: window.NEWS,
          CARDS: window.CARDS, SUBS: window.SUBS, TASKS: window.TASKS,
          TASKS_COMPLETED: window.TASKS_COMPLETED,
        }
      : null
  );

  // Re-fetch /api/home and re-render (used after a task completes in the today zone,
  // and as the retry action on the error banner). A non-2xx or a dropped network both
  // land in .catch — either one means the panels below may be stale/empty, not truly
  // empty, so apiError flips on and the banner (rendered in the JSX below) tells the
  // truth instead of leaving every panel's skeleton looking like a genuinely quiet day.
  const refresh = () => {
    fetch("/api/home")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => {
        d.RECEIVED_AT = Date.now();
        window.GENERATED_AT = d.GENERATED_AT;
        window.CONNECTORS = d.CONNECTORS;
        setHome(d);
        setApiError(false);
      })
      .catch(() => setApiError(true));
  };

  appUseEffect(() => {
    if (home) return;
    let cancelled = false;
    fetch("/api/home")
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((d) => {
        if (cancelled) return;
        // StatusStrip reads window.CONNECTORS; set it before the re-render so the
        // connector dots update too.
        d.RECEIVED_AT = Date.now();
        window.GENERATED_AT = d.GENERATED_AT;
        window.CONNECTORS = d.CONNECTORS;
        setHome(d);
        setApiError(false);
      })
      .catch(() => { if (!cancelled) setApiError(true); });
    return () => { cancelled = true; };
  }, []);

  // tick
  appUseEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  // The three today-scoped caps — today's calendar (LEFT), the done recap
  // (MIDDLE), and bring+due (RIGHT) — must all end on the same row, so
  // "tomorrow" (left), "cards" (middle), and the active/completed tabs
  // (right) all start flush together. This used to be a ~100-line
  // ResizeObserver+ref recompute effect that measured each column and
  // patched in inline padding/min-height — it kept drifting on edge cases
  // (rounds 8, 9, 11 in git history) because it was re-deriving, in JS, what
  // CSS grid already does natively: a shared row track auto-sizes to the
  // tallest item placed in it. `.col-pre` (everything above the divider) is
  // grid-row 1 and `.col-rest-divider` (the divider + everything after) is
  // grid-row 2, both on a subgrid shared with the other two columns (see
  // home.css `.body`/`.col`) — the divider lands on the same pixel row in
  // all three columns with no measuring.

  // NYC weather fetched once here; shared by the today zone + footer strip.
  const wx = useNycWeather();

  const h = home || {};
  const todayIso = localDayStr(now);

  // Two different things can put something other than live data on this page, and
  // they are not the same sentence to the reader.
  //
  // 1. The whole page came out of the browser's own saved copy, because the Hub
  //    itself was unreachable (phone off the tailnet). GENERATED_AT is stamped
  //    server-side when the payload is built, RECEIVED_AT when it lands here, so a
  //    payload that was ALREADY old on arrival is the tell. Measured against
  //    arrival and never against the live clock: `now` ticks every second while
  //    GENERATED_AT is frozen at the one fetch on mount, so the old
  //    `now - GENERATED_AT` test made any tab left open past two minutes announce
  //    itself as offline (2026-09-03). Two minutes is slack for a slow request,
  //    not a freshness policy. Nothing on the page can be saved in this state.
  // 2. The Hub answered normally, but the machine it runs on has no route out, so
  //    only the outward-facing panels (calendar, subscriptions, card balances) are
  //    the saved copy. CACHED_AT says when they were taken; everything else on the
  //    page is live off local disk and IS still editable. See _last_good/_cached_at
  //    in home_data.py.
  const staleMs = h.GENERATED_AT && h.RECEIVED_AT ? h.RECEIVED_AT - h.GENERATED_AT : 0;
  const savedPage = staleMs > 120000;
  const offlineNote = savedPage
    ? `offline — this is the saved copy from ${relAgo(h.GENERATED_AT, now)}. nothing you change here will stick.`
    : h.CACHED_AT
      ? `no internet — calendar and money are from ${relAgo(h.CACHED_AT, now)}. everything else is current.`
      : null;

  // Derive the whole today zone once (pure); the header + the three column caps
  // each consume a slice. selectedIso drives which day the zone shows.
  const view = computeTodayView({
    now,
    schedule: h.SCHEDULE || EMPTY_SCHEDULE,
    wx,
    tasks: h.TASKS || EMPTY_TASKS,
    cards: h.CARDS || EMPTY_CARDS,
    snapshots: h.BRIEFING_SNAPSHOTS || EMPTY_SNAPSHOTS,
    selectedIso,
    todayIso,
  });

  return (
    <div className="hub-shell shell" data-screen-label="home dashboard">
      <Topbar />

      {/* Home: a today row (today panel left; weather and glance cards right, both
          ending on one line) then three columns of titled panels. Each Panel
          carries data-section so the layout tests can name it. Recap left the page
          2026-09-03; log/daily-recap.md is still written, nothing here reads it. */}
      <div className="scroll-region">
        {apiError && (
          <div className="hub-error hub-error-home" role="alert">
            couldn't reach /api/home — panels below may be stale or empty, not actually clear.
            <button type="button" className="hub-btn hub-error-retry" onClick={refresh}>retry</button>
          </div>
        )}
        {!apiError && offlineNote && (
          <div className="hub-error hub-error-home" role="status">
            {offlineNote}
            <button type="button" className="hub-btn hub-error-retry" onClick={refresh}>retry</button>
          </div>
        )}
        <main className="lh-main">
          <div className="lh-top">
            <Panel section="today" className="lp-today">
              <WeekStrip view={view} onSelectDay={setSelectedIso} />
              <TodayHeader
                view={view}
                now={now}
                onSelectDay={setSelectedIso}
                schedule={h.SCHEDULE || EMPTY_SCHEDULE}
                wx={wx}
                todayIso={todayIso}
              />
              <TodayCalendarCap view={view} now={now} />
            </Panel>
            <div className="lh-top-r">
              <Panel section="weather" className="lp-wx"><DayWeather view={view} /></Panel>
              <div className="lp-glance" data-section="glance">
                <GettingThere view={view} now={now} />
                <TodayPrepCap view={view} onRefresh={refresh} />
              </div>
            </div>
          </div>
          <div className="lh-three">
            <div className="lh-stack">
              <Panel section="week" title="week ahead" className="lp-week">
                <Schedule schedule={h.SCHEDULE || EMPTY_SCHEDULE} selectedIso={selectedIso} onSelectDay={setSelectedIso} view="forward" />
              </Panel>
            </div>
            <div className="lh-stack">
              <Panel section="cards"><CreditCards cards={h.CARDS || EMPTY_CARDS} now={now} syncedAt={h.CARDS_SYNCED_AT} /></Panel>
              <Panel section="subs" className="lp-subs"><Subscriptions subs={h.SUBS || EMPTY_SUBS} /></Panel>
              {/* under subscriptions (2026-11-03 mark "move to middle column under subscriptions") */}
              <Panel section="trip" className="lp-trip"><TripCard trip={h.TRIP || null} /></Panel>
              <Panel section="news" className="lp-news"><NewsCard news={h.NEWS || null} /></Panel>
            </div>
            <div className="lh-stack">
              <Panel section="planner" className="lp-planner">
                <Tasks initial={h.TASKS || EMPTY_TASKS} initialCompleted={h.TASKS_COMPLETED || EMPTY_TASKS} hideDueThrough={todayIso} title="planner" />
              </Panel>
            </div>
          </div>
        </main>
      </div>

      <StatusStrip />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
