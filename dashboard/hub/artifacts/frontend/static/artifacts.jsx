/* artifacts.jsx: the catalog of published claude.ai Artifacts (/artifacts/).

   Renders the page body only: the subject rail and the index pane. The top bar
   is topbar.jsx's (it mounts into header.topbar and moves this page's two
   data-slot crumbs into place); the crumb meta text is set here by id. */
window.ArtifactsUI = window.ArtifactsUI || {};

(() => {
const { useState, useEffect, useRef } = React;

const ALL = " all", LIVE = " live", TOOL = " tool";

const isLive = a => a.url.startsWith("/");          // self-hosted on the Hub
const isTool = a => a.tool === true;                // something you use, not something you read
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const subjectOf = a => a.category || "Uncategorized";

// Biggest subject first, alphabetical on a tie. Derived rather than a hand-kept
// order list, so a new subject files itself. A null entry is the separator.
function tabsFor(artifacts) {
  const counts = new Map();
  for (const a of artifacts) counts.set(subjectOf(a), (counts.get(subjectOf(a)) || 0) + 1);
  const subjects = [...counts.entries()]
    .sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
    .map(([name, n]) => ({ key: name, name, n }));
  const liveCount = artifacts.filter(isLive).length;
  const toolCount = artifacts.filter(isTool).length;
  // Tools and Live cut across every shelf, so they sit pinned above the separator
  // instead of competing with the shelves for a slot.
  const tabs = [{ key: ALL, name: "Everything", n: artifacts.length }];
  if (toolCount) tabs.push({ key: TOOL, name: "Tools", n: toolCount });
  if (liveCount) tabs.push({ key: LIVE, name: "Live on the Hub", n: liveCount });
  tabs.push(null);
  tabs.push(...subjects);
  return { tabs, liveCount };
}

function fromHash(tabs) {
  const h = decodeURIComponent(location.hash.slice(1));
  if (!h || h === "all") return ALL;
  if (h === "live") return LIVE;
  if (h === "tools") return TOOL;
  const hit = tabs.find(t => t && t.key !== ALL && t.key !== LIVE && t.key !== TOOL && slug(t.key) === h);
  return hit ? hit.key : ALL;
}

function hashFor(key) {
  return key === ALL ? "all" : key === LIVE ? "live" : key === TOOL ? "tools" : slug(key);
}

function Row({ a, showSubject }) {
  const live = isLive(a);
  return (
    <a className="row" href={a.url}
       {...(live ? {} : { target: "_blank", rel: "noopener noreferrer" })}>{/* internal stays in-tab */}
      {a.favicon ? <span className="row-fav" aria-hidden="true">{a.favicon}</span> : null}
      <span className="row-head">
        <span className="row-title">{a.title}</span>
        {live ? <span className="row-live hub-dot">live</span> : null}
      </span>
      <span className="row-meta">
        {showSubject ? <span className="row-subject">{subjectOf(a)}</span> : null}
        {a.updated ? <time className="row-date" dateTime={a.updated}>{a.updated}</time> : null}
      </span>
      {a.description ? <span className="row-desc">{a.description}</span> : null}
    </a>
  );
}

function Index({ artifacts, tabs, current }) {
  const items = current === ALL ? artifacts
              : current === LIVE ? artifacts.filter(isLive)
              : current === TOOL ? artifacts.filter(isTool)
              : artifacts.filter(a => subjectOf(a) === current);
  if (!items.length) return <div className="empty">nothing here yet</div>;
  if (current === ALL) {
    // Grouped: the subject heading carries the label, so no row repeats it.
    return (
      <div className="index-list" key={current}>
        {tabs.filter(t => t && t.key !== ALL && t.key !== LIVE && t.key !== TOOL).map(t => {
          const group = items.filter(a => subjectOf(a) === t.key);
          if (!group.length) return null;
          return (
            <React.Fragment key={t.key}>
              <h2 className="group">{t.name}<span className="n">{group.length}</span></h2>
              {group.map(a => <Row key={a.url} a={a} showSubject={false} />)}
            </React.Fragment>
          );
        })}
      </div>
    );
  }
  // Flat. "Live" and "Tools" span shelves, so those rows carry their shelf; a
  // single shelf already has its name lit in the rail and doesn't repeat it.
  const showSubject = current === LIVE || current === TOOL;
  return <div className="index-list" key={current}>{items.map(a => <Row key={a.url} a={a} showSubject={showSubject} />)}</div>;
}

function ArtifactsApp() {
  // artifacts: null while loading; error: message when the load failed
  const [artifacts, setArtifacts] = useState(null);
  const [error, setError] = useState(null);
  const [current, setCurrent] = useState(ALL);
  const railRef = useRef(null);
  const indexRef = useRef(null);
  const sorted = artifacts?.slice().sort((a, b) => (b.updated || "").localeCompare(a.updated || ""));
  const { tabs, liveCount } = sorted ? tabsFor(sorted) : { tabs: [], liveCount: 0 };

  useEffect(() => {
    document.querySelector(".body").setAttribute("data-react-mounted", "artifacts");
    fetch("/artifacts/api/data")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(payload => setArtifacts(payload.artifacts || []))
      .catch(err => setError(err.message));
  }, []);

  // first selection comes from the hash once the tabs exist; later hash edits follow it
  useEffect(() => {
    if (!sorted) return;
    setCurrent(fromHash(tabs));
    const onHash = () => setCurrent(fromHash(tabs));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [artifacts]);

  useEffect(() => {
    const meta = document.getElementById("crumbMeta");
    if (!meta) return;
    meta.textContent = error ? "load failed" : sorted
      ? `${sorted.length} artifact${sorted.length === 1 ? "" : "s"}${liveCount ? ` · ${liveCount} live` : ""}`
      : "loading";
  }, [artifacts, error]);

  useEffect(() => { if (indexRef.current) indexRef.current.scrollTop = 0; }, [current]);

  function select(key, push) {
    setCurrent(key);
    if (push && location.hash.slice(1) !== hashFor(key)) location.hash = hashFor(key);
  }

  // Roving tabindex: arrows move between subjects, Home/End jump to the ends.
  function onRailKey(e) {
    const keys = ["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"];
    if (!keys.includes(e.key)) return;
    const els = [...railRef.current.querySelectorAll(".tab")];
    const i = els.indexOf(document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const step = (e.key === "ArrowDown" || e.key === "ArrowRight") ? 1
               : (e.key === "ArrowUp" || e.key === "ArrowLeft") ? -1 : 0;
    const next = e.key === "Home" ? els[0]
               : e.key === "End" ? els[els.length - 1]
               : els[(i + step + els.length) % els.length];
    next.focus();
    select(next.dataset.key, true);
  }

  const active = tabs.find(t => t && t.key === current);
  return (
    <React.Fragment>
      <h1 className="sr-only">Artifacts</h1>
      <nav className="rail" id="rail" role="tablist" aria-label="Filter artifacts by subject"
           ref={railRef} onKeyDown={onRailKey}>
        {tabs.map((t, i) => t
          ? <button key={t.key} type="button" className="tab" id={`tab-${hashFor(t.key)}`} role="tab"
                    aria-selected={t.key === current} tabIndex={t.key === current ? 0 : -1}
                    data-key={t.key} onClick={() => select(t.key, true)}>
              <span className="tab-name">{t.name}</span><span className="tab-count">{t.n}</span>
            </button>
          : <div key={`sep${i}`} className="rail-sep"></div>)}
      </nav>
      <section className="index" id="index" role="tabpanel" tabIndex={0} aria-label="Artifacts"
               aria-labelledby={sorted ? (active ? `tab-${hashFor(active.key)}` : "") : undefined}
               ref={indexRef}>
        {error
          ? <div className="hub-error">couldn't load artifacts {"—"} {error}
              <button type="button" className="hub-error-retry" id="retryLoad"
                      onClick={() => location.reload()}>retry</button></div>
          : sorted ? <Index artifacts={sorted} tabs={tabs} current={current} /> : null}
      </section>
    </React.Fragment>
  );
}

class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err) return <div className="hub-error">page failed to load: {String(this.state.err.message || this.state.err)}</div>;
    return this.props.children;
  }
}

window.ArtifactsUI.App = ArtifactsApp;
ReactDOM.createRoot(document.getElementById("artifacts-root")).render(<ErrorBoundary><ArtifactsApp /></ErrorBoundary>);
})();
