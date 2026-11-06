/* recipes.jsx: index (browse/search/select) and detail (cook mode) of /recipes/.

   Renders the page body only. The top bar is topbar.jsx's (it mounts into
   header.topbar and places this page's data-slot crumb). One body, two views
   chosen by data-view on #recipes-root, exactly as the plain page did. */
window.RecipesUI = window.RecipesUI || {};

(() => {
const { useState, useEffect, useRef } = React;

function get(url) {
  return fetch(url, { headers: { Accept: "application/json" } }).then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });
}
function post(url, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then((r) => r.json());
}
function store(key, val) {
  try {
    if (val === undefined) return JSON.parse(localStorage.getItem(key) || "null");
    localStorage.setItem(key, JSON.stringify(val));
  } catch { /* private window, blocked storage: the page still works */ }
  return null;
}

/* Card head: the photo tile, or an empty tile when there is no photo. The title
   belongs in the body on BOTH branches; putting it in the thumb slot made
   photoless cards a second, louder card design. */
function CardHead({ r }) {
  return (
    <React.Fragment>
      {r.photo ? <img className="rx-thumb" src={r.photo} alt="" loading="lazy" />
               : <div className="rx-thumb-none"></div>}
    </React.Fragment>
  );
}

/* ── index ─────────────────────────────────────────────────────────── */

function Card({ r, picked, onPick }) {
  const meta = [];
  /* At-a-glance rule: show the scale behind the value, never a bare label. */
  if (r.servings) meta.push(<span key="s">{r.servings + (r.servings === 1 ? " serving" : " servings")}</span>);
  else if (r.servings_raw) meta.push(<span key="s">{r.servings_raw}</span>);
  if (r.total_time || r.cook_time) meta.push(<span key="t">{r.total_time || r.cook_time}</span>);
  if (r.difficulty) meta.push(<span key="d">{r.difficulty}</span>);
  return (
    <a className="rx-card" href={`/recipes/${r.slug}`} {...(picked ? { "data-selected": "true" } : {})}>
      <CardHead r={r} />
      <div className="rx-card-body">
        <div className="rx-card-title">{r.dish || r.title}</div>
        <div className="rx-card-meta">{meta}</div>
      </div>
      <button type="button" className="rx-pick" aria-pressed={picked ? "true" : "false"}
              aria-label={`select ${r.dish || r.title} for the grocery list`}
              onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); onPick(r.slug); }}>
        {picked ? "✓" : "+"}
      </button>
    </a>
  );
}

/* fridge matching: ad-hoc, nothing stored. A pantry you maintain by hand goes
   stale and then lies to you. */
function Pantry({ hidden }) {
  const ta = useRef(null);
  const [hits, setHits] = useState([]);
  const [empty, setEmpty] = useState(false);
  const match = () => {
    setHits([]); setEmpty(false);
    post("/recipes/api/pantry", { have: ta.current.value }).then((res) => {
      const h = (res.matches || []).filter((m) => m.coverage > 0);
      if (!h.length) { setEmpty(true); return; }
      setHits(h.slice(0, 24));
    });
  };
  return (
    <div className="rx-pantry" hidden={hidden}>
      <textarea ref={ta} placeholder={"what's in the fridge \u2014 one per line, or comma separated"}></textarea>
      <div className="rx-bar"><button type="button" className="rx-btn" data-primary="1" onClick={match}>match</button></div>
      <div className="rx-grid">
        {empty ? <div className="rx-empty">No recipe uses any of those.</div> : null}
        {hits.map((m) => (
          <a className="rx-card" key={m.slug} href={`/recipes/${m.slug}`}>
            <CardHead r={m} />
            <div className="rx-card-body">
              <div className="rx-card-title">{m.dish || m.title}</div>
              <div className="rx-card-meta">
                <span className="rx-cov">{`${Math.round(m.coverage * 100)}% of ingredients`}</span>
                <span>{`${m.missing.length} missing`}</span>
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}

function Tray({ slugs, onClear, onAdded }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { if (!slugs.length) { setMsg(""); setBusy(false); } }, [slugs.length]);
  const add = () => {
    setBusy(true); setMsg("adding…");
    post("/recipes/api/grocery/add", {
      recipes: slugs.map((s) => ({ slug: s }))
    }).then((res) => {
      setBusy(false);
      if (res.error) { setMsg(res.error); return; }
      setMsg("");
      onAdded(res.added);
    }).catch(() => { setBusy(false); setMsg("could not add"); });
  };
  return (
    <div className="rx-tray" hidden={slugs.length === 0}>
      {slugs.length ? (
        <React.Fragment>
          <span><strong>{String(slugs.length)}</strong>{slugs.length === 1 ? " recipe selected" : " recipes selected"}</span>
          <button type="button" className="rx-btn" data-primary="1" disabled={busy} onClick={add}>add to grocery list</button>
          <button type="button" className="rx-btn" onClick={onClear}>clear</button>
          <span className="rx-count">{msg}</span>
        </React.Fragment>
      ) : null}
    </div>
  );
}

function Index() {
  const [all, setAll] = useState([]);
  const [cats, setCats] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [picked, setPicked] = useState({});
  const [pantryOpen, setPantryOpen] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    get("/recipes/api/index").then((data) => {
      setAll(data.recipes); setCats(data.categories); setLoaded(true);
    }).catch(() => setFailed(true));
  }, []);

  const needle = q.trim().toLowerCase();
  const list = all.filter((r) => {
    if (cat && r.categories.indexOf(cat) < 0) return false;
    return !needle || r.haystack.indexOf(needle) >= 0;
  });
  const slugs = Object.keys(picked);
  const togglePick = (slug) => setPicked((p) => {
    const n = Object.assign({}, p);
    if (n[slug]) delete n[slug]; else n[slug] = true;
    return n;
  });

  return (
    <React.Fragment>
      <div className="rx-bar">
        <input className="rx-search" type="search" placeholder="search titles, ingredients, notes, source…"
               aria-label="search recipes"
               onInput={(e) => {
                 const v = e.target.value;
                 clearTimeout(timer.current);
                 timer.current = setTimeout(() => setQ(v), 90);
               }} />
        <span className="rx-count" hidden={pantryOpen}>{loaded ? `${list.length} of ${all.length}` : ""}</span>
        <button type="button" className="rx-btn" onClick={() => setPantryOpen(!pantryOpen)}>
          {pantryOpen ? "back to browsing" : "what can I make?"}
        </button>
      </div>
      <div className="rx-chips" hidden={pantryOpen}>
        {cats.map((c) => (
          <button type="button" className="rx-chip" key={c.name} aria-pressed={cat === c.name ? "true" : "false"}
                  onClick={() => setCat(cat === c.name ? "" : c.name)}>
            {c.name}<span className="n">{c.count}</span>
          </button>
        ))}
      </div>
      <Pantry hidden={!pantryOpen} />
      <div className="rx-grid" hidden={pantryOpen}>
        {!loaded ? null : !list.length
          ? <div className="rx-empty">{`Nothing matches that. ${all.length} recipes are loaded.`}</div>
          : list.map((r) => <Card key={r.slug} r={r} picked={!!picked[r.slug]} onPick={togglePick} />)}
      </div>
      <Tray slugs={slugs} onClear={() => setPicked({})} onAdded={() => setPicked({})} />
      {failed ? <div className="rx-empty">Could not load the recipe index.</div> : null}
    </React.Fragment>
  );
}

/* ── detail / cook mode ────────────────────────────────────────────── */

/* A checkbox row whose state persists in localStorage; clicking anywhere on the
   row toggles it. Remounted on every draw (key), so it re-reads storage. */
function Check({ k, children }) {
  const [done, setDone] = useState(() => !!store(k));
  const cb = useRef(null);
  const set = (v) => { setDone(v); store(k, v); };
  return (
    <li className="rx-item" data-done={done ? "true" : "false"}
        onClick={(ev) => { if (ev.target !== cb.current) set(!done); }}>
      <input type="checkbox" ref={cb} checked={done} onChange={(e) => set(e.target.checked)} />
      {children}
    </li>
  );
}

/* Native "change" (commit on blur or Enter), not React's per-keystroke onChange:
   the plain page only reloaded the scaled recipe on commit. */
function ServingsInput({ value, onCommit }) {
  const ref = useRef(null);
  useEffect(() => {
    const n = ref.current;
    const h = () => onCommit(n.value);
    n.addEventListener("change", h);
    return () => n.removeEventListener("change", h);
  });
  return <input type="number" min="1" max="100" defaultValue={value} aria-label="target servings" id="rx-servings" ref={ref} />;
}

function Body({ r, load }) {
  const sub = [];
  if (r.servings_raw) sub.push(`Serves ${r.servings_raw}`);
  if (r.prep_time) sub.push(`Prep ${r.prep_time}`);
  if (r.cook_time) sub.push(`Cook ${r.cook_time}`);
  if (r.total_time) sub.push(`Total ${r.total_time}`);
  if (r.difficulty) sub.push(r.difficulty);
  if (r.rating) sub.push(`★ ${r.rating}`);

  const lines = r.scaled_ingredients || [];
  const flagged = lines.filter((l) => l.flagged).length;
  const steps = (r.directions || "").split(/\n{2,}/).map((para, i) => [i, para.replace(/^\s*\d+[.)]\s*/, "").trim()])
    .filter(([, text]) => text);

  return (
    <React.Fragment>
      <a className="rx-back" href="/recipes/">← all recipes</a>
      <h1 className="rx-title">{r.dish || r.title}</h1>
      {/* The note's own title, kept alive under the dish name: it carries the source,
          the original-language name and whatever else the capture came with. */}
      {r.title && r.title !== (r.dish || r.title) ? <div className="rx-origtitle">{r.title}</div> : null}
      <div className="rx-sub">{sub.map((s, i) => <span key={i}>{s}</span>)}</div>
      {r.photo ? <img className="rx-hero" src={r.photo} alt="" /> : null}

      {/* Scaler. A note with a parseable base gets a servings target; the ones
          without one get a plain multiplier, which needs no base at all. */}
      <div className="rx-scaler">
        {r.servings ? (
          <React.Fragment>
            <label htmlFor="rx-servings">Scale to</label>
            <ServingsInput value={String(Math.round(r.servings * parseFloat(r.factor || 1)))}
                           onCommit={(v) => load(`?servings=${encodeURIComponent(v)}`)} />
            <label htmlFor="rx-servings">{`servings (recipe makes ${r.servings})`}</label>
          </React.Fragment>
        ) : (
          <React.Fragment>
            {/* biome-ignore lint/a11y/noLabelWithoutControl: heading for a group of buttons, there is no single control to bind */}
            <label>Scale by</label>
            {[0.5, 1, 1.5, 2, 3].map((f) => (
              <button className="rx-btn" key={f} onClick={() => load(`?factor=${f}`)}
                      {...(parseFloat(r.factor) === f ? { "data-primary": "1" } : {})}>{`×${f}`}</button>
            ))}
            <div className="rx-note">
              {r.servings_raw
                ? `This note says "${r.servings_raw}", which is a yield rather than a serving count, so scaling works by multiplier.`
                : "This note has no serving count, so scaling works by multiplier."}
            </div>
          </React.Fragment>
        )}
      </div>

      <div className="rx-cols">
        <div>
          <h2 className="rx-h">Ingredients</h2>
          {lines.length ? (
            <ul className="rx-list">
              {lines.map((line, i) => (
                <Check key={i} k={`recipes.check.${r.slug}.i${i}`}>
                  <span>{line.text}</span>
                  {line.flagged ? <sup className="rx-flag"
                    title={"This line carries a second quantity the scaler did not touch \u2014 check it before measuring."}>unscaled</sup> : null}
                </Check>
              ))}
            </ul>
          ) : <div className="rx-empty">This note keeps its method in the directions and lists no separate ingredients.</div>}
          {flagged ? (
            <div className="rx-note">{flagged + (flagged === 1 ? " line carries" : " lines carry") +
              " a second quantity that was not scaled. They are marked."}</div>
          ) : null}
        </div>
        <div>
          <h2 className="rx-h">Directions</h2>
          <ol className="rx-list rx-steps">
            {steps.map(([i, text]) => (
              <Check key={i} k={`recipes.step.${r.slug}.s${i}`}><span>{text}</span></Check>
            ))}
          </ol>
        </div>
      </div>

      {r.notes ? (
        <div className="rx-notes">
          <h2 className="rx-h">Notes</h2>
          <div>{r.notes}</div>
        </div>
      ) : null}
      {r.source ? (
        <div className="rx-src">
          Source: {r.source_url
            ? <a href={r.source_url} rel="noopener noreferrer" target="_blank">{r.source}</a>
            : r.source}
        </div>
      ) : null}
    </React.Fragment>
  );
}

function Detail({ slug }) {
  const [state, setState] = useState({ r: null, n: 0, missing: false });
  const wake = useRef(null);

  function holdScreen() {
    /* Wake Lock needs a secure context. Over plain http:// on the tailnet the API is
       simply absent, so this no-ops rather than throwing. */
    if (!navigator.wakeLock || document.visibilityState !== "visible") return;
    if (wake.current && !wake.current.released) return; // already held: one lock, not one per rescale
    navigator.wakeLock.request("screen").then((s) => { wake.current = s; }, () => {});
  }
  function load(query) {
    get(`/recipes/api/recipe/${encodeURIComponent(slug)}${query || ""}`)
      .then((r) => setState((p) => ({ r, n: p.n + 1, missing: false })))
      .catch(() => setState((p) => ({ r: null, n: p.n + 1, missing: true })));
  }

  useEffect(() => {
    const vis = () => { if (document.visibilityState === "visible") holdScreen(); };
    const hide = () => { if (wake.current) { wake.current.release(); wake.current = null; } };
    document.addEventListener("visibilitychange", vis);
    window.addEventListener("pagehide", hide);
    load("");
    return () => {
      document.removeEventListener("visibilitychange", vis);
      window.removeEventListener("pagehide", hide);
    };
  }, []);

  useEffect(() => {
    if (!state.r) return;
    document.title = `HUB · ${state.r.dish || state.r.title}`;
    holdScreen();
  }, [state.r]);

  return (
    <div className="rx-detail">
      {state.r ? <Body key={state.n} r={state.r} load={load} /> : null}
      {state.missing ? <div className="rx-empty">No recipe by that name.</div> : null}
    </div>
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

function RecipesApp({ root }) {
  useEffect(() => { root.setAttribute("data-react-mounted", "recipes"); }, []);
  return root.getAttribute("data-view") === "detail" ? <Detail slug={root.getAttribute("data-slug")} /> : <Index />;
}

window.RecipesUI.App = RecipesApp;
const root = document.getElementById("recipes-root");
if (root) ReactDOM.createRoot(root).render(<ErrorBoundary><RecipesApp root={root} /></ErrorBoundary>);
})();
