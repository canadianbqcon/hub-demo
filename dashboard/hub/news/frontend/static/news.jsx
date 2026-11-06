/* news page body (React). Ported from news.js: same DOM, ids, classes and request bodies.
   Two mount points: the pane (#pane, the React root) and the tab rail (#newsCol, via a portal).
   The topbar extras, the nav drawer's toggle and scrim, the crumb and the footer status bar
   stay in the template and are touched by id, as the plain page did. */
window.NewsUI = window.NewsUI || {};
(() => {
  const { useState, useEffect, useRef } = React;

  const API = "/news/api";
  const CLUSTER_TABS = ["today", "economy", "politics", "world", "nyc", "tech", "opinion", "audience", "community"];
  const TOPIC_KINDS = ["keyword", "ticker", "repo", "pypi", "subreddit"];
  const JSON_HEADERS = { "Content-Type": "application/json" };
  const TAB_PAGE = 150; // api.py _TAB_LIMIT: a page this long may have older stories behind it
  const $ = (id) => document.getElementById(id);

  // The API hands back a python isoformat() string, which already carries an
  // explicit offset for anything written by the poll; only a bare, offset-less
  // timestamp needs "Z" assumed.
  function ago(iso) {
    if (!iso) return "";
    let s = String(iso).replace(" ", "T");
    if (!/(Z|[+-]\d\d:?\d\d)$/.test(s)) s += "Z";
    const then = new Date(s);
    if (Number.isNaN(then.getTime())) return "";
    const mins = Math.max(0, Math.round((Date.now() - then.getTime()) / 60000));
    if (mins < 60) return `${mins}m`;
    if (mins < 1440) return `${Math.round(mins / 60)}h`;
    return `${Math.round(mins / 1440)}d`;
  }

  function setStatus(l, r) {
    if (l != null) $("statusMsg").textContent = l;
    if (r != null) $("statusMeta").textContent = r;
  }

  // fetch helper: never throws, never surfaces a raw error to the caller.
  // A non-2xx or a body that is not JSON both come back as null.
  const getJSON = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);

  const EmptyRow = ({ text }) => <div className="hub-empty-state">{text}</div>;

  // ── lean tokens ────────────────────────────────────────────────────────────

  const LEAN_BUCKET = { left: "l", lean_left: "l", center: "c", lean_right: "r", right: "r", primary: "p" };
  const LEAN_LABEL = { left: "left", lean_left: "lean left", center: "center", lean_right: "lean right", right: "right", primary: "primary" };
  const leanLabel = (lean) => LEAN_LABEL[lean] || lean || "";
  const Lean = ({ lean }) => <span className="news-lean" style={{ color: `var(--lean-${LEAN_BUCKET[lean] || "c"})` }}>{leanLabel(lean)}</span>;

  // ── coverage card ──────────────────────────────────────────────────────────

  const BucketRow = ({ label, count }) => (
    <span className={`coverage-ct${count ? "" : " zero"}`}><b>{count}</b>{` ${label}`}</span>
  );

  function CoverageBar({ buckets }) {
    const total = (buckets.L || 0) + (buckets.C || 0) + (buckets.R || 0);
    return (
      <div className="coverage-bar" role="img" aria-label={`${total} outlet${total === 1 ? "" : "s"} by lean`}>
        {[["L", "k-L"], ["C", "k-C"], ["R", "k-R"]].map(([key, cls]) => {
          const count = buckets[key] || 0;
          if (!count) return null; // absent, never a zero-width segment
          return <span key={key} className={`coverage-seg ${cls}`} style={{ flex: String(count) }} />;
        })}
      </div>
    );
  }

  function Card({ c, selected, onSelect }) {
    const buckets = c.buckets || { L: 0, C: 0, R: 0 };
    const outlets = (buckets.L || 0) + (buckets.C || 0) + (buckets.R || 0);
    return (
      <div className={`hub-t3p-card news-card${selected ? " selected" : ""}`} data-id={c.id} role="button" tabIndex={0}
        id={`cluster-${c.id}`} onClick={() => onSelect(c.id)}
        onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(c.id); } }}>
        <div className="news-card-title">{c.title}</div>
        <div className="news-card-meta">{`${c.section || ""} · ${ago(c.last_seen)} · ${outlets} outlet${outlets === 1 ? "" : "s"}`}</div>
        <CoverageBar buckets={buckets} />
        <div className="coverage-counts">
          <BucketRow label="left" count={buckets.L || 0} />
          <BucketRow label="center" count={buckets.C || 0} />
          <BucketRow label="right" count={buckets.R || 0} />
          {c.primary?.length ? <span className="coverage-prim">{`+ primary: ${c.primary.join(", ")}`}</span> : null}
        </div>
        {c.gap ? <p className="coverage-gap">{c.gap}</p> : null}
        {c.names?.length ? <p className="coverage-names">{c.names.join(", ")}</p> : null}
      </div>
    );
  }

  // ── context rail: members, Read, Move to ───────────────────────────────────

  function MemberBody({ item }) {
    const [phase, setPhase] = useState("idle"); // idle | loading | done
    const [paras, setParas] = useState(null);
    const read = () => {
      setPhase("loading");
      getJSON(`${API}/items/${item.item_id}/read`).then((res) => {
        if (res && res.status === "ok" && res.paragraphs?.length) { setParas(res.paragraphs); setPhase("done"); }
        else setPhase("idle");
      });
    };
    return (
      <div className="news-member-body">
        <a className="news-member-link" href={item.url} target="_blank" rel="noopener">{item.title}</a>
        {item.readable && phase !== "done"
          ? <button type="button" className="hub-btn news-read-btn" disabled={phase === "loading"} onClick={read}>{phase === "loading" ? "loading…" : "Read"}</button>
          : null}
        {paras ? <div className="news-reader">{paras.map((p, i) => <p key={i} className="news-reader-p">{p}</p>)}</div> : null}
      </div>
    );
  }

  // ponytail: the picker's candidates are whatever's already loaded for the
  // active tab, not a dedicated per-section query -- the visible card list IS
  // the plausible move target. Upgrade to a section-scoped fetch if a move
  // across tabs turns out to be common.
  function MoveControl({ item, clusterId, candidates, onMoved }) {
    const [val, setVal] = useState("");
    const change = (e) => {
      const v = e.target.value;
      setVal(v);
      if (!v) return;
      fetch(`${API}/items/${item.item_id}/move`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ cluster_id: v === "new" ? null : Number(v) }),
      }).then(onMoved);
    };
    return (
      <div className="news-member-move">
        <span className="news-move-label">Move to</span>
        <select className="news-select" value={val} onChange={change}>
          <option value="">choose</option>
          {candidates.filter((c) => c.id !== clusterId).map((c) => <option key={c.id} value={String(c.id)}>{c.title}</option>)}
          <option value="new">New cluster</option>
        </select>
      </div>
    );
  }

  function Member({ m, clusterId, candidates, onMoved }) {
    const metaParts = [m.factual, m.owner, m.state_affiliation].filter(Boolean);
    return (
      <div className="news-member">
        <div className="news-member-head">
          <b className="news-member-name">{m.name}</b>
          <Lean lean={m.lean} />
          {m.paywall ? <span className="hub-pill is-warn">paywall</span> : null}
        </div>
        {metaParts.length ? <div className="news-member-meta">{metaParts.join(" · ")}</div> : null}
        <MemberBody item={m} />
        <MoveControl item={m} clusterId={clusterId} candidates={candidates} onMoved={onMoved} />
      </div>
    );
  }

  function Context({ ctx, onMoved }) {
    if (!ctx) return <div className="hub-empty-state">Select a story.</div>;
    const c = ctx.c;
    if (!c || c.error) return <EmptyRow text="Story not found." />;
    return (
      <React.Fragment key={ctx.gen}>
        <div className="hub-detail-title">{c.title}</div>
        {c.gap ? <p className="coverage-gap">{c.gap}</p> : null}
        {!c.members?.length
          ? <EmptyRow text="No members left in this story." />
          : c.members.slice().sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""))
            .map((m) => <Member key={m.item_id} m={m} clusterId={c.id} candidates={ctx.candidates} onMoved={() => onMoved(c.id)} />)}
      </React.Fragment>
    );
  }

  // ── digest (Today only) ────────────────────────────────────────────────────

  // Line-by-line render, not a markdown parser: the skill writes only `## `
  // section headings and `- ` bullets, and a [#id] citation becomes a link to its
  // card. ponytail: add a real renderer if the digest ever grows nested lists.
  function DigestLine({ line, onCite }) {
    const head = /^#{1,6}\s+(.*)$/.exec(line.trim());
    if (head) return <div className="news-digest-head">{head[1]}</div>;
    const bullet = /^\s*(?:[-*]|\d+\.)\s+(.*)$/.exec(line);
    if (bullet) line = bullet[1];
    const parts = [];
    const re = /\[#(\d+)\]/g;
    let last = 0, m;
    while ((m = re.exec(line))) {
      if (m.index > last) parts.push(line.slice(last, m.index));
      const id = m[1];
      // The cited story may not be among the loaded cards; the rail fetches any id.
      parts.push(<a key={m.index} className="news-digest-cite" href={`#cluster-${id}`}
        onClick={(ev) => { ev.preventDefault(); onCite(id); }}>{`#${id}`}</a>);
      last = m.index + m[0].length;
    }
    if (last < line.length) parts.push(line.slice(last));
    return <p className={bullet ? "news-digest-line is-bullet" : "news-digest-line"}>{parts}</p>;
  }

  function Digest({ onCite }) {
    const [d, setD] = useState({ done: false, data: null });
    useEffect(() => { getJSON(`${API}/digest?date=`).then((data) => setD({ done: true, data })); }, []);
    let body = null;
    if (d.done) {
      body = !d.data?.markdown
        ? <EmptyRow text={(d.data?.status) || "No summary yet today"} />
        : String(d.data.markdown).split("\n").filter((l) => l.trim()).map((l, i) => <DigestLine key={i} line={l} onCite={onCite} />);
    }
    return (
      <div className="news-digest">
        <div className="news-digest-label">claude summary · check the linked stories</div>
        <div className="news-digest-body">{body}</div>
      </div>
    );
  }

  // ── sources and topics ─────────────────────────────────────────────────────

  // Fixed thin spots from research (spec "Coverage note" + Sam's economy
  // addition) -- these never come from the API, they are known gaps in the
  // seed list itself.
  const COVERAGE_NOTES = [
    "nyc right: NY Post only",
    "tech right: none",
    "left opinion: The Atlantic only",
    "economy left: none",
  ];

  // enabled/disabled (or on/off) checkbox; the label flips after the PATCH resolves.
  function Toggle({ enabled, onText, offText, url }) {
    const cb = useRef(null);
    const [label, setLabel] = useState(enabled ? onText : offText);
    const change = () => {
      fetch(url, { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify({ enabled: cb.current.checked ? 1 : 0 }) })
        .then(() => setLabel(cb.current.checked ? onText : offText));
    };
    return (
      <label className="hub-chip-toggle">
        <input type="checkbox" defaultChecked={!!enabled} ref={cb} onChange={change} />
        <span>{label}</span>
      </label>
    );
  }

  function SourceRow({ s }) {
    const metaParts = [s.section, s.lane, s.factual, s.owner, s.state_affiliation].filter(Boolean);
    return (
      <div className="news-source-row">
        <div className="news-member-head">
          <b className="news-member-name">{s.name}</b>
          <Lean lean={s.lean} />
          {s.stale ? <span className="hub-pill is-warn">stale</span> : null}
          {s.paywall ? <span className="hub-pill is-warn">paywall</span> : null}
          <Toggle enabled={s.enabled} onText="enabled" offText="disabled" url={`${API}/sources/${s.id}`} />
        </div>
        <div className="news-member-meta">{metaParts.join(" · ")}</div>
        {s.rating_note ? <p className="news-source-note">{s.rating_note}</p> : null}
      </div>
    );
  }

  function TopicRow({ t, onRemoved }) {
    return (
      <div className="news-topic-row">
        <span className="news-topic-kind">{t.kind}</span>
        <span className="news-topic-query">{t.query}</span>
        <Toggle enabled={t.enabled} onText="on" offText="off" url={`${API}/topics/${t.id}`} />
        <button type="button" className="hub-btn hub-btn--danger"
          onClick={() => fetch(`${API}/topics/${t.id}`, { method: "DELETE" }).then(onRemoved)}>remove</button>
      </div>
    );
  }

  function AddTopicForm({ onAdded }) {
    const kind = useRef(null), input = useRef(null);
    const submit = (ev) => {
      ev.preventDefault();
      const query = input.current.value.trim();
      if (!query) return;
      fetch(`${API}/topics`, {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ kind: kind.current.value, query: query, enabled: 1 }),
      }).then(() => { input.current.value = ""; onAdded(); });
    };
    return (
      <form className="news-add-topic" onSubmit={submit}>
        <select className="news-select" ref={kind}>{TOPIC_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select>
        <input className="news-topic-input" type="text" placeholder="keyword, ticker, owner/repo, package, subreddit" required ref={input} />
        <button type="submit" className="hub-btn hub-btn--accent">add</button>
      </form>
    );
  }

  // ── tab rail ───────────────────────────────────────────────────────────────

  const TABS = [
    ["today", <React.Fragment><circle cx="12" cy="12" r="8.4" /><path d="M12 7.2 V12 L15.6 14.4" /></React.Fragment>],
    ["economy", <path d="M4.8 20.4 V13.2 M12 20.4 V8.4 M19.2 20.4 V4.8" />],
    ["politics", <path d="M4.8 20.4 H19.2 M6.6 20.4 V9.6 M17.4 20.4 V9.6 M12 9.6 V20.4 M4.2 9.6 L12 4.2 L19.8 9.6" />],
    ["world", <React.Fragment><circle cx="12" cy="12" r="8.4" /><path d="M3.6 12 H20.4 M12 3.6 C8.4 7.2 8.4 16.8 12 20.4 C15.6 16.8 15.6 7.2 12 3.6 Z" /></React.Fragment>],
    ["nyc", <path d="M4.2 20.4 V9.6 H8.4 V20.4 M9.6 20.4 V6 H14.4 V20.4 M15.6 20.4 V12 H19.8 V20.4" />],
    ["tech", <React.Fragment><rect x="4.8" y="4.8" width="14.4" height="14.4" rx="1.2" /><path d="M9 4.8 V2.4 M15 4.8 V2.4 M9 21.6 V19.2 M15 21.6 V19.2 M4.8 9 H2.4 M4.8 15 H2.4 M21.6 9 H19.2 M21.6 15 H19.2" /></React.Fragment>],
    ["topics", <React.Fragment><path d="M3.6 12 L12 3.6 H18 A2.4 2.4 0 0 1 20.4 6 V12 L12 20.4 Z" /><circle cx="8.4" cy="8.4" r="1.2" /></React.Fragment>],
    ["opinion", <path d="M3.6 5.4 H20.4 V15 H9.6 L5.4 18.6 V15 H3.6 Z" />],
    ["audience", <React.Fragment><path d="M2.4 12 C5.4 6.6 18.6 6.6 21.6 12 C18.6 17.4 5.4 17.4 2.4 12 Z" /><circle cx="12" cy="12" r="2.7" /></React.Fragment>],
    ["community", <React.Fragment><circle cx="8.4" cy="9" r="3" /><circle cx="16.2" cy="9.6" r="2.4" /><path d="M3 19.2 C3 15.6 5.4 13.8 8.4 13.8 C11.4 13.8 13.8 15.6 13.8 19.2 M13.8 15.6 C15.6 15.6 18.6 16.8 18.6 19.2" /></React.Fragment>],
    ["sources", <React.Fragment><path d="M5.4 4.2 H15 L18.6 7.8 V19.8 H5.4 Z M15 4.2 V7.8 H18.6" /><path d="M8.4 12 H15.6 M8.4 15.6 H15.6" /></React.Fragment>],
  ];

  function Nav({ tab, onTab }) {
    return (
      <nav className="hub-nav-rail news-nav" id="newsNav">
        {TABS.map(([t, glyph]) => (
          <button key={t} type="button" className={`hub-t3p-tab hub-nav-item${t === tab ? " active" : ""}`} data-tab={t} onClick={() => onTab(t)}>
            <span className="hub-t3p-tab-label hub-nav-label"><svg className="hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true">{glyph}</svg>{t}</span>
          </button>
        ))}
      </nav>
    );
  }

  // phone nav drawer, same idiom as workbench/trips: toggle is-open on the rail.
  function closeDrawer() {
    const rail = $("newsCol"), scrim = $("newsScrim"), toggle = $("navToggle");
    if (!rail) return;
    rail.classList.remove("is-open");
    if (scrim) scrim.hidden = true;
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  }

  // ── page ───────────────────────────────────────────────────────────────────

  function News() {
    // the plain page's mutable `state`, kept off React state: handlers read it at call time
    const st = useRef({ tab: "today", clusters: [], status: null, gen: 0 }).current;
    const [tab, setTab] = useState("today");
    const [view, setView] = useState({ mode: "blank" });
    const [stale, setStale] = useState({ hidden: true, text: "" });
    const [ctx, setCtx] = useState(null);
    const [selected, setSelected] = useState(null);
    const [open, setOpen] = useState(false);

    function renderStatusBar(status, count) {
      setStatus(`${st.tab} · ${count} stor${count === 1 ? "y" : "ies"}`, status?.last_run ? `updated ${ago(status.last_run)}` : "");
    }

    function renderContext(id) {
      getJSON(`${API}/clusters/${id}`).then((c) => setCtx({ gen: ++st.gen, c, candidates: st.clusters }));
    }

    function selectCard(id) {
      setSelected(String(id));
      renderContext(id);
      document.dispatchEvent(new CustomEvent("news:cluster-selected", { detail: { id } }));
      setOpen(true);
    }

    function loadSources() {
      setView({ mode: "sources", rows: undefined });
      getJSON(`${API}/sources`).then((rows) => setView(rows === null ? { mode: "error" } : { mode: "sources", rows }));
      setStatus(st.tab, "");
    }

    function loadTopics() {
      const gen = ++st.gen; // a fresh form each load, as the plain page rebuilt it
      setView({ mode: "topics", gen, rows: undefined });
      getJSON(`${API}/topics`).then((rows) => setView(rows === null ? { mode: "error" } : { mode: "topics", gen, rows }));
      setStatus(st.tab, "");
    }

    function loadTab() {
      $("crumbSection").textContent = st.tab;
      if (st.tab === "sources") { loadSources(); return; }
      if (st.tab === "topics") { loadTopics(); return; }
      getJSON(`${API}/clusters?tab=${encodeURIComponent(st.tab)}`).then((clusters) => {
        if (clusters === null) { setView({ mode: "error" }); return; }
        st.clusters = clusters || [];
        setSelected(null); // the list is rebuilt, so no card is selected any more
        setView({ mode: "clusters", gen: ++st.gen, tab: st.tab, empty: !!(st.status?.empty), clusters: st.clusters,
          more: st.tab !== "today" && st.clusters.length >= TAB_PAGE });
        renderStatusBar(st.status, st.clusters.length);
        // A push opens /news/#cluster-<id>: open that story once, on the first load.
        if (st.deep) {
          const id = st.deep; st.deep = null;
          selectCard(id);
          setTimeout(() => $(`cluster-${id}`)?.scrollIntoView({ block: "center" }), 50);
        }
      });
    }

    // Older page: the oldest card shown is the cursor; a short page means the cache ran out.
    // ponytail: last_seen is the whole cursor, so a story sharing the exact second of the
    // oldest shown card can be skipped; add the id to the cursor if that ever shows.
    function loadOlder() {
      const tabAtClick = st.tab;
      const oldest = st.clusters.reduce((m, c) => (!m || c.last_seen < m ? c.last_seen : m), "");
      setView((v) => ({ ...v, loading: true }));
      getJSON(`${API}/clusters?tab=${encodeURIComponent(tabAtClick)}&before=${encodeURIComponent(oldest)}`).then((page) => {
        if (st.tab !== tabAtClick) return; // tab changed while the page was in flight
        if (page === null) { setView((v) => ({ ...v, loading: false })); return; }
        st.clusters = st.clusters.concat(page);
        setView((v) => ({ ...v, clusters: st.clusters, loading: false, more: page.length >= TAB_PAGE }));
        renderStatusBar(st.status, st.clusters.length);
      });
    }

    function selectTab(t) {
      if (st.tab === t) return;
      st.tab = t;
      setTab(t);
      setOpen(false); // a phone sheet left open would cover the new tab
      loadTab();
    }

    useEffect(() => {
      $("pane").setAttribute("data-react-mounted", "news");
      st.deep = (location.hash.match(/^#cluster-(\d+)$/) || [])[1] || null;
      const toggle = $("navToggle"), rail = $("newsCol"), scrim = $("newsScrim");
      const flip = () => {
        const isOpen = !rail.classList.contains("is-open");
        rail.classList.toggle("is-open", isOpen);
        scrim.hidden = !isOpen;
        toggle.setAttribute("aria-expanded", String(isOpen));
      };
      if (toggle && rail && scrim) { toggle.addEventListener("click", flip); scrim.addEventListener("click", closeDrawer); }
      getJSON(`${API}/status`).then((status) => {
        st.status = status;
        if (!status?.stale?.length) setStale((s) => ({ hidden: true, text: s.text }));
        else setStale({ hidden: false, text: `${status.stale.length} stale source${status.stale.length === 1 ? "" : "s"}`, names: status.stale.map((s) => s.name || s.id).join(", ") });
        if (CLUSTER_TABS.indexOf(st.tab) >= 0) renderStatusBar(status, st.clusters.length);
      });
      loadTab();
      return () => { if (toggle) toggle.removeEventListener("click", flip); if (scrim) scrim.removeEventListener("click", closeDrawer); };
    }, []);

    const onMoved = (clusterId) => { loadTab(); renderContext(clusterId); };

    let list = null;
    if (view.mode === "error") {
      list = (
        <div className="hub-error">
          <span>Could not reach the news API.</span>
          <button type="button" className="hub-error-retry" onClick={loadTab}>retry</button>
        </div>
      );
    } else if (view.mode === "clusters") {
      const note = view.tab === "audience" ? <p className="news-audience-note">audience view · not a fact source</p> : null;
      if (view.empty) {
        list = <React.Fragment>{note}<EmptyRow text="polling runs on demo-desktop" /></React.Fragment>;
      } else {
        const cards = view.clusters.slice().sort((a, b) => (b.last_seen || "").localeCompare(a.last_seen || ""));
        list = (
          <React.Fragment>
            {note}
            {view.tab === "today" ? <Digest key={view.gen} onCite={(id) => { $(`cluster-${id}`)?.scrollIntoView({ block: "center" }); selectCard(id); }} /> : null}
            {cards.length
              ? cards.map((c) => <Card key={c.id} c={c} selected={selected === String(c.id)} onSelect={selectCard} />)
              : <EmptyRow text="no stories yet" />}
            {view.more
              ? <button type="button" className="hub-btn news-older" disabled={view.loading} onClick={loadOlder}>{view.loading ? "loading…" : "load older"}</button>
              : null}
          </React.Fragment>
        );
      }
    } else if (view.mode === "sources") {
      list = (
        <React.Fragment>
          <div className="news-coverage-note">
            <div className="hub-block-label">known coverage gaps</div>
            {COVERAGE_NOTES.map((line) => <p key={line} className="news-coverage-line">{line}</p>)}
          </div>
          {view.rows && !view.rows.length ? <EmptyRow text="no sources" /> : null}
          {(view.rows || []).map((s) => <SourceRow key={s.id} s={s} />)}
        </React.Fragment>
      );
    } else if (view.mode === "topics") {
      list = (
        <React.Fragment>
          <AddTopicForm key={view.gen} onAdded={loadTopics} />
          {view.rows && !view.rows.length ? <EmptyRow text="no topics" /> : null}
          {(view.rows || []).map((t) => <TopicRow key={t.id} t={t} onRemoved={loadTopics} />)}
        </React.Fragment>
      );
    }

    return (
      <React.Fragment>
        {ReactDOM.createPortal(<Nav tab={tab} onTab={(t) => { selectTab(t); closeDrawer(); }} />, $("newsCol"))}
        <div className="hub-pane-head news-head hub-t3p-head" id="paneHead">
          <button type="button" className="hub-btn news-stale" id="staleBanner" hidden={stale.hidden} title={stale.names}
            onClick={() => selectTab("sources")}>
            <span id="staleBannerText">{stale.text}</span>
          </button>
        </div>
        <div className={`hub-split news-split hub-t3p-split${tab === "sources" || tab === "topics" ? " is-full" : ""}`} id="focusSplit">
          <div className="hub-pane-col news-col hub-t3p-list-col" id="focusCol">
            <div className="hub-pane-list news-list hub-t3p-list" id="cardList">{list}</div>
          </div>
          <div className="side-pane hub-t3p-side" id="sidePane">
            <section className={`hub-detail-rail hub-slide-over context${open ? " is-open" : ""}`} id="contextCol">
              <button type="button" className="hub-slide-over-close" id="contextMobileClose" aria-label="back to list" onClick={() => setOpen(false)}>← back</button>
              <div className="hub-detail-rail-inner context-inner hub-t3p-context" id="contextDetail">
                <Context ctx={ctx} onMoved={onMoved} />
              </div>
            </section>
          </div>
        </div>
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen (getJSON).
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[news] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  $("newsCol").textContent = ""; // the template's static rail would sit above the portal's live one
  ReactDOM.createRoot($("pane")).render(<Boundary><News /></Boundary>);
})();
