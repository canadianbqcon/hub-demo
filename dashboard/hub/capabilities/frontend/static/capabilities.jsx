/* capabilities page body (React). Ported from the inline script in capabilities.html:
   same DOM, ids and classes, one GET, nothing else on the wire (read-only page). */
window.CapabilitiesUI = window.CapabilitiesUI || {};
(() => {
  const { useState, useEffect, useRef } = React;
  const PLUGIN_EXPAND_THRESHOLD = 5; // plugins with more skills than this get their own nested expandable

  function matches(row, q) {
    if (!q) return true;
    const hay = (`${row.name} ${row.description || ""} ${row.plugin || ""}`).toLowerCase();
    return hay.indexOf(q) >= 0;
  }

  function Row({ row }) {
    return (
      <div className="row">
        <span className="nm">{row.name}{row.source === "plugin" && row.plugin ? <span className="chip">{row.plugin}</span> : null}</span>
        {row.description ? <span className="ds">{row.description}</span> : null}
        <span className="pth">{row.path}</span>
      </div>
    );
  }

  const NoneRow = () => <div className="row"><span className="ds">(none)</span></div>;

  // A <details> whose summary is chev + label + badge, as the plain page built it.
  function Group({ cls, open, label, h, count, children }) {
    const Label = h || "span";
    return (
      <details className={cls} open={open}>
        <summary><span className="chev">›</span><Label className="label">{label}</Label><span className="badge">{count}</span></summary>
        {children}
      </details>
    );
  }

  function Categories({ data, q }) {
    let shown = 0, total = 0;
    const groups = [];
    for (const [category, rows] of Object.entries(data.categories || {})) {
      total += rows.length;
      const mineRows = rows.filter((r) => r.source !== "plugin");
      const pluginRows = rows.filter((r) => r.source === "plugin");
      const visibleMine = mineRows.filter((r) => matches(r, q));
      const visiblePlugin = pluginRows.filter((r) => matches(r, q));
      shown += visibleMine.length + visiblePlugin.length;
      if (q && visibleMine.length === 0 && visiblePlugin.length === 0) continue;

      let plugins = null;
      if (pluginRows.length) {
        // Group by plugin; a plugin with hella skills (e.g. gsd, 60+) gets its own
        // nested expandable. Grouped plugins sort to the top, highest count first;
        // small ungrouped plugins stay below, in their original order.
        const byPlugin = new Map();
        for (const row of pluginRows) {
          if (!byPlugin.has(row.plugin)) byPlugin.set(row.plugin, []);
          byPlugin.get(row.plugin).push(row);
        }
        const grouped = [...byPlugin.entries()]
          .filter(([, allRows]) => allRows.length > PLUGIN_EXPAND_THRESHOLD)
          .sort((a, b) => b[1].length - a[1].length);
        const ungrouped = [...byPlugin.entries()]
          .filter(([, allRows]) => allRows.length <= PLUGIN_EXPAND_THRESHOLD);
        plugins = (
          <Group cls="group plugin-group" open={Boolean(q) && visiblePlugin.length > 0} label="Plugins" count={pluginRows.length}>
            {visiblePlugin.length === 0 ? <NoneRow /> : null}
            {[...grouped, ...ungrouped].map(([pluginName, allRows]) => {
              const visibleRows = allRows.filter((r) => matches(r, q));
              if (visibleRows.length === 0) return null;
              if (allRows.length > PLUGIN_EXPAND_THRESHOLD) {
                return (
                  <Group key={pluginName} cls="group plugin-group" open={Boolean(q)} label={pluginName} count={allRows.length}>
                    {visibleRows.map((row, i) => <Row key={i} row={row} />)}
                  </Group>
                );
              }
              return <React.Fragment key={pluginName}>{visibleRows.map((row, i) => <Row key={i} row={row} />)}</React.Fragment>;
            })}
          </Group>
        );
      }
      // Collapsed by default (120+ rows was a wall of options on first paint);
      // a query auto-opens any category that has a match, same as the plugin sub-group.
      groups.push(
        <Group key={category} cls="group" open={Boolean(q)} h="h2" label={category} count={rows.length}>
          {visibleMine.length === 0 && pluginRows.length === 0 ? <NoneRow /> : null}
          {visibleMine.map((row, i) => <Row key={i} row={row} />)}
          {plugins}
        </Group>
      );
    }
    return { shown, total, groups };
  }

  function Capabilities() {
    const [data, setData] = useState(null);
    const [err, setErr] = useState(null);
    const [view, setView] = useState({ query: "", n: 0 }); // n bumps per render so the DOM rebuilds like the plain page
    const input = useRef(null);
    const timer = useRef(null);
    const dataRef = useRef(null);

    useEffect(() => {
      fetch("/capabilities/api/data")
        .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then((payload) => { dataRef.current = payload; setData(payload); setView((v) => ({ query: "", n: v.n + 1 })); })
        .catch((e) => { setErr(e); });
      // "/" focuses search from anywhere on the page, except while already typing
      // into a text field (matches the common list-page convention).
      const onKey = (e) => {
        if (e.key !== "/") return;
        const tag = document.activeElement?.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        input.current.focus();
      };
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    }, []);

    const rerender = (query) => setView((v) => ({ query, n: v.n + 1 }));
    const onInput = (e) => {
      const value = e.target.value;
      clearTimeout(timer.current);
      timer.current = setTimeout(() => { if (dataRef.current) rerender(value); }, 130);
    };
    const onKeyDown = (e) => {
      if (e.key === "Escape" && input.current.value) {
        clearTimeout(timer.current);
        input.current.value = "";
        if (dataRef.current) rerender("");
      }
    };
    const setAll = (open) => document.querySelectorAll("#content details").forEach((d) => { d.open = open; });

    const q = view.query.trim().toLowerCase();
    let body = null, count = "";
    if (err) {
      body = (
        <div className="hub-error">{`couldn't load capabilities — ${err.message}`}
          <button type="button" className="hub-error-retry" id="retryLoad" onClick={() => location.reload()}>retry</button></div>
      );
    } else if (data) {
      const { shown, total, groups } = Categories({ data, q });
      count = q ? `${shown} / ${total} match` : `${total} skills`;
      body = (
        <React.Fragment key={view.n}>
          <div className="agent">{groups}</div>
          {q ? null : (
            <div className="agent">
              <h2>System status</h2>
              {Object.entries(data.system_status || {}).map(([label, rows]) => (
                <Group key={label} cls="group" open={false} h="h3" label={label} count={rows.length}>
                  {rows.map((r, i) => (
                    <div key={i} className={`badgeline ${r.present ? "present" : "absent"}`}>
                      <span className="hub-dot" style={{ "--dot-color": r.present ? "var(--good)" : "var(--fg-ghost)" }}>{r.present ? "present" : "missing"}</span>
                      <span className="pth">{r.path}</span>
                    </div>
                  ))}
                </Group>
              ))}
            </div>
          )}
          {q && shown === 0 ? <div className="empty-state">{`no skills match "${view.query}"`}</div> : null}
        </React.Fragment>
      );
    }

    return (
      <React.Fragment>
        <div className="searchbar">
          <input id="search" type="text" placeholder="filter by name or description… ( / to focus, Esc to clear )" autoComplete="off"
            aria-label="filter capabilities by name or description" ref={input} onInput={onInput} onKeyDown={onKeyDown} />
          <span className="count" id="matchcount" aria-live="polite">{count}</span>
          <button type="button" className="toolbtn" id="expandAll" onClick={() => setAll(true)}>expand all</button>
          <button type="button" className="toolbtn" id="collapseAll" onClick={() => setAll(false)}>collapse all</button>
        </div>
        <div className="content" id="content">{body}</div>
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen (fetch .catch).
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[capabilities] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  function Root() {
    useEffect(() => { document.getElementById("cap-root").setAttribute("data-react-mounted", "capabilities"); }, []);
    return <Boundary><Capabilities /></Boundary>;
  }

  // ponytail: #cap-root is display:contents so the searchbar/content stay direct flex children of body.
  ReactDOM.createRoot(document.getElementById("cap-root")).render(<Root />);
})();
