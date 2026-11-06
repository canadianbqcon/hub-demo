/* vault map page body (React). Ported from the inline script in vault_map.html:
   same DOM, ids and classes, one GET (/vault-map/api/tree), nothing else on the wire (read-only page). */
window.VaultMapUI = window.VaultMapUI || {};
(() => {
  const { useState, useEffect, useLayoutEffect, useMemo, useRef } = React;
  const ROOT = "@";

  // function = role, derived from intrinsic tells (ext / frontmatter / location)
  const FUNCTIONS = [
    ["knowledge",   "authored prose to be read: wiki, briefings, memory, docs"],
    ["ingest",      "raw captured inputs awaiting processing"],
    ["asset",       "media: images, svg, pdf, fonts"],
    ["code",        "executable source: .py / .js / .css / .sh"],
    ["data",        "structured stores: .db / .sql / .csv"],
    ["config",      "tool & system settings: .json / .yaml / dotfiles"],
    ["governance",  "the rule layer: CLAUDE.md, .claude skills & hooks"],
    ["records",     "operational history: logs, audits, working state"],
    ["misc",        "generated / derived junk: .git, caches (recedes)"],
    ["unclassified","not yet categorized, needs a decision"],
  ];
  const fnVar = (f) => `var(--fn-${f})`;
  const FN_MEANING = Object.fromEntries(FUNCTIONS);
  // redundant non-color cue for the color-only row fill (P2: WCAG 1.4.1)
  const FN_ABBR = {
    knowledge: "kn", ingest: "in", asset: "as", code: "co", data: "da",
    config: "cf", governance: "gv", records: "rc", misc: "mi", unclassified: "un",
  };

  function humanSize(b) {
    if (b == null) return "—";
    if (b < 1024) return `${b} B`;
    const u = ["KB", "MB", "GB"]; let v = b, i = -1;
    do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
    return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${u[i]}`;
  }

  // Enter / Space activate a role=button element, as on the plain page.
  const keyAct = (fn) => (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } };

  // full ancestry root→node, walked via parent_path:  [ "@", repoRoot, …, path ]
  function chainOf(byPath, path) {
    const chain = []; let cur = byPath.get(path);
    while (cur) { chain.unshift(cur.path); cur = (cur.parent_path != null) ? byPath.get(cur.parent_path) : null; }
    return chain;
  }

  // which parents' children become columns. ROOT renders as the merged repos column.
  function colParents(byPath, path) {
    const n = byPath.get(path); if (!n) return [ROOT];
    const chain = chainOf(byPath, path);
    if (chain.length <= 2) return [ROOT];
    const tail = n.node_kind === "folder" ? chain.slice(2) : chain.slice(2, -1);
    return [ROOT].concat(tail);
  }

  function Row({ n, selected, lit, onPick }) {
    const act = () => onPick(n.path);
    const cls = "row " + (n.node_kind === "folder" ? "folder" : "file") + (n.generated ? " gen" : "")
      + (n.path === selected ? " sel" : (lit.has(n.path) ? " lit" : ""));
    return (
      <div className={cls} style={{ "--fn": fnVar(n.node_function) }}
           title={`${n.node_function}: ${FN_MEANING[n.node_function] || ""}`}
           role="button" tabIndex={0} onClick={act} onKeyDown={keyAct(act)}>
        <span className="fnlabel">{FN_ABBR[n.node_function] || "--"}</span>
        <span className="nm">{n.name}</span>
        <span className="ct">{n.node_kind === "folder" ? n.file_count.toLocaleString() : (n.ext || "")}</span>
        <span className="chev">{n.node_kind === "folder" ? "›" : ""}</span>
      </div>
    );
  }

  function NormalColumn({ pp, kids, selected, lit, onPick }) {
    return (
      <div className="col">
        <div className="col-head">{pp.split("/").pop()}</div>
        {(kids.get(pp) || []).map((n) => <Row key={n.path} n={n} selected={selected} lit={lit} onPick={onPick} />)}
      </div>
    );
  }

  function MergedColumn({ kids, selected, lit, onPick }) {
    return (
      <div className="col">
        <div className="col-head">repos</div>
        {(kids.get(ROOT) || []).map((repo) => {
          const act = () => onPick(repo.path);
          return (
            <React.Fragment key={repo.path}>
              <div className={`repo-group${repo.path === selected ? " sel" : (lit.has(repo.path) ? " lit" : "")}`}
                   style={{ "--fn": fnVar(repo.node_function) }}
                   title={`${repo.node_function}: ${FN_MEANING[repo.node_function] || ""}`}
                   role="button" tabIndex={0} onClick={act} onKeyDown={keyAct(act)}>
                <span className="rg-line"><span className="fnlabel">{FN_ABBR[repo.node_function] || "--"}</span><span className="rg-name">{repo.name}</span></span>
                <span className="rg-meta">{repo.file_count.toLocaleString()} files · {humanSize(repo.size)}</span>
              </div>
              {(kids.get(repo.path) || []).map((n) => <Row key={n.path} n={n} selected={selected} lit={lit} onPick={onPick} />)}
            </React.Fragment>
          );
        })}
      </div>
    );
  }

  function Panel({ n }) {
    const [copied, setCopied] = useState(false);
    const path = n ? n.path : null;
    useEffect(() => { setCopied(false); }, [path]);
    if (!n) return <aside className="panel empty" id="panel">select a node to inspect.</aside>;
    const rows = [];
    if (n.wiki_type) rows.push(["wiki type", n.wiki_type]);
    else if (n.ext) rows.push(["file type", n.ext]);
    rows.push(["provenance", n.generated ? "generated · derived" : "authored"]);
    if (n.node_kind === "folder") rows.push(["contains", `${n.file_count.toLocaleString()} files`]);
    rows.push(["size", humanSize(n.size)]);
    if (n.lines != null) rows.push(["lines", n.lines.toLocaleString()]);
    if (n.mtime) rows.push(["modified", n.mtime]);
    rows.push(["depth", String(n.depth)]);
    const isLeaf = n.node_kind === "file";
    const copy = () => {
      navigator.clipboard.writeText(n.path).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      });
    };
    return (
      <aside className="panel" id="panel" style={{ "--fn": fnVar(n.node_function) }}>
        <div className="pfn"><span className="dot"></span>{n.node_function}{n.generated ? <React.Fragment> · <em style={{ fontStyle: "normal", opacity: 0.7 }}>generated</em></React.Fragment> : null}</div>
        <h2>{n.name}</h2>
        <div className="kind">{isLeaf ? "file" : "folder"}</div>
        <p className="purpose">{n.purpose ? n.purpose : <em style={{ opacity: 0.55 }}>no description yet</em>}</p>
        <dl className="meta-grid">{rows.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{v}</dd></React.Fragment>)}</dl>
        {(isLeaf && !n.purpose) ? <div className="aihint">no description yet: a Sonnet pass over the file body will write one here.</div> : null}
        <div className="pathline">
          <button type="button" className="tbtn copybtn" aria-live="polite" data-path={n.path} onClick={copy}>{copied ? "copied" : "copy path"}</button>
          <span className="pathtext">{n.path}</span>
        </div>
      </aside>
    );
  }

  function VaultMap() {
    const [nodes, setNodes] = useState([]);
    const [status, setStatus] = useState("loading");   // loading | error | ok
    const [errMsg, setErrMsg] = useState("");
    const [selected, setSelected] = useState(ROOT);
    const [q, setQ] = useState("");
    const [matches, setMatches] = useState(null);      // null = no list rendered (plain page's empty innerHTML)
    const [listHidden, setListHidden] = useState(true);
    const mapRef = useRef(null);

    function loadTree() {
      fetch("/vault-map/api/tree")
        .then((r) => { if (!r.ok) throw new Error(`http ${r.status}`); return r.json(); })
        .then((payload) => {
          setNodes(payload.nodes || payload);
          setSelected(ROOT);
          setStatus("ok");
        })
        .catch((err) => { setErrMsg(err.message); setStatus("error"); });
    }
    useEffect(loadTree, []);

    const { byPath, kids } = useMemo(() => {
      const byPath = new Map(), kids = new Map();
      for (const n of nodes) {
        byPath.set(n.path, n);
        const p = n.parent_path;
        if (p === null || p === undefined) continue;
        if (!kids.has(p)) kids.set(p, []);
        kids.get(p).push(n);
      }
      // folders first, then alpha (matches db.get_children intent)
      for (const arr of kids.values())
        arr.sort((a, b) => (a.node_kind !== b.node_kind ? (a.node_kind === "folder" ? -1 : 1)
                  : a.name.toLowerCase().localeCompare(b.name.toLowerCase())));
      return { byPath, kids };
    }, [nodes]);

    // keep the deepest column in view
    useLayoutEffect(() => { if (mapRef.current) mapRef.current.scrollLeft = mapRef.current.scrollWidth; }, [selected, status, nodes]);

    const ok = status === "ok";
    const chain = ok ? chainOf(byPath, selected) : [];
    const lit = new Set(chain); lit.add(selected);
    const parents = ok ? colParents(byPath, selected) : [];

    function runSearch(v) {
      const s = v.trim().toLowerCase();
      if (!s) { setListHidden(true); setMatches(null); return; }
      setMatches(nodes.filter((n) =>
        n.name.toLowerCase().includes(s) ||
        n.node_function.includes(s) ||
        (n.purpose?.toLowerCase().includes(s))
      ).slice(0, 40));
      setListHidden(false);
    }
    function jump(path) { setSelected(path); setListHidden(true); setQ(""); }

    useEffect(() => {
      const h = (e) => { if (!e.target.closest(".search-wrap")) setListHidden(true); };
      document.addEventListener("click", h);
      return () => document.removeEventListener("click", h);
    }, []);

    const sbox = useRef(null);
    function onSearchKey(e) {
      if (e.key === "Escape") { setQ(""); runSearch(""); e.target.blur(); }
      else if (e.key === "Enter") {
        if (matches?.length) jump(matches[0].path);
      }
    }

    return (
      <React.Fragment>
        <div className="intro">
          <p className="lead"><b>second brain</b>: the whole system. The first column groups its two repos,
            {" "}<em>Obsidian Vault</em> (knowledge + data) and its sibling <em>vault-code</em> (the app that reads it),
            each with its top folders beneath. Drill right into anything, and color marks what each part <em>does</em>:</p>
          <div className="leg" id="legend">
            {ok ? FUNCTIONS.map(([f, meaning]) => (
              <span key={f}><i style={{ background: fnVar(f) }}></i><b>{f}</b>&nbsp;<em>{meaning}</em></span>
            )) : null}
          </div>
          {/* ponytail: db.get_tree() never excludes a path (_GEN_DIRS only marks `generated`), so this is a fixed statement, not a live check */}
          <div className="hidden-note" id="hiddennote">showing everything, including .git internals: nothing is hidden.</div>
        </div>

        <div className="crumbrow">
          <span className="crumbs-label">path</span>
          <div className="crumbs" id="crumbs">
            {chain.map((p, i) => {
              const node = byPath.get(p);
              const act = () => setSelected(p);
              return (
                <React.Fragment key={`${selected}|${p}`}>
                  {i ? <span className="sepc">›</span> : null}
                  <span className={`c${p === selected ? " here" : ""}`} role="button" tabIndex={0}
                        onClick={act} onKeyDown={keyAct(act)}>{node ? node.name : p.split("/").pop()}</span>
                </React.Fragment>
              );
            })}
          </div>
          <div className="search-wrap">
            <input type="search" id="searchBox" className="search-input" placeholder="find a node…" autoComplete="off"
                   aria-label="find a node by name" ref={sbox} value={q}
                   onChange={(e) => { setQ(e.target.value); runSearch(e.target.value); }} onKeyDown={onSearchKey} />
            <div className="search-results" id="searchResults" role="listbox" hidden={listHidden}
                 onKeyDown={(e) => {
                   if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("sr-item")) {
                     e.preventDefault(); jump(e.target.dataset.path);
                   }
                 }}>
              {matches === null ? null : matches.length
                ? matches.map((n) => (
                  <div key={n.path} className="sr-item" data-path={n.path} role="option" tabIndex={0}
                       onClick={() => jump(n.path)}>
                    <span>{n.name}</span><span className="sr-path">{n.path}</span>
                  </div>))
                : <div className="sr-empty">no matches</div>}
            </div>
          </div>
        </div>

        <div className="stage">
          <div className="map" id="map" data-colormode="fill" ref={mapRef}>
            {status === "loading" ? <div className="map-status" aria-live="polite">loading vault tree…</div> : null}
            {status === "error" ? (
              <div className="hub-error" aria-live="assertive">could not load the vault tree ({errMsg}).{" "}
                <button type="button" className="hub-error-retry" id="retryLoad" onClick={loadTree}>retry</button></div>
            ) : null}
            {ok ? parents.map((pp) => pp === ROOT
              ? <MergedColumn key={`${selected}|${pp}`} kids={kids} selected={selected} lit={lit} onPick={setSelected} />
              : <NormalColumn key={`${selected}|${pp}`} pp={pp} kids={kids} selected={selected} lit={lit} onPick={setSelected} />) : null}
          </div>
          {ok ? <Panel n={byPath.get(selected)} /> : <aside className="panel empty" id="panel">select a node to inspect.</aside>}
        </div>
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen (fetch .catch).
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[vault-map] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  function Root() {
    useEffect(() => { document.getElementById("vm-root").setAttribute("data-react-mounted", "vault-map"); }, []);
    return <Boundary><VaultMap /></Boundary>;
  }

  // ponytail: #vm-root is display:contents so intro/crumbrow/stage stay direct flex children of body.
  ReactDOM.createRoot(document.getElementById("vm-root")).render(<Root />);
})();
