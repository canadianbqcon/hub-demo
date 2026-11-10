/* food-view.jsx — the /food area view as a component, mounted by two surfaces.
   React port of food-view.js; the plain file stays until its last consumer converts.

   <HubUI.FoodView els data api navigate onSelect compact /> owns the rail, the list,
   the map and the place detail and nothing about where they live: the caller hands it
   the elements to draw into (it portals into each) and a way to fetch one place.

     /food        elements from its own page shell, child areas are links to /food/<slug>.
     trips board  elements from the trips shell, child areas filter in place (navigate).

   els      {rail, head, list, map, detail, sidePane} DOM elements
   data     {area, children, places, portal?} straight off either endpoint
   api      {place(slug) -> place with .evidence}
   navigate optional fn(childSlugOrName); present = the caller handles child areas
   onSelect optional fn(slug|null), fired when the detail opens or closes
   compact  the rail is a slot inside someone else's nav (see food-view.js)
   A new `data` is a new view: the caller remounts with a key, as mount() used to.

   Read-only, on both. There is no POST here and there is not meant to be one. */
window.HubUI = window.HubUI || {};
(() => {
  const { useState, useEffect, useRef, useMemo } = React;
  const { createPortal } = ReactDOM;

  const UNIT_SEP = "\x1f";          // group_concat(char(31)) separator from db.get_areas
  const STALE_MS = 90 * 864e5;      // practical facts go stale by policy at 90 days

  const parseJSON = (s, fallback) => {
    if (Array.isArray(s) || (s && typeof s === "object")) return s;
    try { return JSON.parse(s); } catch { return fallback; }
  };

  // Used only for the Leaflet marker icons, which take an HTML string.
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

  const fold = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().trim();

  const areaHref = (slug) => `/food/${String(slug).split("/").map(encodeURIComponent).join("/")}`;

  const emptyFilters = () => ({ hood: "", broad: "", specific: "", price: new Set(), discovery: new Set(), minDepth: 0, q: "" });

  /* ------------------------------------------------------------- scores ---
     Three states, three renderings. A thin score shows its number WITH the size of
     the ledger under it; a place with no literate evidence has no number at all. */

  function ScoreBlock({ score, confidence, rows, emptyLabel }) {
    if (score === null || score === undefined || confidence === "none") {
      return <div className="score"><span className="score-none">{emptyLabel}</span></div>;
    }
    const thin = confidence === "thin";
    const label = thin
      ? `thin · ${rows} source${rows === 1 ? "" : "s"}`
      : `${confidence} · ${rows} source${rows === 1 ? "" : "s"}`;
    return (
      <div className="score">
        <span className="score-num">{Number(score).toFixed(1)}</span>
        <span className={`score-conf${thin ? " thin" : ""}`}>{label}</span>
      </div>
    );
  }

  const DepthBlock = ({ p }) =>
    <ScoreBlock score={p.depth_score} confidence={p.depth_confidence} rows={p.literate_count ?? 0} emptyLabel="no expert signal found" />;
  const ExecBlock = ({ p }) =>
    <ScoreBlock score={p.execution_score} confidence={p.execution_confidence} rows={p.evidence_count ?? 0} emptyLabel="no evidence yet" />;

  const StatusFlag = ({ p }) =>
    p.status === "unverified" ? <span className="status-flag status-unverified">unverified</span>
    : p.status === "closed" ? <span className="status-flag status-closed">closed</span>
    : null;

  const scored = (p) => p.depth_score !== null && p.depth_score !== undefined
    && p.depth_confidence !== "none";

  /* -------------------------------------------------------------- scene ---
     Three input shapes are accepted, newest first, so an area researched under an
     older contract still renders:
       {city:[...], neighborhoods:[...]}   the current format
       [{label, items}]                    sections only, no neighborhood split
       "prose"                             the original free text */

  function parseScene(raw) {
    const empty = { city: [], neighborhoods: [] };
    if (!raw) return empty;
    const v = parseJSON(raw, null);
    if (v && !Array.isArray(v) && typeof v === "object") {
      return { city: v.city || [], neighborhoods: v.neighborhoods || [] };
    }
    if (Array.isArray(v) && v.every((s) => s && Array.isArray(s.items))) {
      return { city: v, neighborhoods: [] };
    }
    return {
      city: [{ label: "rundown", items: String(raw).split(/\n{2,}/).filter((s) => s.trim()).map((p) => ({ v: p.trim() })) }],
      neighborhoods: [],
    };
  }

  const sceneCount = (sections) => sections.reduce((n, s) => n + s.items.length, 0);

  const NoRundown = ({ area }) => (
    <div className="empty">
      <p className="lead">No rundown for this area yet.</p>
      <p className="hint">Run <code>/food {area.name}</code> to write one.</p>
    </div>
  );

  function Scene({ sections, area }) {
    if (!sections.length) return <NoRundown area={area} />;
    return sections.map((sec, i) => (
      <section className="sc-sec" key={i}>
        <h3 className="sc-head">{sec.label || ""}</h3>
        {sec.items.map((it, j) => it.k
          ? <div className="sc-row" key={j}><span className="k">{it.k}</span><span className="v">{it.v}</span></div>
          : <div className="sc-row bare" key={j}><span className="v">{it.v}</span></div>)}
      </section>
    ));
  }

  /* One grid, not two: a child that has a rundown card keeps the card; a child with
     no card still shows up; a card with no child is kept, but not a link. */
  function withinCards(scene, children) {
    const cards = new Map((scene.neighborhoods || [])
      .filter((h) => h?.name).map((h) => [fold(h.name), h]));
    const out = children.map((c) => {
      const card = cards.get(fold(c.name));
      cards.delete(fold(c.name));
      return Object.assign({}, c, { note: card?.note, traditions: card?.traditions,
                                    streets: card?.streets, heads_up: card?.heads_up });
    });
    return out.concat([...cards.values()].map((h) => Object.assign({}, h, { orphan: true, place_count: 0 })));
  }

  function HoodCard({ h, navigate }) {
    const traditions = (h.traditions || []).filter(Boolean);
    const cuisines = (h.cuisines || "").split(UNIT_SEP).filter(Boolean).slice(0, 3);
    const Tag = h.orphan ? "div" : (navigate ? "button" : "a");
    const open = h.orphan ? {}
      : navigate ? { type: "button", "data-child": h.slug || h.name, onClick: () => navigate(h.slug || h.name) }
      : { href: areaHref(h.slug) };
    const member = h.orphan ? {} : { "data-member": JSON.stringify(h.member) ?? "" };
    const pills = traditions.length ? traditions : cuisines;
    return (
      <Tag className={`hcard${h.orphan ? " hcard-orphan" : ""}`} {...open} {...member}>
        <div className="hcard-head">
          <span className="hname">{h.name}</span>
          {h.orphan
            ? <span className="hboro">not researched</span>
            : <span className="hboro">{h.place_count} place{h.place_count === 1 ? "" : "s"}</span>}
        </div>
        {h.note ? <p className="hsum">{h.note}</p> : null}
        <div className="hcard-pills">
          {pills.length
            ? pills.map((t, i) => <span className="hpill" key={i}>{t}</span>)
            : <span className="hpill hpill-none">no tradition recorded</span>}
        </div>
        <div className="hcard-foot">
          <span className="hfact-k">where exactly</span>
          <span className="hfact-v">{h.streets || "not narrowed down yet"}</span>
          {h.heads_up ? <span className="hnote">{h.heads_up}</span> : null}
        </div>
      </Tag>
    );
  }

  function Within({ cards, area, navigate }) {
    if (!cards.length) return <NoRundown area={area} />;
    const real = cards.filter((c) => !c.orphan);
    const orphans = cards.filter((c) => c.orphan);
    const group = (label, items) => items.length ? (
      <React.Fragment>
        <div className="group-head"><span>{label}</span><span className="n">{items.length}</span></div>
        <div className="hoodgrid">{items.map((h, i) => <HoodCard h={h} navigate={navigate} key={i} />)}</div>
      </React.Fragment>
    ) : null;
    return <React.Fragment>{group(`inside ${area.name}`, real)}{group("noted, not researched", orphans)}</React.Fragment>;
  }

  /* ------------------------------------------------------------ filters --- */

  const cuisinesOf = (p) =>
    [p.cuisine_specific, ...parseJSON(p.cuisines_extra, [])].filter(Boolean);

  function matches(p, f) {
    // A borough or city page is a roll-up of several neighborhoods, and "where do I
    // go" is a neighborhood question, not a borough one.
    if (f.hood && p.neighborhood !== f.hood) return false;
    if (f.broad && p.cuisine_broad !== f.broad) return false;
    // A place that also cooks a second tradition surfaces under both.
    if (f.specific && !cuisinesOf(p).includes(f.specific)) return false;
    if (f.price.size && !f.price.has(p.price_band)) return false;
    if (f.discovery.size && !f.discovery.has(p.discovery)) return false;
    if (f.minDepth && !(p.depth_score >= f.minDepth)) return false;
    if (f.q) {
      const hay = [p.name, p.cuisine_specific, p.cuisine_broad, p.neighborhood, p.borough, p.summary]
        .map((v) => String(v || "").toLowerCase()).join(" ");
      if (!hay.includes(f.q)) return false;
    }
    return true;
  }

  // Count for one chip = what the list would hold if that chip alone were toggled on,
  // every other filter still applied. Anything else and the number lies about the click.
  function countWith(places, filters, dimension, value) {
    const f = Object.assign({}, filters, { price: new Set(filters.price), discovery: new Set(filters.discovery) });
    if (dimension === "price" || dimension === "discovery") { f[dimension] = new Set([value]); }
    else { f[dimension] = value; }
    return places.filter((p) => matches(p, f)).length;
  }

  const specificsUnder = (places, broad) =>
    [...new Set(places.filter((p) => !broad || p.cuisine_broad === broad).flatMap(cuisinesOf))];

  const filtersActive = (f) =>
    !!(f.hood || f.broad || f.specific || f.price.size || f.discovery.size || f.minDepth || f.q);

  /* -------------------------------------------------------------- places --- */

  function PlaceRow({ p, selected, onOpen }) {
    const hood = p.neighborhood || p.borough || "";
    return (
      <button type="button" className={`row${selected === p.slug ? " selected" : ""}`} data-slug={p.slug} onClick={() => onOpen(p.slug)}>
        <span className="row-name">{p.name}</span>
        <DepthBlock p={p} />
        <span className="row-sub">
          <span className="chip chip-cuisine" title={p.cuisine_specific || p.cuisine_broad || ""}>{p.cuisine_specific || p.cuisine_broad || "—"}</span>
          {p.price_band ? <span className="chip chip-price">{p.price_band}</span> : null}
          {hood ? <React.Fragment><span>{hood}</span><span className="dot">·</span></React.Fragment> : null}
          <span className={`mark mark-${p.discovery ?? ""}`}>{p.discovery}</span>
          <StatusFlag p={p} />
        </span>
      </button>
    );
  }

  function Results({ shown, places, area, selected, onOpen }) {
    if (!shown.length) {
      return (
        <div className="empty">
          <p className="lead">{places.length ? "Nothing matches these filters." : "No places researched in this area yet."}</p>
          <p className="hint">{places.length
            ? "Clear a filter to widen the set."
            : <React.Fragment>Run <code>/food {area.name}</code> to research it.</React.Fragment>}</p>
        </div>
      );
    }
    // Judged and unjudged are separate groups, not one numeric sort with the unknowns
    // swept to the tail. A place nobody qualified has assessed is not a bad place.
    const group = (label, items) => items.length ? (
      <React.Fragment>
        <div className="group-head"><span>{label}</span><span className="n">{items.length}</span></div>
        {items.map((p) => <PlaceRow p={p} selected={selected} onOpen={onOpen} key={p.slug} />)}
      </React.Fragment>
    ) : null;
    return <React.Fragment>{group("scored on depth", shown.filter(scored))}{group("no expert signal yet", shown.filter((p) => !scored(p)))}</React.Fragment>;
  }

  /* ---------------------------------------------------------------- map ---
     The mark is the Hub's shared one (map.css): a dot that never leaves its
     coordinate, with the label hung above it on a leader, led here by the depth score. */

  function markIcon(p, selected) {
    const cls = [
      "mstop", `mstop-${p.discovery}`,
      scored(p) ? "" : "is-anytime",           // nothing qualified has scored it: hollow dot
      selected === p.slug ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    return L.divIcon({
      className: "",
      html: `<span class="${cls}">`
        + `<span class="mchip">${scored(p) ? `<b>${Number(p.depth_score).toFixed(1)}</b>` : ""}`
        + `<em>${esc(p.name)}</em></span><span class="mlead"></span><span class="mdot"></span></span>`,
      iconSize: [10, 10], iconAnchor: [5, 5],
    });
  }

  /* Area overlay: the hull of a child's own places, not its civic boundary. */
  const OVERLAY_STYLE = { className: "area-overlay", weight: 2, dashArray: "5 4",
                          fillOpacity: 0.12, interactive: false };

  const centroid = (pts) => [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ];

  /* Monotone chain. `cross <= 0` drops collinear points, which is also the degenerate
     test: a collinear or coincident set cannot produce three vertices, so it falls
     through to the circle. */
  function hullOf(pts) {
    if (pts.length < 3) return null;
    const P = pts.map(([lat, lng]) => [lng, lat]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const half = (src) => src.reduce((h, p) => {
      while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], p) <= 0) h.pop();
      h.push(p);
      return h;
    }, []);
    const ring = half(P).slice(0, -1).concat(half([...P].reverse()).slice(0, -1));
    return ring.length < 3 ? null : ring.map(([lng, lat]) => [lat, lng]);
  }

  /* Push each vertex out from the centre so pins sit inside the edge rather than on it.
     ponytail: a metre offset applied per-vertex, not a real polygon buffer — good enough
     at neighborhood scale; swap in a buffering library if a concave area ever needs one. */
  function padRing(ring, metres) {
    const c = centroid(ring);
    const k = Math.cos(c[0] * Math.PI / 180) || 1;
    return ring.map(([lat, lng]) => {
      const dy = lat - c[0], dx = (lng - c[1]) * k;
      const d = Math.hypot(dx, dy) || 1;
      return [lat + (metres / 111320) * dy / d, lng + (metres / 111320) * dx / d / k];
    });
  }

  const metresBetween = (a, b) => Math.hypot(
    (a[0] - b[0]) * 111320,
    (a[1] - b[1]) * 111320 * Math.cos(a[0] * Math.PI / 180));

  const inMember = (p, m) =>
    p.city === m.city
    && (!("borough" in m) || (m.borough === null
        ? !String(p.borough || "").trim() : p.borough === m.borough))
    && (!("neighborhood" in m) || p.neighborhood === m.neighborhood);

  /* ------------------------------------------------------------- detail --- */

  function Quote({ e }) {
    return (
      <div className={`ev ev-${e.cohort} ev-polarity-${e.polarity}`}>
        <blockquote>{e.quote}</blockquote>
        {e.cohort_reason ? <p className="why">{e.cohort_reason}</p> : null}
        <div className="ev-foot">
          <span className="ev-cohort">{e.cohort}</span>
          <a href={e.url} target="_blank" rel="noopener">{e.source}</a>
          {e.author ? <span className="who">{e.author}</span> : null}
          {e.dated ? <span className="who">{e.dated}</span> : null}
        </div>
      </div>
    );
  }

  function Detail({ p, onBack }) {
    const lit = p.evidence.filter((e) => e.cohort === "literate");
    const rest = p.evidence.filter((e) => e.cohort !== "literate");
    const practical = parseJSON(p.practical, {});
    const stale = p.practical_checked && (Date.now() - Date.parse(p.practical_checked)) > STALE_MS;
    const order = parseJSON(p.order_this, []);
    const pros = parseJSON(p.pros, []);
    const cons = parseJSON(p.cons, []);
    return (
      <div className="detail">
        <div className="detail-head">
          <button type="button" className="detail-back" id="fvDetailBack" aria-label="close" onClick={onBack}>✕</button>
          <div className="detail-title">
            <h2>{p.name}</h2>
            <span className="addr">{p.address || ""}</span>
          </div>
          {p.address
            ? <a className="detail-maps" target="_blank" rel="noreferrer"
                 href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address}`)}`}>maps</a>
            : null}
        </div>
        <div className="detail-body">
          <div className="score-pair">
            <div className="score-cell">
              <span className="axis">depth</span>
              <DepthBlock p={p} />
              <span className="axis-note">how real it is within {p.cuisine_specific || "its tradition"}</span>
            </div>
            <div className="score-cell">
              <span className="axis">execution</span>
              <ExecBlock p={p} />
              <span className="axis-note">how well it does what it is going for</span>
            </div>
          </div>

          <p className="summary">{p.summary}</p>

          <div className="sec"><h3>identity</h3>
            <div className="idrow">
              <span className="chip chip-cuisine" title={p.cuisine_specific || p.cuisine_broad || ""}>{p.cuisine_specific || "—"}</span>
              {parseJSON(p.cuisines_extra, []).map((c, i) => <span className="chip chip-cuisine" title={c} key={i}>{c}</span>)}
              {p.price_band ? <span className="chip chip-price">{p.price_band}</span> : null}
              <span className={`mark mark-${p.discovery ?? ""}`}>{p.discovery}</span>
              <StatusFlag p={p} />
            </div>
          </div>

          {order.length ? <div className="sec"><h3>order this</h3><ul className="order">
            {order.map((o, i) => <li key={i}><span className="dish">{o.dish ?? o}</span><span className="why">{o.why ?? ""}</span></li>)}
          </ul></div> : null}

          {pros.length ? <div className="sec"><h3>pros</h3><ul className="pros">{pros.map((x, i) => <li key={i}>{x}</li>)}</ul></div> : null}
          {cons.length ? <div className="sec"><h3>cons</h3><ul className="cons">{cons.map((x, i) => <li key={i}>{x}</li>)}</ul></div> : null}

          <div className="sec"><h3>practical{" "}
            {p.practical_checked ? <span className={`stamp${stale ? " stale" : ""}`}>checked {p.practical_checked}{stale ? " — over 90 days, re-check before you go" : ""}</span> : null}
          </h3>
            <ul className="pc">{Object.entries(practical).length
              ? Object.entries(practical).map(([k, v]) =>
                  <li key={k}><span className="k">{k.replace(/_/g, " ")}</span><span>{typeof v === "boolean" ? (v ? "yes" : "no") : String(v ?? "")}</span></li>)
              : <li><span className="score-none">nothing checked yet</span></li>}</ul>
          </div>

          <div className="sec"><h3>evidence <span className="stamp">{lit.length} literate · {rest.length} other</span></h3>
            {p.evidence.length
              ? <div className="ledger">{lit.map((e, i) => <Quote e={e} key={`l${i}`} />)}{rest.map((e, i) => <Quote e={e} key={`r${i}`} />)}</div>
              : <p className="score-none">No quotes were recorded for this place. Both scores are withheld.</p>}
          </div>
        </div>
      </div>
    );
  }

  /* --------------------------------------------------------------- rail --- */

  function Rail({ st, set }) {
    const { places, children, scene, filters: f, view, compact, navigate } = st;
    // Only worth a control when the view actually spans more than one: a neighborhood
    // holds one value and the select would be a no-op.
    const hoods = [...new Set(places.map((p) => p.neighborhood).filter(Boolean))].sort();
    const broads = [...new Set(places.map((p) => p.cuisine_broad).filter(Boolean))].sort();
    const specifics = specificsUnder(places, f.broad).sort();
    const prices = [...new Set(places.map((p) => p.price_band).filter(Boolean))]
      .sort((a, b) => a.length - b.length);

    const chip = (dim, value, label) => {
      const on = f[dim].has(value);
      const n = countWith(places, f, dim, value);
      return (
        <button type="button" className={`filter-chip${on ? " active" : ""}`} data-dim={dim} data-val={value} key={value}
                disabled={n === 0 && !on} aria-pressed={on}
                onClick={() => set.toggle(dim, value)}>
          <span className="filter-chip-box"></span>{label}
          <span className="filter-chip-count">{n}</span>
        </button>
      );
    };

    const nav = (v, label, n) => (
      <button type="button" className={`hub-nav-item fvtab${view === v ? " active" : ""}`} data-view={v}
              aria-pressed={view === v} onClick={() => set.view(v)}>
        <span className="hub-nav-label fvtab-l">{label}</span><span className="fvtab-n">{n}</span>
      </button>
    );

    const cards = withinCards(scene, children);
    const within = cards.filter((c) => !c.orphan).length;
    const sel = (id, label, value, onChange, first, opts, disabled) => (
      <span className="f-sel"><select className="f-select" id={id} aria-label={label} disabled={disabled}
                                       value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={first[0]}>{first[1]}</option>
        {opts}
      </select></span>
    );
    const optList = (list) => list.map((h) => <option value={h} key={h}>{h}</option>);
    return (
      <React.Fragment>
        <nav className="hub-nav-rail fview-nav">
          {nav("places", "places", places.length)}
          {nav("city", "the city", sceneCount(scene.city))}
          {/* The count is the areas you can actually open, which is what the label promises. */}
          {cards.length ? nav("within", "areas within", within) : null}
        </nav>
        {children.length && !compact ? <div className="within">
          <span className="filters-head">areas within</span>
          {children.map((c) => {
            const Tag = navigate ? "button" : "a";
            const open = navigate
              ? { type: "button", "data-child": c.slug || c.name, onClick: () => navigate(c.slug || c.name) }
              : { href: areaHref(c.slug) };
            return (
              <Tag className={`within-row${f.hood && f.hood === c.name ? " active" : ""}`} {...open}
                   data-member={JSON.stringify(c.member) ?? ""} key={c.slug || c.name}>
                <span className="within-name">{c.name}</span>
                <span className="chip">{c.level}</span>
                <span className="within-n">{c.place_count}</span>
              </Tag>
            );
          })}
        </div> : null}
        {view === "places" && places.length ? <details className="filters" open={!compact && window.innerWidth > 680}>
          <summary className="filters-head">filter</summary>
          <div className="filter-row">
            {hoods.length > 1 ? sel("fvHood", "neighborhood", f.hood, set.hood, ["", "every neighborhood"], optList(hoods)) : null}
            {sel("fvBroad", "cuisine", f.broad, set.broad, ["", "every cuisine"], optList(broads))}
            {sel("fvSpecific", "tradition", f.specific, set.specific, ["", "every tradition"], optList(specifics), !specifics.length)}
            {sel("fvDepth", "minimum depth", String(f.minDepth), (v) => set.depth(Number(v)), ["0", "any depth"],
                 [6, 7, 8, 9].map((v) => <option value={String(v)} key={v}>depth {v}+</option>))}
          </div>
          <div className="filter-row wrap">
            {chip("discovery", "consensus", "consensus")}
            {chip("discovery", "dig", "dig")}
          </div>
          {prices.length ? <div className="filter-row wrap">{prices.map((pb) => chip("price", pb, pb))}</div> : null}
        </details> : null}
      </React.Fragment>
    );
  }

  /* --------------------------------------------------------------- view --- */

  function FoodView({ els, data, api, navigate, onSelect, compact }) {
    const area = data.area;
    const children = data.children || [];
    const places = data.places || [];
    const portal = data.portal || null;
    const scene = useMemo(() => parseScene(area.scene), [area]);

    const [view, setViewRaw] = useState(() => places.length ? "places" : (scene.city.length ? "city" : "places"));
    const [filters, setFiltersRaw] = useState(emptyFilters);
    const [text, setText] = useState("");          // the search box as typed; filters.q is its folded form
    const [selected, setSelected] = useState(null);
    const [place, setPlace] = useState(null);
    const [err, setErr] = useState(null);
    const [map, setMap] = useState(null);

    // Handlers read the newest props/state through this, so Leaflet and document
    // listeners registered once never see a stale closure.
    const live = useRef({});
    live.current = { api, onSelect, selected };
    const M = useRef({ pinLayer: null, overlay: null, homeView: null, markers: new Map(), fitted: false, canvas: null });
    const canvasRef = useRef(null);

    /* The rail is redrawn on a filter change or a tab change but NOT on a keystroke in
       the search box (the head would lose the caret), so its chip counts keep the values
       from the last redraw until then. railF is that snapshot. */
    const filtersRef = useRef(filters);
    const [railF, setRailF] = useState(filters);
    // A new filter state or view clears a failed-load message, as the next render did.
    const setFilters = (fn, typing) => {
      const next = fn(filtersRef.current);
      filtersRef.current = next;
      setErr(null);
      setFiltersRaw(next);
      if (!typing) setRailF(next);
    };
    const setView = (v) => { setErr(null); setViewRaw(v); setRailF(filtersRef.current); };

    // The trips board's guest CSS hides every button inside the list and the detail
    // pane; marking the elements this view owns lets its deny-by-default rule skip
    // exactly this subtree.
    useEffect(() => {
      Object.values(els).forEach((e) => { e?.classList.add("fview-own"); });
      return () => { Object.values(els).forEach((e) => { e?.classList.remove("fview-own"); }); };
    }, [els]);

    /* ---- map ---- */
    const visiblePins = () => places.filter((p) => matches(p, filters) && p.lat !== null && p.lng !== null);

    /* Chips are hover-only, so nothing collides. What is left is the frame edge: near
       it a chip anchors to the dot instead of centring on it. */
    function edgeAnchor() {
      if (!map) return;
      const w = map.getSize().x;
      M.current.markers.forEach((m) => {
        const chip = m.getElement()?.querySelector(".mchip");
        if (!chip) return;
        const x = map.latLngToContainerPoint(m.getLatLng()).x;
        chip.classList.toggle("at-l", x < 90);
        chip.classList.toggle("at-r", x > w - 90);
      });
    }

    function fitPins(pins) {
      if (!map) return;
      if (pins.length) map.fitBounds(pins.map((p) => [p.lat, p.lng]),
                                     { padding: [40, 40], maxZoom: 15, animate: false });
      else map.setView([area.lat ?? 40.7, area.lng ?? -73.95], 11);
    }

    function clearOverlay() {
      const m = M.current;
      if (m.overlay) { map.removeLayer(m.overlay); m.overlay = null; }
      canvasRef.current?.classList.remove("map-silhouette");
      // The view was borrowed to show the shape, so it goes back.
      if (m.homeView) {
        map.flyTo(m.homeView.c, m.homeView.z, { duration: 0.4 });
        m.homeView = null;
      }
    }

    function showOverlay(member) {
      if (!map || !member) return;
      clearOverlay();
      const pts = [...new Map(places
        .filter((p) => inMember(p, member) && p.lat !== null && p.lng !== null)
        .map((p) => [`${p.lat},${p.lng}`, [p.lat, p.lng]])).values()];
      if (!pts.length) return;                     // card says "no places mapped yet"

      const m = M.current;
      const hull = hullOf(pts);
      m.overlay = hull
        ? L.polygon(padRing(hull, 60), OVERLAY_STYLE)
        : L.circle(centroid(pts), Object.assign({}, OVERLAY_STYLE, {
            radius: Math.max(150, ...pts.map((p) => metresBetween(centroid(pts), p))),
          }));
      m.overlay.addTo(map);
      // Drawing it is not showing it: the map goes to the shape while the pointer is
      // held, and clearOverlay brings it back.
      if (!m.homeView) m.homeView = { c: map.getCenter(), z: map.getZoom() };
      map.flyToBounds(m.overlay.getBounds(), { padding: [60, 60], maxZoom: 14, duration: 0.5 });
      // Pins go away entirely while an area is held.
      canvasRef.current?.classList.add("map-silhouette");
    }

    // The map itself: built once, the view set before anything reads geometry.
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas || !window.L) return undefined;
      M.current.canvas = canvas;
      const lm = L.map(canvas, { scrollWheelZoom: true, attributionControl: false })
        .setView([area.lat ?? 40.7, area.lng ?? -73.95], 11);
      M.current.pinLayer = L.layerGroup().addTo(lm);
      // Back to the whole area: re-runs the FIT, not a redraw, so the open place panel survives.
      const b = document.createElement("button");
      b.type = "button";
      b.className = "map-recenter";
      b.title = "back to the whole area";
      b.setAttribute("aria-label", "recenter the map");
      b.textContent = "⌖";
      b.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); live.current.refit(); };
      // disableClickPropagation is not optional: leaflet listens for drag on the
      // container, so without it the press starts a pan under the pointer.
      L.DomEvent.disableClickPropagation(b);
      L.DomEvent.disableScrollPropagation(b);
      canvas.appendChild(b);
      setMap(lm);
      return () => { lm.remove(); M.current.markers.clear(); M.current.overlay = null; M.current.homeView = null; setMap(null); };
    }, []);

    // Pins: redrawn on every filter or selection change; fitted only the first time.
    useEffect(() => {
      if (!map) return;
      clearOverlay();          // the markers it highlighted are about to be replaced
      const m = M.current;
      m.pinLayer.clearLayers();
      m.markers.clear();
      const pins = visiblePins();
      pins.forEach((p) => {
        const mk = L.marker([p.lat, p.lng], { icon: markIcon(p, selected), title: p.name })
          .on("click", () => live.current.showPlace(p.slug));
        m.markers.set(p.slug, mk);
        m.pinLayer.addLayer(mk);
      });
      edgeAnchor();
      if (!m.fitted) { fitPins(pins); m.fitted = true; }
    }, [map, filters, selected]);

    useEffect(() => {
      if (!map) return undefined;
      map.on("moveend zoomend", edgeAnchor);
      return () => { map.off("moveend zoomend", edgeAnchor); };
    }, [map, filters]);

    live.current.refit = () => fitPins(visiblePins());

    // Detail open/close: the map just changed height, so Leaflet has to be told.
    useEffect(() => {
      els.sidePane?.classList.toggle("has-detail", !!place);
      if (!map) return;
      map.invalidateSize();
      const mk = place && M.current.markers.get(selected);
      if (mk) map.setView(mk.getLatLng(), Math.max(map.getZoom(), 15), { animate: true });
    }, [place]);

    /* ---- overlay hover: delegated, 220ms leave delay (see food-view.js) ---- */
    live.current.showOverlay = showOverlay;
    live.current.clearOverlay = clearOverlay;
    useEffect(() => {
      let t = null;
      const target = (e) => e.target.closest?.("[data-member]");
      const enter = (e) => {
        const n = target(e);
        if (n && live.current.map) { clearTimeout(t); live.current.showOverlay(JSON.parse(n.dataset.member)); }
      };
      const leave = (e) => {
        if (!target(e)) return;
        clearTimeout(t);
        t = setTimeout(() => live.current.map && live.current.clearOverlay(), 220);
      };
      const hosts = [els.rail, els.list].filter(Boolean);
      hosts.forEach((h) => {
        h.addEventListener("pointerover", enter);
        h.addEventListener("focusin", enter);
        h.addEventListener("pointerout", leave);
        h.addEventListener("focusout", leave);
      });
      return () => {
        clearTimeout(t);
        hosts.forEach((h) => {
          h.removeEventListener("pointerover", enter);
          h.removeEventListener("focusin", enter);
          h.removeEventListener("pointerout", leave);
          h.removeEventListener("focusout", leave);
        });
      };
    }, [els]);
    live.current.map = map;

    /* ---- detail ---- */
    function showPlace(slug) {
      return live.current.api.place(slug).then((p) => {
        // The list rows carry these counts as columns; the detail already has the whole
        // ledger in hand, so it counts what it is about to render.
        const lit = p.evidence.filter((e) => e.cohort === "literate");
        setSelected(slug);
        setPlace(Object.assign({}, p, { literate_count: lit.length, evidence_count: p.evidence.length }));
        if (live.current.onSelect) live.current.onSelect(slug);
      }, (e) => { console.error(e); setErr(e); });
    }
    live.current.showPlace = showPlace;

    function backToList() {
      setSelected(null);
      setPlace(null);
      if (live.current.onSelect) live.current.onSelect(null);
    }
    live.current.backToList = backToList;

    useEffect(() => {
      const onKey = (e) => { if (e.key === "Escape" && live.current.selected) live.current.backToList(); };
      document.addEventListener("keydown", onKey);
      return () => { document.removeEventListener("keydown", onKey); };
    }, []);

    /* ---- rail handlers ---- */
    const upd = (patch, typing) => setFilters((f) => Object.assign({}, f, patch), typing);
    const set = {
      view: setView,
      toggle: (dim, val) => setFilters((f) => {
        const s = new Set(f[dim]);
        s.has(val) ? s.delete(val) : s.add(val);
        return Object.assign({}, f, { [dim]: s });
      }),
      hood: (v) => upd({ hood: v }),
      // A tradition picked under the old cuisine may not exist under the new one.
      broad: (v) => setFilters((f) => Object.assign({}, f, { broad: v,
        specific: f.specific && !specificsUnder(places, v).includes(f.specific) ? "" : f.specific })),
      specific: (v) => upd({ specific: v }),
      depth: (v) => upd({ minDepth: v }),
    };

    const st = { places, children, scene, filters: railF, view, compact: !!compact, navigate };
    const shown = places.filter((p) => matches(p, filters));
    const cards = withinCards(scene, children);
    const sceneHead = (count) => {
      const stamp = area.scene_researched ? `researched ${area.scene_researched}` : "not researched yet";
      return <div className="fview-head"><span>{count}</span><span>{stamp}</span></div>;
    };
    const within = cards.filter((c) => !c.orphan).length;

    let headEl, listEl;
    if (view === "city" || view === "within") {
      headEl = sceneHead(view === "city"
        ? `${sceneCount(scene.city)} across ${scene.city.length} section${scene.city.length === 1 ? "" : "s"}`
        : `${within} area${within === 1 ? "" : "s"} within`);
      listEl = view === "city"
        ? <div className="scene-view"><Scene sections={scene.city} area={area} /></div>
        : <div className="scene-view hoods-view"><Within cards={cards} area={area} navigate={navigate} /></div>;
    } else {
      headEl = (
        <div className="fview-head">
          <span className="fview-search"><span aria-hidden="true">🔍</span><input id="fvSearch" type="search"
            aria-label={`search ${area.name}`} placeholder="cuisine, neighborhood, name"
            value={text}
            onChange={(e) => { setText(e.target.value); upd({ q: e.target.value.trim().toLowerCase() }, true); }} /></span>
          <span className="fview-count">{shown.length} of {places.length} shown</span>
          <button type="button" className="hub-btn filter-reset" id="fvReset" hidden={!filtersActive(filters)}
                  onClick={() => { setText(""); setFilters(() => emptyFilters()); }}>clear filters</button>
          {portal ? <a className="hub-btn fview-portal" href={portal}>open the full research</a> : null}
        </div>
      );
      listEl = <div className="results"><Results shown={shown} places={places} area={area} selected={selected} onOpen={showPlace} /></div>;
    }
    if (err) listEl = <div className="hub-error">could not load this place. {String(err.message || err)}</div>;

    return (
      <React.Fragment>
        {els.rail && createPortal(<Rail st={st} set={set} />, els.rail)}
        {els.head && createPortal(headEl, els.head)}
        {els.list && createPortal(listEl, els.list)}
        {els.map && createPortal(window.L
          ? <div className="fview-map" ref={canvasRef}></div>
          : <div className="map-note">map unavailable — leaflet did not load. The list is unaffected.</div>, els.map)}
        {els.detail && place ? createPortal(<Detail p={place} onBack={backToList} />, els.detail) : null}
        <HubUI.Basemap map={map} />
      </React.Fragment>
    );
  }

  HubUI.FoodView = FoodView;
})();
