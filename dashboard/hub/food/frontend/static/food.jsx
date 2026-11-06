/* Food module frontend (React). Ported from food.js: same DOM, ids, classes and requests.
   Read-only: no form posts anywhere in this file.

   Filtering runs client-side over the area's already-fetched place list (HubUI.FoodView),
   so every chip can show a live count of what it would leave behind. The crumb lives in the
   template's topbar and is drawn through a portal; #food-root is the React root. */
(() => {
  const { useState, useEffect, useLayoutEffect, useRef } = React;
  const { createPortal } = ReactDOM;

  const UNIT_SEP = "\x1f";   // group_concat(char(31)) separator from db.get_areas
  const root = document.getElementById("food-root");
  const crumb = document.getElementById("crumb");

  function json(url) {
    return fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return r.json();
    });
  }

  const Failed = ({ err, what }) =>
    <div className="hub-error">could not load {what}. {String(err.message || err)}</div>;

  /* ----------------------------------------------------------- area index --- */

  /* The landing surface is a globe, not a list. Areas are researched at three grains
     (city, borough, neighborhood) and that hierarchy is spatial, so the zoom level IS the
     filter. The rail beside it is the old list, kept whole, and what renders when maplibre
     does not load. */

  const LEVEL_ZOOM = { city: 0, borough: 6.5, neighborhood: 9.5 };
  // Below this the pins are dots only: two city labels a thousand miles apart still
  // collide on a globe zoomed out far enough to hold both.
  const LABEL_ZOOM = 2;
  const LEVEL_FLYTO = { city: 9, borough: 11, neighborhood: 13.5 };

  const isNight = () => document.documentElement.getAttribute("data-surface") === "dark";

  /* Two raster sources rather than one flat basemap: Esri's imagery is the daylit earth,
     NASA's Black Marble the same earth at night. All of this is paint properties on two
     layers that always exist, so a surface flip is a handful of setPaintProperty calls,
     never a style reload. */
  const SAT_PAINT = (night) => ({
    "raster-brightness-max": night ? ["interpolate", ["linear"], ["zoom"], 0, 0.34, 9, 0.62] : 1,
    "raster-saturation": night ? -0.32 : -0.06,
    "raster-contrast": night ? -0.08 : 0.05,
  });
  const NIGHT_PAINT = (night) => ({
    "raster-opacity": night ? ["interpolate", ["linear"], ["zoom"], 0, 0.82, 5.5, 0.8, 8, 0] : 0,
  });
  /* The atmosphere is what makes the sphere read as a planet; faded out by z7. */
  const SKY = (night) => ({
    "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 0.7, 7, 0],
    "sky-color": night ? "#0a1330" : "#8fb8e8",
    "horizon-color": night ? "#3d7ac9" : "#dceaf8",
    "fog-color": night ? "#0a1330" : "#e8f1fb",
    "sky-horizon-blend": 0.6,
    "horizon-fog-blend": 0.55,
  });

  const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));

  // Builds the maplibre globe into `el`; returns {fly, home, stop}.
  function drawGlobe(el, areas) {
    const g = { map: null, pins: [], home: null, userMoved: false };
    // Centre on the areas rather than on nothing: an empty ocean is a worse first frame.
    const lat = areas.reduce((s, a) => s + a.lat, 0) / areas.length;
    const lng = areas.reduce((s, a) => s + a.lng, 0) / areas.length;

    const night = isNight();
    const map = new maplibregl.Map({
      container: el,
      center: [lng, lat],
      // A phone-width frame at zoom 2.2 is filled edge to edge by one continent, so
      // the sphere never appears. Start further out.
      zoom: el.clientWidth < 700 ? 0.9 : 2.2,
      attributionControl: false,
      style: {
        version: 8,
        projection: { type: "globe" },   // set in the style, so it survives style.load
        sky: SKY(night),
        sources: {
          sat: {
            type: "raster", tileSize: 256, maxzoom: 19,
            tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
            attribution: "Imagery © Esri",
          },
          night: {
            type: "raster", tileSize: 256, maxzoom: 8,
            tiles: ["https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/VIIRS_CityLights_2012/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpg"],
            attribution: "NASA GIBS",
          },
        },
        // No background layer: space is left transparent so the CSS starfield shows through.
        layers: [
          { id: "sat", type: "raster", source: "sat", paint: SAT_PAINT(night) },
          { id: "night", type: "raster", source: "night", paint: NIGHT_PAINT(night) },
        ],
      },
    });
    g.map = map;
    // The camera it returns to when nothing is being pointed at.
    g.home = { center: map.getCenter(), zoom: map.getZoom() };
    // A gesture is a claim on the camera: once he has dragged or scrolled the globe
    // himself, pulling it back home on every un-hover would be fighting him.
    map.on("movestart", (e) => { if (e.originalEvent) g.userMoved = true; });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    g.pins = areas.map((a) => {
      const pin = document.createElement("button");
      pin.className = `globe-pin globe-pin-${a.level}`;
      pin.type = "button";
      pin.title = a.name;
      pin.innerHTML = `<i class="globe-dot globe-dot-${escHtml(a.level)}"></i>
      <span class="globe-pin-label">${escHtml(a.name)}${a.place_count ? `<em>${a.place_count}</em>` : ""}</span>`;
      pin.addEventListener("click", () => { location.href = `/food/${encodeURIComponent(a.slug)}`; });
      // anchor "center" on a zero-sized element puts the element origin exactly on the coordinate.
      const m = new maplibregl.Marker({ element: pin, anchor: "center", opacityWhenCovered: "0" })
        .setLngLat([a.lng, a.lat]).addTo(map);
      return { area: a, el: pin, marker: m };
    });

    const gate = () => {
      const z = map.getZoom();
      g.pins.forEach((p) => {
        p.el.classList.toggle("is-far", z < (LEVEL_ZOOM[p.area.level] ?? 0));
        p.el.classList.toggle("is-dot", z < LABEL_ZOOM);
      });
    };
    map.on("zoom", gate);
    gate();

    // Day side / night side is the only thing the surface toggle changes here, and it
    // is all paint: the sources, the markers and the camera survive the flip.
    const repaint = () => {
      const n = isNight();
      Object.entries(SAT_PAINT(n)).forEach(([k, v]) => { map.setPaintProperty("sat", k, v); });
      Object.entries(NIGHT_PAINT(n)).forEach(([k, v]) => { map.setPaintProperty("night", k, v); });
      map.setSky(SKY(n));
    };
    document.addEventListener("hub:themechange", repaint);
    document.addEventListener("hub:surfacechange", repaint);

    return {
      fly(slug) {
        const p = g.pins.find((x) => x.area.slug === slug);
        if (!p) return;
        g.userMoved = false;   // this move is ours, so ours is still the camera to restore
        map.flyTo({ center: [p.area.lng, p.area.lat], zoom: LEVEL_FLYTO[p.area.level] ?? 9, speed: 1.1 });
      },
      home() {
        if (!g.home || g.userMoved) return;
        map.flyTo(Object.assign({}, g.home, { speed: 1.1 }));
      },
      stop() {
        document.removeEventListener("hub:themechange", repaint);
        document.removeEventListener("hub:surfacechange", repaint);
        map.remove();
      },
    };
  }

  /* Areas nest: a borough sits inside its city, a neighborhood inside its borough. An
     area whose parent has not been researched yet is a root here rather than being
     hidden: the run that created it is real. */
  function areaTree(areas) {
    const by = new Map(areas.map((a) => [a.slug, Object.assign({}, a, { kids: [] })]));
    const roots = [];
    by.forEach((n) => {
      const parent = n.parent_slug ? by.get(n.parent_slug) : null;
      (parent || { kids: roots }).kids.push(n);
    });
    return roots;
  }

  function AreaRow({ a, depth }) {
    // Coverage is shown honestly: the cuisines actually present are on the row.
    const cuisines = (a.cuisines || "").split(UNIT_SEP).filter(Boolean);
    const shown = cuisines.slice(0, 4);
    const rest = cuisines.length - shown.length;
    // The place count on a parent already includes everything under it, so say so.
    const within = a.kids?.length
      ? <span>{a.kids.length} area{a.kids.length === 1 ? "" : "s"} within</span> : null;
    return (
      <a className={`area-row${depth ? " area-row-nested" : ""}`} style={{ "--depth": depth }}
         href={`/food/${encodeURIComponent(a.slug)}`} data-slug={a.slug}>
        <div>
          <div className="area-row-main">
            {a.kids?.length ? <i className="area-caret" aria-hidden="true"></i> : null}
            <span className="area-name">{a.name}</span>
            <span className="chip">{a.level}</span>
          </div>
          {cuisines.length ? <div className="area-cuisines">
            {shown.map((c) => <span className="chip chip-cuisine" key={c}>{c}</span>)}
            {rest > 0 ? <span className="chip">+{rest}</span> : null}
          </div> : null}
        </div>
        <div className="area-stats">
          <span><b>{a.place_count}</b>place{a.place_count === 1 ? "" : "s"}</span>
          {within}
          <span>{a.scene_researched ? `researched ${a.scene_researched}` : "no rundown yet"}</span>
        </div>
      </a>
    );
  }

  /* <details>, not a state object: the browser already owns open/closed, keyboard
     operation and the ARIA for a disclosure. The one thing it does not know is that the
     summary holds a link, which is what the click handler below is for. */
  function AreaBranch({ node, depth }) {
    const row = <AreaRow a={node} depth={depth} />;
    if (!node.kids.length) return row;
    return (
      <details className="area-node"><summary className="area-sum">{row}</summary>
        {node.kids.map((k) => <AreaBranch node={k} depth={depth + 1} key={k.slug} />)}
      </details>
    );
  }

  /* The summary wraps the whole row, so a click on the name would open the area AND
     toggle the doll. The link wins, except on the caret. */
  function onIndexClick(e) {
    const sum = e.target.closest?.(".area-sum");
    if (!sum) return;
    // A modified click is the browser's business: new tab, new window, download.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
    if (e.target.closest(".area-caret")) {
      e.preventDefault();
      sum.parentElement.open = !sum.parentElement.open;
      return;
    }
    const row = e.target.closest(".area-row");
    if (row) { e.preventDefault(); location.href = row.href; }
    // Anything else on the summary is the summary itself; <details> toggles as it always does.
  }

  function Areas() {
    const [areas, setAreas] = useState(null);
    const [err, setErr] = useState(null);
    const globe = useRef(null);
    const globeEl = useRef(null);
    const homeT = useRef(null);

    useEffect(() => {
      json("/food/api/areas").then(setAreas).catch((e) => { console.error(e); setErr(e); });
    }, []);

    const hasGlobe = !!(areas?.length && window.maplibregl);
    useEffect(() => {
      if (!hasGlobe) return undefined;
      const pts = areas.filter((a) => a.lat !== null && a.lng !== null);
      if (!pts.length) return undefined;
      globe.current = drawGlobe(globeEl.current, pts);
      return () => { globe.current.stop(); globe.current = null; };
    }, [hasGlobe]);

    if (err) return <Failed err={err} what="the area list" />;
    if (!areas) return null;
    if (!areas.length) {
      return (
        <div className="index-wrap"><div className="empty">
          <p className="lead">No areas researched yet.</p>
          <p className="hint">Run <code>/food &lt;area&gt;</code> to research one, optionally with a cuisine.</p>
        </div></div>
      );
    }

    const list = (
      <React.Fragment>
        <div className="index-head">
          <span className="index-title">areas</span>
          <span className="index-count">{areas.length} researched</span>
        </div>
        {areaTree(areas).map((n) => <AreaBranch node={n} depth={0} key={n.slug} />)}
      </React.Fragment>
    );
    if (!window.maplibregl) return <div className="index-wrap" onClick={onIndexClick}>{list}</div>;

    /* Pointing at a row aims the globe at it, and letting go pulls back out to the whole
       world. The delay is what makes a slide down the rail read as one movement: leaving
       row A for row B fires pointerout before pointerover. */
    const over = (e) => {
      const row = e.target.closest?.(".globe-rail .area-row");
      if (row) { clearTimeout(homeT.current); globe.current?.fly(row.dataset.slug); }
    };
    const out = (e) => {
      if (!e.target.closest?.(".globe-rail .area-row")) return;
      clearTimeout(homeT.current);
      homeT.current = setTimeout(() => globe.current?.home(), 220);
    };
    return (
      <div className="globe-wrap" onClick={onIndexClick} onPointerOver={over} onPointerOut={out}>
        <div className="globe-stage"><div id="globe" ref={globeEl}></div>
          <div className="globe-legend">
            <span className="globe-legend-k">zoom in for finer areas</span>
            {["city", "borough", "neighborhood"].map((l) =>
              <span className="globe-legend-l" key={l}><i className={`globe-dot globe-dot-${l}`}></i>{l}</span>)}
          </div>
        </div>
        <aside className="globe-rail">{list}</aside>
      </div>
    );
  }

  /* ------------------------------------------------------------ area page ---

     The area view itself is HubUI.FoodView, mounted here and again by the trips board's
     food tab. This page's whole job is to fetch, hand that view the elements it draws
     into, and say what a child area means here: a link to its own page. */

  /* An area's `member` is the tuple that selects its places, and it is the ONLY thing
     that may select them. Not the name, and not the slug.

     A key that is absent means "any": a city keeps all its boroughs. A key that is
     present and null means "none". Those are different queries. */
  function memberQuery(m) {
    const q = new URLSearchParams({ city: m.city });
    for (const k of ["borough", "neighborhood"]) {
      if (!(k in m)) continue;
      if (m[k] === null) q.set(`${k}_none`, "1"); else q.set(k, m[k]);
    }
    return q.toString();
  }

  const placeApi = { place: (s) => json(`/food/api/place/${encodeURIComponent(s)}`) };

  function AreaPage({ slug, setCrumb }) {
    const [res, setRes] = useState(null);   // {payload, places} | {missing} | {err}
    const refs = { rail: useRef(), head: useRef(), list: useRef(), map: useRef(), detail: useRef(), sidePane: useRef() };
    const [els, setEls] = useState(null);

    useEffect(() => {
      // One call carries the area, what it sits inside, and what sits inside it.
      json(`/food/api/area/${slug.split("/").map(encodeURIComponent).join("/")}`).then((payload) =>
        json(`/food/api/places?${memberQuery(payload.area.member)}`).then((places) => {
          setCrumb(<React.Fragment>
            {/* "food / New York / Brooklyn", every step of it a link back up the doll. */}
            {payload.ancestors.map((a) => (
              <React.Fragment key={a.slug}>
                <a href={`/food/${encodeURIComponent(a.slug)}`}>{a.name}</a><span className="crumb-sep">/</span>
              </React.Fragment>))}
            {payload.area.name}
          </React.Fragment>);
          setRes({ payload, places });
        })
      ).catch((e) => {
        if (String(e.message || e).startsWith("404")) setRes({ missing: true });
        else { console.error(e); setRes({ err: e }); }
      });
    }, [slug]);

    const ready = !!(res?.payload);
    useLayoutEffect(() => {
      if (!ready) return;
      setEls(Object.fromEntries(Object.entries(refs).map(([k, r]) => [k, r.current])));
    }, [ready]);

    if (!res) return null;
    if (res.missing) {
      return (
        <div className="index-wrap"><div className="empty">
          <p className="lead">No area matches <code>{slug}</code>.</p>
          <p className="hint"><a href="/food/">Back to all areas</a></p>
        </div></div>
      );
    }
    if (res.err) return <Failed err={res.err} what="this area" />;
    return (
      <div className="body">
        <aside className="col funnel" id="rail" ref={refs.rail}></aside>
        <div className="col pane hub-split focus-split">
          <div className="col focus" id="focus">
            <div id="focusHead" ref={refs.head}></div>
            <div className="focus-body" id="focusList" ref={refs.list}></div>
          </div>
          <div className="side-pane" id="sidePane" ref={refs.sidePane}>
            <div className="side-map" id="mapHost" ref={refs.map}></div>
            <div id="sideDetail" ref={refs.detail}></div>
          </div>
        </div>
        {/* No navigate hook: a child area has its own page here, so its rows are links. */}
        {els ? <HubUI.FoodView els={els} data={{ area: res.payload.area, children: res.payload.children, places: res.places }} api={placeApi} /> : null}
      </div>
    );
  }

  function Food() {
    const [crumbEl, setCrumb] = useState("food");
    useEffect(() => { root.setAttribute("data-react-mounted", "food"); }, []);
    return (
      <React.Fragment>
        {createPortal(crumbEl, crumb)}
        {root.dataset.view === "areas" ? <Areas /> : <AreaPage slug={root.dataset.area} setCrumb={setCrumb} />}
      </React.Fragment>
    );
  }

  // Render errors land here; load failures are caught where they happen.
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[food] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  crumb.textContent = "";   // the template's static crumb would sit beside the portal's live one
  ReactDOM.createRoot(root).render(<Boundary><Food /></Boundary>);
})();
