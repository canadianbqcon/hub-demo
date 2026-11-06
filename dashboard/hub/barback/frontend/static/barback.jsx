/* barback.jsx — the "bar back" panel of the juniper & co page (/jc/).

   The sub-tabs ARE the jobs: opening · closing · stock check. Selecting one
   starts (or resumes) that run for the current bar-day and shows its list —
   there is no day heading, no weekday cadence strip and no run-card layer in
   between, because Sam works a shift already knowing which shift it is:
   "It's not gonna read based on day. I just get to select what I need to do."

   Low boy fill is not a fourth tab. It is the item-level detail of opening, so
   it renders as a collapsed section INSIDE the opening tab, at the top — it is
   the first thing done on the floor. Collapsed is what lets it lead: 67 product
   rows expanded above the shift steps would drown them (the same altitude rule
   that keeps the two templates separate in the DB).

   It renders CONTENT ONLY. Page chrome — topbar, theme/surface controls,
   module launcher, the primary tab bar — belongs to the umbrella shell.
*/
const { useState: bUseState, useEffect: bUseEffect, useCallback: bUseCallback } = React;
const BAPI = "/barback/api/barback";

async function bUnwrap(res) { const j = await res.json(); if (j.status !== "ok") throw new Error(j.message || "request failed"); return j.data; }
async function bGet(path) { return bUnwrap(await fetch(BAPI + path)); }
async function bSend(method, path, body) {
  return bUnwrap(await fetch(BAPI + path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }));
}

// Tab key IS the template key — one less mapping to keep in step.
const BB_TABS = [
  ["opening_barback", "opening"],
  ["closing_barback", "closing"],
  ["stock_check", "stock check"],
];

function BarbackPanel() {
  const [tab, setTab] = bUseState(BB_TABS[0][0]);
  return (
    <React.Fragment>
      <div className="jc-subtabs" role="tablist" aria-label="bar back runs">
        {BB_TABS.map(([key, label]) => (
          <button key={key} className="jc-tab" type="button" role="tab"
                  aria-selected={tab === key} tabIndex={tab === key ? 0 : -1}
                  onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {/* key= remounts on switch, which resets run state without a single effect */}
      <main className="bb-main">
        <RunView key={tab} templateKey={tab} />
      </main>
    </React.Fragment>
  );
}

function Loading({ label }) { return <div className="bb-loading"><span className="bb-spinner" aria-hidden="true"></span>{label || "loading…"}</div>; }
// Load failure previously had no recovery but a page refresh — shared .hub-error
// banner + retry affordance (matches purchases/App.jsx pattern) fixes that.
function Failed({ msg, onRetry }) {
  return (
    <div className="hub-error" style={{ margin: 16 }}>
      Couldn't load: {msg}
      {onRetry && <button type="button" className="hub-error-retry" onClick={onRetry}>Retry</button>}
    </div>
  );
}

/* Start-or-resume a template's run for the current bar-day, then tick its items
   optimistically. POST /run is idempotent per (template, bar_date), so selecting
   a tab twice resumes rather than duplicating. onSaved(runId) fires after a tick
   lands server-side — the sweep is the only thing that needs it. */
function useRun(templateKey, onSaved) {
  const [run, setRun] = bUseState(null);
  const [err, setErr] = bUseState(null);

  const load = bUseCallback(async () => {
    setErr(null);
    try { setRun(await bSend("POST", "/run", { key: templateKey })); }
    catch (e) { setErr(String(e.message || e)); }
  }, [templateKey]);
  bUseEffect(() => { load(); }, [load]);

  // explicitState lets a stock row's long-press/Shift+Enter reset land on "open"
  // directly, since the forward tap cycle never returns there on its own.
  const tick = (item, explicitState) => {
    const L = window.BarbackLogic;
    const next = explicitState || (
      run.kind === "stock" ? L.nextStockState(item.state)
        : run.kind === "fill" ? L.nextFillState(item.state)
        : L.nextDutyState(item.state));
    setRun(r => ({ ...r, items: r.items.map(i => i.id === item.id ? { ...i, state: next } : i) }));  // optimistic
    bSend("PUT", `/run/item/${item.id}`, { state: next })
      .then(() => { if (onSaved) onSaved(run.id); })
      .catch(() => { setRun(r => ({ ...r, items: r.items.map(i => i.id === item.id ? { ...i, state: item.state } : i) })); setErr("save failed — reverted"); });
  };

  return { run, err, tick, reload: load };
}

/* One tab's run. Opening carries the low boy fill underneath it. */
function RunView({ templateKey }) {
  const { run, err, tick, reload } = useRun(templateKey);
  const [lowout, setLowout] = bUseState(null);
  const [lowoutErr, setLowoutErr] = bUseState(null);

  if (err) return <Failed msg={err} onRetry={reload} />;
  if (!run) return <Loading label="loading run…" />;

  const isStock = run.kind === "stock";
  const prog = window.BarbackLogic.summarizeProgress(run.items);

  return (
    <div className="bb-run">
      <div className="run-head">
        <span className="run-head-prog">{prog.done}/{prog.total}</span>
      </div>
      {/* Low boy fill leads the opening tab: it is the first thing done on the
          floor, so it sits above the shift steps rather than under them. */}
      {templateKey === "opening_barback" && <LowboyFill />}
      <ItemList run={run} onTick={tick} />
      {isStock && (
        <React.Fragment>
          <button type="button" className="lowout-btn" onClick={async () => {
            setLowoutErr(null);
            try { setLowout(await bGet(`/run/${run.id}/lowout`)); }
            catch (e) { setLowoutErr(String(e.message || e)); }
          }}>Low / Out summary</button>
          {lowoutErr && <p className="run-legend">{lowoutErr}</p>}
          {lowout && <pre className="lowout-text">{lowout.text}</pre>}
        </React.Fragment>
      )}
    </div>
  );
}

/* The item-level restock, nested under opening. Collapsed by default so the
   shift steps above it stay readable; the summary carries the tally so you can
   see what is owed without opening it. */
function LowboyFill() {
  const [sweep, setSweep] = bUseState(null);
  const loadSweep = bUseCallback(async (runId) => {
    try { setSweep(await bGet(`/run/${runId}/sweep`)); } catch { setSweep(null); }
  }, []);
  const { run, err, tick, reload } = useRun("lowboy_fill", loadSweep);

  bUseEffect(() => { if (run && !sweep) loadSweep(run.id); }, [run?.id]);

  if (err) return <Failed msg={err} onRetry={reload} />;
  if (!run) return <div className="lowboy"><Loading label="loading low boy fill…" /></div>;

  const fill = window.BarbackLogic.summarizeFill(run.items);
  // Clearing from the sweep is the same tick the row above does, just aimed at
  // "0" — so it reuses the run's optimistic tick and its onSaved sweep reload
  // rather than a second write path.
  const clearItem = (itemId) => {
    const item = run.items.find(i => i.id === itemId);
    if (item) tick(item, "0");
  };
  // Clear all is one POST, not N per-item ticks — a 40-row low boy would
  // otherwise fire 40 writes and 40 sweep reloads. Confirmed because a stray
  // tap here wipes a whole shift's tally, and the counts are not recoverable.
  const clearAll = async () => {
    if (!window.confirm(`Clear all ${fill.units} back to zero?`)) return;
    await bSend("POST", `/run/${run.id}/clear`);
    await reload();
    loadSweep(run.id);
  };
  return (
    <details className="lowboy">
      <summary className="lowboy-head">
        <span className="lowboy-name">Low boy fill</span>
        <span className="lowboy-tally">{fill.units ? `${fill.units} to grab` : "nothing to grab"}</span>
      </summary>
      <div className="lowboy-body">
        <ItemList run={run} onTick={tick} />
        <FillSweep sweep={sweep} onClear={clearItem} />
        {/* Whole-list wipe stays last. The per-row ✕ is the control you reach for
            while counting; this one undoes a shift and should not sit first. */}
        <button className="fill-clear-all" type="button" onClick={clearAll}
                disabled={!fill.units}
                aria-label="Clear the whole low boy fill list back to zero">
          Clear all
        </button>
      </div>
    </details>
  );
}

// The sweep: everything owed, grouped by the area you walk to collect it, so a
// restock is one trip per area instead of front-back-front-side.
function FillSweep({ sweep, onClear }) {
  if (!sweep) return <div className="sweep sweep-loading">building sweep…</div>;
  if (!sweep.rows) {
    return <div className="sweep sweep-empty">Nothing to grab. Tap a row above if something is short.</div>;
  }
  return (
    <div className="sweep">
      <h3 className="sweep-head">Sweep — {sweep.units} to grab</h3>
      {sweep.areas.map(a => (
        <section className={`sweep-area${a.area === "Unsorted" ? " is-unsorted" : ""}`} key={a.area}>
          <h4 className="sweep-area-head">{a.area}<span className="sweep-units">{a.units}</span></h4>
          {a.area === "Unsorted" && (
            <p className="sweep-note">Not placed on the storage map yet — grab these on whichever pass suits.</p>
          )}
          {a.stops.map(s => (
            <div className="sweep-stop" key={s.location}>
              <div className="sweep-loc">{s.location}</div>
              <ul className="sweep-items">
                {s.items.map(it => (
                  <li key={it.item_id}>
                    <span className="sweep-count">{it.count}</span>
                    <span className="sweep-name">{it.text}</span>
                    {it.detail ? <span className="sweep-detail">{it.detail}</span> : null}
                    {/* A grabbed line comes off the sweep here. Since tapping a row
                        only ever adds, this ✕ is the single-line way back to 0.
                        Its own button, not a whole-row tap: a brushed row while
                        walking the bar with your hands full should not wipe a count. */}
                    <button className="sweep-clear" type="button"
                            aria-label={`Clear ${it.text} from the sweep`}
                            title="Got it — clear from the sweep"
                            onClick={() => onClear(it.item_id)}>✕</button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function ItemList({ run, onTick }) {
  const isStock = run.kind === "stock";
  const isFill = run.kind === "fill";
  const groups = []; const seen = new Map();
  run.items.forEach(i => { const k = i.section || ""; if (!seen.has(k)) { seen.set(k, []); groups.push([k, seen.get(k)]); } seen.get(k).push(i); });

  // Stock rows: tap-forward cycle (good→low→out→good) never returns to "open",
  // so a mis-tap had no correction. Long-press (pointer held ~500ms) resets to
  // "open"; Shift+Enter is the keyboard-equivalent in onKeyDown below.
  // ponytail: no pointercancel/move-threshold guard — held-still-for-500ms is
  // signal enough for this low-stakes control; add a movement threshold if
  // scroll-triggered false positives show up in practice.
  const pressTimers = React.useRef(new Map());
  const pressFired = React.useRef(new Set());
  const pressStart = (id) => { pressTimers.current.set(id, setTimeout(() => pressFired.current.add(id), 500)); };
  const pressEnd = (id) => { clearTimeout(pressTimers.current.get(id)); pressTimers.current.delete(id); };
  const activate = (item) => {
    if (pressFired.current.delete(item.id)) { if (isStock) onTick(item, "open"); return; }
    onTick(item);
  };

  return (
    <React.Fragment>
      <p className="run-legend">
        {isStock ? "Tap to cycle good → low → out → good. Long-press (or Shift+Enter) to reset to open."
          : isFill ? "Tap a row to add one — how many to grab. It keeps counting up, so tap eight times for eight. Over-tapped? The ✕ on the row sends it back to zero. Clear all wipes the whole list. The sweep at the bottom groups them by where you collect them."
          : "Tap to toggle done."}
      </p>
      {groups.map(([section, items]) => (
        <React.Fragment key={section || "_"}>
          {section ? <h3 className="section-head">{section}</h3> : null}
          <ul className="item-list">
            {items.map(i => {
              const n = isFill ? (parseInt(i.state, 10) || 0) : 0;
              const cls = isStock ? `stock-${i.state}`
                : isFill ? (n > 0 ? "fill-needs" : "fill-zero")
                : (i.state === "done" ? "done" : "open");
              const badge = isStock ? i.state : isFill ? String(n) : (i.state === "done" ? "✓" : "");
              const label = isFill
                ? `${i.text}${i.detail ? ` — ${i.detail}` : ""} — grab ${n}`
                : `${i.text}${i.detail ? ` — ${i.detail}` : ""} — ${i.state}`;
              const badgeStyle = isFill ? { background: window.BarbackLogic.fillColor(i.state) } : undefined;
              return (
                // biome-ignore lint/a11y/useAriaPropsSupportedByRole: role and aria-checked below are driven by the same isStock||isFill condition, so aria-checked is only ever set when role is "checkbox" — biome can't correlate two separate ternaries even when their conditions match.
                <li className={`item-row ${cls}`} key={i.id}
                    role={isStock || isFill ? "button" : "checkbox"}
                    tabIndex={0}
                    aria-checked={isStock || isFill ? undefined : i.state === "done"}
                    aria-label={label}
                    onPointerDown={isStock ? () => pressStart(i.id) : undefined}
                    onPointerUp={isStock ? () => pressEnd(i.id) : undefined}
                    onPointerLeave={isStock ? () => pressEnd(i.id) : undefined}
                    onClick={() => activate(i)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (isStock && e.shiftKey) onTick(i, "open"); else onTick(i); } }}>
                  <span className="i-state" style={badgeStyle}>{badge}</span>
                  <span className="i-text">{i.text}{i.detail ? <span className="i-detail">{i.detail}</span> : null}</span>
                  {i.deadline ? <span className="deadline">{i.deadline}</span> : null}
                  {/* The tap cycle used to wrap 3 → 0, so an over-count fixed
                      itself by tapping on. Counting up to 99 has no roof, so a
                      mis-tap is stuck without this — the row's own way back to
                      zero, on the row you are counting, not down in the sweep.
                      Its own button so a brushed row does not wipe a count. */}
                  {isFill && n > 0 ? (
                    <button className="row-clear" type="button"
                            aria-label={`Reset ${i.text} to zero`}
                            title="Back to zero"
                            onClick={(e) => { e.stopPropagation(); onTick(i, "0"); }}
                            onKeyDown={(e) => e.stopPropagation()}>✕</button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </React.Fragment>
      ))}
    </React.Fragment>
  );
}

/* Mount lazily, the first time the bar back tab is shown. Since bar back became
   the umbrella's leading (and default) tab, that IS on load for a hash-less
   /jc/ — so today's opening run starts on page view now. Deliberate: it is the
   landing surface. A visit that deep-links #batch or #map still never mounts
   this, which is what the laziness is still buying. The umbrella fires
   `jc:tab` on each switch; we also read the live tab once, because the shell's
   first fire happens before this file is compiled. */
(() => {
  let mounted = false;
  const mount = (tab) => {
    if (mounted || tab !== "barback") return;
    const host = document.getElementById("barback-root");
    if (!host) return;
    mounted = true;
    ReactDOM.createRoot(host).render(<BarbackPanel />);
  };
  document.addEventListener("jc:tab", (e) => mount(e.detail.tab));
  mount(window.JcTabs ? window.JcTabs.current() : null);
})();
